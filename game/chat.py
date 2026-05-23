import aioconsole


async def chat_loop(chat_service):
    while True:
        msg = await aioconsole.ainput("> ")
        chat_service.send(msg)
