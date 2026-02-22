import random
from typing import Mapping, Optional
from uuid import UUID

from app.Ingredient import Ingredient
from app.PlayerState import PlayerState
from app.user import User

OPEN_DISPLAY_SIZE = 5

INITIAL_BAG: list[Ingredient] = (
    [Ingredient.WHISKEY] * 5
    + [Ingredient.GIN] * 5
    + [Ingredient.RUM] * 5
    + [Ingredient.TEQUILA] * 5
    + [Ingredient.VODKA] * 5
    + [Ingredient.COLA] * 4
    + [Ingredient.SODA] * 4
    + [Ingredient.TONIC] * 4
    + [Ingredient.CRANBERRY] * 4
    + [Ingredient.SPECIAL] * 4
)


class GameState:
    def __init__(
        self,
        winner: Optional[UUID],
        bag_contents: list[Ingredient],
        player_states: Mapping[UUID, PlayerState],
        player_turn: Optional[UUID],
        open_display: list[Ingredient] | None = None,
    ):
        self.winner: Optional[UUID] = winner
        self.bag_contents: list[Ingredient] = bag_contents
        self.player_states: Mapping[UUID, PlayerState] = player_states
        self.player_turn: Optional[UUID] = player_turn
        self.open_display: list[Ingredient] = (
            open_display if open_display is not None else []
        )

    @classmethod
    def new_game(cls, host: User) -> "GameState":
        return cls(None, [], {host: PlayerState.new_player(host)}, None)

    @classmethod
    def start_game(cls, players: list[UUID]) -> "GameState":
        """Build the initial game state when a game is started."""
        bag = list(INITIAL_BAG)
        random.shuffle(bag)

        # Draw 5 ingredients to the open display
        display_count = min(OPEN_DISPLAY_SIZE, len(bag))
        open_display = bag[:display_count]
        bag = bag[display_count:]

        player_states: dict[UUID, PlayerState] = {
            pid: PlayerState.new_player(pid) for pid in players
        }

        first_player = random.choice(players)

        return cls(
            winner=None,
            bag_contents=bag,
            player_states=player_states,
            player_turn=first_player,
            open_display=open_display,
        )

    def to_dict(self) -> dict:
        return {
            "winner": str(self.winner) if self.winner else None,
            "bag_contents": [ingredient.name for ingredient in self.bag_contents],
            "player_states": {
                str(player): player_state.to_dict()
                for player, player_state in self.player_states.items()
            },
            "player_turn": str(self.player_turn) if self.player_turn else None,
            "open_display": [ingredient.name for ingredient in self.open_display],
        }
