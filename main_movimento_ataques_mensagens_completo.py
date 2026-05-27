import time
import asyncio
import socket
import uuid
import argparse
import grpc
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.layout.controls import BufferControl
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
        self.channels = {}
        self.stubs_chat = {}

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
        channel = grpc.aio.insecure_channel(request.address)
        self.peer.channels[request.uuid] = channel
        return multiplayer_pb2.Empty()

    async def GetPeers(self, request, context):
        return multiplayer_pb2.AllPeers(peers=self.peer.peers)

    async def RemovePeer(self, request, context):
        self.peer.peers.pop(request.uuid, None)
        return multiplayer_pb2.Empty()


class Chat(multiplayer_pb2_grpc.ChatServicer):
    def __init__(self, game):
        self.game = game

    async def Broadcast(self, request, context):
        # Adiciona mensagem ao historial do chat
        self.game.add_chat_message(request.from_uuid, request.text)
        return multiplayer_pb2.Empty()


class Game:
    def __init__(self, peer, network):
        self.peer = peer
        self.network = network
        
        # Jogo
        self.w = 20
        self.h = 10
        self.x = 5
        self.y = 5
        self.facing = "?"
        self.frozen_until = 0
        
        # Chat
        self.chat_history = []  # Lista de tuplos (uuid, mensagem)
        
        # UI
        self.game_display = TextArea(
            text="",
            focusable=False,
            height=12
        )
        
        self.chat_display = TextArea(
            text="",
            focusable=False,
            height=8
        )
        
        self.input_field = TextArea(
            text="",
            height=3,
            focusable=True,
            prompt="> ",
            multiline=False,
            wrap_lines=False
        )
        
        self.kb = KeyBindings()
        
        # Bindings do jogo
        @self.kb.add("up")
        def _(event):
            self.handle_movement("up")
        
        @self.kb.add("down")
        def _(event):
            self.handle_movement("down")
        
        @self.kb.add("left")
        def _(event):
            self.handle_movement("left")
        
        @self.kb.add("right")
        def _(event):
            self.handle_movement("right")
        
        # Freeze com números
        for i in range(1, 10):
            @self.kb.add(str(i))
            def _(event, sec=i):
                self.freeze(sec)
        
        # Enviar mensagem (Enter)
        @self.kb.add("enter")
        def _(event):
            self.send_message()
        
        # Sair
        @self.kb.add("q")
        def _(event):
            event.app.exit()
        
        # Layout
        self.app = Application(
            layout=Layout(
                HSplit([
                    self.game_display,
                    self.chat_display,
                    self.input_field
                ])
            ),
            key_bindings=self.kb,
            full_screen=True,
            refresh_interval=0.05
        )
        
        # Inicia o loop de atualização
        self.update_task = None
        
    async def start(self):
        self.render()
        self.update_task = asyncio.create_task(self.update_loop())
        with patch_stdout():
            await self.app.run_async()
    
    async def update_loop(self):
        """Atualiza a UI periodicamente"""
        while True:
            self.render()
            await asyncio.sleep(0.05)
    
    def render(self):
        # Renderiza o jogo
        grid = ""
        for y in range(self.h):
            for x in range(self.w):
                if x == self.x and y == self.y:
                    grid += self.dir_symbol()
                else:
                    grid += "."
            grid += "\n"
        
        remaining = max(0, self.frozen_until - time.time())
        game_info = (
            f"Posição: ({self.x}, {self.y})  Direção: {self.facing}  "
            f"Freeze: {remaining:.1f}s\n"
            f"{grid}"
        )
        self.game_display.text = game_info
        
        # Renderiza o chat
        chat_text = "Chat Messages:\n"
        for from_uuid, msg in self.chat_history[-10:]:  # Últimas 10 mensagens
            name = from_uuid[:8] if from_uuid != self.peer.uuid else "You"
            chat_text += f"{name}: {msg}\n"
        self.chat_display.text = chat_text
    
    def handle_movement(self, direction):
        if self.is_frozen():
            return
        
        if self.facing != direction:
            self.facing = direction
        else:
            dx, dy = {
                "up": (0, -1),
                "down": (0, 1),
                "left": (-1, 0),
                "right": (1, 0)
            }.get(direction, (0, 0))
            
            self.x = max(0, min(self.w - 1, self.x + dx))
            self.y = max(0, min(self.h - 1, self.y + dy))
        
        self.render()
    
    def dir_symbol(self):
        return {
            "up": "^",
            "down": "v",
            "left": "<",
            "right": ">"
        }.get(self.facing, "?")
    
    def freeze(self, seconds):
        self.frozen_until = time.time() + seconds
    
    def is_frozen(self):
        return time.time() < self.frozen_until
    
    def send_message(self):
        message = self.input_field.text.strip()
        if not message:
            return
        
        # Limpa o input field
        self.input_field.text = ""
        
        # Adiciona ao historial local
        self.add_chat_message(self.peer.uuid, message)
        
        # Envia para a rede
        asyncio.create_task(self.network.broadcast(message))
    
    def add_chat_message(self, from_uuid, message):
        self.chat_history.append((from_uuid, message))
        self.render()


class Network:
    def __init__(self, peer):
        self.peer = peer
        self.server = None
        self.game = None

    async def run(self, game):
        self.game = game
        await self.start()
        
        chat_task = asyncio.create_task(self.game.start())
        
        try:
            await self.server.wait_for_termination()
        except KeyboardInterrupt:
            pass
        finally:
            chat_task.cancel()
            await self.stop()
            await self.server.stop(grace=1)

    async def start(self):
        self.server = grpc.aio.server(options=[("grpc.so_reuseport", 0)])
        
        peerdiscovery = PeerDiscovery(self.peer)
        multiplayer_pb2_grpc.add_PeerDiscoveryServicer_to_server(peerdiscovery, self.server)
        
        chat = Chat(self.game)
        multiplayer_pb2_grpc.add_ChatServicer_to_server(chat, self.server)
        
        try:
            self.server.add_insecure_port(f"0.0.0.0:{self.peer.port}")
        except Exception as e:
            print(f"[ERROR] Port {self.peer.port} is already in use: {e}")
            return

        await self.server.start()
        
        self.peer.peers[self.peer.uuid] = self.peer.address()
        
        if self.peer.bootstrap:
            await self.join()

    async def join(self):
        channel = grpc.aio.insecure_channel(self.peer.bootstrap)
        stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)
        
        # Regista-te no bootstrap
        await stub.RegisterPeer(
            multiplayer_pb2.Peer(
                uuid=self.peer.uuid,
                address=self.peer.address()
            )
        )
        
        # Obtém lista de peers
        getpeers = await stub.GetPeers(multiplayer_pb2.Empty())
        self.peer.peers.update(getpeers.peers)
        
        await channel.close()
        
        # Notifica outros peers
        for peer_uuid, peer_address in dict(self.peer.peers).items():
            if peer_address == self.peer.address():
                continue
            
            try:
                channel = grpc.aio.insecure_channel(peer_address)
                stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)
                self.peer.channels[peer_uuid] = channel
                await stub.RegisterPeer(
                    multiplayer_pb2.Peer(
                        uuid=self.peer.uuid,
                        address=self.peer.address()
                    )
                )
            except Exception:
                pass

    async def broadcast(self, message):
        for peer_uuid in list(self.peer.peers.keys()):
            if peer_uuid == self.peer.uuid:
                continue
            
            try:
                stub = self.peer.stubs_chat.get(peer_uuid)
                if not stub:
                    channel = self.peer.channels.get(peer_uuid)
                    if not channel:
                        continue
                    stub = multiplayer_pb2_grpc.ChatStub(channel)
                    self.peer.stubs_chat[peer_uuid] = stub
                
                await stub.Broadcast(
                    multiplayer_pb2.BroadcastMessage(
                        from_uuid=self.peer.uuid,
                        text=message
                    )
                )
            except Exception as e:
                print(f"[ERROR] Broadcast to {peer_uuid[:8]}: {e}")

    async def stop(self):
        for peer_address in list(self.peer.peers.values()):
            if peer_address == self.peer.address():
                continue
            
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
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--username", required=True)
    parser.add_argument("--host", default="127.0.0.1")
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
    game = Game(peer, network)
    network.game = game
    
    try:
        asyncio.run(network.run(game))
    except KeyboardInterrupt:
        print("\nServer stopped by user")


if __name__ == "__main__":
    main()
