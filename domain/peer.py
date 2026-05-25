import socket
import uuid


class Peer:

    def __init__(self, username, host="127.0.0.1", grpc_port=None, kad_port=None, bootstrap=None):

        self.username = username
        self.uuid = str(uuid.uuid4())

        self.host = host
        self.bootstrap = bootstrap

        self.grpc_port = grpc_port or self._find_free_port()
        self.kad_port = kad_port or self._find_free_port()

    def grpc_address(self):
        return f"{self.host}:{self.grpc_port}"

    def kad_address(self):
        return f"{self.host}:{self.kad_port}"

    def _find_free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("", 0))
            return sock.getsockname()[1]
