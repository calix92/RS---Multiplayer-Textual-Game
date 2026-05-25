import socket
import uuid

class Peer:

    def __init__(self, username, host="127.0.0.1", grpc_port=None, kad_port=None, bootstrap=None):
        self.username = username
        self.uuid = str(uuid.uuid4())
        self.host = host
        self.bootstrap = bootstrap

        self.grpc_port = grpc_port or self._free_port()
        self.kad_port = kad_port or self._free_port()

    def grpc_address(self):
        return f"{self.host}:{self.grpc_port}"

    def kad_address(self):
        return f"{self.host}:{self.kad_port}"

    def _free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]




from kademlia.network import Server

class KademliaNode:

    def __init__(self, port):
        self.server = Server()
        self.port = port

    async def start(self, bootstrap=None):
        await self.server.listen(self.port)

        if bootstrap:
            host, port = bootstrap.split(":")
            await self.server.bootstrap([(host, int(port))])

    async def set(self, key, value):
        await self.server.set(key, value)

    async def get(self, key):
        return await self.server.get(key)



class PeerRegistry:

    def __init__(self, kad):
        self.kad = kad
        self.peers = {}

    async def register_self(self, uuid, address):
        await self.kad.set(f"peer:{uuid}", address)

    async def discover_peers(self, known_uuids):
        for uuid in known_uuids:
            addr = await self.kad.get(f"peer:{uuid}")
            if addr:
                self.peers[uuid] = addr

    def get_peers(self):
        return dict(self.peers)



import asyncio

class App:

    def __init__(self, peer):
        self.peer = peer
        self.peers = {}

    async def start(self):

        print("Starting node...")

        # 1. Kademlia
        kad = KademliaNode(self.peer.kad_port)
        await kad.start(self.peer.bootstrap)

        # 2. Registry em cima do Kademlia
        registry = PeerRegistry(kad)

        # 3. regista o próprio peer na rede
        await registry.register_self(
            self.peer.uuid,
            self.peer.grpc_address()
        )

        # 4. tenta descobrir peers (limitado por agora)
        # nota: Kademlia não lista tudo, então isto é parcial
        self.peers = registry.get_peers()

        print("Peers conhecidos:")
        print(self.peers)

        while True:
            await asyncio.sleep(5)




import asyncio

def main():

    peer = Peer(
        username="user1",
        bootstrap=None  # ou "127.0.0.1:8468"
    )

    asyncio.run(App(peer).start())

if __name__ == "__main__":
    main()




