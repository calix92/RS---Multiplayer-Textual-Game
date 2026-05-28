import asyncio
import time
import logging
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger("game.state")

MAX_HP, RESPAWN_HP, HEAL_AMOUNT = 100, 50, 15

WEAPON_DAMAGE = {
    "sword": 10, "axe": 15, "dagger": 7,
    "staff": 12, "bow": 9, "fists": 5,
}

POSITIONS = ["Town Square", "Dark Forest", "Mountain Pass",
             "Tavern", "Ruins", "River Bank", "Castle Gate"]

class PlayerStatus(Enum):
    ALIVE = "alive"
    DEAD  = "dead"

@dataclass
class Player:
    player_id: str
    name: str
    ip: str
    port: int
    hp: int = MAX_HP
    status: PlayerStatus = PlayerStatus.ALIVE
    position: str = "Town Square"
    last_seen: float = field(default_factory=time.time)
    joined_at: float = field(default_factory=time.time)

    def is_alive(self) -> bool:
        return self.status == PlayerStatus.ALIVE

    def take_damage(self, amount: int, attacker: str) -> str:
        if not self.is_alive(): return f"{self.name} is already dead."
        self.hp = max(0, self.hp - amount)
        if self.hp == 0:
            self.status = PlayerStatus.DEAD
            return f"{self.name} took {amount} damage from {attacker} and DIED! 💀"
        return f"{self.name} took {amount} damage from {attacker}. HP: {self.hp}/{MAX_HP}"

    def heal(self, amount: int, healer: str) -> str:
        if not self.is_alive(): return f"Cannot heal {self.name} (dead)."
        old = self.hp
        self.hp = min(MAX_HP, self.hp + amount)
        return f"{healer} healed {self.name} for {self.hp - old} HP."

    def respawn(self) -> str:
        self.hp, self.status, self.position = RESPAWN_HP, PlayerStatus.ALIVE, "Town Square"
        return f"{self.name} respawned at Town Square."

    def move(self, destination: str) -> str:
        old, self.position = self.position, destination
        return f"{self.name} moved from {old} to {destination}."

    def touch(self):
        self.last_seen = time.time()

@dataclass
class GameEvent:
    timestamp: float
    actor: str
    action: str
    target: str
    result: str

class GameState:
    def __init__(self, player_id: str, name: str, ip: str, port: int):
        self._lock = asyncio.Lock()
        self.self_player = Player(player_id, name, ip, port)
        self.peers: dict[str, Player] = {}
        self.event_log: list[GameEvent] = []

    def log_external_event(self, msg: str):
        """Logs an event that was generated externally (e.g., from main.py)."""
        self._log("system", "EVENT", "all", msg)

    def _log(self, actor: str, action: str, target: str, result: str):
        self.event_log.append(GameEvent(time.time(), actor, action, target, result))
        if len(self.event_log) > 200: self.event_log.pop(0)
        log.info("[%s] %s -> %s: %s", action, actor, target, result)

    def _get_player(self, player_id: str) -> Optional[Player]:
        return self.self_player if player_id == self.self_player.player_id else self.peers.get(player_id)

    async def add_peer(self, player_id: str, name: str, ip: str, port: int, joined_at: float = None):
        async with self._lock:
            if player_id == self.self_player.player_id: return False
            
            is_new = player_id not in self.peers
            if is_new:
                self.peers[player_id] = Player(player_id, name, ip, port, joined_at=joined_at or time.time())
                self._log("system", "JOIN", name, f"{name} entered the realm")
                return True
            
            p = self.peers[player_id]
            # Update name if it was a placeholder
            if p.name in ["Nó_Inicial", "Desconhecido", "Host", "Peer"] and name not in ["Host", "Peer"]:
                p.name = name
            
            if joined_at: p.joined_at = joined_at
            p.touch()
            
            # If the player was dead or inactive, a JOIN event is still useful
            if not p.is_alive():
                p.status = PlayerStatus.ALIVE
                p.hp = MAX_HP
                self._log("system", "REJOIN", name, f"{name} returned to the realm")
                return True
                
            return False

    async def remove_peer(self, player_id: str):
        async with self._lock:
            p = self.peers.pop(player_id, None)
            if p: self._log("system", "LEAVE", p.name, f"{p.name} left")

    async def process_attack(self, sid: str, sname: str, weapon: str) -> tuple[int, str]:
        async with self._lock:
            if not self.self_player.is_alive(): return 0, f"{self.self_player.name} is dead."
            attacker = self.peers.get(sid)
            if attacker:
                if not attacker.is_alive(): return 0, f"{sname} is dead."
                if attacker.position != self.self_player.position: return 0, "Out of range."
            
            dmg = WEAPON_DAMAGE.get(weapon.lower(), 10)
            res = self.self_player.take_damage(dmg, sname)
            self._log(sname, "ATTACK", self.self_player.name, f"{weapon} (-{dmg}HP)")
            return -dmg, res

    async def process_heal(self, sid: str, sname: str, amount: int) -> tuple[int, str]:
        async with self._lock:
            healer = self.peers.get(sid)
            if healer and not healer.is_alive(): return 0, f"{sname} is dead."
            old_hp = self.self_player.hp
            res = self.self_player.heal(amount, sname)
            actual = self.self_player.hp - old_hp
            if actual > 0: self._log(sname, "HEAL", self.self_player.name, f"+{actual} HP")
            return actual, res

    async def process_speak(self, sname: str, text: str) -> str:
        self._log(sname, "SPEAK", "all", text)
        return f"[{sname}] {text}"

    async def process_move(self, sid: str, sname: str, dest: str) -> str:
        async with self._lock:
            p = self._get_player(sid)
            if not p: return f"Unknown player {sname}"
            if not p.is_alive(): return f"Ignored: {sname} is dead."
            res = p.move(dest)
            self._log(sname, "MOVE", dest, res)
            return res

    async def process_join(self, sid: str, sname: str, ip: str, port: int, joined_at: float = None) -> str:
        return f"{sname} joined!" if await self.add_peer(sid, sname, ip, port, joined_at) else ""

    async def process_leave(self, sid: str, sname: str) -> str:
        await self.remove_peer(sid)
        return f"{sname} left"

    async def process_status(self, sid: str, sname: str, payload: str) -> str:
        async with self._lock:
            p = self.peers.get(sid)
            if not p: return ""
            try:
                parts = payload.split(":")
                hp, status, pos = parts[0], parts[1], parts[2]
                p.hp, p.status, p.position = int(hp), PlayerStatus(status), pos
                if len(parts) > 3:
                    try:
                        new_joined = float(parts[3])
                        # Only update if the received joined_at is older than what we have, 
                        # or if our current joined_at was just a placeholder (very recent).
                        if new_joined < p.joined_at or (time.time() - p.joined_at < 10):
                            p.joined_at = new_joined
                    except ValueError: pass
                p.touch()
            except: pass
            return ""

    async def self_heal(self, target_id: str) -> tuple[bool, str]:
        async with self._lock:
            if not self.self_player.is_alive(): return False, "You are dead."
            target = self.peers.get(target_id)
            if not target: return False, "Target not found."
            if not target.is_alive(): return False, f"{target.name} is dead."
            if self.self_player.position != target.position: return False, "Not in same room."
            return True, ""

    async def self_move(self, dest: str) -> tuple[bool, str]:
        async with self._lock:
            if not self.self_player.is_alive(): return False, "You are dead."
            if dest not in POSITIONS: return False, "Unknown location."
            if dest == self.self_player.position: return False, f"Already at {dest}."
            return True, self.self_player.move(dest)

    async def self_respawn(self) -> tuple[bool, str]:
        async with self._lock:
            if self.self_player.is_alive(): return False, "Already alive."
            return True, self.self_player.respawn()
        
    async def self_attack(self, target_id: str, weapon: str):
        async with self._lock:
            if not self.self_player.is_alive(): return False, "You are dead."
            target = self.peers.get(target_id)
            if not target: return False, "Target not found."
            if not target.is_alive(): return False, f"{target.name} is dead."
            if self.self_player.position != target.position: return False, "Not in same room."
            return True, ""

    async def get_world_state_json(self) -> str:
        async with self._lock:
            all_p = [self._player_to_dict(self.self_player)] + [self._player_to_dict(p) for p in self.peers.values()]
            return json.dumps(all_p)

    def _player_to_dict(self, p: Player):
        return {"player_id": p.player_id, "name": p.name, "ip": p.ip, "port": p.port,
                "hp": p.hp, "status": p.status.value, "position": p.position,
                "joined_at": p.joined_at}

    async def apply_world_state(self, json_data: str, dht=None):
        data = json.loads(json_data)
        async with self._lock:
            for d in data:
                pid = d["player_id"]
                if pid == self.self_player.player_id: continue
                self.peers[pid] = Player(pid, d["name"], d["ip"], d["port"], d["hp"], 
                                         PlayerStatus(d["status"]), d["position"], 
                                         joined_at=d.get("joined_at", time.time()))
                if dht:
                    from dht.kademlia import NodeInfo
                    dht.add_peer(NodeInfo(pid, d["ip"], d["port"], d["name"]))
            self._log("system", "SYNC", "world", "World synchronized")

    async def clean_inactive_peers(self, timeout: int = 15):
        async with self._lock:
            now = time.time()
            dead = [pid for pid, p in self.peers.items() if now - p.last_seen > timeout]
            for pid in dead:
                name = self.peers[pid].name
                del self.peers[pid]
                self._log("system", "TIMEOUT", name, f"{name} disappeared")
            return len(dead) > 0

    def status_board(self) -> str:
        p, leader_id = self.self_player, self.get_leader_id()
        is_leader = " ⭐" if p.player_id == leader_id else ""
        lines = ["="*50, f"  ⚔  REALM OF ASYNCIO  ⚔", "="*50,
                 f"  {'💚' if p.is_alive() else '💀'} YOU  {p.name + is_leader:<16} HP {p.hp:>3}/{MAX_HP}  📍{p.position}"]
        if self.peers:
            lines.append("-" * 50)
            for pid, peer in self.peers.items():
                is_p_leader = " ⭐" if pid == leader_id else ""
                lines.append(f"  {'💚' if peer.is_alive() else '💀'}     {peer.name + is_p_leader:<16} HP {peer.hp:>3}/{MAX_HP}  📍{peer.position}")
        lines.append("="*50)
        return "\n".join(lines)

    def recent_events(self, n: int = 8) -> list[str]:
        output = []
        for e in self.event_log[-n:]:
            tm = time.strftime("%H:%M:%S", time.localtime(e.timestamp))
            if e.action == "EVENT":
                output.append(f"  [{tm}] {e.result}")
            else:
                output.append(f"  [{tm}] {e.actor} {e.action}({e.target}): {e.result}")
        return output

    def get_room_occupants(self) -> dict[str, list[str]]:
        rooms = {pos: [] for pos in POSITIONS}
        rooms[self.self_player.position].append(f"{self.self_player.name} (TU)")
        for p in self.peers.values():
            rooms[p.position].append(f"{p.name}{'' if p.is_alive() else ' [MORTO]'}")
        return rooms

    def get_leader_id(self) -> str:
        """O líder é o nó ativo mais antigo (seniority) ou com menor ID em caso de empate."""
        candidates = [self.self_player.player_id] + list(self.peers.keys())
        if not candidates: return self.self_player.player_id
        
        def sort_key(pid):
            p = self._get_player(pid)
            # Priorizamos o tempo de entrada (menor timestamp = mais antigo)
            return (p.joined_at if p else float('inf'), pid)
            
        return min(candidates, key=sort_key)
