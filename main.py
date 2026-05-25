import argparse
import asyncio

from core.app import App
from domain.peer import Peer

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--username", required=True)
    parser.add_argument("--host")
    parser.add_argument("--grpc-port", type=int)
    parser.add_argument("--kad-port", type=int)
    parser.add_argument("--bootstrap")

    args = parser.parse_args()

    peer = Peer(
        username=args.username,
        host=args.host,
        grpc_port=args.grpc_port,
        kad_port=args.kad_port,
        bootstrap=args.bootstrap
    )

    asyncio.run(App(peer).start())


if __name__ == "__main__":
    main()
