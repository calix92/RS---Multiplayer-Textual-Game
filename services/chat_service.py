from network.grpc_client import ChatClient


class ChatService:

    def __init__(self, name, grpc_port, discovery):
        self.name = name
        self.grpc_port = grpc_port
        self.discovery = discovery

        self.client = ChatClient([])

    async def initialize(self):

        address = f"localhost:{self.grpc_port}"

        # -----------------------
        # register self
        # -----------------------
        await self.discovery.register(f"user:{self.name}", address)

        # -----------------------
        # get user list (via DHT index)
        # -----------------------
        users = await self.discovery.get_users_index()

        peers = []

        for user, addr in users.items():
            if user != self.name:
                peers.append(addr)

        self.client.add_peers(peers)

        print(f"[CHAT] peers = {peers}")

    def send(self, message):
        self.client.broadcast(self.name, message)
