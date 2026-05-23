import grpc
from concurrent import futures

import proto.game_pb2 as pb2
import proto.game_pb2_grpc as pb2_grpc


class ChatService(pb2_grpc.ChatServiceServicer):

    def __init__(self, registry):
        self.registry = registry

    def Join(self, request, context):

        print(f"[JOIN] {request.address}", flush=True)

        self.registry.add(request.address)

        return pb2.JoinResponse(
            peers=self.registry.all()
        )

    def Chat(self, request, context):

        print(f"[{request.sender}] {request.message}", flush=True)

        return pb2.Empty()


def serve(port, registry):

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10)
    )

    pb2_grpc.add_ChatServiceServicer_to_server(
        ChatService(registry),
        server
    )

    server.add_insecure_port(f"[::]:{port}")

    server.start()

    print(f"[SERVER] running on port {port}", flush=True)

    server.wait_for_termination()
