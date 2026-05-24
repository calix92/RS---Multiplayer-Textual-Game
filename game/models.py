from dataclasses import dataclass


@dataclass
class Player:
    uuid: str
    username: str
    address: str


@dataclass
class Message:
    sender_uuid: str
    text: str
    timestamp: float
