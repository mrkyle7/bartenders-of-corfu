from enum import Enum
from uuid import uuid4

class Status(Enum):
    NEW = 1
    STARTED = 2
    ENDED = 3

class Game:
    """Holds information about each individual game"""

    __players = []
    status = Status.NEW

    def __init__(self):
        self.id = uuid4()

    def to_dict(self):
        """Returns a dictionary representation of the game"""
        return {
            "id": str(self.id),
            "status": self.status.name,
            "players": [player.to_dict() for player in self.__players]
        }