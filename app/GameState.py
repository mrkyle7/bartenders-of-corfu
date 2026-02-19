from typing import Mapping, Optional
from uuid import UUID

from app.Ingredient import Ingredient
from app.PlayerState import PlayerState
from app.user import User


class GameState:
    def __init__(
        self,
        winner: Optional[UUID],
        bag_contents: list[Ingredient],
        player_states: Mapping[UUID, PlayerState],
        player_turn: Optional[UUID],
    ):
        self.winner: Optional[UUID] = winner
        self.bag_contents: list[Ingredient] = bag_contents
        self.player_states: Mapping[UUID, PlayerState] = player_states
        self.player_turn: Optional[UUID] = player_turn

    @classmethod
    def new_game(cls, host: User) -> "GameState":
        return cls(None, [], {host: PlayerState.new_player(host)}, None)

    def to_dict(self) -> dict:
        return {
            "winner": str(self.winner) if self.winner else None,
            "bag_contents": [ingredient.name for ingredient in self.bag_contents],
            "player_states": {
                str(player): player_state.to_dict()
                for player, player_state in self.player_states.items()
            },
            "player_turn": str(self.player_turn) if self.player_turn else None,
        }
