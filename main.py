import asyncio
import socket
import uuid
import grpc
import discovery_pb2
import discovery_pb2_grpc


class Peer:
    def __init__(self, username, host="127.0.0.1", port=None, bootstrap=None):
        self.username = username
        self.uuid = str(uuid.uuid4())
        self.host = host
        self.port = port or self._free_port()
        self.bootstrap = bootstrap
        self.peers = {}

    def address(self):
        return f"{self.host}:{self.port}"

    def _free_port(self):
        s = socket.socket()
        s.bind(("", 0))
        free_port = s.getsockname()[1]
        s.close()
        return free_port


class Discovery(discovery_pb2_grpc.DiscoveryServiceServicer):
    def __init__(self, peer):
        self.peer = peer

    async def Register(self, request, context):
        self.peer.peers[request.uuid] = request.address

        return discovery_pb2.RegisterResponse(all_peers=self.peers)

    async def GetAllPeers(self, request, context):
        return discovery_pb2.GetAllPeersResponse(peers=self.peers)

    async def NotifyNewPeer(self, request, context):
        self.peer.peers[request.uuid] = request.address
        return discovery_pb2.Empty()


class Network:
    def __init__(self, peer):
        self.peer = peer
        self.server = grpc.aio.server()
        self.service = Discovery(peer)

        discovery_pb2_grpc.add_DiscoveryServiceServicer_to_server(
            self.service,
            self.server
        )

        self.server.add_insecure_port(f"[::]:{peer.port}")

    async def start(self):
        await self.server.start()

        if self.peer.bootstrap:
            await self.join()
        else:
            self.peer.peers[self.peer.uuid] = self.peer.address()

        while True:
            await asyncio.sleep(1)

    async def join(self):
        channel = grpc.aio.insecure_channel(self.peer.bootstrap)
        stub = discovery_pb2_grpc.DiscoveryServiceStub(channel)

        resp = await stub.Register(
            discovery_pb2.RegisterRequest(
                uuid=self.peer.uuid,
                address=self.peer.address(),
                username=self.peer.username
            )
        )

        self.peer.peers.update(resp.all_peers)
        await channel.close()


def main():
    peer = Peer("A")
    net = Network(peer)
    asyncio.run(net.start())
