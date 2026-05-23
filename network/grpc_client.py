import grpc
import proto.game_pb2 as pb2
import proto.game_pb2_grpc as pb2_grpc


class ChatClient:

    def __init__(self, peers=None):
        self.peers = set(peers or [])
        self.stubs = {}

        self._rebuild_stubs()

    # 🔹 cria/recria stubs
    def _rebuild_stubs(self):
        self.stubs = {}

        for peer in self.peers:
            try:
                channel = grpc.insecure_channel(peer)
                stub = pb2_grpc.ChatServiceStub(channel)
                self.stubs[peer] = stub
            except Exception as e:
                print(f"[CLIENT] failed to connect {peer}: {e}", flush=True)

    # 🔹 adicionar novos peers dinamicamente
    def add_peers(self, new_peers):
        before = len(self.peers)

        self.peers.update(new_peers)

        if len(self.peers) != before:
            self._rebuild_stubs()

    # 🔹 broadcast
    def broadcast(self, sender, message):
        for peer, stub in list(self.stubs.items()):
            try:
                stub.Chat(pb2.ChatMessage(
                    sender=sender,
                    message=message
                ))
            except Exception as e:
                print(f"[CLIENT] failed to send to {peer}: {e}", flush=True)
