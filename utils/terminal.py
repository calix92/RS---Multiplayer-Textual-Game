import asyncio
import logging
import os
import sys
import aioconsole
from game.state import GameState, POSITIONS, WEAPON_DAMAGE

log = logging.getLogger('terminal')

BANNER = """
\033[95m
  ██████╗ ██████╗ ██████╗     ██████╗ ██████╗  ██████╗ 
  ██╔══██╗██╔══██╗██╔══██╗    ██╔══██╗██╔══██╗██╔════╝ 
  ██████╔╝██████╔╝██████╔╝    ██████╔╝██████╔╝██║  ███╗ 
  ██╔═══╝ ██╔══██╗██╔═══╝     ██╔══██╗██╔═══╝ ██║   ██║ 
  ██║     ██║  ██║██║         ██║  ██║██║     ╚██████╔╝ 
  ╚═╝     ╚═╝  ╚═╝╚═╝         ╚═╝  ╚═╝╚═╝      ╚═════╝  
\033[0m"""

HELP_TEXT = """
\033[1mMENU DE COMANDOS:\033[0m
- \033[96msay\033[0m <msg>            : Chat para todos
- \033[96mmove\033[0m <local>         : Mudar de zona
- \033[96mlook\033[0m                 : Ver quem está em cada sala
- \033[91mattack\033[0m <nome> [arma] : Atacar jogador
- \033[92mheal\033[0m <nome>           : Curar jogador (+15 HP)
- \033[93mstatus\033[0m               : Ver vida e posição de todos
- \033[93mlog\033[0m                  : Ver últimos eventos
- \033[94mpeers\033[0m                : Ver detalhes técnicos da rede
- \033[95mrespawn\033[0m              : Reviver (se estiveres morto)
- \033[1mquit\033[0m                 : Sair do jogo
"""

DEATH_SCREEN = """
\033[91m
      NOOOO! TU MORRESTE!
           ______
        .-"      "-.
       /            \\
      |              |
      |,  .-.  .-.  ,|
      | )(__/  \__)( |
      |/     /\     \|
      (_     ^^     _)
       \__|IIIIII|__/
        | \IIIIII/ |
        \          /
         `--------`
    Digita 'respawn' para voltar!
\033[0m"""

def red(s):    return f'\033[91m{s}\033[0m'
def green(s):  return f'\033[92m{s}\033[0m'
def yellow(s): return f'\033[93m{s}\033[0m'
def cyan(s):   return f'\033[96m{s}\033[0m'
def magenta(s):return f'\033[95m{s}\033[0m'
def bold(s):   return f'\033[1m{s}\033[0m'

class Terminal:
    def __init__(self, game_state, action_handler):
        self.state   = game_state
        self.handler = action_handler
        self._event_queue = asyncio.Queue()
        self._running = True

    def push_event(self, message):
        self._event_queue.put_nowait(message)

    async def run_loop(self):
        os.system('clear' if os.name == 'posix' else 'cls')
        print(BANNER)
        print(green(f'  Bem-vindo, herói {bold(self.state.self_player.name)}!'))
        print(cyan('  Escreve "help" para ver os comandos.'))
        
        input_task = asyncio.create_task(self._input_loop())
        printer_task = asyncio.create_task(self._event_printer())
        
        try:
            done, pending = await asyncio.wait(
                [input_task, printer_task], 
                return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            input_task.cancel()
            printer_task.cancel()
            await asyncio.gather(input_task, printer_task, return_exceptions=True)

    async def _input_loop(self):
        try:
            while self._running:
                # Se estivermos mortos, mostramos um prompt diferente
                prompt_color = red if not self.state.self_player.is_alive() else cyan
                try:
                    raw = await aioconsole.ainput(prompt_color('⚔  > '))
                except (EOFError, KeyboardInterrupt):
                    self._running = False
                    break
                
                raw = raw.strip()
                if not raw: continue
                parts = raw.split(maxsplit=1)
                cmd = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ''
                
                if cmd in ('quit', 'exit'):
                    print(yellow('A sair do reino...'))
                    self._running = False
                    if self.handler: await self.handler('quit', '')
                    break
                await self._dispatch(cmd, args)
        except asyncio.CancelledError:
            pass

    async def _dispatch(self, cmd, args):
        try:
            if cmd == 'help':
                print(HELP_TEXT)
            elif cmd == 'status':
                print(self.state.status_board())
            elif cmd == 'look':
                rooms = self.state.get_room_occupants()
                print(bold("\n--- MAPA DO REINO ---"))
                for room, folks in rooms.items():
                    color = green if room == self.state.self_player.position else cyan
                    folks_str = ", ".join(folks) if folks else "Vazio"
                    print(f" {color(room):<20} : {folks_str}")
                print()
            elif cmd == 'log':
                events = self.state.recent_events(12)
                print('\n'.join(events) if events else 'Sem eventos.')
            elif cmd == 'peers':
                await self.handler('peers', args)
            elif cmd == 'ping':
                if not args: print(red('Uso: ping <nome>')); return
                await self.handler('ping', args.strip())
            elif cmd == 'attack':
                if not args: print(red('Uso: attack <nome> [arma]')); return
                await self.handler('attack', args)
            elif cmd == 'heal':
                if not args: print(red('Uso: heal <nome>')); return
                await self.handler('heal', args.strip())
            elif cmd == 'move':
                if not args: print(red('Uso: move <local>')); return
                await self.handler('move', args.strip())
            elif cmd == 'say':
                if not args: print(red('Uso: say <msg>')); return
                await self.handler('say', args)
            elif cmd == 'respawn':
                await self.handler('respawn', '')
            else:
                print(red(f'Comando "{cmd}" desconhecido. Escreve "help".'))
        except Exception as exc:
            print(red(f'Erro: {exc}'))

    async def _event_printer(self):
        try:
            while self._running:
                try:
                    msg = await asyncio.wait_for(self._event_queue.get(), timeout=0.5)
                    
                    # Formatação especial baseada no conteúdo da mensagem
                    final_msg = msg
                    if "took" in msg or "Atacou" in msg:
                        final_msg = red(f"💥 {msg}")
                    elif "healed" in msg or "Curaste" in msg:
                        final_msg = green(f"✨ {msg}")
                    elif "moved" in msg:
                        final_msg = cyan(f"🏃 {msg}")
                    elif "DIED" in msg:
                        final_msg = bold(red(f"💀 {msg}"))
                        # Se fomos NÓS que morremos, mostrar a tela de morte
                        if self.state.self_player.name in msg and not self.state.self_player.is_alive():
                            print(DEATH_SCREEN)
                    elif "joined" in msg or "entrou" in msg:
                        final_msg = magenta(f"👋 {msg}")
                    else:
                        final_msg = yellow(f"► {msg}")

                    print(f'\r\033[K  {final_msg}')
                    
                    if self._running:
                        prompt_color = red if not self.state.self_player.is_alive() else cyan
                        print(prompt_color('⚔  > '), end='', flush=True)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
        except asyncio.CancelledError:
            pass
