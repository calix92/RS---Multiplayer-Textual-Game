import asyncio
import logging
import re
from typing import Callable
import grpc
from grpc import aio as grpc_aio
try:
    from proto import game_pb2, game_pb2_grpc
except ImportError:
    game_pb2, game_pb2_grpc = None, None
from game.state import GameState
from dht.kademlia import DHTNode, NodeInfo

def extract_ip(context) -> str | None:
    if not context: return None
    match = re.match(r'ipv[46]:\[?([^\]]+)\]?:(\d+)', context.peer())
    return match.group(1) if match else None

class GameServicer(game_pb2_grpc.GameServiceServicer):
    def __init__(self, game_state: GameState, dht_node: DHTNode, on_event: Callable[[str], None]):
        self.state, self.dht, self.on_event = game_state, dht_node, on_event

    async def _force_peer(self, sid, sname, context=None):
        if sid == self.state.self_player.player_id: return
        in_ip = extract_ip(context)
        if sid in self.state.peers:
            p = self.state.peers[sid]
            p.touch()
            # Update name if placeholder
            if sname and sname not in ["Peer", "Host"] and p.name in ["Peer", "Host", "Desconhecido"]:
                p.name = sname
            
            if in_ip and not in_ip.startswith("127.") and (p.ip.startswith("127.") or p.ip != in_ip):
                p.ip = in_ip
                node = next((n for n in self.dht.all_peers() if n.node_id == sid), None)
                if node: node.ip = in_ip
        else:
            node = next((n for n in self.dht.all_peers() if n.node_id == sid), None)
            if node:
                if in_ip and not in_ip.startswith("127."): node.ip = in_ip
                await self.state.add_peer(node.node_id, node.name, node.ip, node.port)

    async def SyncWorld(self, request, context):
        await self._force_peer(request.reader_id, "Peer", context)
        return game_pb2.WorldState(world_data_json=await self.state.get_world_state_json())

    async def SendAction(self, request, context):
        await self._force_peer(request.sender_id, request.sender_name, context)
        at, sid, sname, pay = request.action, request.sender_id, request.sender_name, request.payload
        hp, msg = 0, ""
        try:
            if at == game_pb2.ATTACK: hp, msg = await self.state.process_attack(sid, sname, pay)
            elif at == game_pb2.MOVE: msg = await self.state.process_move(sid, sname, pay)
            elif at == game_pb2.SPEAK: msg = await self.state.process_speak(sname, pay)
            elif at == game_pb2.HEAL: hp, msg = await self.state.process_heal(sid, sname, int(pay) if pay.isdigit() else 15)
            elif at == game_pb2.JOIN:
                ip, port = pay.split(":") if ":" in pay else (sid, 0)
                in_ip = extract_ip(context)
                if in_ip and not in_ip.startswith("127.") and (ip.startswith("127.") or ip.startswith("172.")):
                    ip = in_ip
                msg = await self.state.process_join(sid, sname, ip, int(port), joined_at=request.timestamp/1000.0)
                self.dht.add_peer(NodeInfo(sid, ip, int(port), sname))
            elif at == game_pb2.LEAVE: msg = await self.state.process_leave(sid, sname)
            elif at == game_pb2.STATUS: msg = await self.state.process_status(sid, sname, pay)
        except Exception as e: msg = f"Error: {e}"
        if msg: self.on_event(msg)
        return game_pb2.ActionResponse(success=True, message=msg, hp_delta=hp)

    async def Ping(self, request, context):
        await self._force_peer(request.sender_id, "Peer", context)
        return game_pb2.PingResponse(node_id=self.dht.node_id, alive=True)

    async def FindNode(self, request, context):
        closest = self.dht.on_find_node(request.target_id, request.requester_id)
        pb = [game_pb2.NodeInfo(node_id=n.node_id, ip=n.ip, port=n.port, name=n.name) for n in closest]
        return game_pb2.FindNodeResponse(closest_nodes=pb)

    async def StoreNode(self, request, context):
        success = self.dht.on_store_node(NodeInfo(request.node.node_id, request.node.ip, request.node.port, request.node.name))
        return game_pb2.StoreNodeResponse(success=success)

async def start_server(host, port, state, dht, on_event):
    server = grpc_aio.server()
    game_pb2_grpc.add_GameServiceServicer_to_server(GameServicer(state, dht, on_event), server)
    addr = f"0.0.0.0:{port}"
    server.add_insecure_port(addr)
    try: server.add_insecure_port(f"[::]:{port}")
    except: pass
    await server.start()
    return server
