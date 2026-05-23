import aioconsole

async def chat_loop(client, name):
    while True:
        msg = await aioconsole.ainput("> ")
        client.broadcast(name, msg)
