import asyncio
import argparse
import logging
from game.state import GameState
from dht.kademlia import DHTNode
from network.server import start_server
from network.client import BroadcastClient
from utils.terminal import Terminal

logging.basicConfig(level=logging.ERROR)

async def main():
    parser = argparse.ArgumentParser(description="P2P Text RPG")
    parser.add_argument("--name", required=True, help="Nome do jogador")
    parser.add_argument("--ip", default="127.0.0.1", help="Endereço IP local")
    parser.add_argument("--port", type=int, required=True, help="Porta local do gRPC")
    parser.add_argument("--bootstrap", type=str, help="IP:Porta de um nó existente para entrada na rede")
    args = parser.parse_args()

    player_id = f"{args.ip}:{args.port}"
    state = GameState(player_id, args.name, args.ip, args.port)
    dht = DHTNode(args.ip, args.port, args.name)
    client = BroadcastClient(dht)
    
    terminal = Terminal(state, None)
    
    def on_event(msg: str):
        terminal.push_event(msg)

    server = await start_server(args.ip, args.port, state, dht, on_event)

    async def action_handler(cmd: str, args_str: str):
        if cmd == "quit":
            await client.announce_leave(player_id, args.name)
            await client.close_all()
            await server.stop(0)
            
        elif cmd == "say":
            await client.broadcast(player_id, args.name, 2, args_str)
            
        elif cmd == "move":
            await state.self_move(args_str)
            await client.broadcast(player_id, args.name, 1, args_str)
            
        elif cmd == "attack":
            parts = args_str.split(":")
            target = parts[0]
            weapon = parts[1] if len(parts) > 1 else "sword"
            
            target_node = next((p for p in dht.all_peers() if p.name == target), None)
            if target_node:
                await client.send_to(target_node, player_id, args.name, 0, weapon)
            else:
                terminal.push_event(f"Alvo '{target}' desconhecido na DHT.")
                
        elif cmd == "heal":
            target_node = next((p for p in dht.all_peers() if p.name == args_str), None)
            if target_node:
                await client.send_to(target_node, player_id, args.name, 3, "15")
            else:
                terminal.push_event(f"Alvo '{args_str}' desconhecido na DHT.")
                
        elif cmd == "respawn":
            await state.self_respawn()
            await client.announce_join(player_id, args.name, args.ip, args.port)
            
        elif cmd == "peers":
            peers = dht.all_peers()
            terminal.push_event(f"DHT Peers ({len(peers)}): " + ", ".join([p.name for p in peers]))

    terminal.handler = action_handler

    if args.bootstrap:
        b_ip, b_port_str = args.bootstrap.split(":")
        class MockNode:
            node_id = f"{b_ip}:{b_port_str}"
            ip = b_ip
            port = int(b_port_str)
        
        await client.send_to(MockNode(), player_id, args.name, 4, f"{args.ip}:{args.port}")

    await client.announce_join(player_id, args.name, args.ip, args.port)

    await terminal.run_loop()

if __name__ == "__main__":
    asyncio.run(main())