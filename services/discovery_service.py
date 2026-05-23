class DiscoveryService:

    def __init__(self, kad):
        self.kad = kad

    async def start(self, bootstrap=None):
        await self.kad.start(bootstrap)

    async def register(self, key, value):
        await self.kad.set(key, value)

    async def get_users_index(self):
        return await self.kad.get("users") or {}

    async def get_peer(self, name):
        return await self.kad.get_peer(name)

    async def get_all_users(self):
        return await self.kad.get_all_values_with_prefix("user:")

    async def discover_peers(self, known_names):
        peers = []

        for name in known_names:
            addr = await self.kad.get_peer(name)
            if addr:
                peers.append(addr)

        return peers
