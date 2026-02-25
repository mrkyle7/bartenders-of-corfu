import random
from typing import Mapping, Optional
from uuid import UUID

from app.card import CardRow, build_deck, deal_initial_rows
from app.Ingredient import Ingredient
from app.PlayerState import Cup, PlayerState
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
        card_rows: list[CardRow] | None = None,
        deck: list[dict] | None = None,
        turn_order: list[UUID] | None = None,
        turn_number: int = 0,
        ingredients_taken_this_turn: int = 0,
        drunk_ingredients_this_turn: list[Ingredient] | None = None,
        bag_draw_pending: list[Ingredient] | None = None,
    ):
        self.winner: Optional[UUID] = winner
        self.bag_contents: list[Ingredient] = bag_contents
        self.player_states: Mapping[UUID, PlayerState] = player_states
        self.player_turn: Optional[UUID] = player_turn
        self.open_display: list[Ingredient] = (
            open_display if open_display is not None else []
        )
        self.card_rows: list[CardRow] = card_rows if card_rows is not None else []
        # Remaining deck (serialised as list[dict] for storage; rebuild Card objects on demand)
        self._deck_dicts: list[dict] = deck if deck is not None else []
        # Fixed turn order established at game start
        self.turn_order: list[UUID] = turn_order if turn_order is not None else []
        # Current turn counter (monotonically increasing)
        self.turn_number: int = turn_number
        # Tracks progress of a multi-batch TakeIngredients action within a single turn.
        # Reset to 0 when the turn advances.
        self.ingredients_taken_this_turn: int = ingredients_taken_this_turn
        # Accumulates all ingredients drunk (disposition=drink) across batches this turn.
        # Applied as a single drunk-modifier calculation when the turn completes.
        self.drunk_ingredients_this_turn: list[Ingredient] = (
            drunk_ingredients_this_turn if drunk_ingredients_this_turn is not None else []
        )
        # Ingredients drawn from the bag (via draw-from-bag) awaiting cup/drink assignment.
        # Cleared when take-ingredients assigns them or when the turn advances.
        self.bag_draw_pending: list[Ingredient] = (
            bag_draw_pending if bag_draw_pending is not None else []
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

        # Randomise turn order; persist it for the duration of the game
        turn_order = list(players)
        random.shuffle(turn_order)
        first_player = turn_order[0]

        # Build card deck and deal 3 rows of 3 cards
        deck = build_deck()
        card_rows, remaining_deck = deal_initial_rows(deck)

        return cls(
            winner=None,
            bag_contents=bag,
            player_states=player_states,
            player_turn=first_player,
            open_display=open_display,
            card_rows=card_rows,
            deck=[c.to_dict() for c in remaining_deck],
            turn_order=turn_order,
            turn_number=0,
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
            "card_rows": [row.to_dict() for row in self.card_rows],
            "deck_size": len(self._deck_dicts),
            "deck": self._deck_dicts,
            "turn_order": [str(pid) for pid in self.turn_order],
            "turn_number": self.turn_number,
            "ingredients_taken_this_turn": self.ingredients_taken_this_turn,
            "drunk_ingredients_this_turn": [i.name for i in self.drunk_ingredients_this_turn],
            "bag_draw_pending": [i.name for i in self.bag_draw_pending],
        }

    @classmethod
    def from_dict(cls, state_data: dict) -> "GameState":
        """Deserialise a GameState from a stored dict (DB JSONB)."""

        player_states = {}
        for player_str, ps_data in state_data.get("player_states", {}).items():
            if "cups" in ps_data:
                cups = [Cup.from_dict(c) for c in ps_data["cups"]]
            else:
                cups = [
                    Cup(ingredients=[Ingredient[i] for i in ps_data.get("cup1", [])]),
                    Cup(ingredients=[Ingredient[i] for i in ps_data.get("cup2", [])]),
                ]
            player_states[UUID(player_str)] = PlayerState(
                player_id=UUID(ps_data["player_id"]),
                points=ps_data["points"],
                drunk_level=ps_data["drunk_level"],
                cups=cups,
                bladder=[Ingredient[i] for i in ps_data.get("bladder", [])],
                bladder_capacity=ps_data.get("bladder_capacity", 8),
                toilet_tokens=ps_data.get("toilet_tokens", 4),
                special_ingredients=ps_data.get("special_ingredients", []),
                karaoke_cards_claimed=ps_data.get("karaoke_cards_claimed", 0),
                status=ps_data.get("status", "active"),
                cards=ps_data.get("cards", []),
            )

        card_rows = [CardRow.from_dict(r) for r in state_data.get("card_rows", [])]
        deck_dicts = state_data.get("deck", [])
        turn_order = [UUID(pid) for pid in state_data.get("turn_order", [])]

        return cls(
            winner=UUID(state_data["winner"]) if state_data.get("winner") else None,
            bag_contents=[Ingredient[i] for i in state_data.get("bag_contents", [])],
            player_states=player_states,
            player_turn=UUID(state_data["player_turn"]) if state_data.get("player_turn") else None,
            open_display=[Ingredient[i] for i in state_data.get("open_display", [])],
            card_rows=card_rows,
            deck=deck_dicts,
            turn_order=turn_order,
            turn_number=state_data.get("turn_number", 0),
            ingredients_taken_this_turn=state_data.get("ingredients_taken_this_turn", 0),
            drunk_ingredients_this_turn=[
                Ingredient[i] for i in state_data.get("drunk_ingredients_this_turn", [])
            ],
            bag_draw_pending=[
                Ingredient[i] for i in state_data.get("bag_draw_pending", [])
            ],
        )
