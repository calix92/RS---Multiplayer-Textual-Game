import asyncio
import logging
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

class GameServicer(game_pb2_grpc.GameServiceServicer):
    def __init__(self, game_state: GameState, dht_node: DHTNode, on_event: Callable[[str], None]):
        self.state = game_state
        self.dht   = dht_node
        self.on_event = on_event

    async def _force_peer(self, sid, sname):
        """Garante que o peer existe e está atualizado."""
        if sid == self.state.self_player.player_id: return
        if sid in self.state.peers:
            self.state.peers[sid].touch()
        else:
            node = next((n for n in self.dht.all_peers() if n.node_id == sid), None)
            if node:
                await self.state.add_peer(node.node_id, node.name, node.ip, node.port)

    async def SyncWorld(self, request, context):
        self.on_event(f"🌐 Sincronização pedida por {request.reader_id[:8]}")
        await self._force_peer(request.reader_id, "Peer")
        return game_pb2.WorldState(world_data_json=await self.state.get_world_state_json())

    async def SendAction(self, request, context):
        await self._force_peer(request.sender_id, request.sender_name)
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
                msg = await self.state.process_join(sid, sname, ip, port)
                self.dht.add_peer(NodeInfo(sid, ip, port, sname))
            elif at == 5: msg = await self.state.process_leave(sid, sname)
        except Exception as e: msg = f"Erro: {e}"
        if msg: self.on_event(msg)
        return game_pb2.ActionResponse(success=True, message=msg, hp_delta=hp)

    async def Ping(self, request, context):
        await self._force_peer(request.sender_id, "Peer")
        return game_pb2.PingResponse(node_id=self.dht.node_id, alive=True)

    async def FindNode(self, request, context): return game_pb2.FindNodeResponse(closest_nodes=[])
    async def StoreNode(self, request, context): return game_pb2.StoreNodeResponse(success=True)

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
