import threading
import asyncio
import aioconsole

from network.grpc_server import serve
from network.grpc_client import ChatClient


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--peers", default="")

    args = parser.parse_args()

    name = args.name
    port = int(args.port)

    peers = [p.strip() for p in args.peers.split(",") if p.strip()]

    # remove self if included
    self_addr = f"player1:{port}"
    peers = [p for p in peers if p != self_addr]

    print(f"[INFO] peers = {peers}", flush=True)

    # start server thread
    threading.Thread(target=serve, args=(port,), daemon=True).start()

    client = ChatClient(peers)

    async def chat_loop():
        while True:
            msg = await aioconsole.ainput("> ")
            client.broadcast(name, msg)

    asyncio.run(chat_loop())


if __name__ == "__main__":
    main()
