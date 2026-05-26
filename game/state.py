"""
game/state.py
~~~~~~~~~~~~~
All mutable game state lives here.
Thread-safe via asyncio.Lock — state is only mutated from the event loop.
"""

import asyncio
import time
import logging
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger("game.state")

MAX_HP        = 100
RESPAWN_HP    = 50
ATTACK_DAMAGE = 10
HEAL_AMOUNT   = 15

WEAPON_DAMAGE = {
    "sword":   10,
    "axe":     15,
    "dagger":   7,
    "staff":   12,
    "bow":      9,
    "fists":    5,
}

POSITIONS = ["Town Square", "Dark Forest", "Mountain Pass",
             "Tavern", "Ruins", "River Bank", "Castle Gate"]


class PlayerStatus(Enum):
    ALIVE = "alive"
    DEAD  = "dead"


@dataclass
class Player:
    player_id:  str
    name:       str
    ip:         str
    port:       int
    hp:         int  = MAX_HP
    status:     PlayerStatus = PlayerStatus.ALIVE
    position:   str = "Town Square"
    last_seen:  float = field(default_factory=time.time)

    def is_alive(self) -> bool:
        return self.status == PlayerStatus.ALIVE

    def take_damage(self, amount: int, attacker: str) -> str:
        if not self.is_alive():
            return f"{self.name} is already dead."
        self.hp = max(0, self.hp - amount)
        if self.hp == 0:
            self.status = PlayerStatus.DEAD
            return (f"{self.name} took {amount} damage from {attacker} "
                    f"and has DIED! 💀")
        return (f"{self.name} took {amount} damage from {attacker}. "
                f"HP: {self.hp}/{MAX_HP}")

    def heal(self, amount: int, healer: str) -> str:
        if not self.is_alive():
            return f"Cannot heal {self.name} — they are dead."
        old = self.hp
        self.hp = min(MAX_HP, self.hp + amount)
        delta = self.hp - old
        return f"{healer} healed {self.name} for {delta} HP. HP: {self.hp}/{MAX_HP}"

    def respawn(self) -> str:
        self.hp = RESPAWN_HP
        self.status = PlayerStatus.ALIVE
        self.position = "Town Square"
        return f"{self.name} has respawned with {RESPAWN_HP} HP at Town Square."

    def move(self, destination: str) -> str:
        old = self.position
        self.position = destination
        return f"{self.name} moved from {old} to {destination}."

    def touch(self):
        self.last_seen = time.time()


@dataclass
class GameEvent:
    timestamp: float
    actor:     str
    action:    str
    target:    str
    result:    str


class GameState:
    """
    Central mutable state for the local node.
    `self_player` is this node's own player object.
    `peers`       maps player_id → Player for known remote players.
    """

    def __init__(self, player_id: str, name: str, ip: str, port: int):
        self._lock = asyncio.Lock()
        self.self_player = Player(player_id, name, ip, port)
        self.peers: dict[str, Player] = {}
        self.event_log: list[GameEvent] = []

    # ── Internal helpers ──────────────────────────────────────────────────

    def _log(self, actor: str, action: str, target: str, result: str):
        ev = GameEvent(time.time(), actor, action, target, result)
        self.event_log.append(ev)
        if len(self.event_log) > 200:
            self.event_log = self.event_log[-200:]
        log.info("[EVENT] %s → %s(%s): %s", actor, action, target, result)

    def _get_player(self, player_id: str) -> Optional[Player]:
        if player_id == self.self_player.player_id:
            return self.self_player
        return self.peers.get(player_id)

    # ── Peer management ───────────────────────────────────────────────────

    async def add_peer(self, player_id: str, name: str, ip: str, port: int):
        async with self._lock:
            if player_id == self.self_player.player_id:
                return False
            
            if player_id not in self.peers:
                self.peers[player_id] = Player(player_id, name, ip, port)
                self._log("system", "JOIN", name, f"{name} entrou no reino")
                return True
            else:
                # Se o nó já existe mas o nome era temporário, atualiza
                if self.peers[player_id].name in ["Nó_Inicial", "Desconhecido"]:
                    self.peers[player_id].name = name
                self.peers[player_id].touch()
                return False

    async def remove_peer(self, player_id: str):
        async with self._lock:
            p = self.peers.pop(player_id, None)
            if p:
                self._log("system", "LEAVE", p.name, f"{p.name} left the game")

    # ── Action processors (called when WE receive an action via gRPC) ─────

    

    async def process_attack(self, sender_id: str, sender_name: str, weapon: str) -> tuple[int, str]:
        """Verificação no lado de quem recebe o ataque (Servidor)"""
        async with self._lock:
            # Tentar encontrar o atacante na nossa lista de conhecidos
            attacker = self.peers.get(sender_id)
            
            # Validação de segurança: Se soubermos onde o atacante está, validamos a posição
            if attacker and attacker.position != self.self_player.position:
                self._log(sender_name, "ATTACK_BLOCKED", self.self_player.name, "Tentativa de ataque à distância")
                return 0, f"Ataque de {sender_name} ignorado: Fora de alcance."

            # Se estiverem no mesmo local, processa o dano baseado na arma
            damage = WEAPON_DAMAGE.get(weapon.lower(), 10)
            result = self.self_player.take_damage(damage, sender_name)
            self._log(sender_name, "ATTACK", self.self_player.name, f"{weapon} (-{damage}HP)")
            return -damage, result

    async def process_heal(self, sender_id: str, sender_name: str,
                           amount: int) -> tuple[int, str]:
        """Someone healed us."""
        async with self._lock:
            result = self.self_player.heal(amount, sender_name)
            actual = min(amount, MAX_HP - (self.self_player.hp - amount))
            self._log(sender_name, "HEAL", self.self_player.name,
                      f"+{actual} HP")
            return (actual, result)

    async def process_speak(self, sender_name: str, text: str) -> str:
        msg = f"[{sender_name}] {text}"
        self._log(sender_name, "SPEAK", "all", text)
        return msg

    async def process_move(self, sender_id: str, sender_name: str,
                            destination: str) -> str:
        async with self._lock:
            p = self._get_player(sender_id)
            if p:
                result = p.move(destination)
                self._log(sender_name, "MOVE", destination, result)
                return result
            return f"Unknown player {sender_name}"

    async def process_join(self, sender_id: str, sender_name: str,
                            ip: str, port: int) -> str:
        added = await self.add_peer(sender_id, sender_name, ip, port)
        return f"{sender_name} joined!" if added else ""

    async def process_leave(self, sender_id: str, sender_name: str) -> str:
        await self.remove_peer(sender_id)
        return f"{sender_name} left the game"

    async def self_heal(self, target_id: str) -> Optional[str]:
        async with self._lock:
            if not self.self_player.is_alive():
                return "You are dead."
            return None

    async def self_move(self, destination: str) -> str:
        async with self._lock:
            return self.self_player.move(destination)

    async def self_respawn(self) -> str:
        async with self._lock:
            return self.self_player.respawn()
        
    async def self_attack(self, target_id: str, weapon: str):
        """Verificação no lado de quem ataca (Cliente)"""
        async with self._lock:
            if target_id not in self.peers:
                return False, "Alvo não encontrado."
            
            target = self.peers[target_id]
            # ERRO CORRIGIDO: Verifica se estão na mesma posição
            if self.self_player.position != target.position:
                return False, f"O alvo está em {target.position}, mas tu estás em {self.self_player.position}."
            
            return True, ""
        


    async def get_world_state_json(self) -> str:
        """Transforma todos os jogadores conhecidos (incluindo eu) em JSON."""
        async with self._lock:
            all_players = []
            # Adiciono-me a mim mesmo
            all_players.append(self._player_to_dict(self.self_player))
            # Adiciono os outros que eu conheço
            for p in self.peers.values():
                all_players.append(self._player_to_dict(p))
            
            return json.dumps(all_players)

    def _player_to_dict(self, p: Player):
        return {
            "player_id": p.player_id,
            "name": p.name,
            "ip": p.ip,
            "port": p.port,
            "hp": p.hp,
            "status": p.status.value,
            "position": p.position
        }

    async def apply_world_state(self, json_data: str, dht=None):
        """Lê o JSON recebido e preenche o meu dicionário de peers e opcionalmente a DHT."""
        data = json.loads(json_data)
        async with self._lock:
            for p_dict in data:
                pid = p_dict["player_id"]
                if pid == self.self_player.player_id:
                    continue 
                
                new_player = Player(
                    player_id = pid,
                    name      = p_dict["name"],
                    ip        = p_dict["ip"],
                    port      = p_dict["port"],
                    hp        = p_dict["hp"],
                    status    = PlayerStatus(p_dict["status"]),
                    position  = p_dict["position"]
                )
                self.peers[pid] = new_player

                if dht:
                    from dht.kademlia import NodeInfo
                    dht.add_peer(NodeInfo(pid, p_dict["ip"], p_dict["port"], p_dict["name"]))

            self._log("system", "SYNC", "world", f"Mundo sincronizado ({len(data)} jogadores)")

    
    async def clean_inactive_peers(self, timeout: int = 15):
        """
        Remove peers que não enviam atualizações há mais de 'timeout' segundos.
        """
        async with self._lock:
            now = time.time()
            to_remove = []
            
            for pid, player in self.peers.items():
                if now - player.last_seen > timeout:
                    to_remove.append(pid)
            
            for pid in to_remove:
                p_name = self.peers[pid].name
                del self.peers[pid]
                self._log("system", "TIMEOUT", p_name, f"{p_name} desapareceu nas brumas (Timeout)")
            
            return len(to_remove) > 0 # Retorna True se limpou alguém

    # ── Display helpers ───────────────────────────────────────────────────

    def status_board(self) -> str:
        lines = ["═" * 50,
                 f"  ⚔  REALM OF ASYNCIO  ⚔  (P2P RPG)",
                 "═" * 50]
        # Self
        p = self.self_player
        alive = "💚" if p.is_alive() else "💀"
        lines.append(f"  {alive} YOU  {p.name:<16} "
                     f"HP {p.hp:>3}/{MAX_HP}  📍{p.position} ({p.ip}:{p.port})")
        # Peers
        if self.peers:
            lines.append("─" * 50)
            for peer in self.peers.values():
                alive = "💚" if peer.is_alive() else "💀"
                lines.append(f"  {alive}     {peer.name:<16} "
                              f"HP {peer.hp:>3}/{MAX_HP}  📍{peer.position} ({peer.ip}:{peer.port})")
        lines.append("═" * 50)
        return "\n".join(lines)

    def recent_events(self, n: int = 8) -> list[str]:
        return [f"  {e.actor} → {e.action}({e.target}): {e.result}"
                for e in self.event_log[-n:]]
