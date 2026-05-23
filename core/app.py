import threading
import asyncio
import time

from game.chat import chat_loop

from network.grpc_server import serve
from network.grpc_client import ChatClient
from network.kademlia_node import KademliaNode

from services.discovery_service import DiscoveryService
from services.chat_service import ChatService


class App:

    def __init__(self, name, grpc_port, kad_port, bootstrap=None):
        self.name = name
        self.grpc_port = grpc_port
        self.kad_port = kad_port
        self.bootstrap = bootstrap

    async def start(self):

        # -----------------------
        # gRPC server
        # -----------------------
        threading.Thread(
            target=serve,
            args=(self.grpc_port,),
            daemon=True
        ).start()

        time.sleep(1)

        # -----------------------
        # Kademlia
        # -----------------------
        kad = KademliaNode(self.kad_port)
        discovery = DiscoveryService(kad)

        await discovery.start(self.bootstrap)

        # -----------------------
        # chat service
        # -----------------------
        chat_service = ChatService(
            name=self.name,
            grpc_port=self.grpc_port,
            discovery=discovery
        )

        await chat_service.initialize()

        await chat_loop(chat_service)
