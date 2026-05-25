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

class KademliaNode:
    def __init__(self, port):
        self.port = port
        self.server = Server()

    async def start(self, bootstrap=None):
        await self.server.listen(self.port)
        
        if bootstrap:
            host, port = bootstrap.split(":")
            await self.server.bootstrap([(host, int(port))])
            print(f"✅ Bootstrapped to {bootstrap}")
        
        print(f"📡 Kademlia node listening on port {self.port}")

    async def store_peer(self, key, value):
        """Store peer information in DHT"""
        await self.server.set(key, value)
        print(f"💾 Stored {key} -> {value}")

    async def get_peer(self, key):
        """Retrieve peer information from DHT"""
        return await self.server.get(key)

    async def get_all_peers_from_bootstrap(self):
        """Get all registered peers from bootstrap node"""
        # Get all keys from DHT (this is a bit hacky but works for small networks)
        all_peers = {}
        
        # We need to iterate through known peers and ask them
        # For simplicity, we'll use the routing table to find peers
        for peer in self.server.protocol.router.routing_table._buckets:
            for node in peer.nodes:
                peer_id = node.node_id.hex()
                # Try to get peer info from DHT
                peer_info = await self.server.get(peer_id)
                if peer_info:
                    all_peers[peer_id] = peer_info
        
        return all_peers

    async def discover_peers(self):
        """Discover all peers in the network"""
        discovered_peers = {}
        
        # Get peers from routing table
        all_known_nodes = []
        for bucket in self.server.protocol.router.routing_table._buckets:
            for node in bucket.nodes:
                all_known_nodes.append(node)
        
        # Query each known node for their peers
        for node in all_known_nodes:
            try:
                # Store this node's info
                node_id = node.node_id.hex()
                node_address = f"{node.address[0]}:{node.address[1]}"
                discovered_peers[node_id] = node_address
            except:
                pass
        
        return discovered_peers

    def stop(self):
        self.server.stop()

class DiscoveryService:
    def __init__(self, kademlia):
        self.kademlia = kademlia
        self.known_peers = {}  # uuid -> address

    async def start(self, bootstrap):
        await self.kademlia.start(bootstrap)
        
        # If this node is not a bootstrap, request peers from bootstrap
        if bootstrap:
            print(f"🔍 Requesting peer list from bootstrap...")
            discovered = await self.kademlia.discover_peers()
            
            # Register discovered peers
            for peer_id, address in discovered.items():
                self.known_peers[peer_id] = address
            
            print(f"📋 Discovered {len(self.known_peers)} peers")
            for peer_id, address in self.known_peers.items():
                print(f"   - {peer_id[:8]}... @ {address}")
        else:
            print(f"🌟 Running as bootstrap node (no bootstrap address provided)")

    def register_peer(self, uuid, address):
        """Register a peer locally and in DHT"""
        self.known_peers[uuid] = address
        # Store in DHT for others to find
        asyncio.create_task(self.kademlia.store_peer(uuid, address))
        print(f"📝 Registered peer {uuid[:8]}... @ {address}")

    def get_peer_address(self, uuid):
        return self.known_peers.get(uuid)

    def get_all_peers(self):
        """Return all known peers"""
        return dict(self.known_peers)

class App:
    def __init__(self, peer):
        self.peer = peer
        self.kademlia = None
        self.discovery = None

    async def start(self):
        print(f"\n🚀 Starting node for {self.peer.username}")
        print(f"   UUID: {self.peer.uuid}")
        print(f"   KAD Port: {self.peer.kad_port}")
        print(f"   GRPC Port: {self.peer.grpc_port}")
        print(f"   Bootstrap: {self.peer.bootstrap}\n")

        # Initialize Kademlia
        self.kademlia = KademliaNode(self.peer.kad_port)
        
        # Initialize Discovery Service
        self.discovery = DiscoveryService(self.kademlia)
        
        # Start the node
        bootstrap = self.peer.bootstrap if self.peer.bootstrap else None
        await self.discovery.start(bootstrap)
        
        # Register this peer
        self.discovery.register_peer(self.peer.uuid, self.peer.kad_address())
        
        # Display all known peers
        await self.show_all_peers()
        
        # Keep the node running
        print("\n⏳ Node running. Press Ctrl+C to stop.\n")
        
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Shutting down...")
            self.kademlia.stop()

    async def show_all_peers(self):
        """Display all known peers"""
        all_peers = self.discovery.get_all_peers()
        
        print(f"\n{'='*50}")
        print(f"📊 KNOWN PEERS ({len(all_peers)} total)")
        print(f"{'='*50}")
        
        if all_peers:
            for idx, (peer_id, address) in enumerate(all_peers.items(), 1):
                current = "👈 YOU" if peer_id == self.peer.uuid else ""
                print(f"{idx}. {peer_id[:16]}... @ {address} {current}")
        else:
            print("   No peers found (you might be the first one)")
        
        print(f"{'='*50}\n")

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
