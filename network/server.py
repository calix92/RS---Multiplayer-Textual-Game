import asyncio
import logging
import re
from typing import Callable
import grpc
from grpc import aio as grpc_aio
try:
    from proto import game_pb2, game_pb2_grpc
except ImportError:
    game_pb2 = None
    game_pb2_grpc = None
from game.state import GameState
from dht.kademlia import DHTNode, NodeInfo

def extract_ip_from_context(context) -> str | None:
    """Extrai o IP do peer do contexto gRPC."""
    if not context: return None
    peer = context.peer()
    # Formatos comuns: 'ipv4:127.0.0.1:54321' ou 'ipv6:[::1]:54321'
    match = re.match(r'ipv[46]:\[?([^\]]+)\]?:(\d+)', peer)
    if match:
        return match.group(1)
    return None

class GameServicer(game_pb2_grpc.GameServiceServicer):
    def __init__(self, game_state: GameState, dht_node: DHTNode, on_event: Callable[[str], None]):
        self.state = game_state
        self.dht   = dht_node
        self.on_event = on_event

    async def _force_peer(self, sid, sname, context=None):
        """Garante que o peer existe e está atualizado, corrigindo o IP se necessário."""
        if sid == self.state.self_player.player_id: return
        
        inferred_ip = extract_ip_from_context(context)
        
        # Se já conhecemos o peer no estado do jogo
        if sid in self.state.peers:
            peer_obj = self.state.peers[sid]
            peer_obj.touch()
            # Se o IP que ele reportou é 127.0.0.1 ou diferente do que o gRPC vê, 
            # e o gRPC vê um IP externo, preferimos o do gRPC.
            if inferred_ip and (peer_obj.ip.startswith("127.") or peer_obj.ip != inferred_ip):
                if not inferred_ip.startswith("127."):
                    logging.info(f"Atualizar IP de {sname}: {peer_obj.ip} -> {inferred_ip}")
                    peer_obj.ip = inferred_ip
                    # Atualizar também na DHT
                    node = next((n for n in self.dht.all_peers() if n.node_id == sid), None)
                    if node: node.ip = inferred_ip
        else:
            # Se não conhecemos no jogo, ver se está na DHT
            node = next((n for n in self.dht.all_peers() if n.node_id == sid), None)
            if node:
                if inferred_ip and (node.ip.startswith("127.") or node.ip != inferred_ip):
                    if not inferred_ip.startswith("127."):
                        node.ip = inferred_ip
                await self.state.add_peer(node.node_id, node.name, node.ip, node.port)
            elif inferred_ip and not inferred_ip.startswith("127."):
                # Caso extremo: não conhecemos de lado nenhum, mas ele está a falar connosco.
                # Assumimos a porta por defeito ou tentamos adivinhar (JOIN tratará disto melhor)
                pass

    async def SyncWorld(self, request, context):
        self.on_event(f"🌐 Sincronização pedida por {request.reader_id[:8]}")
        await self._force_peer(request.reader_id, "Peer", context)
        return game_pb2.WorldState(world_data_json=await self.state.get_world_state_json())

    async def SendAction(self, request, context):
        await self._force_peer(request.sender_id, request.sender_name, context)
        at, sid, sname, pay = request.action, request.sender_id, request.sender_name, request.payload
        hp, msg = 0, ""
        try:
            if at == 0: hp, msg = await self.state.process_attack(sid, sname, pay)
            elif at == 1: msg = await self.state.process_move(sid, sname, pay)
            elif at == 2: msg = await self.state.process_speak(sname, pay)
            elif at == 3: hp, msg = await self.state.process_heal(sid, sname, int(pay) if pay.isdigit() else 15)
            elif at == 4:
                parts = pay.split(":")
                ip, port = (parts[0], int(parts[1])) if len(parts) > 1 else (sid, 0)
                
                # Inteligência de IP: se o que vem no payload é localhost mas o gRPC vê um IP externo
                inferred_ip = extract_ip_from_context(context)
                if inferred_ip and not inferred_ip.startswith("127."):
                    if ip.startswith("127.") or ip.startswith("172."): # Docker ou localhost
                        ip = inferred_ip
                
                msg = await self.state.process_join(sid, sname, ip, port)
                self.dht.add_peer(NodeInfo(sid, ip, port, sname))
            elif at == 5: msg = await self.state.process_leave(sid, sname)
        except Exception as e: msg = f"Erro: {e}"
        if msg: self.on_event(msg)
        return game_pb2.ActionResponse(success=True, message=msg, hp_delta=hp)

    async def Ping(self, request, context):
        await self._force_peer(request.sender_id, "Peer", context)
        return game_pb2.PingResponse(node_id=self.dht.node_id, alive=True)

    async def FindNode(self, request, context):
        closest = self.dht.on_find_node(request.target_id, request.requester_id)
        # Convert NodeInfo objects to protobuf NodeInfo messages
        pb_nodes = [
            game_pb2.NodeInfo(
                node_id=n.node_id,
                ip=n.ip,
                port=n.port,
                name=n.name
            ) for n in closest
        ]
        return game_pb2.FindNodeResponse(closest_nodes=pb_nodes)

    async def StoreNode(self, request, context):
        node = request.node
        success = self.dht.on_store_node(NodeInfo(node.node_id, node.ip, node.port, node.name))
        return game_pb2.StoreNodeResponse(success=success)

async def start_server(host, port, game_state, dht_node, on_event):
    server = grpc_aio.server()
    game_pb2_grpc.add_GameServiceServicer_to_server(GameServicer(game_state, dht_node, on_event), server)
    
    # Ouvir em TODAS as interfaces (IPv4 e IPv6)
    # Ignoramos o 'host' passado para garantir que apanhamos o Tailscale
    listen_addr = f"0.0.0.0:{port}"
    server.add_insecure_port(listen_addr)
    try:
        server.add_insecure_port(f"[::]:{port}")
    except: pass
    
    await server.start()
    logging.info(f"Server started on {listen_addr}")
    return server
