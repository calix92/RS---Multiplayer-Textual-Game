"""
network/server.py
~~~~~~~~~~~~~~~~~
gRPC server that runs on each peer node.
Handles incoming GameService RPCs and delegates to GameState + DHTNode.
"""

import asyncio
import logging
import time
from typing import Callable

import grpc
from grpc import aio as grpc_aio

# Generated stubs are imported lazily to allow running without compiled proto
try:
    from proto import game_pb2, game_pb2_grpc
except ImportError:
    game_pb2 = None
    game_pb2_grpc = None

from game.state import GameState
from dht.kademlia import DHTNode, NodeInfo

log = logging.getLogger("network.server")


class GameServicer:
    """
    Implements the gRPC GameService.
    All methods are coroutines (async def) — asyncio-native.
    """

    def __init__(self,
                 game_state: GameState,
                 dht_node: DHTNode,
                 on_event: Callable[[str], None]):
        self.state = game_state
        self.dht   = dht_node
        self.on_event = on_event   # callback to print to terminal

    # ── GameService.SendAction ────────────────────────────────────────────

    async def SendAction(self, request, context):
        action_type = request.action
        sender_id   = request.sender_id
        sender_name = request.sender_name
        payload     = request.payload

        hp_delta = 0
        message  = ""

        try:
            # ActionType enum values: ATTACK=0, MOVE=1, SPEAK=2,
            #                         HEAL=3, JOIN=4, LEAVE=5
            if action_type == 0:   # ATTACK
                hp_delta, message = await self.state.process_attack(
                    sender_id, sender_name, payload)

            elif action_type == 1:  # MOVE
                message = await self.state.process_move(
                    sender_id, sender_name, payload)

            elif action_type == 2:  # SPEAK
                message = await self.state.process_speak(sender_name, payload)

            elif action_type == 3:  # HEAL
                try:
                    amount = int(payload)
                except ValueError:
                    amount = 15
                hp_delta, message = await self.state.process_heal(
                    sender_id, sender_name, amount)

            elif action_type == 4:  # JOIN
                # payload = "ip:port"
                parts = payload.split(":")
                ip   = parts[0] if parts else sender_id
                port = int(parts[1]) if len(parts) > 1 else 0
                message = await self.state.process_join(
                    sender_id, sender_name, ip, port)
                # Also register in DHT
                peer_info = NodeInfo(sender_id, ip, port, sender_name)
                self.dht.add_peer(peer_info)

            elif action_type == 5:  # LEAVE
                message = await self.state.process_leave(sender_id, sender_name)
                self.dht.remove_peer(sender_id)

        except Exception as exc:
            log.exception("Error processing action %d from %s", action_type, sender_name)
            message = f"Error: {exc}"

        self.on_event(message)

        return game_pb2.ActionResponse(
            success=True,
            message=message,
            hp_delta=hp_delta,
        )

    # ── GameService.FindNode ──────────────────────────────────────────────

    async def FindNode(self, request, context):
        # Obter os K nós mais próximos, incluindo o próprio Host se for solicitado
        closest = self.dht.find_closest(request.target_id)
        
        # Inserir o próprio nó na resposta para que o recém-chegado saiba quem é o Host
        if self.dht.node_id not in [n.node_id for n in closest]:
            closest.append(self.dht.info)

        nodes = [
            game_pb2.NodeInfo(
                node_id=n.node_id,
                ip=n.ip,
                port=n.port,
                name=n.name,
            )
            for n in closest
        ]
        return game_pb2.FindNodeResponse(closest_nodes=nodes)

    # ── GameService.StoreNode ─────────────────────────────────────────────

    async def StoreNode(self, request, context):
        info = NodeInfo(
            request.node.node_id,
            request.node.ip,
            request.node.port,
            request.node.name,
        )
        ok = self.dht.on_store_node(info)
        return game_pb2.StoreNodeResponse(success=ok)

    # ── GameService.Ping ──────────────────────────────────────────────────

    async def Ping(self, request, context):
        return game_pb2.PingResponse(
            node_id=self.dht.node_id,
            alive=True,
        )


# ─── Server factory ───────────────────────────────────────────────────────────

async def start_server(host: str,
                       port: int,
                       game_state: GameState,
                       dht_node: DHTNode,
                       on_event: Callable[[str], None]) -> grpc_aio.Server:
    """Create and start the async gRPC server."""
    server = grpc_aio.server()
    servicer = GameServicer(game_state, dht_node, on_event)

    game_pb2_grpc.add_GameServiceServicer_to_server(servicer, server)

    address = f"{host}:{port}"
    server.add_insecure_port(address)
    await server.start()
    log.info("gRPC server listening on %s", address)
    return server