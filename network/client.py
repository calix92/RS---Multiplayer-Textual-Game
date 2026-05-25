"""
network/client.py
~~~~~~~~~~~~~~~~~
gRPC client helpers.
`PeerClient` wraps a channel to a single peer and provides typed async methods.
`BroadcastClient` fans out a call to all known peers concurrently.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

import grpc
from grpc import aio as grpc_aio

try:
    from proto import game_pb2, game_pb2_grpc
except ImportError:
    game_pb2 = None
    game_pb2_grpc = None

from dht.kademlia import DHTNode, NodeInfo

log = logging.getLogger("network.client")

TIMEOUT = 5.0   # seconds per RPC call


class PeerClient:
    """Async gRPC client for one peer."""

    def __init__(self, ip: str, port: int):
        self.address = f"{ip}:{port}"
        self._channel: grpc_aio.Channel | None = None
        self._stub = None

    async def _get_stub(self):
        if self._channel is None:
            self._channel = grpc_aio.insecure_channel(self.address)
            self._stub = game_pb2_grpc.GameServiceStub(self._channel)
        return self._stub

    async def close(self):
        if self._channel:
            await self._channel.close()
            self._channel = None

    # ── Actions ───────────────────────────────────────────────────────────

    async def send_action(self,
                          sender_id: str,
                          sender_name: str,
                          action_type: int,
                          payload: str) -> "game_pb2.ActionResponse | None":
        try:
            stub = await self._get_stub()
            req = game_pb2.ActionRequest(
                sender_id=sender_id,
                sender_name=sender_name,
                action=action_type,
                payload=payload,
                timestamp=int(time.time() * 1000),
            )
            resp = await asyncio.wait_for(
                stub.SendAction(req), timeout=TIMEOUT)
            return resp
        except asyncio.TimeoutError:
            log.warning("Timeout sending to %s", self.address)
        except grpc.RpcError as e:
            log.warning("gRPC error to %s: %s", self.address, e.details())
        except Exception as exc:
            log.warning("Error sending to %s: %s", self.address, exc)
        return None

    async def ping(self, sender_id: str) -> bool:
        try:
            stub = await self._get_stub()
            resp = await asyncio.wait_for(
                stub.Ping(game_pb2.PingRequest(sender_id=sender_id)),
                timeout=TIMEOUT)
            return resp.alive
        except Exception:
            return False

    async def find_node(self, target_id: str,
                        requester_id: str) -> list[NodeInfo]:
        try:
            stub = await self._get_stub()
            resp = await asyncio.wait_for(
                stub.FindNode(game_pb2.FindNodeRequest(
                    target_id=target_id,
                    requester_id=requester_id,
                )),
                timeout=TIMEOUT)
            return [NodeInfo(n.node_id, n.ip, n.port, n.name)
                    for n in resp.closest_nodes]
        except Exception as exc:
            log.debug("find_node failed for %s: %s", self.address, exc)
            return []

    async def store_node(self, info: NodeInfo) -> bool:
        try:
            stub = await self._get_stub()
            resp = await asyncio.wait_for(
                stub.StoreNode(game_pb2.StoreNodeRequest(
                    node=game_pb2.NodeInfo(
                        node_id=info.node_id,
                        ip=info.ip,
                        port=info.port,
                        name=info.name,
                    )
                )),
                timeout=TIMEOUT)
            return resp.success
        except Exception:
            return False


# ─── Broadcast helpers ────────────────────────────────────────────────────────

class BroadcastClient:
    """Fan-out sender: sends an action to ALL known peers concurrently."""

    def __init__(self, dht: DHTNode):
        self.dht = dht
        self._clients: dict[str, PeerClient] = {}

    def _get_client(self, info: NodeInfo) -> PeerClient:
        if info.node_id not in self._clients:
            self._clients[info.node_id] = PeerClient(info.ip, info.port)
        return self._clients[info.node_id]

    async def broadcast(self,
                         sender_id: str,
                         sender_name: str,
                         action_type: int,
                         payload: str) -> list:
        """Send to all peers; returns list of responses (None = failed)."""
        peers = self.dht.all_peers()
        if not peers:
            log.debug("No peers to broadcast to.")
            return []

        tasks = [
            self._get_client(p).send_action(
                sender_id, sender_name, action_type, payload)
            for p in peers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

    async def send_to(self,
                       target: NodeInfo,
                       sender_id: str,
                       sender_name: str,
                       action_type: int,
                       payload: str):
        """Send to a single peer by NodeInfo."""
        client = self._get_client(target)
        return await client.send_action(
            sender_id, sender_name, action_type, payload)

    async def announce_join(self, sender_id: str, sender_name: str,
                             ip: str, port: int):
        """Announce ourselves to all known peers."""
        await self.broadcast(
            sender_id, sender_name,
            action_type=4,   # JOIN
            payload=f"{ip}:{port}")

    async def announce_leave(self, sender_id: str, sender_name: str):
        await self.broadcast(sender_id, sender_name, action_type=5, payload="")

    async def close_all(self):
        for c in self._clients.values():
            await c.close()
        self._clients.clear()

    async def sync_with_host(self, host_node_info):
        """
        Liga-se ao nó de bootstrap e saca o estado atual do jogo.
        """
        try:
            # host_node_info deve ter o IP e Porta do gajo ao qual nos estamos a ligar
            channel = grpc.aio.insecure_channel(f"{host_node_info.ip}:{host_node_info.port}")
            stub = game_pb2_grpc.GameServiceStub(channel)
            
            # Pede o mundo
            request = game_pb2.SyncRequest(reader_id=self.dht.node_id)
            response = await stub.SyncWorld(request)
            
            await channel.close()
            return response.players_json # Retorna o JSON
        except Exception as e:
            print(f"Erro na sincronização: {e}")
            return None