import asyncio, logging, os, sys, aioconsole
from game.state import GameState, POSITIONS, WEAPON_DAMAGE

BANNER = """\033[95m
  ██████╗ ██████╗ ██████╗     ██████╗ ██████╗  ██████╗ 
  ██╔══██╗██╔══██╗██╔══██╗    ██╔══██╗██╔══██╗██╔════╝ 
  ██████╔╝██████╔╝██████╔╝    ██████╔╝██████╔╝██║  ███╗ 
  ██╔═══╝ ██╔══██╗██╔═══╝     ██╔══██╗██╔═══╝ ██║   ██║ 
  ██║     ██║  ██║██║         ██║  ██║██║     ╚██████╔╝ 
  ╚═╝     ╚═╝  ╚═╝╚═╝         ╚═╝  ╚═╝╚═╝      ╚═════╝  \033[0m"""

HELP_TEXT = """
\033[1m╔════════════════════════════════════════════════════════════════╗\033[0m
\033[1m║\033[0m                     \033[1;95m📜  MENU DE COMANDOS 📜\033[0m                   \033[1m║\033[0m
\033[1m╠════════════════════════════════════════════════════════════════╣\033[0m
\033[1m║\033[0m  \033[96msay\033[0m <msg>            : Fala com todos no reino            \033[1m║\033[0m
\033[1m║\033[0m  \033[96mmove\033[0m <local>         : Move-te para uma nova área         \033[1m║\033[0m
\033[1m║\033[0m  \033[96mlook\033[0m                 : Vê quem está em cada área          \033[1m║\033[0m
\033[1m║\033[0m  \033[91mattack\033[0m <nome> [arma] : Ataca um jogador (ex: sword, axe)  \033[1m║\033[0m
\033[1m║\033[0m  \033[92mheal\033[0m <nome>           : Cura um companheiro                \033[1m║\033[0m
\033[1m║\033[0m  \033[93mstatus\033[0m               : Mostra o placar e a tua vida       \033[1m║\033[0m
\033[1m║\033[0m  \033[93mlog\033[0m                  : Vê os últimos acontecimentos       \033[1m║\033[0m
\033[1m║\033[0m  \033[94mpeers\033[0m                : Lista jogadores ligados            \033[1m║\033[0m
\033[1m║\033[0m  \033[95mrespawn\033[0m              : Volta à vida (se morreste)         \033[1m║\033[0m
\033[1m║\033[0m  \033[1mquit\033[0m                 : Sair do jogo                       \033[1m║\033[0m
\033[1m╚════════════════════════════════════════════════════════════════╝\033[0m"""

DEATH_SCREEN = """\033[91m
      NOOOO! TU MORRESTE!
           ______
        .-"      "-.
       /            \\
      |              |
      |,  .-.  .-.  ,|
      | )(__/  \\__)( |
      |/     /\\     \\|
      (_     ^^     _)
       \\__|IIIIII|__/
        | \\IIIIII/ |
        \\          /
         `--------`
    Digita 'respawn' para voltar!\033[0m"""

def red(s):    return f'\033[91m{s}\033[0m'
def green(s):  return f'\033[92m{s}\033[0m'
def yellow(s): return f'\033[93m{s}\033[0m'
def cyan(s):   return f'\033[96m{s}\033[0m'
def magenta(s):return f'\033[95m{s}\033[0m'
def bold(s):   return f'\033[1m{s}\033[0m'

class Terminal:
    def __init__(self, state, handler):
        self.state, self.handler = state, handler
        self._queue, self._running = asyncio.Queue(), True

    def push_event(self, msg): 
        self.state.log_external_event(msg)
        self._queue.put_nowait(msg)

    async def run_loop(self):
        os.system('clear' if os.name == 'posix' else 'cls')
        print(BANNER + f"\n  Welcome, {bold(self.state.self_player.name)}!")
        tasks = [asyncio.create_task(self._input_loop()), asyncio.create_task(self._event_printer())]
        try: await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            self._running = False
            for t in tasks: t.cancel()

    async def _input_loop(self):
        while self._running:
            p_color = red if not self.state.self_player.is_alive() else cyan
            try:
                raw = (await aioconsole.ainput(p_color('⚔  > '))).strip()
                if not raw: continue
                cmd, *args = raw.split(maxsplit=1)
                args = args[0] if args else ''
                if cmd.lower() in ('quit', 'exit'):
                    self._running = False
                    if self.handler: await self.handler('quit', '')
                    break
                await self._dispatch(cmd.lower(), args)
            except: break

    async def _dispatch(self, cmd, args):
        try:
            if cmd == 'help': print(HELP_TEXT)
            elif cmd == 'status': print(self.state.status_board())
            elif cmd == 'look':
                rooms = self.state.get_room_occupants()
                for r, f in rooms.items():
                    c = green if r == self.state.self_player.position else cyan
                    print(f" {c(r):<20} : {', '.join(f) if f else 'Empty'}")
            elif cmd == 'log': print('\n'.join(self.state.recent_events(12)))
            elif cmd in ('peers', 'ping', 'attack', 'heal', 'move', 'say', 'respawn'):
                await self.handler(cmd, args)
        except Exception as e: print(red(f"Error: {e}"))

    async def _event_printer(self):
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                fmt = yellow(f"► {msg}")
                if "took" in msg: fmt = red(f"💥 {msg}")
                elif "healed" in msg: fmt = green(f"✨ {msg}")
                elif "DIED" in msg:
                    fmt = bold(red(f"💀 {msg}"))
                    if self.state.self_player.name in msg: print(DEATH_SCREEN)
                print(f'\r\033[K  {fmt}')
                if self._running:
                    p_color = red if not self.state.self_player.is_alive() else cyan
                    print(p_color('⚔  > '), end='', flush=True)
            except asyncio.TimeoutError: continue
            except: break
