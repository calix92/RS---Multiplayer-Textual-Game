import asyncio, logging, time, grpc
from grpc import aio as grpc_aio
try:
    from proto import game_pb2, game_pb2_grpc
except:
    game_pb2, game_pb2_grpc = None, None
from dht.kademlia import NodeInfo

log = logging.getLogger("network.client")
TIMEOUT = 5.0

class PeerClient:
    def __init__(self, ip: str, port: int):
        self.addr, self._chan, self._stub = f"{ip}:{port}", None, None

    async def _get_stub(self):
        if not self._chan:
            opts = [('grpc.keepalive_time_ms', 10000), ('grpc.keepalive_timeout_ms', 5000)]
            self._chan = grpc_aio.insecure_channel(self.addr, options=opts)
            self._stub = game_pb2_grpc.GameServiceStub(self._chan)
        return self._stub

    async def close(self):
        if self._chan: await self._chan.close()
        self._chan = None

    async def send_action(self, sid, sname, atype, pay):
        try:
            stub = await self._get_stub()
            req = game_pb2.ActionRequest(sender_id=sid, sender_name=sname, action=atype, payload=pay, timestamp=int(time.time()*1000))
            return await asyncio.wait_for(stub.SendAction(req), timeout=TIMEOUT)
        except Exception as e: log.debug(f"Action failed for {self.addr}: {e}")
        return None

    async def ping(self, sid):
        try:
            stub = await self._get_stub()
            res = await asyncio.wait_for(stub.Ping(game_pb2.PingRequest(sender_id=sid)), timeout=TIMEOUT)
            return res.alive
        except: return False

    async def find_node(self, target, rid):
        try:
            stub = await self._get_stub()
            res = await asyncio.wait_for(stub.FindNode(game_pb2.FindNodeRequest(target_id=target, requester_id=rid)), timeout=TIMEOUT)
            return [NodeInfo(n.node_id, n.ip, n.port, n.name) for n in res.closest_nodes]
        except: return []

    async def store_node(self, info: NodeInfo):
        try:
            stub = await self._get_stub()
            node = game_pb2.NodeInfo(node_id=info.node_id, ip=info.ip, port=info.port, name=info.name)
            res = await asyncio.wait_for(stub.StoreNode(game_pb2.StoreNodeRequest(node=node)), timeout=TIMEOUT)
            return res.success
        except: return False

class BroadcastClient:
    def __init__(self, dht):
        self.dht, self._clients = dht, {}

    def _get_client(self, info: NodeInfo) -> PeerClient:
        if info.node_id not in self._clients: self._clients[info.node_id] = PeerClient(info.ip, info.port)
        return self._clients[info.node_id]

    async def broadcast(self, sid, sname, atype, pay):
        peers = self.dht.all_peers()
        if not peers: return []
        tasks = [self._get_client(p).send_action(sid, sname, atype, pay) for p in peers]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def send_to(self, target: NodeInfo, sid, sname, atype, pay):
        return await self._get_client(target).send_action(sid, sname, atype, pay)

    async def announce_join(self, sid, sname, ip, port):
        await self.broadcast(sid, sname, game_pb2.JOIN, f"{ip}:{port}")

    async def announce_status(self, sid, sname, hp, status, pos, joined_at):
        await self.broadcast(sid, sname, game_pb2.STATUS, f"{hp}:{status}:{pos}:{joined_at}")

    async def announce_leave(self, sid, sname):
        await self.broadcast(sid, sname, game_pb2.LEAVE, "")

    async def close_all(self):
        for c in self._clients.values(): await c.close()
        self._clients.clear()

    async def sync_with_host(self, host: NodeInfo):
        try:
            chan = grpc.aio.insecure_channel(f"{host.ip}:{host.port}")
            stub = game_pb2_grpc.GameServiceStub(chan)
            res = await stub.SyncWorld(game_pb2.SyncRequest(reader_id=self.dht.node_id))
            await chan.close()
            return res.world_data_json
        except: return None
