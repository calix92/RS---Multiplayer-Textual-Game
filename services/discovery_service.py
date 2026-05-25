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
