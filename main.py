import asyncio
import argparse
import logging
import socket
import sys
import os
from game.state import GameState
from dht.kademlia import DHTNode, NodeInfo, node_id_from
try:
    from proto import game_pb2
except ImportError:
    game_pb2 = None
from network.server import start_server
from network.client import BroadcastClient, PeerClient
from utils.terminal import Terminal

# Silenciar logs técnicos do gRPC e C++
os.environ['GRPC_VERBOSITY'] = 'NONE'
os.environ['GLOG_minloglevel'] = '3'

logging.basicConfig(level=logging.CRITICAL)

def get_lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0)
            s.connect(('8.8.8.8', 1))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."): return ip
    except: pass
    for target in ["10.255.255.255", "192.168.1.255"]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target, 1))
                ip = s.getsockname()[0]
                if ip and not ip.startswith("127."): return ip
        except: continue
    return "127.0.0.1"

async def maintenance_loop(player_id, name, ip, port, state, dht, client):
    try:
        while True:
            await asyncio.sleep(5)
            p = state.self_player
            await client.announce_status(player_id, name, p.hp, p.status.value, p.position, p.joined_at)
            for peer in dht.all_peers():
                if peer.node_id != player_id:
                    try: await client._get_client(peer).ping(player_id)
                    except: pass
            await state.clean_inactive_peers(timeout=100)
    except asyncio.CancelledError: pass
    except Exception as e: logging.error(f"Maintenance error: {e}")

async def main():
    detected_ip = get_lan_ip()
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--ip", default=detected_ip)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--bootstrap", type=str)
    args = parser.parse_args()

    if args.ip == "127.0.0.1":
        print("\033[91m[CRITICAL]\033[0m IP is 127.0.0.1. Use --ip to set LAN IP.")

    player_id = node_id_from(args.ip, args.port)
    state, dht = GameState(player_id, args.name, args.ip, args.port), DHTNode(args.ip, args.port, args.name)
    client, terminal = BroadcastClient(dht), Terminal(state, None)
    server = await start_server(args.ip, args.port, state, dht, terminal.push_event)

    async def action_handler(cmd_raw, args_str):
        cmd = cmd_raw.lower().strip()
        if cmd == "ping":
            target = next((p for p in state.peers.values() if p.name.lower() == args_str.lower()), None)
            if target:
                terminal.push_event(f"Pinging {target.name}...")
                ok = await client._get_client(NodeInfo(target.player_id, target.ip, target.port)).ping(player_id)
                terminal.push_event(f"{target.name}: {'✅ OK' if ok else '❌ FAIL'}")
        elif cmd == "say":
            terminal.push_event(f"[{args.name}] {args_str}")
            await client.broadcast(player_id, args.name, game_pb2.SPEAK, args_str)
        elif cmd == "move":
            ok, msg = await state.self_move(args_str)
            terminal.push_event(msg)
            if ok: await client.broadcast(player_id, args.name, game_pb2.MOVE, args_str)
        elif cmd == "attack":
            target = next((p for p in state.peers.values() if p.name.lower() == args_str.split()[0].lower()), None) if args_str else None
            weapon = args_str.split()[1] if args_str and len(args_str.split()) > 1 else "sword"
            if target:
                ok, err = await state.self_attack(target.player_id, weapon)
                if ok:
                    terminal.push_event(f"Attacked {target.name} with {weapon}!")
                    await client.broadcast(player_id, args.name, game_pb2.SPEAK, f"Attacked {target.name} with {weapon}!")
                    await client.send_to(NodeInfo(target.player_id, target.ip, target.port, target.name), player_id, args.name, game_pb2.ATTACK, weapon)
                else: terminal.push_event(f"Error: {err}")
            else: terminal.push_event("Target not found.")
        elif cmd == "heal":
            target = next((p for p in state.peers.values() if p.name.lower() == args_str.lower()), None)
            if target:
                ok, err = await state.self_heal(target.player_id)
                if ok:
                    await client.send_to(NodeInfo(target.player_id, target.ip, target.port, target.name), player_id, args.name, game_pb2.HEAL, "15")
                    terminal.push_event(f"Healed {target.name}!")
                    await client.broadcast(player_id, args.name, game_pb2.SPEAK, f"Healed {target.name}!")
                else: terminal.push_event(f"Error: {err}")
        elif cmd == "respawn":
            ok, msg = await state.self_respawn()
            terminal.push_event(msg)
            if ok: await client.announce_join(player_id, args.name, args.ip, args.port)
        elif cmd == "peers":
            peers = dht.all_peers()
            if peers: terminal.push_event(f"DHT: {', '.join([f'{p.name} ({p.ip}:{p.port})' for p in peers])}")
            g_peers = [f"{p.name} ({p.ip}:{p.port})" for p in state.peers.values()]
            if g_peers: terminal.push_event(f"Game: {', '.join(g_peers)}")

    terminal.handler = action_handler
    if args.bootstrap:
        try:
            b_ip, b_port = args.bootstrap.split(":") if ":" in args.bootstrap else (args.bootstrap, 50051)
            b_id = node_id_from(b_ip, int(b_port))
            b_node = NodeInfo(b_id, b_ip, int(b_port), "Host")
            dht.add_peer(b_node)
            await state.add_peer(b_id, "Host", b_ip, int(b_port))
            world = await client.sync_with_host(b_node)
            if world: await state.apply_world_state(world, dht)
            await dht.bootstrap(lambda ip, pt: client._get_client(NodeInfo("", ip, pt)), [(b_ip, int(b_port))])
        except Exception as e: terminal.push_event(f"Bootstrap error: {e}")
    
    await client.announce_join(player_id, args.name, args.ip, args.port)
    m_task = asyncio.create_task(maintenance_loop(player_id, args.name, args.ip, args.port, state, dht, client))
    try: await terminal.run_loop()
    finally:
        m_task.cancel()
        try: await asyncio.wait_for(client.announce_leave(player_id, args.name), timeout=2.0)
        except: pass
        await server.stop(0)
        await client.close_all()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
