import asyncio
import argparse
import logging
from game.state import GameState
from dht.kademlia import DHTNode, NodeInfo, node_id_from
from network.server import start_server
from network.client import BroadcastClient, PeerClient
from utils.terminal import Terminal

logging.basicConfig(level=logging.ERROR)

async def maintenance_loop(player_id, name, ip, port, state, dht, client):
    """Mantém a rede viva e reconecta se necessário."""
    while True:
        try:
            await asyncio.sleep(20)
            # Re-anuncia a nossa presença
            await client.announce_join(player_id, name, ip, port)
            
            for peer in dht.all_peers():
                if peer.node_id != player_id:
                    try:
                        c = PeerClient(peer.ip, peer.port)
                        await c.ping(player_id)
                        await c.close()
                    except: pass
            await state.clean_inactive_peers(timeout=100)
        except: pass

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--bootstrap", type=str)
    args = parser.parse_args()

    player_id = node_id_from(args.ip, args.port)
    state = GameState(player_id, args.name, args.ip, args.port)
    dht = DHTNode(args.ip, args.port, args.name)
    client = BroadcastClient(dht)
    terminal = Terminal(state, None)
    
    # IMPORTANTE: Guardar a variável 'server' para não ser apagada!
    server = await start_server(args.ip, args.port, state, dht, terminal.push_event)

    async def action_handler(cmd_raw, args_str):
        cmd = cmd_raw.lower().strip()
        if cmd in ("quit", "exit"):
            await client.announce_leave(player_id, args.name)
            await server.stop(0)
            exit(0)
        elif cmd == "say":
            terminal.push_event(f"[{args.name}] {args_str}")
            await client.broadcast(player_id, args.name, 2, args_str)
        elif cmd == "move":
            res = await state.self_move(args_str)
            terminal.push_event(res)
            await client.broadcast(player_id, args.name, 1, args_str)
        elif cmd == "attack":
            target = next((p for p in state.peers.values() if p.name.lower() == args_str.split()[0].lower()), None)
            if target:
                ok, err = await state.self_attack(target.player_id, "sword")
                if ok:
                    terminal.push_event(f"Atacaste {target.name}!")
                    await client.send_to(NodeInfo(target.player_id, target.ip, target.port, target.name), player_id, args.name, 0, "sword")
                else: terminal.push_event(f"Erro: {err}")
            else: terminal.push_event("Alvo não encontrado ou noutra zona.")
        elif cmd == "heal":
            target = next((p for p in state.peers.values() if p.name.lower() == args_str.lower()), None)
            if target:
                await client.send_to(NodeInfo(target.player_id, target.ip, target.port, target.name), player_id, args.name, 3, "15")
                terminal.push_event(f"Curaste {target.name}!")
        elif cmd == "respawn":
            await state.self_respawn()
            await client.announce_join(player_id, args.name, args.ip, args.port)
        elif cmd == "peers":
            terminal.push_event(f"DHT: {', '.join([p.name for p in dht.all_peers()])}")

    terminal.handler = action_handler

    if args.bootstrap:
        try:
            b_ip, b_port = args.bootstrap.split(":")
            b_id = node_id_from(b_ip, int(b_port))
            b_node = NodeInfo(b_id, b_ip, int(b_port), "Host")
            dht.add_peer(b_node)
            await state.add_peer(b_id, "Host", b_ip, int(b_port))
            world = await client.sync_with_host(b_node)
            if world: await state.apply_world_state(world)
        except: pass
    
    await client.announce_join(player_id, args.name, args.ip, args.port)
    asyncio.create_task(maintenance_loop(player_id, args.name, args.ip, args.port, state, dht, client))
    await terminal.run_loop()

if __name__ == "__main__":
    asyncio.run(main())
