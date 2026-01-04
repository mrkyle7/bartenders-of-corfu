from enum import Enum
from uuid import UUID, uuid4

from app.db import db
from app.user import User

class Status(Enum):
    NEW = 1
    STARTED = 2
    ENDED = 3

class GameException(Exception):
    """Raised when user input validation fails."""
    pass

class Game:
    """Holds information about each individual game"""

    def __init__(self, userId: UUID):
        self.id = uuid4()
        self.host = userId
        self.players: set[UUID] = set()
        self.players.add(userId)
        self.status = Status.NEW

    def add_player(self, userId: UUID):
        if len(self.players) == 4:
            raise GameException("Max players is 4")
        
        self.players.add(userId)

    def remove_player(self, userId: UUID):
        self.players.discard(userId)

    def to_dict(self):
        """Returns a dictionary representation of the game"""
        userHost = db.get_user_by_id(self.host)
        userPlayers = db.get_users_by_ids(self.players)
        return {
            "id": str(self.id),
            "host": userHost.to_dict(),
            "status": self.status.name,
            "players": [player.to_dict() for player in userPlayers]
        }