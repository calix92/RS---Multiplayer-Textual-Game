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
                self.x = random.randint(0, 19)
                self.y = random.randint(0, 19)
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
            self.peer.peers[request.uuid] = PeerPlayer(request.address, request.username, request.x, request.y)
            print(self.peer.peers)

            channel = grpc.aio.insecure_channel(request.address)
            self.peer.channels[request.uuid] = channel

            self.peer.refresh_game.set()
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

            self.peer.refresh_game.set()
            return multiplayer_pb2.Empty()


class Chat(multiplayer_pb2_grpc.ChatServicer):
    def __init__(self, peer):
        self.peer = peer

    async def Broadcast(self, request, context):
        self.peer.messages.append(f"{request.username} screamed: {request.text}")
        self.peer.refresh_chat.set()

        return multiplayer_pb2.Empty()


class Game(multiplayer_pb2_grpc.GameServicer):
    def __init__(self, peer):
        self.peer = peer

    async def SetPosition(self, request, context):
        peerplayer = self.peer.peers[request.uuid]
        peerplayer.x = request.x
        peerplayer.y = request.y
        self.peer.refresh_game.set()
        return multiplayer_pb2.Empty()

class GameController:
    def __init__(self, network):
        self.network = network
        self.peer = self.network.peer
        self.peer.refresh_game = asyncio.Event()
        self.peer.refresh_game.set()
        self.peer.refresh_chat = asyncio.Event()
        self.peer.messages = []

        self.height = 20
        self.width = 20


        self.game_display = TextArea(
                focusable=False, 
                height=20
                )
        self.chat_display = TextArea(
                focusable = False,
                height = 4
                )
        self.input_field = TextArea(
                focusable = True,
                prompt = "> ",
                multiline = False,
                height = 1
                )

        self.kb = KeyBindings()

        @self.kb.add("up")
        def _(event): self.action_position("up")

        @self.kb.add("down")
        def _(event): self.action_position("down")

        @self.kb.add("left")
        def _(event): self.action_position("left")

        @self.kb.add("right")
        def _(event): self.action_position("right")

        @self.kb.add("enter")
        def _(event): self.action_chat()

        @self.kb.add("c-c")
        def _(event):
            event.app.exit()
            raise KeyboardInterrupt

        self.app = Application(
            layout=Layout(
                HSplit([
                    self.game_display,
                    self.chat_display,
                    self.input_field
                ])
            ),
            key_bindings=self.kb,
            full_screen=True
            )

        asyncio.create_task(self.loop_game())
        asyncio.create_task(self.loop_chat())


    def action_position(self, direction):
        movement = {
            "up": (0, -1),
            "down": (0, 1),
            "left": (-1, 0),
            "right": (1, 0)
        }

        dx, dy = movement[direction]

        self.peer.x = max(0, min(self.width - 1, self.peer.x + dx))
        self.peer.y = max(0, min(self.height - 1, self.peer.y + dy))
        
        self.peer.refresh_game.set()

        asyncio.create_task(self.network.position())


    def action_chat(self):
        msg = self.input_field.text.strip()
        if not msg:
            return

        self.input_field.text = ""

        self.peer.messages.append(f"You screamed: {msg}")
        self.peer.refresh_chat.set()

        asyncio.create_task(self.network.broadcast(msg))


    async def loop_game(self):
        while True:
            await self.peer.refresh_game.wait()
            self.render_game()
            self.peer.refresh_game.clear()
        
    async def loop_chat(self):
        while True:
            await self.peer.refresh_chat.wait()
            self.render_chat()
            self.peer.refresh_chat.clear()

    def render_game(self):
        grid = [["." for number in range(self.width)] for number in range(self.height)]
        for peerplayer in list(self.peer.peers.values()):
            grid[peerplayer.y][peerplayer.x] = "@"
        grid[self.peer.y][self.peer.x] = "@"

        rendered = "\n".join("".join(row) for row in grid)
        self.game_display.text = rendered


    def render_chat(self):
        self.peer.messages = self.peer.messages[-4:]
        self.chat_display.text = "\n".join(self.peer.messages)


class Network:
        def __init__(self, peer):
                self.peer = peer
                self.server = None

                self.peer.channels = {}
                self.peer.stubs_chat = {}


        async def run(self):
            await self.start()

            game = GameController(self)

            try:
                with patch_stdout():
                    await game.app.run_async()

            except KeyboardInterrupt:
                pass

            finally:
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
                chat = Chat(self.peer)
                multiplayer_pb2_grpc.add_ChatServicer_to_server(
                        chat,
                        self.server
                        )
                game = Game(self.peer)
                multiplayer_pb2_grpc.add_GameServicer_to_server(
                        game,
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


        async def broadcast(self, message):
            for channel in list(self.peer.channels.values()):
                stub = multiplayer_pb2_grpc.ChatStub(channel)

                await stub.Broadcast(
                    multiplayer_pb2.BroadcastMessage(
                        username = self.peer.username,
                        text = message
                        )
                    )

        async def position(self):
            for channel in list(self.peer.channels.values()):
                stub = multiplayer_pb2_grpc.GameStub(channel)

                await stub.SetPosition(
                    multiplayer_pb2.Position(
                        uuid=self.peer.uuid,
                        x=self.peer.x,
                        y=self.peer.y
                        )
                    )


        async def stop(self):
            for channel in list(self.peer.channels.values()):
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
