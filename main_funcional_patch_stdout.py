import argparse
import asyncio
import socket
import uuid
import grpc

import multiplayer_pb2
import multiplayer_pb2_grpc

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout


# =========================
# Peer model
# =========================
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
        port = sock.getsockname()[1]
        sock.close()
        return port


# =========================
# Discovery service
# =========================
class PeerDiscovery(multiplayer_pb2_grpc.PeerDiscoveryServicer):
    def __init__(self, peer):
        self.peer = peer

    async def RegisterPeer(self, request, context):
        self.peer.peers[request.uuid] = request.address
        return multiplayer_pb2.Empty()

    async def GetPeers(self, request, context):
        return multiplayer_pb2.AllPeers(peers=self.peer.peers)


# =========================
# Chat service (NO PRINT!)
# =========================
class Chat(multiplayer_pb2_grpc.ChatServicer):
    def __init__(self, inbox):
        self.inbox = inbox

    async def Broadcast(self, request, context):
        await self.inbox.put(
            f"[CHAT] {request.from_uuid}: {request.text}"
        )
        return multiplayer_pb2.Empty()


# =========================
# Network
# =========================
class Network:
    def __init__(self, peer):
        self.peer = peer
        self.server = None

        self.inbox = asyncio.Queue()
        self.session = PromptSession()

    # ------------------------
    # Start server
    # ------------------------
    async def start(self):
        self.server = grpc.aio.server()

        peer_service = PeerDiscovery(self.peer)
        chat_service = Chat(self.inbox)

        multiplayer_pb2_grpc.add_PeerDiscoveryServicer_to_server(
            peer_service,
            self.server
        )

        multiplayer_pb2_grpc.add_ChatServicer_to_server(
            chat_service,
            self.server
        )

        port = self.server.add_insecure_port(f"0.0.0.0:{self.peer.port}")
        if port == 0:
            raise RuntimeError(f"Port {self.peer.port} already in use")

        await self.server.start()

        self.peer.peers[self.peer.uuid] = self.peer.address()
        print(f"[STARTED] {self.peer.address()}")

        if self.peer.bootstrap:
            await self.join()

    # ------------------------
    # Join network
    # ------------------------
    async def join(self):
        channel = grpc.aio.insecure_channel(self.peer.bootstrap)
        stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)

        peers = await stub.GetPeers(multiplayer_pb2.Empty())
        self.peer.peers.update(peers.peers)

        await channel.close()

        for addr in list(self.peer.peers.values()):
            if addr == self.peer.address():
                continue

            channel = grpc.aio.insecure_channel(addr)
            stub = multiplayer_pb2_grpc.PeerDiscoveryStub(channel)

            await stub.RegisterPeer(
                multiplayer_pb2.Peer(
                    uuid=self.peer.uuid,
                    address=self.peer.address()
                )
            )

            await channel.close()

    # ------------------------
    # Input loop
    # ------------------------
    async def chat_loop(self):
        while True:
            msg = await self.session.prompt_async("> ")
            await self.broadcast(msg)

    # ------------------------
    # Message loop (IMPORTANT FIX)
    # ------------------------
    async def message_loop(self):
        # 🔥 isto evita quebrar o input visual
        with patch_stdout():
            while True:
                msg = await self.inbox.get()
                print(msg)

    # ------------------------
    # Broadcast
    # ------------------------
    async def broadcast(self, message):
        for addr in self.peer.peers.values():
            if addr == self.peer.address():
                continue

            try:
                channel = grpc.aio.insecure_channel(addr)
                stub = multiplayer_pb2_grpc.ChatStub(channel)

                await stub.Broadcast(
                    multiplayer_pb2.BroadcastMessage(
                        from_uuid=self.peer.uuid,
                        text=message
                    )
                )

                await channel.close()

            except Exception as e:
                print(f"[ERROR] {addr}: {e}")

    # ------------------------
    # Run
    # ------------------------
    async def run(self):
        await self.start()

        tasks = [
            asyncio.create_task(self.chat_loop()),
            asyncio.create_task(self.message_loop()),
        ]

        try:
            await self.server.wait_for_termination()
        except KeyboardInterrupt:
            pass
        finally:
            for t in tasks:
                t.cancel()
            await self.server.stop(grace=1)


# =========================
# Main
# =========================
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

    asyncio.run(network.run())


if __name__ == "__main__":
    main()
