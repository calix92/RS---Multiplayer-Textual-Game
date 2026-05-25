class MessageService:

    def __init__(self, node, client):

        self.node = node
        self.client = client

    def send(self, message):

        self.client.broadcast(
            self.node.username,
            message
        )
