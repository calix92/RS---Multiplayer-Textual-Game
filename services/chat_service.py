class ChatService:

    def __init__(
        self,
        uuid,
        username,
        grpc_port,
        discovery
    ):
        self.uuid = uuid
        self.username = username
        self.grpc_port = grpc_port
        self.discovery = discovery

        self.client = ChatClient([])

    async def initialize(self):

        address = f"localhost:{self.grpc_port}"

        await self.discovery.register_user(
            self.uuid,
            address
        )

        peers = await self.discovery.get_peer_addresses(
            exclude_uuid=self.uuid
        )

        self.client.add_peers(peers)

        print(f"[CHAT] peers = {peers}")

    def send(self, message):
        self.client.broadcast(
            self.username,
            message
        )
