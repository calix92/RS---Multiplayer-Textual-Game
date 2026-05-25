import asyncio
import socket
import uuid
import argparse
from kademlia.network import Server

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



import json
from kademlia.network import Server


import json
from kademlia.network import Server


class KademliaNode:
    def __init__(self, port, username):
        self.port = port
        self.username = username
        self.server = Server()

        self.peer_key = f"peer:{username}"
        self.index_key = "peer_index"

    async def start(self, bootstrap=None):
        await self.server.listen(self.port)

        if bootstrap:
            host, port = bootstrap.split(":")
            await self.server.bootstrap([(host, int(port))])
            print(f"✅ Bootstrapped to {bootstrap}")

        print(f"📡 Kademlia node listening on port {self.port}")

        await self.register_self()

    async def register_self(self):
        peer_data = {
            "username": self.username,
            "port": self.port
        }

        await self.server.set(self.peer_key, json.dumps(peer_data))

        peers_raw = await self.server.get(self.index_key)

        if peers_raw:
            peers = json.loads(peers_raw)
        else:
            peers = []

        if self.username not in peers:
            peers.append(self.username)

        await self.server.set(self.index_key, json.dumps(peers))

        print(f"💾 Registered peer {self.username}")

    async def get_peer(self, username):
        data = await self.server.get(f"peer:{username}")

        if data:
            return json.loads(data)

        return None

    async def get_all_peers(self):
        peers_raw = await self.server.get(self.index_key)

        if not peers_raw:
            return {}

        usernames = json.loads(peers_raw)

        result = {}

        for u in usernames:
            peer = await self.get_peer(u)
            if peer:
                result[u] = peer

        return result

    def stop(self):
        self.server.stop()




import asyncio


class DiscoveryService:
    def __init__(self, kademlia):
        self.kademlia = kademlia
        self.known_peers = {}

    async def start(self, bootstrap):
        await self.kademlia.start(bootstrap)

        await self.sync_peers()

    async def sync_peers(self):
        """Sync from DHT"""
        peers = await self.kademlia.get_all_peers()

        for username, data in peers.items():
            address = f"127.0.0.1:{data['port']}"
            self.known_peers[username] = address

        print(f"📋 Synced {len(self.known_peers)} peers")

    def register_local(self, username, address):
        self.known_peers[username] = address

        # IMPORTANT: usar task async corretamente
        asyncio.create_task(
            self.kademlia.server.set(
                f"peer:{username}",
                "REGISTERED"
            )
        )

    def get_peer_address(self, username):
        return self.known_peers.get(username)

    def get_all_peers(self):
        return dict(self.known_peers)


class App:
    def __init__(self, peer):
        self.peer = peer
        self.kademlia = None
        self.discovery = None

    async def start(self):
        print(f"\n🚀 Starting node for {self.peer.username}")

        self.kademlia = KademliaNode(
            self.peer.kad_port,
            self.peer.username
        )

        self.discovery = DiscoveryService(self.kademlia)

        await self.discovery.start(self.peer.bootstrap)

        # registo local correto
        self.discovery.register_local(
            self.peer.username,
            self.peer.grpc_address()
        )

        await self.show_all_peers()

        print("\n⏳ Node running...\n")

        while True:
            await asyncio.sleep(1)



def main():
    parser = argparse.ArgumentParser(description="Kademlia P2P Discovery System")
    parser.add_argument("--username", required=True, help="Your username")
    parser.add_argument("--host", default="127.0.0.1", help="Host address")
    parser.add_argument("--grpc-port", type=int, help="gRPC port (auto if not provided)")
    parser.add_argument("--kad-port", type=int, help="Kademlia port (auto if not provided)")
    parser.add_argument("--bootstrap", help="Bootstrap node address (host:port)")

    args = parser.parse_args()

    peer = Peer(
        username=args.username,
        host=args.host,
        grpc_port=args.grpc_port,
        kad_port=args.kad_port,
        bootstrap=args.bootstrap
    )

    try:
        asyncio.run(App(peer).start())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")

if __name__ == "__main__":
    main()
