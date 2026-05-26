import argparse
import asyncio
import socket
import uuid
import grpc
import multiplayer_pb2
import multiplayer_pb2_grpc


class Peer:
        def __init__(self, username, host=None, port=None, bootstrap=None):
                self.username = username
                self.uuid = str(uuid.uuid4())
                self.host = host or "127.0.0.1"
                self.port = port or self._free_port()
                self.bootstrap = bootstrap
                self.peers = {}

        def address(self):
                return f"{self.host}:{self.port}"

        def _free_port(self):
                sock = socket.socket()
                sock.bind(("", 0))
                free_port = sock.getsockname()[1]
                sock.close()
                return free_port


class PeerDiscovery(multiplayer_pb2_grpc.PeerDiscoveryServicer):
        def __init__(self, peer):
                self.peer = peer

        async def RegisterPeer(self, request, context):
            self.peer.peers[request.uuid] = request.address
            print(self.peer.peers)
            return multiplayer_pb2.Empty()

        async def GetPeers(self, request, context):
                return multiplayer_pb2.AllPeers(peers=self.peer.peers)


class Network:
        def __init__(self, peer):
                self.peer = peer


        async def start(self):
                self.service = PeerDiscovery(self.peer)
                self.server = grpc.aio.server()
                multiplayer_pb2_grpc.add_PeerDiscoveryServicer_to_server(
                        self.service,
                        self.server
                )
                self.server.add_insecure_port(f"0.0.0.0:{self.peer.port}")

                await self.server.start()

                self.peer.peers[self.peer.uuid] = self.peer.address()
                print(self.peer.peers)

                if self.peer.bootstrap:
                        await self.join()

                try:
                        await self.server.wait_for_termination()
                except KeyboardInterrupt:
                        pass
                finally:
                        await self.server.stop(grace=1)

        async def join(self):
                channel = grpc.aio.insecure_channel(self.peer.bootstrap)
                stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)

                getpeers = await stub.GetPeers(multiplayer_pb2.Empty())
                self.peer.peers.update(getpeers.peers)
                print(self.peer.peers)

                await channel.close()

                for peer_address in self.peer.peers.values():
                        if peer_address == self.peer.address():
                                continue

                        channel = grpc.aio.insecure_channel(peer_address)
                        stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)

                        await stub.RegisterPeer(
                                multiplayer_pb2.Peer(
                                        uuid=self.peer.uuid,
                                        address=self.peer.address()
                                )
                        )

                        await channel.close()


def main():
        parser = argparse.ArgumentParser()

        parser.add_argument("--username", required=True)
        parser.add_argument("--host")
        parser.add_argument("--port", type=int)
        parser.add_argument("--bootstrap")

        args = parser.parse_args()

        peer = Peer(
                username=args.username,
                host=args.host,
                port=args.port,
                bootstrap=args.bootstrap
        )

        network = Network(peer)

        try:
                asyncio.run(network.start())
        except KeyboardInterrupt:
                print("\nServer stopped by user")


if __name__ == "__main__":
        main()
