from core.peer_registry import PeerRegistry
from network.grpc_server import serve
from network.grpc_client import ChatClient
from game.chat import chat_loop

import threading
import asyncio
import argparse
import grpc

import proto.game_pb2 as pb2
import proto.game_pb2_grpc as pb2_grpc

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--bootstrap", default=None)

    args = parser.parse_args()

    name = args.name
    port = int(args.port)

    registry = PeerRegistry()

    # start server
    threading.Thread(
        target=serve,
        args=(port, registry),
        daemon=True
    ).start()

    peers = []
    if args.bootstrap:
        peers.append(args.bootstrap)

    client = ChatClient(peers)

    if args.bootstrap:

        channel = grpc.insecure_channel(args.bootstrap)

        stub = pb2_grpc.ChatServiceStub(channel)

        response = stub.Join(
            pb2.JoinRequest(
                address=f"localhost:{port}"
            )
        )

        client.add_peers(response.peers)

        print(f"[INFO] discovered peers: {client.peers}")

    asyncio.run(chat_loop(client, name))

if __name__ == "__main__":
    main()
