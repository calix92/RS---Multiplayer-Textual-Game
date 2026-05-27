import time
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout


class Game:
    def __init__(self):
        self.w = 20
        self.h = 10

        self.x = 5
        self.y = 5

        self.facing = "?"
        self.last_input = None

        self.frozen_until = 0  # ⬅️ freeze control

        self.game = TextArea(focusable=False)
        self.info = TextArea(height=4, focusable=False)

        self.kb = KeyBindings()

        @self.kb.add("up")
        def _(event):
            self.handle("up")

        @self.kb.add("down")
        def _(event):
            self.handle("down")

        @self.kb.add("left")
        def _(event):
            self.handle("left")

        @self.kb.add("right")
        def _(event):
            self.handle("right")

        # números 1–9 = freeze
        for i in range(1, 10):
            @self.kb.add(str(i))
            def _(event, sec=i):
                self.freeze(sec)

        @self.kb.add("q")
        def _(event):
            event.app.exit()

        self.app = Application(
            layout=Layout(HSplit([self.game, self.info])),
            key_bindings=self.kb,
            full_screen=True,
            refresh_interval=0.1,
        )

        self.render()

    # ---------- FREEZE ----------
    def freeze(self, seconds):
        self.frozen_until = time.time() + seconds
        self.render()

    def is_frozen(self):
        return time.time() < self.frozen_until

    # ---------- MOVEMENT ----------
    def handle(self, direction):
        if self.is_frozen():
            return

        if self.facing != direction:
            self.facing = direction
        else:
            dx, dy = {
                "up": (0, -1),
                "down": (0, 1),
                "left": (-1, 0),
                "right": (1, 0)
            }.get(direction, (0, 0))

            self.x = max(0, min(self.w - 1, self.x + dx))
            self.y = max(0, min(self.h - 1, self.y + dy))

        self.render()

    def dir_symbol(self):
        return {
            "up": "^",
            "down": "v",
            "left": "<",
            "right": ">"
        }.get(self.facing, "?")

    # ---------- RENDER ----------
    def render(self):
        grid = ""

        for y in range(self.h):
            for x in range(self.w):
                if x == self.x and y == self.y:
                    grid += self.dir_symbol()
                else:
                    grid += "."
            grid += "\n"

        self.game.text = grid

        remaining = max(0, self.frozen_until - time.time())

        self.info.text = (
            f"Posição: ({self.x}, {self.y})\n"
            f"Direção: {self.facing}\n"
            f"Freeze: {remaining:.1f}s\n"
            "Setas = mover | 1–9 = freeze | Q = sair"
        )

    def run(self):
        with patch_stdout():
            self.app.run()


if __name__ == "__main__":
    Game().run()
