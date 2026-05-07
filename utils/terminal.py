"""
utils/terminal.py
~~~~~~~~~~~~~~~~~
Terminal interface for the game.
Uses aioconsole so the user can type while gRPC events arrive in background.
"""

import asyncio
import logging
import os
import sys

import aioconsole

from game.state import GameState, POSITIONS, WEAPON_DAMAGE

log = logging.getLogger("terminal")

BANNER = r"""
  ██████╗ ██████╗ ██████╗     ██████╗ ██████╗  ██████╗
  ██╔══██╗╚════██╗██╔══██╗    ██╔══██╗██╔══██╗██╔════╝
  ██████╔╝ █████╔╝██████╔╝    ██████╔╝██████╔╝██║  ███╗
  ██╔═══╝ ██╔═══╝ ██╔═══╝     ██╔══██╗██╔═══╝ ██║   ██║
  ██║     ███████╗██║         ██║  ██║██║     ╚██████╔╝
  ╚═╝     ╚══════╝╚═╝         ╚═╝  ╚═╝╚═╝      ╚═════╝
  ─────── P2P  Async  Multiplayer  Text  RPG ──────────
"""

HELP_TEXT = """
┌──────────────────────────────────────────────────────┐
│                    COMMANDS                          │
├─────────────────────┬────────────────────────────────┤
│ attack <name> [wpn] │ Attack a player (sword default)│
│ heal <name>         │ Heal a player (+15 HP)         │
│ move <place>        │ Move to a new location         │
│ say <message>       │ Broadcast a chat message       │
│ status              │ Show players & HP board        │
│ log                 │ Show recent events             │
│ peers               │ List known peers (DHT)         │
│ respawn             │ Respawn after dying            │
│ help                │ Show this menu                 │
│ quit / exit         │ Leave the game                 │
└─────────────────────┴────────────────────────────────┘
Weapons: """ + ", ".join(WEAPON_DAMAGE.keys()) + """
Locations: """ + ", ".join(POSITIONS) + "\n"


# ANSI helpers
def red(s):    return f"\033[91m{s}\033[0m"
def green(s):  return f"\033[92m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def cyan(s):   return f"\033[96m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"


class Terminal:
    """
    Manages all terminal I/O.
    `run_loop()` should be awaited; it returns when the user types quit/exit.
    """

    def __init__(self, game_state: GameState, action_handler):
        self.state   = game_state
        self.handler = action_handler   # async callable(command, args)
        self._event_queue: asyncio.Queue[str] = asyncio.Queue()
        self._running = True

    # ── Public API ────────────────────────────────────────────────────────

    def push_event(self, message: str):
        """Called from gRPC server to display incoming events."""
        self._event_queue.put_nowait(message)

    async def run_loop(self):
        print(BANNER)
        print(green(f"  Welcome, {bold(self.state.self_player.name)}!"))
        print(f"  Your ID: {self.state.self_player.player_id[:12]}…")
        print(cyan("  Type 'help' for commands.\n"))

        # Run input and event-printer concurrently
        await asyncio.gather(
            self._input_loop(),
            self._event_printer(),
        )

    # ── Input loop ────────────────────────────────────────────────────────

    async def _input_loop(self):
        while self._running:
            try:
                raw = await aioconsole.ainput(cyan("⚔  > "))
            except (EOFError, KeyboardInterrupt):
                break

            raw = raw.strip()
            if not raw:
                continue

            parts = raw.split(maxsplit=1)
            cmd   = parts[0].lower()
            args  = parts[1] if len(parts) > 1 else ""

            if cmd in ("quit", "exit"):
                print(yellow("Leaving the realm…"))
                self._running = False
                await self.handler("quit", "")
                break

            await self._dispatch(cmd, args)

        self._running = False

    async def _dispatch(self, cmd: str, args: str):
        try:
            if cmd == "help":
                print(HELP_TEXT)

            elif cmd == "status":
                print(self.state.status_board())

            elif cmd == "log":
                events = self.state.recent_events(12)
                if events:
                    print("\n".join(events))
                else:
                    print("  (no events yet)")

            elif cmd == "peers":
                await self.handler("peers", args)

            elif cmd == "attack":
                # attack <name> [weapon]
                parts = args.split(maxsplit=1)
                if not parts:
                    print(red("Usage: attack <player_name> [weapon]"))
                    return
                target_name = parts[0]
                weapon = parts[1].lower() if len(parts) > 1 else "sword"
                await self.handler("attack", f"{target_name}:{weapon}")

            elif cmd == "heal":
                if not args:
                    print(red("Usage: heal <player_name>"))
                    return
                await self.handler("heal", args.strip())

            elif cmd == "move":
                if not args:
                    print(red("Usage: move <location>"))
                    print("  Locations: " + ", ".join(POSITIONS))
                    return
                await self.handler("move", args.strip())

            elif cmd == "say":
                if not args:
                    print(red("Usage: say <message>"))
                    return
                await self.handler("say", args)

            elif cmd == "respawn":
                await self.handler("respawn", "")

            else:
                print(red(f"Unknown command '{cmd}'. Type 'help'."))

        except Exception as exc:
            print(red(f"Command error: {exc}"))
            log.exception("Command dispatch error")

    # ── Event printer ─────────────────────────────────────────────────────

    async def _event_printer(self):
        """Print incoming network events without blocking input."""
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self._event_queue.get(), timeout=0.5)
                print(f"\n  {yellow('►')} {msg}")
                print(cyan("⚔  > "), end="", flush=True)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break