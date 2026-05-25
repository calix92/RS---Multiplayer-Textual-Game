import asyncio
import socket
import uuid
import argparse
import grpc
from concurrent import futures
from typing import Dict

# Importar os protos gerados
import discovery_pb2
import discovery_pb2_grpc

class Peer:
    def __init__(self, username, host="127.0.0.1", grpc_port=None, kad_port=None, bootstrap=None):
        self.username = username
        self.uuid = str(uuid.uuid4())
        self.host = host
        self.bootstrap = bootstrap
        self.grpc_port = grpc_port or self._find_free_port()
        self.kad_port = kad_port or self._find_free_port()
        self.known_peers: Dict[str, str] = {}  # uuid -> address

    def grpc_address(self):
        return f"{self.host}:{self.grpc_port}"

    def kad_address(self):
        return f"{self.host}:{self.kad_port}"

    def _find_free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("", 0))
            return sock.getsockname()[1]

class DiscoveryServiceServicer(discovery_pb2_grpc.DiscoveryServiceServicer):
    """Implementação do serviço gRPC para descoberta de peers"""
    
    def __init__(self, peer):
        self.peer = peer
        self.all_peers: Dict[str, str] = {}
        
    async def Register(self, request, context):
        """Regista um peer e devolve todos os peers conhecidos"""
        print(f"📝 Pedido de registo de {request.uuid[:8]}... @ {request.address}")
        
        # Adiciona o novo peer
        self.all_peers[request.uuid] = request.address
        self.peer.known_peers[request.uuid] = request.address
        
        # Cria a resposta com todos os peers
        response = discovery_pb2.RegisterResponse()
        response.all_peers.update(self.all_peers)
        
        # Notifica os outros peers sobre o novo peer (em background)
        asyncio.create_task(self._notify_other_peers(request.uuid, request.address))
        
        print(f"✅ Peer {request.uuid[:8]}... registado. Total: {len(self.all_peers)} peers")
        return response
    
    async def GetAllPeers(self, request, context):
        """Devolve todos os peers conhecidos"""
        response = discovery_pb2.GetAllPeersResponse()
        response.peers.update(self.all_peers)
        return response
    
    async def NotifyNewPeer(self, request, context):
        """Recebe notificação de um novo peer"""
        if request.uuid not in self.peer.known_peers:
            self.peer.known_peers[request.uuid] = request.address
            print(f"🔔 Notificado de novo peer: {request.uuid[:8]}... @ {request.address}")
        
        return discovery_pb2.Empty()
    
    async def _notify_other_peers(self, new_uuid, new_address):
        """Notifica todos os outros peers sobre o novo peer"""
        for uuid_addr, address in self.all_peers.items():
            if uuid_addr != new_uuid:
                try:
                    channel = grpc.aio.insecure_channel(address)
                    stub = discovery_pb2_grpc.DiscoveryServiceStub(channel)
                    await stub.NotifyNewPeer(discovery_pb2.NotifyNewPeerRequest(
                        uuid=new_uuid,
                        address=new_address
                    ))
                except Exception as e:
                    print(f"⚠️ Não foi possível notificar peer {uuid_addr[:8]}...: {e}")

class GRPCServer:
    """Servidor gRPC do peer"""
    
    def __init__(self, peer):
        self.peer = peer
        self.server = None
        self.servicer = None
        
    async def start(self):
        self.server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
        self.servicer = DiscoveryServiceServicer(self.peer)
        
        # Registar o servicer
        discovery_pb2_grpc.add_DiscoveryServiceServicer_to_server(
            self.servicer, self.server
        )
        
        self.server.add_insecure_port(f"[::]:{self.peer.grpc_port}")
        await self.server.start()
        print(f"🎮 gRPC server listening on port {self.peer.grpc_port}")
        
        return self.server
    
    async def stop(self):
        if self.server:
            await self.server.stop(grace=5)

class GRPCClient:
    """Cliente gRPC para comunicar com outros peers"""
    
    def __init__(self, peer):
        self.peer = peer
    
    async def register_with_bootstrap(self, bootstrap_address):
        """Regista no bootstrap e obtém lista de todos os peers"""
        print(f"🔌 Conectando ao bootstrap {bootstrap_address}...")
        
        try:
            # Conecta ao bootstrap
            channel = grpc.aio.insecure_channel(bootstrap_address)
            stub = discovery_pb2_grpc.DiscoveryServiceStub(channel)
            
            # Faz o registo
            response = await stub.Register(discovery_pb2.RegisterRequest(
                uuid=self.peer.uuid,
                address=self.peer.grpc_address(),
                username=self.peer.username
            ), timeout=10)
            
            # Converte a resposta para dicionário
            peers = dict(response.all_peers)
            print(f"✅ Registado com sucesso! Recebidos {len(peers)} peers do bootstrap")
            
            # Fecha o channel
            await channel.close()
            
            return peers
            
        except Exception as e:
            print(f"❌ Erro ao registar no bootstrap: {e}")
            return {}

class DiscoveryService:
    """Serviço de descoberta de peers usando gRPC"""
    
    def __init__(self, peer):
        self.peer = peer
        self.grpc_server = GRPCServer(peer)
        self.grpc_client = GRPCClient(peer)
        
    async def start(self):
        """Inicia o serviço de descoberta"""
        # Inicia servidor gRPC
        await self.grpc_server.start()
        
        # Se tem bootstrap, regista-se
        if self.peer.bootstrap:
            print(f"🔍 A registar no bootstrap {self.peer.bootstrap}...")
            peers = await self.grpc_client.register_with_bootstrap(self.peer.bootstrap)
            self.peer.known_peers.update(peers)
            
            # Remove a si próprio da lista se lá estiver
            if self.peer.uuid in self.peer.known_peers:
                del self.peer.known_peers[self.peer.uuid]
                
            print(f"📋 Conhece {len(self.peer.known_peers)} outros peers")
        else:
            print("🌟 A correr como bootstrap node")
            # Bootstrap regista-se a si próprio
            self.peer.known_peers[self.peer.uuid] = self.peer.grpc_address()
            # Adiciona ao servicer também
            self.grpc_server.servicer.all_peers[self.peer.uuid] = self.peer.grpc_address()
    
    def get_all_peers(self):
        """Devolve todos os peers conhecidos"""
        return dict(self.peer.known_peers)

class App:
    def __init__(self, peer):
        self.peer = peer
        self.discovery = DiscoveryService(peer)

    async def start(self):
        print(f"\n🚀 Starting node for {self.peer.username}")
        print(f"   UUID: {self.peer.uuid}")
        print(f"   gRPC Port: {self.peer.grpc_port}")
        print(f"   KAD Port: {self.peer.kad_port}")
        print(f"   Bootstrap: {self.peer.bootstrap}\n")

        await self.discovery.start()
        
        # Mostra todos os peers conhecidos
        await self.show_all_peers()
        
        print("\n⏳ Node running. Press Ctrl+C to stop.\n")
        
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Shutting down...")
            await self.discovery.grpc_server.stop()

    async def show_all_peers(self):
        all_peers = self.discovery.get_all_peers()
        
        print(f"\n{'='*50}")
        print(f"📊 KNOWN PEERS ({len(all_peers)} total)")
        print(f"{'='*50}")
        
        if all_peers:
            for idx, (peer_id, address) in enumerate(all_peers.items(), 1):
                print(f"{idx}. {peer_id[:16]}... @ {address}")
        else:
            print("   No other peers found")
        
        print(f"{'='*50}\n")

def main():
    parser = argparse.ArgumentParser(description="P2P Discovery System with gRPC")
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
