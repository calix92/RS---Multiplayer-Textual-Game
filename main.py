from aioconsole import ainput
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.widgets import Label
from prompt_toolkit import PromptSession
import argparse
import asyncio
import math
import random
import socket
import sys
import time
import uuid
import grpc
import multiplayer_pb2
import multiplayer_pb2_grpc


class PeerPlayer:
    def __init__(self, address, username, x, y, direction):
        self.address = address
        self.username = username
        self.x = x
        self.y = y
        self.direction = direction

class Peer:
        def __init__(self, username, host=None, port=None, bootstrap=None):
                self.uuid = str(uuid.uuid4())
                self.username = username
                self.host = host or "127.0.0.1"
                self.port = port or self._free_port()
                self.bootstrap = bootstrap
                self.x = random.randint(0, 19)
                self.y = random.randint(0, 19)
                self.direction = "none"
                self.hp = 20
                self.peers = {}
                self.announcements = []


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
            self.peer.peers[request.uuid] = PeerPlayer(request.address, request.username, request.x, request.y, request.direction)
            self.peer.announcements.append(f"A new warrior arrived. His name is {request.username}")
            self.peer.refresh_news.set()

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
                        y = peerplayer.y,
                        direction = peerplayer.direction
                        )
            allpeers[self.peer.uuid] = multiplayer_pb2.PeerInfo(
                    address = self.peer.address(),
                    username = self.peer.username,
                    x = self.peer.x,
                    y = self.peer.y,
                    direction = self.peer.direction
                    )

            return multiplayer_pb2.AllPeers(peers=allpeers)

        async def RemovePeer(self, request, context):
            channel = self.peer.channels[request.uuid]
            await channel.close()
            self.peer.channels.pop(request.uuid)
            self.peer.peers.pop(request.uuid)
            self.peer.announcements.append(f"The brave warrior {request.username} has withdrawn")
            self.peer.refresh_news.set()

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
        peerplayer.direction = request.direction
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
        self.peer.refresh_news = asyncio.Event()
        self.peer.refresh_news.set()
        self.peer.refresh_status = asyncio.Event()
        self.peer.refresh_status.set()

        self.height = 38
        self.width = 40

        self.recover = 0

        self.warrior = TextArea(
                focusable = False,
                height = 4
                )
        self.news_display = TextArea(
                focusable = False,
                height = 8
                )
        self.game_display = TextArea(
                focusable = False, 
                height = self.height + 2
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

        for i in range(1, 10):
            @self.kb.add(str(i))
            def _(event):
                self.action_attack(i)

        @self.kb.add("up")
        def _(event): self.action_position("up")

        @self.kb.add("down")
        def _(event): self.action_position("down")

        @self.kb.add("left")
        def _(event): self.action_position("left")

        @self.kb.add("right")
        def _(event): self.action_position("right")

        @self.kb.add("enter")
        def _(event): self.action_input()

        @self.kb.add("c-c")
        def _(event):
            event.app.exit()
            raise KeyboardInterrupt

        self.app = Application(
            layout=Layout(
                HSplit([
                    self.warrior,
                    self.label(" Announcements "),
                    self.news_display,
                    Label(""),
                    self.label(" Multiplayer "),
                    self.game_display,
                    Label(""),
                    self.label(" Messages "),
                    self.chat_display,
                    self.input_field
                ])
            ),
            key_bindings=self.kb,
            full_screen=True
            )

        asyncio.create_task(self.loop_status())
        asyncio.create_task(self.loop_news())
        asyncio.create_task(self.loop_game())
        asyncio.create_task(self.loop_chat())

    
    def label(self, message):
        size_message = len(message)
        size_borders = int((self.width + 2 - size_message)/2)
        return Label("=" * size_borders + message + "=" * size_borders)
    
    def action_position(self, direction):
        if not self.is_ready():
            return

        movement = {
            "up": (0, -1),
            "down": (0, 1),
            "left": (-1, 0),
            "right": (1, 0)
        }

        if self.peer.direction != direction:
            self.peer.direction = direction
            self.peer.refresh_game.set()
            asyncio.create_task(self.network.position())
            return

        dx, dy = movement[direction]

        self.peer.x = max(0, min(self.width - 1, self.peer.x + dx))
        self.peer.y = max(0, min(self.height - 1, self.peer.y + dy))
        self.peer.direction = direction
        
        self.peer.refresh_game.set()

        asyncio.create_task(self.network.position())


    def action_attack(self, level):
        recover = math.sqrt(level)
        self.recover = time.time() + recover
    
    def is_ready(self):
        return time.time() > self.recover

    def action_input(self):
        msg = self.input_field.text.strip()
        if not msg:
            return

        self.input_field.text = ""

        self.peer.messages.append(f"You screamed: {msg}")
        self.peer.refresh_chat.set()

        asyncio.create_task(self.network.broadcast(msg))


    async def loop_status(self):
        while True:
            await self.peer.refresh_status.wait()
            self.render_status()
            self.peer.refresh_status.clear()

    async def loop_news(self):
        while True:
            await self.peer.refresh_news.wait()
            self.render_news()
            self.peer.refresh_news.clear()

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

    def render_status(self):
        top = f"Battlefield's localization: {self.peer.address()}"
        middle = f"Warrior's Name: {self.peer.username}"
        bottom = f"Warrior's Health Points: {self.peer.hp}"

        final = [top] + [middle] + [bottom]
        self.warrior.text = "\n".join(final)
        
    def render_news(self):
        self.peer.announcements = self.peer.announcements[-8:]
        self.news_display.text = "\n".join(self.peer.announcements)

    def render_game(self):
        grid = [["." for _ in range(self.width)] for _ in range(self.height)]

        symbols = {
            "up": "^",
            "down": "v",
            "left": "<",
            "right": ">",
            "none": "@"
        }

        for peerplayer in list(self.peer.peers.values()):
            symbol = symbols[peerplayer.direction]
            grid[peerplayer.y][peerplayer.x] = symbol

        symbol = symbols[self.peer.direction]
        grid[self.peer.y][self.peer.x] = symbol

        top = "+" + "-" * self.width + "+"
        middle = ["|" + "".join(row) + "|" for row in grid]
        bottom = top

        final = [top] + middle + [bottom]
        self.game_display.text = "\n".join(final)


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

                if self.peer.bootstrap:
                    self.peer.announcements.append(f"You entered in a new battle. Good Luck.")
                    await self.join()
                else:
                    self.peer.announcements.append(f"You entered in a new arena. Good Luck.")


        async def join(self):
                channel = grpc.aio.insecure_channel(self.peer.bootstrap)
                stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)

                getpeers = await stub.GetPeers(multiplayer_pb2.Empty())
                for peer_uuid, peerplayer in getpeers.peers.items():
                    self.peer.peers[peer_uuid] = PeerPlayer(
                            peerplayer.address,
                            peerplayer.username,
                            peerplayer.x,
                            peerplayer.y,
                            peerplayer.direction
                            )
                    self.peer.announcements.append(f"You are fighting against {peerplayer.username}")

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
                                        y = self.peer.y,
                                        direction = self.peer.direction
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
                        uuid = self.peer.uuid,
                        x = self.peer.x,
                        y = self.peer.y,
                        direction = self.peer.direction
                        )
                    )


        async def stop(self):
            for channel in list(self.peer.channels.values()):
                stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)
                        

                await stub.RemovePeer(
                    multiplayer_pb2.Peer(
                        uuid=self.peer.uuid,
                        address=self.peer.address(),
                        username = self.peer.username
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
                print("The brave warrior withdrew from battle")


if __name__ == "__main__":
        main()
