import asyncio
import logging
import os
import sys
import aioconsole
from game.state import GameState, POSITIONS, WEAPON_DAMAGE

log = logging.getLogger('terminal')

BANNER = '--- P2P RPG ---'

HELP_TEXT = """
MENU DE COMANDOS:
- say <mensagem>       : Chat para todos
- move <local>         : Mudar de zona
- attack <nome> [arma] : Atacar jogador (ex: attack Calix axe)
- heal <nome>          : Curar jogador (+15 HP)
- status               : Ver HP de todos
- log                  : Ver ultimos eventos
- peers                : Ver nos da rede
- ping <nome>          : Testar ligação a um jogador
- respawn              : Reviver
- help                 : Este menu
- quit                 : Sair
"""

def red(s):    return f'\033[91m{s}\033[0m'
def green(s):  return f'\033[92m{s}\033[0m'
def yellow(s): return f'\033[93m{s}\033[0m'
def cyan(s):   return f'\033[96m{s}\033[0m'
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
        print(BANNER)
        print(green(f'  Bem-vindo, {bold(self.state.self_player.name)}!'))
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
                try:
                    raw = await aioconsole.ainput(cyan('⚔  > '))
                except (EOFError, KeyboardInterrupt):
                    self._running = False
                    break
                
                raw = raw.strip()
                if not raw: continue
                parts = raw.split(maxsplit=1)
                cmd = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ''
                
                if cmd in ('quit', 'exit'):
                    print(yellow('A sair...'))
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
                print('Armas: ' + ', '.join(WEAPON_DAMAGE.keys()))
                print('Locais: ' + ', '.join(POSITIONS))
            elif cmd == 'status':
                print(self.state.status_board())
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
                    print(f'\n  {yellow("►")} {msg}')
                    if self._running: print(cyan('⚔  > '), end='', flush=True)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
        except asyncio.CancelledError:
            pass
