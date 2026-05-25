class ChatService:

    def __init__(self, node, discovery, client):

        self.node = node
        self.discovery = discovery
        self.client = client

    async def initialize(self):

        address = self.node.grpc_address()

        await self.discovery.register_user(
            self.node.uuid,
            address
        )

        peers = await self.discovery.get_peer_addresses(
            exclude_uuid=self.node.uuid
        )

        self.client.add_peers(peers)

        print(f"[CHAT] peers = {peers}")
