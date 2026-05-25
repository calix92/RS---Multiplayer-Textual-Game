import asyncio

class App:

    def __init__(self, peer):
        self.peer = peer


    async def start(self):
        print("Starting node...")

        kad = KademliaNode(self.peer.kad_port)

        await kad.start(self.peer.bootstrap)


import socket
import uuid

class Peer:

    def __init__(self, username, host="127.0.0.1", grpc_port=None, kad_port=None, bootstrap=None):

        self.username = username
        self.uuid = str(uuid.uuid4())

        self.host = host
        self.bootstrap = bootstrap

        self.grpc_port = grpc_port or self._find_free_port()
        self.kad_port = kad_port or self._find_free_port()

    def grpc_address(self):
        return f"{self.host}:{self.grpc_port}"

    def kad_address(self):
        return f"{self.host}:{self.kad_port}"

    def _find_free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("", 0))
            return sock.getsockname()[1]



from kademlia.network import Server

class KademliaNode:

    def __init__(self, port):
        self.port = port
        self.server = Server()

    async def start(self, bootstrap):
        await self.server.listen(self.port)

        if bootstrap:
            host, port = bootstrap.split(":")
            await self.server.bootstrap([(host, int(port))])

    async def set(self, key, value):
        await self.server.set(key, value)

    async def get(self, key):
        return await self.server.get(key)

    def stop(self):
        self.server.stop()




class DiscoveryService:

    def __init__(self, kademlia):
        self.kademlia = kademlia
        self.known_peers = {}

    async def start(self, bootstrap):
        await self.kademlia.start(bootstrap)

    def register_peer(self, uuid, address):
        self.known_peers[uuid] = address

    def get_peer_address(self, uuid):
        return self.known_peers.get(uuid)

    def get_all_peers(self):
        return dict(self.known_peers)



import argparse
import asyncio

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

