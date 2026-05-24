class DiscoveryService:

    def __init__(self, kad):
        self.kad = kad
        self.known_users = set()

    async def start(self, bootstrap=None):
        await self.kad.start(bootstrap)

    async def register_user(self, uuid: str, address: str):
        await self.kad.set(f"user:{uuid}", address)
        self.known_users.add(uuid)

    async def get_user_address(self, uuid: str):
        return await self.kad.get(f"user:{uuid}")

    async def discover_user(self, uuid: str):
        address = await self.get_user_address(uuid)
        if address:
            self.known_users.add(uuid)
        return address

    def get_known_users(self):
        return list(self.known_users)

    async def get_peer_addresses(self, exclude_uuid=None):
        peers = []
        for uuid in self.known_users:
            if uuid == exclude_uuid:
                continue
            address = await self.get_user_address(uuid)
            if address:
                peers.append(address)
        return peers
