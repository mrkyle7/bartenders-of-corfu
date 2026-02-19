from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from app.GameState import GameState


class Status(Enum):
    NEW = 1
    STARTED = 2
    ENDED = 3


class GameException(Exception):
    """Raised when user input validation fails."""

    pass


class Game:
    """Holds information about each individual game"""

    def __init__(
        self,
        id: UUID,
        host: UUID,
        players: set[UUID],
        status: Status,
        game_state: GameState,
        created: datetime,
    ):
        self.id: UUID = id
        self.host: UUID = host
        self.players: set[UUID] = players
        self.status: Status = status
        self.game_state: GameState = game_state
        self.created: datetime = created

    @classmethod
    def new_game(cls, host: UUID) -> "Game":
        players = set()
        players.add(host)
        return cls(
            id=uuid4(),
            host=host,
            players=players,
            status=Status.NEW,
            game_state=GameState.new_game(host),
            created=datetime.now(),
        )

    def remove_player(self, userId: UUID):
        self.players.discard(userId)

    def to_dict(self):
        """Returns a dictionary representation of the game"""
        return {
            "id": str(self.id),
            "host": str(self.host),
            "status": self.status.name,
            "players": [str(player) for player in self.players],
            "game_state": self.game_state.to_dict(),
        }
