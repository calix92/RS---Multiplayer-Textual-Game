from kademlia.network import Server
import asyncio


class KademliaNode:

    def __init__(self, port):
        self.server = Server()
        self.port = port

    async def start(self, bootstrap=None):

        await self.server.listen(self.port)

        if bootstrap:
            host, port = bootstrap.split(":")
            await self.server.bootstrap([
                (host, int(port))
            ])

    async def set_peer(self, key, value):
        await self.server.set(key, value)

    async def get_peer(self, key):
        return await self.server.get(key)
