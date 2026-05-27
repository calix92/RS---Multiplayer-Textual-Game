from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit
from prompt_toolkit.layout.containers import Window, VSplit
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.styles import Style
from prompt_toolkit.patch_stdout import patch_stdout
import asyncio


class GameUI:
    def __init__(self):
        # Área do jogo (vazia por agora)
        self.game_area = TextArea(
            text="\n" * 10,
            focusable=False,
            scrollbar=False,
        )

        # Chat (onde vamos guardar mensagens)
        self.chat_log = TextArea(
            text="",
            focusable=False,
            scrollbar=True,
            height=4,
        )

        # Input do utilizador
        self.input_box = TextArea(
            height=1,
            prompt="> ",
            multiline=False,
        )

        self.input_box.accept_handler = self.on_enter

        self.messages = []

        self.root = HSplit([
            self.game_area,
            self.chat_log,
            self.input_box
        ])

        self.app = Application(
            layout=Layout(self.root),
            full_screen=True,
            refresh_interval=0.2,
        )

    def on_enter(self, buff):
        text = self.input_box.text.strip()

        if text:
            self.add_message(text)

        self.input_box.text = ""

    def add_message(self, msg):
        self.messages.append(msg)

        # mantém só as últimas 4 mensagens
        self.messages = self.messages[-4:]

        self.chat_log.text = "\n".join(self.messages)

    def run(self):
        with patch_stdout():
            self.app.run()


if __name__ == "__main__":
    ui = GameUI()
    ui.run()
