"""
network/server.py
~~~~~~~~~~~~~~~~~
Servidor gRPC que corre em cada nó (Peer).
Trata os pedidos GameService e delega para o GameState e DHTNode.
"""

import asyncio
import logging
import time
from typing import Callable

import grpc
from grpc import aio as grpc_aio

# Tenta importar os stubs gerados pelo protoc
try:
    from proto import game_pb2, game_pb2_grpc
except ImportError:
    # Caso os ficheiros ainda não tenham sido compilados
    game_pb2 = None
    game_pb2_grpc = None

from game.state import GameState
from dht.kademlia import DHTNode, NodeInfo

log = logging.getLogger("network.server")

class GameServicer(game_pb2_grpc.GameServiceServicer):
    """
    Implementação do serviço gRPC definido no game.proto.
    Todos os métodos são assíncronos (asyncio-native).
    """

    def __init__(self,
                 game_state: GameState,
                 dht_node: DHTNode,
                 on_event: Callable[[str], None]):
        self.state = game_state
        self.dht   = dht_node
        self.on_event = on_event   # Callback para enviar mensagens para o terminal

    def _touch_peer(self, sender_id: str):
        """
        Atualiza o timestamp 'last_seen' do peer. 
        Crucial para o sistema de limpeza de inatividade (Heartbeat).
        """
        if sender_id in self.state.peers:
            self.state.peers[sender_id].touch()

    # ── GameService.SyncWorld ─────────────────────────────────────────────

    async def SyncWorld(self, request, context):
        """
        Envia o estado completo do mundo (jogadores, HP, posições) para um novo peer.
        """
        log.info("Recebido pedido de SyncWorld de %s", request.requester_id)
        
        # Se o peer já existe, atualizamos o sinal de vida dele
        self._touch_peer(request.requester_id)
        
        # Gera o JSON com todos os dados atuais
        world_json = await self.state.get_world_state_json()
        
        return game_pb2.WorldState(players_json=world_json)

    # ── GameService.SendAction ────────────────────────────────────────────

    async def SendAction(self, request, context):
        """
        Trata ações de combate, movimento e chat entre peers.
        """
        action_type = request.action
        sender_id   = request.sender_id
        sender_name = request.sender_name
        payload     = request.payload

        # SINAL DE VIDA: Se recebemos uma ação, o peer está ativo.
        self._touch_peer(sender_id)

        hp_delta = 0
        message  = ""

        try:
            # ActionType: ATTACK=0, MOVE=1, SPEAK=2, HEAL=3, JOIN=4, LEAVE=5
            if action_type == 0:   # ATTACK
                hp_delta, message = await self.state.process_attack(
                    sender_id, sender_name, payload)

            elif action_type == 1:  # MOVE
                message = await self.state.process_move(
                    sender_id, sender_name, payload)

            elif action_type == 2:  # SPEAK
                message = await self.state.process_speak(sender_name, payload)

            elif action_type == 3:  # HEAL
                try:
                    amount = int(payload)
                except ValueError:
                    amount = 15
                hp_delta, message = await self.state.process_heal(
                    sender_id, sender_name, amount)

            elif action_type == 4:  # JOIN
                parts = payload.split(":")
                ip   = parts[0] if parts else sender_id
                port = int(parts[1]) if len(parts) > 1 else 0
                message = await self.state.process_join(
                    sender_id, sender_name, ip, port)
                
                # Registar também na DHT para descoberta de rede
                peer_info = NodeInfo(sender_id, ip, port, sender_name)
                self.dht.add_peer(peer_info)

            elif action_type == 5:  # LEAVE
                message = await self.state.process_leave(sender_id, sender_name)
                self.dht.remove_peer(sender_id)

        except Exception as exc:
            log.exception("Erro ao processar ação %d de %s", action_type, sender_name)
            message = f"Erro Interno: {exc}"

        # Envia a mensagem do evento para o Terminal (UI)
        self.on_event(message)

        return game_pb2.ActionResponse(
            success=True,
            message=message,
            hp_delta=hp_delta,
        )

    # ── GameService.FindNode (DHT) ────────────────────────────────────────

    async def FindNode(self, request, context):
        """Responde com os nós mais próximos de um ID (Kademlia)."""
        closest = self.dht.find_closest(request.target_id)
        
        # Garantir que o próprio Host está na lista se for o bootstrap
        if self.dht.node_id not in [n.node_id for n in closest]:
            closest.append(self.dht.info)

        nodes = [
            game_pb2.NodeInfo(
                node_id=n.node_id,
                ip=n.ip,
                port=n.port,
                name=n.name,
            )
            for n in closest
        ]
        return game_pb2.FindNodeResponse(closest_nodes=nodes)

    # ── GameService.StoreNode (DHT) ───────────────────────────────────────

    async def StoreNode(self, request, context):
        """Guarda informações de um nó na DHT local."""
        info = NodeInfo(
            request.node.node_id,
            request.node.ip,
            request.node.port,
            request.node.name,
        )
        ok = self.dht.on_store_node(info)
        return game_pb2.StoreNodeResponse(success=ok)

    # ── GameService.Ping ──────────────────────────────────────────────────

    async def Ping(self, request, context):
        """Verificação básica de conectividade gRPC."""
        return game_pb2.PingResponse(
            node_id=self.dht.node_id,
            alive=True,
        )


# ─── Server Factory ───────────────────────────────────────────────────────────

async def start_server(host: str,
                       port: int,
                       game_state: GameState,
                       dht_node: DHTNode,
                       on_event: Callable[[str], None]) -> grpc_aio.Server:
    """Cria e inicia o servidor gRPC assíncrono em cada Peer."""
    server = grpc_aio.server()
    servicer = GameServicer(game_state, dht_node, on_event)

    game_pb2_grpc.add_GameServiceServicer_to_server(servicer, server)

    address = f"{host}:{port}"
    server.add_insecure_port(address)
    await server.start()
    log.info("Servidor gRPC ativo em %s", address)
    return server