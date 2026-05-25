import asyncio
import argparse
import logging
from game.state import GameState
from dht.kademlia import DHTNode, NodeInfo, node_id_from
from network.server import start_server
from network.client import BroadcastClient, PeerClient
from utils.terminal import Terminal

logging.basicConfig(level=logging.ERROR)
log = logging.getLogger("main")

async def peer_monitor_loop(state):
    """Tarefa que corre em background para limpar jogadores inativos."""
    while True:
        try:
            await asyncio.sleep(10) # Verifica a cada 10 segundos
            # Aumentamos o timeout para 60 segundos para ser menos agressivo
            await state.clean_inactive_peers(timeout=60)
        except Exception as e:
            logging.error(f"Erro no monitor de peers: {e}")

async def heartbeat_loop(player_id, dht, client):
    """Envia um ping a todos os peers conhecidos para manter a ligação viva."""
    while True:
        try:
            await asyncio.sleep(20) # Ping a cada 20 segundos
            peers = dht.all_peers()
            for peer in peers:
                if peer.node_id != player_id:
                    # Usamos o PeerClient diretamente para um ping simples
                    p_client = PeerClient(peer.ip, peer.port)
                    await p_client.ping(player_id)
                    await p_client.close()
        except Exception as e:
            log.debug(f"Erro no heartbeat: {e}")

async def main():
    parser = argparse.ArgumentParser(description="P2P Text RPG")
    parser.add_argument("--name", required=True, help="Nome do jogador")
    parser.add_argument("--ip", default="127.0.0.1", help="Endereço IP local")
    parser.add_argument("--port", type=int, required=True, help="Porta local do gRPC")
    parser.add_argument("--bootstrap", type=str, help="IP:Porta de um nó existente para entrada na rede")
    args = parser.parse_args()

    player_id = node_id_from(args.ip, args.port)
    state = GameState(player_id, args.name, args.ip, args.port)
    dht = DHTNode(args.ip, args.port, args.name)
    client = BroadcastClient(dht)
    
    terminal = Terminal(state, None)
    
    def on_event(msg: str):
        terminal.push_event(msg)

    server = await start_server(args.ip, args.port, state, dht, on_event)

    async def action_handler(cmd_raw: str, args_str: str):
        cmd = cmd_raw.lower().strip()
        
        if cmd == "quit" or cmd == "exit":
            await client.announce_leave(player_id, args.name)
            await client.close_all()
            await server.stop(0)
            
        elif cmd == "say":
            await client.broadcast(player_id, args.name, 2, args_str)
            
        elif cmd == "move":
            await state.self_move(args_str)
            await client.broadcast(player_id, args.name, 1, args_str)
            
        elif cmd == "attack":
            parts = args_str.split(" ")
            target_name = parts[0]
            weapon = parts[1] if len(parts) > 1 else "sword"
            
            # Procurar o alvo nos PEERS do jogo (mais fiável que a DHT direta)
            target_player = next((p for p in state.peers.values() if p.name.lower() == target_name.lower()), None)
            
            if target_player:
                can_attack, error_msg = await state.self_attack(target_player.player_id, weapon)
                
                if can_attack:
                    # Encontrar a info do nó para enviar o gRPC
                    target_node = NodeInfo(target_player.player_id, target_player.ip, target_player.port, target_player.name)
                    await client.send_to(target_node, player_id, args.name, 0, weapon)
                else:
                    terminal.push_event(f"Falha: {error_msg}")
            else:
                terminal.push_event(f"Jogador '{target_name}' não encontrado ou está noutra zona.")
                
        elif cmd == "heal":
            target_name = args_str.strip()
            target_player = next((p for p in state.peers.values() if p.name.lower() == target_name.lower()), None)
            
            if target_player:
                target_node = NodeInfo(target_player.player_id, target_player.ip, target_player.port, target_player.name)
                await client.send_to(target_node, player_id, args.name, 3, "15")
            else:
                terminal.push_event(f"Alvo '{target_name}' não encontrado.")
                
        elif cmd == "respawn":
            await state.self_respawn()
            await client.announce_join(player_id, args.name, args.ip, args.port)
            
        elif cmd == "peers":
            peers = dht.all_peers()
            terminal.push_event(f"DHT Peers ({len(peers)}): " + ", ".join([p.name for p in peers]))
            
        elif cmd == "status":
            # O terminal já mostra o status no loop, mas podemos forçar refresh se quisermos
            pass

    terminal.handler = action_handler

    if args.bootstrap:
        try:
            b_ip, b_port_str = args.bootstrap.split(":")
            b_port = int(b_port_str)
            b_id = node_id_from(b_ip, b_port)
            b_node = NodeInfo(b_id, b_ip, b_port)

            # 1. Sincronização Total (HP, Posições, Nomes)
            world_data = await client.sync_with_host(b_node)
            if world_data:
                await state.apply_world_state(world_data)
                terminal.push_event("🌍 Mundo sincronizado via Bootstrap.")
            
            # 2. Inserir o nó de bootstrap na nossa DHT
            dht.add_peer(b_node) 

            # 3. Descobrir outros vizinhos
            temp_client = client._get_client(b_node)
            nodes = await temp_client.find_node(b_id, player_id)
            for n in nodes:
                if n.node_id != player_id:
                    dht.add_peer(n)
        except Exception as e:
            terminal.push_event(f"⚠️ Falha ao ligar ao bootstrap: {e}")

    # 3. Anunciar JOIN a TODOS os pares conhecidos
    await client.announce_join(player_id, args.name, args.ip, args.port)

    # Iniciar loops de background
    asyncio.create_task(peer_monitor_loop(state))
    asyncio.create_task(heartbeat_loop(player_id, dht, client))

    await terminal.run_loop()

if __name__ == "__main__":
    asyncio.run(main())
