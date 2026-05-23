import argparse
import asyncio
import threading

from core.app import App


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--name", required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--kad-port", required=True)
    parser.add_argument("--bootstrap", default=None)

    args = parser.parse_args()

    app = App(
        name=args.name,
        grpc_port=int(args.port),
        kad_port=int(args.kad_port),
        bootstrap=args.bootstrap
    )

    asyncio.run(app.start())


if __name__ == "__main__":
    main()
