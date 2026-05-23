import threading


class PeerRegistry:
    def __init__(self):
        self.peers = set()
        self.lock = threading.Lock()

    def add(self, peer):
        with self.lock:
            self.peers.add(peer)

    def remove(self, peer):
        with self.lock:
            self.peers.discard(peer)

    def all(self):
        with self.lock:
            return list(self.peers)
