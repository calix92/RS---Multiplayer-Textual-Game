
import asyncio
import unittest
from game.state import GameState, PlayerStatus
from dht.kademlia import DHTNode, NodeInfo, node_id_from
from network.server import start_server
from network.client import BroadcastClient
import time

class TestGameRequirements(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Setup 3 nodes to simulate a small P2P network
        self.nodes = []
        self.configs = [
            ("Node1", "127.0.0.1", 50051),
            ("Node2", "127.0.0.1", 50052),
            ("Node3", "127.0.0.1", 50053),
        ]
        
        for name, ip, port in self.configs:
            pid = node_id_from(ip, port)
            state = GameState(pid, name, ip, port)
            dht = DHTNode(ip, port, name)
            client = BroadcastClient(dht)
            
            # Use a dummy on_event
            server = await start_server(ip, port, state, dht, lambda x: None)
            
            self.nodes.append({
                "pid": pid,
                "name": name,
                "state": state,
                "dht": dht,
                "client": client,
                "server": server
            })

    async def asyncTearDown(self):
        for node in self.nodes:
            await node["server"].stop(0)
            await node["client"].close_all()

    async def test_p2p_connectivity(self):
        # Node 2 joins Node 1
        n1, n2 = self.nodes[0], self.nodes[1]
        await n2["state"].add_peer(n1["pid"], n1["name"], "127.0.0.1", 50051)
        n2["dht"].add_peer(NodeInfo(n1["pid"], "127.0.0.1", 50051, n1["name"]))
        
        # Node 2 announces join to Node 1
        await n2["client"].announce_join(n2["pid"], n2["name"], "127.0.0.1", 50052)
        
        # Give some time for async processing
        await asyncio.sleep(0.5)
        
        # Check if Node 1 knows about Node 2
        self.assertIn(n2["pid"], n1["state"].peers)
        self.assertEqual(n1["state"].peers[n2["pid"]].name, "Node2")

    async def test_concurrent_attacks(self):
        # N1 and N3 attack N2 concurrently
        n1, n2, n3 = self.nodes[0], self.nodes[1], self.nodes[2]
        
        # Setup peering
        for n in [n1, n3]:
            await n["state"].add_peer(n2["pid"], n2["name"], "127.0.0.1", 50052)
            n["dht"].add_peer(NodeInfo(n2["pid"], "127.0.0.1", 50052, n2["name"]))

        target_info = NodeInfo(n2["pid"], "127.0.0.1", 50052, n2["name"])
        
        # Perform concurrent attacks
        tasks = [
            n1["client"].send_to(target_info, n1["pid"], n1["name"], 0, "sword"),
            n3["client"].send_to(target_info, n3["pid"], n3["name"], 0, "axe")
        ]
        
        await asyncio.gather(*tasks)
        
        # N2 should have lost 10 (sword) + 15 (axe) = 25 HP
        self.assertEqual(n2["state"].self_player.hp, 100 - 10 - 15)

    async def test_dht_find_node(self):
        # Node 1 knows Node 2, Node 2 knows Node 3
        n1, n2, n3 = self.nodes[0], self.nodes[1], self.nodes[2]
        
        n1["dht"].add_peer(NodeInfo(n2["pid"], "127.0.0.1", 50052, n2["name"]))
        n2["dht"].add_peer(NodeInfo(n3["pid"], "127.0.0.1", 50053, n3["name"]))
        
        # Node 1 asks Node 2 for Node 3
        res = await n1["client"]._get_client(NodeInfo(n2["pid"], "127.0.0.1", 50052)).find_node(n3["pid"], n1["pid"])
        
        # Node 3 should be in the results returned by Node 2
        self.assertTrue(any(node.node_id == n3["pid"] for node in res))

if __name__ == "__main__":
    unittest.main()
