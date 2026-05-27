from aioconsole import ainput
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit
from prompt_toolkit.widgets import TextArea
from prompt_toolkit import PromptSession
import argparse
import asyncio
import random
import socket
import sys
import time
import uuid
import grpc
import multiplayer_pb2
import multiplayer_pb2_grpc


class PeerPlayer:
    def __init__(self, address, username, x, y):
        self.address = address
        self.username = username
        self.x = x
        self.y = y

class Peer:
        def __init__(self, username, host=None, port=None, bootstrap=None):
                self.uuid = str(uuid.uuid4())
                self.username = username
                self.host = host or "127.0.0.1"
                self.port = port or self._free_port()
                self.bootstrap = bootstrap
                self.x = random.randint(0, 20)
                self.y = random.randint(0, 20)
                self.peers = {}

                self.mypeer(self.x, self.y)

        def mypeer(self, x, y):
            self.mypeer = PeerPlayer(self.address(), self.username, x, y)
            self.x = x
            self.y = y
            
                
                
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
            self.peer.peers[request.uuid] = PeerPlayer(request.address, request.username, request.x, request.y)
            print(self.peer.peers)

            channel = grpc.aio.insecure_channel(request.address)
            self.peer.channels[request.uuid] = channel

            return multiplayer_pb2.Empty()

        async def GetPeers(self, request, context):
            allpeers = {}
            for peer_uuid, peerplayer in dict(self.peer.peers).items():
                allpeers[peer_uuid] = multiplayer_pb2.PeerInfo(
                        address = peerplayer.address,
                        username = peerplayer.username,
                        x = peerplayer.x,
                        y = peerplayer.y
                        )
            allpeers[self.peer.uuid] = multiplayer_pb2.PeerInfo(
                    address = self.peer.address(),
                    username = self.peer.username,
                    x = self.peer.x,
                    y = self.peer.y
                    )

            return multiplayer_pb2.AllPeers(peers=allpeers)

        async def RemovePeer(self, request, context):
            self.peer.peers.pop(request.uuid, None)
            print(self.peer.peers)
            return multiplayer_pb2.Empty()


class Chat(multiplayer_pb2_grpc.ChatServicer):
    async def Broadcast(self, request, context):
        print(f"{request.username} screamed: {request.text}")
        return multiplayer_pb2.Empty()


class Game(multiplayer_pb2_grpc.GameServicer):
    def __init__(self, peer):
        self.peer = peer

    async def SetPosition(self, request, context):
        print(f"x: {request.x}, y: {request.y}")
        peerplayer = self.peer.peers[request.uuid]
        peerplayer.x = request.x
        peerplayer.y = request.y

class Network:
        def __init__(self, peer):
                self.peer = peer
                self.server = None
                self.session = PromptSession()

                self.peer.channels = {}
                self.peer.stubs_chat = {}


        async def run(self):
            await self.start()

            chat_task = asyncio.create_task(self.chat_loop())
            
            with patch_stdout():
                try:
                    await self.server.wait_for_termination()
                except KeyboardInterrupt:
                    pass
                finally:
                    chat_task.cancel()
                    await self.stop()
                    await self.server.stop(grace=1)


        async def start(self):
                self.server = grpc.aio.server(
                    options=[
                        ("grpc.so_reuseport", 0)
                    ]
                )
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

                try:
                    self.server.add_insecure_port(f"0.0.0.0:{self.peer.port}")
                except Exception:
                    print(f"[ERROR] Port {self.peer.port} is already in use")
                    sys.exit(1)

                await self.server.start()

                print(self.peer.uuid)
                print(self.peer.address())

                if self.peer.bootstrap:
                        await self.join()


        async def join(self):
                channel = grpc.aio.insecure_channel(self.peer.bootstrap)
                stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)

                getpeers = await stub.GetPeers(multiplayer_pb2.Empty())
                for peer_uuid, peerplayer in getpeers.peers.items():
                    self.peer.peers[peer_uuid] = PeerPlayer(
                            peerplayer.address,
                            peerplayer.username,
                            peerplayer.x,
                            peerplayer.y
                            )

                print(self.peer.peers)

                await channel.close()

                for peer_uuid, peerplayer in dict(self.peer.peers).items():

                        channel = grpc.aio.insecure_channel(peerplayer.address)
                        stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)

                        self.peer.channels[peer_uuid] = channel

                        await stub.RegisterPeer(
                                multiplayer_pb2.Peer(
                                        uuid = self.peer.uuid,
                                        address = self.peer.address(),
                                        username = self.peer.username,
                                        x = self.peer.x,
                                        y = self.peer.y
                                )
                        )


        async def chat_loop(self):
            while True:
                message = await self.session.prompt_async("> ")

                await self.broadcast(message)

        
        async def broadcast(self, message):
            for peer_uuid in list(self.peer.peers.keys()):
                stub = self.get_stubs_chat(peer_uuid)

                await stub.Broadcast(
                        multiplayer_pb2.BroadcastMessage(
                            username = self.peer.username,
                            text = message
                            )
                        )

        def get_stubs_chat(self, peer_uuid):
            try:
                stub = self.peer.stubs_chat.get(peer_uuid, None)
                if not stub:
                    channel = self.peer.channels.get(peer_uuid, None)
                    stub = multiplayer_pb2_grpc.ChatStub(channel)
                    self.peer.stubs_chat[peer_uuid] = stub

                return stub
            except Exception as e:
                print(e)


        async def stop(self):
                for peerplayer in list(self.peer.peers.values()):

                        channel = grpc.aio.insecure_channel(peerplayer.address)
                        stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)
                        

                        await stub.RemovePeer(
                                multiplayer_pb2.Peer(
                                        uuid=self.peer.uuid,
                                        address=self.peer.address()
                                )
                        )

                        await channel.close()

                for channel in self.peer.channels.values():
                            await channel.close()

def main():
        parser = argparse.ArgumentParser()

        parser.add_argument("-u", "--username", required=True)
        parser.add_argument("--host")
        parser.add_argument("-p", "--port", type=int)
        parser.add_argument("-b", "--bootstrap")

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
                print("")
                print("Server stopped by user")


if __name__ == "__main__":
        main()
