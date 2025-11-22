from enum import Enum
from uuid import uuid4

class Status(Enum):
    NEW = 1
    STARTED = 2
    ENDED = 3

class GameException(Exception):
    """Raised when user input validation fails."""
    pass

class Game:
    """Holds information about each individual game"""

    __players = set()
    status = Status.NEW

    def __init__(self):
        self.id = uuid4()

    def add_player(self, player):
        if len(self.__players) == 4:
            raise GameException("Max players is 4")
        
        self.__players.add(player)

    def remove_player(self, player):
        self.__players.discard(player)

    def to_dict(self):
        """Returns a dictionary representation of the game"""
        return {
            "id": str(self.id),
            "status": self.status.name,
            "players": [player.to_dict() for player in self.__players]
        }