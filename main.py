from aioconsole import ainput
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

        async def RemovePeer(self, request, context):
            self.peer.peers.pop(request.uuid, None)
            print(self.peer.peers)
            return multiplayer_pb2.Empty()


class Chat(multiplayer_pb2_grpc.ChatServicer):
    async def Broadcast(self, request, context):
        print(f"From {request.from_uuid} to everyone: {request.text}")
        return multiplayer_pb2.Empty()


class Network:
        def __init__(self, peer):
                self.peer = peer
                self.server = None

        async def start(self):
                self.server = grpc.aio.server()
                peerdiscovery = PeerDiscovery(self.peer)
                multiplayer_pb2_grpc.add_PeerDiscoveryServicer_to_server(
                        peerdiscovery,
                        self.server
                )
                chat = Chat()
                multiplayer_pb2_grpc.add_ChatServicer_to_server(
                        chat,
                        self.server
                        )

                self.server.add_insecure_port(f"0.0.0.0:{self.peer.port}")

                await self.server.start()

                self.peer.peers[self.peer.uuid] = self.peer.address()
                print(self.peer.peers)

                if self.peer.bootstrap:
                        await self.join()


        async def join(self):
                channel = grpc.aio.insecure_channel(self.peer.bootstrap)
                stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)

                getpeers = await stub.GetPeers(multiplayer_pb2.Empty())
                self.peer.peers.update(getpeers.peers)
                print(self.peer.peers)

                await channel.close()

                for peer_address in list(self.peer.peers.values()):
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


        async def chat_loop(self):
            while True:
                message = await ainput("> ")

                await self.broadcast(message)


        async def broadcast(self, message):
            print(f"📤 Broadcasting to {len(self.peer.peers)} peers...")
            for peer_address in list(self.peer.peers.values()):
                if peer_address == self.peer.address():
                    print(f"   ⏭️ Skipping self: {peer_address}")
                    continue

                print(f"   📡 Sending to {peer_address}")
                try:
                    channel = grpc.aio.insecure_channel(peer_address)
                    stub = multiplayer_pb2_grpc.ChatStub(channel)
                    await stub.Broadcast(
                        multiplayer_pb2.BroadcastMessage(
                            from_uuid=self.peer.uuid,
                            text=message
                        )
                    )
                    await channel.close()
                    print(f"   ✅ Sent to {peer_address}")
                except Exception as e:
                    print(f"   ❌ Failed to send to {peer_address}: {e}")

        """
        async def broadcast(self, message):
            for peer_address in self.peer.peers.values():
                if peer_address == self.peer.address():
                    continue

                channel = grpc.aio.insecure_channel(peer_address)
                stub = multiplayer_pb2_grpc.ChatStub(channel)

                await stub.Broadcast(
                        multiplayer_pb2.BroadcastMessage(
                            from_uuid = self.peer.uuid,
                            text = message
                            )
                        )
                await channel.close()
        """

        async def run(self):
            await self.start()

            chat_task = asyncio.create_task(self.chat_loop())

            try:
                await self.server.wait_for_termination()
            except KeyboardInterrupt:
                pass
            finally:
                chat_task.cancel()
                await self.stop()
                await self.server.stop(grace=1)


            #chat_task = asyncio.create_task(self.chat_loop())

            """
            try:
                    await self.server.wait_for_termination()
            except KeyboardInterrupt:
                    pass
            finally:
                chat_task.cancel()
                await self.server.stop(grace=1)
            """


        """
        async def stop(self):
                for peer_address in list(self.peer.peers.values()):
                        if peer_address == self.peer.address():
                                continue

                        channel = grpc.aio.insecure_channel(peer_address)
                        stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)

                        await stub.RemovePeer(
                                multiplayer_pb2.Peer(
                                        uuid=self.peer.uuid,
                                        address=self.peer.address()
                                )
                        )

                        await channel.close()
        """


        async def stop(self):
            print(f"\n🛑 Stopping and removing from peers...")
            dead_peers = []

            for peer_uuid, peer_address in list(self.peer.peers.items()):
                if peer_address == self.peer.address():
                    continue
    
                print(f"   📡 Removing from {peer_address}")
                try:
                    channel = grpc.aio.insecure_channel(peer_address)
                    stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)

                    await stub.RemovePeer(
                        multiplayer_pb2.Peer(
                            uuid=self.peer.uuid,
                            address=self.peer.address()
                        )
                    )
                    await channel.close()
                    print(f"   ✅ Removed from {peer_address}")

                except Exception as e:
                    print(f"   ❌ Failed to remove from {peer_address}: {e}")
                    dead_peers.append(peer_uuid)

            # Remove peers mortos da lista local
            for peer_uuid in dead_peers:
                if peer_uuid in self.peer.peers:
                    del self.peer.peers[peer_uuid]
                    print(f"   🗑️ Removed dead peer {peer_uuid[:8]}... from local list")

            print(f"📊 Remaining peers: {len(self.peer.peers)}")


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
                asyncio.run(network.run())
        except KeyboardInterrupt:
                print("\nServer stopped by user")


if __name__ == "__main__":
        main()
