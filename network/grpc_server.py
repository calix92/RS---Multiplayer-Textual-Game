import grpc
from concurrent import futures

import proto.game_pb2 as pb2
import proto.game_pb2_grpc as pb2_grpc


class ChatService(pb2_grpc.ChatServiceServicer):

    def Chat(self, request, context):
        print(f"[{request.sender}] {request.message}", flush=True)
        return pb2.Empty()


def serve(port):

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10)
    )

    pb2_grpc.add_ChatServiceServicer_to_server(
        ChatService(),
        server
    )

    server.add_insecure_port(f"[::]:{port}")

    server.start()

    print(f"[SERVER] running on port {port}", flush=True)

    server.wait_for_termination()
