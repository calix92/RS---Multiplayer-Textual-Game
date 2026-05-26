import asyncio
import argparse
import logging
import socket
from game.state import GameState
from dht.kademlia import DHTNode, NodeInfo, node_id_from
from network.server import start_server
from network.client import BroadcastClient, PeerClient
from utils.terminal import Terminal
from utils.net_utils import get_local_ip

logging.basicConfig(level=logging.WARNING)

async def maintenance_loop(player_id, name, ip, port, state, dht, client, terminal):
    """Mantém a rede viva e reconecta se necessário."""
    try:
        while True:
            await asyncio.sleep(20)
            # Re-anuncia a nossa presença
            await client.announce_join(player_id, name, ip, port)
            
            for peer in dht.all_peers():
                if peer.node_id != player_id:
                    try:
                        c = client._get_client(peer)
                        ok = await c.ping(player_id)
                        if not ok:
                            # terminal.push_event(f"⚠️ Ligação perdida a {peer.name} ({peer.ip})")
                            pass
                    except: pass
            await state.clean_inactive_peers(timeout=100)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Error in maintenance_loop: {e}")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--ip", default=None, help="O teu IP (se omitido, tenta auto-detetar)")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--bootstrap", type=str, help="IP:Porta de outro jogador (ex: 192.168.1.10:50051)")
    args = parser.parse_args()

    my_ip = args.ip if args.ip else get_local_ip()
    
    player_id = node_id_from(my_ip, args.port)
    state = GameState(player_id, args.name, my_ip, args.port)
    dht = DHTNode(my_ip, args.port, args.name)
    client = BroadcastClient(dht)
    terminal = Terminal(state, None)
    
    server = await start_server(my_ip, args.port, state, dht, terminal.push_event)

    terminal.push_event(f"🚀 Servidor iniciado em {my_ip}:{args.port}")
    if my_ip == "127.0.0.1":
        terminal.push_event("⚠️  AVISO: Estás a usar 127.0.0.1. Outros jogadores não conseguirão ligar-se a ti!")

    async def action_handler(cmd_raw, args_str):
        cmd = cmd_raw.lower().strip()
        if cmd in ("quit", "exit"): pass
        elif cmd == "ping":
            target = next((p for p in state.peers.values() if p.name.lower() == args_str.lower()), None)
            if target:
                terminal.push_event(f"📡 A testar ligação a {target.name} em {target.ip}:{target.port}...")
                ok = await client._get_client(NodeInfo(target.player_id, target.ip, target.port)).ping(player_id)
                terminal.push_event(f"Resultado para {target.name}: {'✅ OK' if ok else '❌ FALHA (Verifica a Firewall!)'}")
            else: terminal.push_event("Jogador não encontrado para ping.")
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
            await client.announce_join(player_id, args.name, my_ip, args.port)
        elif cmd == "peers":
            terminal.push_event(f"DHT: {', '.join([p.name for p in dht.all_peers()])}")
        elif cmd == "debug":
            terminal.push_event(f"O teu ID: {player_id[:12]}...")
            terminal.push_event(f"O teu IP: {my_ip}:{args.port}")

    terminal.handler = action_handler

    if args.bootstrap:
        try:
            b_ip, b_port = args.bootstrap.split(":")
            terminal.push_event(f"🔗 A tentar ligar ao Host {b_ip}:{b_port}...")
            b_id = node_id_from(b_ip, int(b_port))
            b_node = NodeInfo(b_id, b_ip, int(b_port), "Host")
            
            # Testa ping antes de tentar sync
            c = PeerClient(b_ip, int(b_port))
            ok = await c.ping(player_id)
            if ok:
                dht.add_peer(b_node)
                await state.add_peer(b_id, "Host", b_ip, int(b_port))
                world = await client.sync_with_host(b_node)
                if world: 
                    await state.apply_world_state(world, dht)
                    terminal.push_event("✅ Sincronização concluída com sucesso.")
                else:
                    terminal.push_event("⚠️ Falha ao sincronizar mundo, mas o nó foi adicionado.")
            else:
                terminal.push_event(f"❌ Não foi possível alcançar o Host {b_ip}:{b_port}.")
            await c.close()
        except Exception as e:
            terminal.push_event(f"❌ Erro no bootstrap: {e}")
    
    await client.announce_join(player_id, args.name, my_ip, args.port)
    m_task = asyncio.create_task(maintenance_loop(player_id, args.name, my_ip, args.port, state, dht, client, terminal))
    
    try:
        await terminal.run_loop()
    finally:
        m_task.cancel()
        try:
            await asyncio.wait_for(client.announce_leave(player_id, args.name), timeout=1.0)
        except: pass
        await server.stop(0)
        await client.close_all()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
