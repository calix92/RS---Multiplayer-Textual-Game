import asyncio
import argparse
import logging
import socket
import sys
from game.state import GameState
from dht.kademlia import DHTNode, NodeInfo, node_id_from
from network.server import start_server
from network.client import BroadcastClient, PeerClient
from utils.terminal import Terminal

logging.basicConfig(level=logging.WARNING)

def get_lan_ip():
    """Tenta descobrir o IP da rede local de forma robusta."""
    try:
        # Tenta conectar a um IP externo (não envia dados) para ver qual interface o SO usa
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0)
            s.connect(('8.8.8.8', 1))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass

    # Fallback para interfaces comuns
    for target in ["10.255.255.255", "192.168.1.255"]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target, 1))
                ip = s.getsockname()[0]
                if ip and not ip.startswith("127."):
                    return ip
        except Exception:
            continue
    
    return "127.0.0.1"

async def maintenance_loop(player_id, name, ip, port, state, dht, client):
    """Mantém a rede viva e reconecta se necessário."""
    try:
        while True:
            await asyncio.sleep(20)
            # Re-anuncia a nossa presença
            await client.announce_join(player_id, name, ip, port)
            
            for peer in dht.all_peers():
                if peer.node_id != player_id:
                    try:
                        # Reutiliza o cliente do BroadcastClient para aproveitar o Keepalive
                        c = client._get_client(peer)
                        await c.ping(player_id)
                    except: pass
            await state.clean_inactive_peers(timeout=100)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Error in maintenance_loop: {e}")

async def main():
    detected_ip = get_lan_ip()
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--ip", default=detected_ip, help=f"O teu IP (detetado: {detected_ip})")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--bootstrap", type=str, help="IP:Porta do nó de entrada")
    args = parser.parse_args()

    # Se o IP detetado for 127.0.0.1, dar um aviso sério
    if args.ip == "127.0.0.1":
        print("\033[91m[AVISO CRÍTICO]\033[0m O teu IP foi detetado como 127.0.0.1.")
        print("Isto acontece quando não há uma interface de rede ativa ou sem rota por defeito.")
        print("Se estás num Hotspot, tenta ligar o Wi-Fi ou Dados Móveis.")
        print("Podes forçar o IP com: --ip <teu_ip_na_rede>\n")
    
    print("\033[94m[DICA]\033[0m Se não conseguires ligar ao teu colega:")
    print("1. Verifica se a Firewall do Windows/Linux está a bloquear a porta", args.port)
    print("2. Alguns Hotspots têm 'Isolamento de AP' que impede a comunicação entre dispositivos.")
    print("3. Garante que ambos estão na MESMA rede Wi-Fi.\n")

    player_id = node_id_from(args.ip, args.port)
    state = GameState(player_id, args.name, args.ip, args.port)
    dht = DHTNode(args.ip, args.port, args.name)
    client = BroadcastClient(dht)
    terminal = Terminal(state, None)
    
    # IMPORTANTE: Guardar a variável 'server' para não ser apagada!
    server = await start_server(args.ip, args.port, state, dht, terminal.push_event)

    print(f"\n--- CONFIGURAÇÃO DE REDE ---")
    print(f"O teu nome: {args.name}")
    print(f"O teu IP: {args.ip}")
    print(f"A ouvir na porta: {args.port}")
    print(f"ID do Jogador: {player_id[:12]}...")
    if args.bootstrap:
        print(f"A tentar ligar ao Bootstrap: {args.bootstrap}")
    print(f"----------------------------\n")

    async def action_handler(cmd_raw, args_str):
        cmd = cmd_raw.lower().strip()
        if cmd in ("quit", "exit"):
            pass
        elif cmd == "ping":
            target = next((p for p in state.peers.values() if p.name.lower() == args_str.lower()), None)
            if target:
                terminal.push_event(f"A testar ligação a {target.name} ({target.ip}:{target.port})...")
                ok = await client._get_client(NodeInfo(target.player_id, target.ip, target.port)).ping(player_id)
                terminal.push_event(f"Resultado para {target.name}: {'✅ OK' if ok else '❌ FALHA'}")
            else: terminal.push_event("Jogador não encontrado para ping.")
        elif cmd == "say":
            terminal.push_event(f"[{args.name}] {args_str}")
            await client.broadcast(player_id, args.name, 2, args_str)
        elif cmd == "move":
            res = await state.self_move(args_str)
            terminal.push_event(res)
            await client.broadcast(player_id, args.name, 1, args_str)
        elif cmd == "attack":
            target_name = args_str.split()[0] if args_str else ""
            weapon = args_str.split()[1] if len(args_str.split()) > 1 else "sword"
            target = next((p for p in state.peers.values() if p.name.lower() == target_name.lower()), None)
            if target:
                ok, err = await state.self_attack(target.player_id, weapon)
                if ok:
                    terminal.push_event(f"Atacaste {target.name} com {weapon}!")
                    await client.broadcast(player_id, args.name, 2, f"Atacou {target.name} com {weapon}!")
                    await client.send_to(NodeInfo(target.player_id, target.ip, target.port, target.name), player_id, args.name, 0, weapon)
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
        elif cmd == "find":
            if not args_str:
                terminal.push_event("Uso: find <player_id>")
                return
            terminal.push_event(f"A procurar {args_str[:8]} na DHT...")
            closest = dht.find_closest(args_str)
            if closest:
                results = ", ".join([f"{n.name} ({n.ip}:{n.port})" for n in closest])
                terminal.push_event(f"Nós mais próximos encontrados: {results}")
            else:
                terminal.push_event("Nenhum nó encontrado na DHT.")
        elif cmd == "peers":
            peers = dht.all_peers()
            if not peers:
                terminal.push_event("Nenhum nó conhecido na DHT.")
            else:
                p_list = [f"{p.name} ({p.ip}:{p.port})" for p in peers]
                terminal.push_event(f"DHT ({len(peers)} nós): {', '.join(p_list)}")
            
            # Mostrar também os peers no estado do jogo
            g_peers = [f"{p.name} ({p.ip}:{p.port})" for p in state.peers.values()]
            if g_peers:
                terminal.push_event(f"Jogo ({len(g_peers)} ativos): {', '.join(g_peers)}")

    terminal.handler = action_handler

    if args.bootstrap:
        try:
            if ":" in args.bootstrap:
                b_ip, b_port = args.bootstrap.split(":")
                b_port = int(b_port)
            else:
                b_ip = args.bootstrap
                b_port = 50051 # Porta por defeito
                terminal.push_event(f"Aviso: Porta não especificada no bootstrap, a usar {b_port}")
            
            b_id = node_id_from(b_ip, b_port)
            b_node = NodeInfo(b_id, b_ip, b_port, "Host")
            
            dht.add_peer(b_node)
            await state.add_peer(b_id, "Host", b_ip, int(b_port))
            
            world = await client.sync_with_host(b_node)
            if world: 
                await state.apply_world_state(world, dht)
                terminal.push_event(f"Sincronização com {args.bootstrap} OK")
            else:
                terminal.push_event(f"Aviso: Não foi possível sincronizar o estado inicial.")
            
            def stub_factory(ip, port):
                return client._get_client(NodeInfo("", ip, port))
            
            await dht.bootstrap(stub_factory, [(b_ip, int(b_port))])
            terminal.push_event(f"Bootstrap da DHT concluído.")
        except Exception as e:
            terminal.push_event(f"Erro no bootstrap: {e}")
    
    await client.announce_join(player_id, args.name, args.ip, args.port)
    m_task = asyncio.create_task(maintenance_loop(player_id, args.name, args.ip, args.port, state, dht, client))
    
    try:
        await terminal.run_loop()
    finally:
        m_task.cancel()
        try:
            await asyncio.wait_for(client.announce_leave(player_id, args.name), timeout=2.0)
        except: pass
        
        await server.stop(0)
        await client.close_all()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
