import asyncio
import time
from collections import deque

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea


# -------------------------
# GAME STATE
# -------------------------

class GameState:
    def __init__(self):
        self.x = 5
        self.y = 5
        self.direction = ">"
        self.messages = deque(maxlen=4)
        self.frozen_until = 0

    def add_message(self, msg):
        self.messages.append(msg)

    def can_move(self):
        return time.time() > self.frozen_until

    def freeze(self, seconds):
        self.frozen_until = time.time() + seconds

    def move_forward(self):
        if not self.can_move():
            return

        if self.direction == ">":
            self.x += 1
        elif self.direction == "<":
            self.x -= 1
        elif self.direction == "^":
            self.y -= 1
        elif self.direction == "v":
            self.y += 1

    def turn(self, direction):
        self.direction = direction


state = GameState()


# -------------------------
# RENDER GAME AREA
# -------------------------

def render_game():
    width, height = 20, 10
    grid = []

    for y in range(height):
        row = []
        for x in range(width):
            if x == state.x and y == state.y:
                row.append(state.direction)
            else:
                row.append(".")
        grid.append("".join(row))

    return "\n".join(grid)


# -------------------------
# RENDER MESSAGES
# -------------------------

def render_messages():
    return "\n".join(list(state.messages))


# -------------------------
# INPUT AREA
# -------------------------

input_field = TextArea(height=1, prompt="> ")


# -------------------------
# KEY BINDINGS
# -------------------------

kb = KeyBindings()


@kb.add("left")
def _(event):
    state.turn("<")


@kb.add("right")
def _(event):
    state.turn(">")


@kb.add("up")
def _(event):
    state.turn("^")


@kb.add("down")
def _(event):
    state.turn("v")


@kb.add("enter")
def _(event):
    text = input_field.text.strip()
    input_field.text = ""

    if not text:
        return

    # NUMBER = freeze
    if text.isdigit():
        state.freeze(int(text))
        state.add_message(f"⏳ frozen for {text}s")
        return

    # normal chat message
    state.add_message(f"you: {text}")


@kb.add("space")
def _(event):
    state.move_forward()


# -------------------------
# UI COMPONENTS
# -------------------------

game_window = Window(content=FormattedTextControl(render_game))
message_window = Window(content=FormattedTextControl(render_messages))

root = HSplit([
    Window(height=1, content=FormattedTextControl(lambda: "=== GAME ===")),
    game_window,
    Window(height=1, char="-"),
    Window(height=1, content=FormattedTextControl(lambda: "=== MESSAGES (last 4) ===")),
    message_window,
    Window(height=1, char="-"),
    input_field,
])


app = Application(
    layout=Layout(root),
    key_bindings=kb,
    full_screen=True,
)


# -------------------------
# GAME LOOP
# -------------------------

async def tick():
    while True:
        app.invalidate()
        await asyncio.sleep(0.1)


async def main():
    asyncio.create_task(tick())
    await app.run_async()


if __name__ == "__main__":
    asyncio.run(main())
