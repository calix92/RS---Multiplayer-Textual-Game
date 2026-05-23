import grpc
import time

import proto.game_pb2 as pb2
import proto.game_pb2_grpc as pb2_grpc


class ChatClient:

    def __init__(self, peers):
        self.stubs = []

        for peer in peers:
            channel = grpc.insecure_channel(peer)
            stub = pb2_grpc.ChatServiceStub(channel)
            self.stubs.append(stub)

    def broadcast(self, sender, message):
        for stub in self.stubs:
            try:
                stub.Chat(pb2.ChatMessage(
                    sender=sender,
                    message=message
                ))
            except Exception as e:
                print(f"[CLIENT] failed to send: {e}", flush=True)
