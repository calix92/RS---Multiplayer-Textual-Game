"""
dht/kademlia.py
~~~~~~~~~~~~~~~
Simplified Kademlia-inspired DHT for peer discovery.

Each node has a 160-bit (20-byte) Node ID derived from SHA-1 of
"ip:port". Nodes are stored in k-buckets (k=8) organised by XOR distance.
Lookups do an iterative FIND_NODE until the closest k nodes are found.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("dht")

K = 8          # k-bucket size
ALPHA = 3      # concurrency factor for lookups
ID_BITS = 160  # SHA-1 length


# ─── Helpers ──────────────────────────────────────────────────────────────────

def node_id_from(ip: str, port: int) -> str:
    """Derive a deterministic 160-bit hex node ID."""
    raw = f"{ip}:{port}".encode()
    return hashlib.sha1(raw).hexdigest()


def xor_distance(a: str, b: str) -> int:
    return int(a, 16) ^ int(b, 16)


def bucket_index(own_id: str, other_id: str) -> int:
    """Return which k-bucket (0–159) this node belongs to."""
    dist = xor_distance(own_id, other_id)
    if dist == 0:
        return 0
    return dist.bit_length() - 1


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class NodeInfo:
    node_id: str
    ip: str
    port: int
    name: str = ""

    def __eq__(self, other):
        return isinstance(other, NodeInfo) and self.node_id == other.node_id

    def __hash__(self):
        return hash(self.node_id)

    def address(self) -> str:
        return f"{self.ip}:{self.port}"


@dataclass
class KBucket:
    nodes: list[NodeInfo] = field(default_factory=list)

    def add(self, node: NodeInfo) -> bool:
        """Insert or refresh node. Returns True if added."""
        # Already present → move to tail (most recently seen)
        if node in self.nodes:
            self.nodes.remove(node)
            self.nodes.append(node)
            return False
        if len(self.nodes) < K:
            self.nodes.append(node)
            return True
        # Bucket full → drop (no eviction strategy for simplicity)
        log.debug("k-bucket full, dropping %s", node.node_id[:8])
        return False

    def remove(self, node_id: str):
        self.nodes = [n for n in self.nodes if n.node_id != node_id]

    def closest(self, target_id: str, count: int = K) -> list[NodeInfo]:
        return sorted(self.nodes, key=lambda n: xor_distance(n.node_id, target_id))[:count]


# ─── Routing Table ────────────────────────────────────────────────────────────

class RoutingTable:
    def __init__(self, own_id: str):
        self.own_id = own_id
        self.buckets: list[KBucket] = [KBucket() for _ in range(ID_BITS)]

    def add(self, node: NodeInfo):
        if node.node_id == self.own_id:
            return
        idx = bucket_index(self.own_id, node.node_id)
        self.buckets[idx].add(node)

    def remove(self, node_id: str):
        idx = bucket_index(self.own_id, node_id)
        self.buckets[idx].remove(node_id)

    def find_closest(self, target_id: str, count: int = K) -> list[NodeInfo]:
        """Return the `count` nodes closest (XOR) to target_id."""
        all_nodes: list[NodeInfo] = []
        for bucket in self.buckets:
            all_nodes.extend(bucket.nodes)
        return sorted(all_nodes, key=lambda n: xor_distance(n.node_id, target_id))[:count]

    def all_nodes(self) -> list[NodeInfo]:
        nodes = []
        for b in self.buckets:
            nodes.extend(b.nodes)
        return nodes

    def size(self) -> int:
        return sum(len(b.nodes) for b in self.buckets)


# ─── DHT Node ─────────────────────────────────────────────────────────────────

class DHTNode:
    """
    High-level DHT logic.  Network I/O is delegated to the gRPC layer
    (network/server.py calls dht.on_find_node / dht.on_store_node).
    """

    def __init__(self, ip: str, port: int, name: str = ""):
        self.node_id = node_id_from(ip, port)
        self.info = NodeInfo(self.node_id, ip, port, name)
        self.routing_table = RoutingTable(self.node_id)
        log.info("DHT node %s  id=%s", self.info.address(), self.node_id[:12])

    # ── Routing table operations ───────────────────────────────────────────

    def add_peer(self, info: NodeInfo):
        self.routing_table.add(info)
        log.debug("Added peer %s (%s)", info.name or info.node_id[:8], info.address())

    def remove_peer(self, node_id: str):
        self.routing_table.remove(node_id)

    def find_closest(self, target_id: str, count: int = K) -> list[NodeInfo]:
        return self.routing_table.find_closest(target_id, count)

    def all_peers(self) -> list[NodeInfo]:
        return self.routing_table.all_nodes()

    # ── Bootstrap ─────────────────────────────────────────────────────────

    async def bootstrap(self, stub_factory, bootstrap_nodes: list[tuple[str, int]]):
        """
        Join the network by contacting bootstrap_nodes and performing
        a FIND_NODE lookup for our own ID to populate our routing table.
        """
        for ip, port in bootstrap_nodes:
            peer_id = node_id_from(ip, port)
            peer = NodeInfo(peer_id, ip, port)
            try:
                stub = stub_factory(ip, port)
                resp = await stub.Ping({"sender_id": self.node_id})
                if resp.alive:
                    self.add_peer(peer)
                    log.info("Bootstrap contact %s:%d  OK", ip, port)
                    # Ask it for nodes close to us
                    fn_resp = await stub.FindNode({
                        "target_id": self.node_id,
                        "requester_id": self.node_id,
                    })
                    for n in fn_resp.closest_nodes:
                        self.add_peer(NodeInfo(n.node_id, n.ip, n.port, n.name))
            except Exception as exc:
                log.warning("Bootstrap %s:%d failed: %s", ip, port, exc)

    # ── RPC handlers (called by gRPC servicer) ────────────────────────────

    def on_find_node(self, target_id: str, requester_id: str) -> list[NodeInfo]:
        """Return K closest nodes to target_id."""
        return self.find_closest(target_id)

    def on_store_node(self, info: NodeInfo) -> bool:
        self.add_peer(info)
        return True

    def on_ping(self) -> bool:
        return True