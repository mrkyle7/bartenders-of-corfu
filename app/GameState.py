import random
from typing import Mapping, Optional
from uuid import UUID

from app.card import CardRow, build_deck, build_order_deck, deal_market
from app.Ingredient import (
    SPECIAL_INGREDIENTS,
    SPECIALS_PER_TYPE,
    Ingredient,
    is_special,
)
from app.PlayerState import Cup, PlayerState
from app.user import User

OPEN_DISPLAY_SIZE = 5


def score_to_win(num_players: int) -> int:
    """Points that trigger the last round: 40 for two players, 35 for three, 30 for four."""
    if num_players <= 2:
        return 40
    if num_players == 3:
        return 35
    return 30


def create_initial_bag(num_players: int) -> list[Ingredient]:
    """Each spirit and mixer: players + 3 tokens. Each special: 2 tokens."""
    multiplier = num_players + 3
    return (
        [Ingredient.WHISKEY] * multiplier
        + [Ingredient.GIN] * multiplier
        + [Ingredient.RUM] * multiplier
        + [Ingredient.TEQUILA] * multiplier
        + [Ingredient.VODKA] * multiplier
        + [Ingredient.COLA] * multiplier
        + [Ingredient.SODA] * multiplier
        + [Ingredient.TONIC] * multiplier
        + [Ingredient.CRANBERRY] * multiplier
        + [s for s in SPECIAL_INGREDIENTS for _ in range(SPECIALS_PER_TYPE)]
    )


def draw_token(gs: "GameState") -> Ingredient | None:
    """Draw one spirit or mixer at random from the bag.

    Any special that comes out on the way goes to the specials display and
    the draw carries on. Returns None when the bag has no spirit or mixer left.
    """
    while gs.bag_contents:
        token = random.choice(gs.bag_contents)
        gs.bag_contents.remove(token)
        if is_special(token):
            gs.specials_display.append(token)
            continue
        return token
    return None


def regular_in_bag(gs: "GameState") -> int:
    """Tokens in the bag that a draw can hand you (everything but specials)."""
    return sum(1 for t in gs.bag_contents if not is_special(t))


def _faces_for(
    tokens: list[Ingredient], faces: list[str | None] | None
) -> list[str | None]:
    """Special faces lined up with ``tokens``.

    Games saved before specials were rolled on the display have no faces:
    their special tokens show "choose any".
    """
    if faces is not None and len(faces) == len(tokens):
        return list(faces)
    return ["any" if t == Ingredient.SPECIAL else None for t in tokens]


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
        taken_records_this_turn: list[dict] | None = None,
        discard: list[dict] | None = None,
        last_round: bool = False,
        main_action_taken_this_turn: bool = False,
        main_action_this_turn: str | None = None,
        free_actions_used_this_turn: list[str] | None = None,
        game_modes: list[str] | None = None,
        order_deck: list[dict] | None = None,
        display_specials: list[str | None] | None = None,
        bag_draw_pending_specials: list[str | None] | None = None,
        specials_display: list[Ingredient] | None = None,
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
            drunk_ingredients_this_turn
            if drunk_ingredients_this_turn is not None
            else []
        )
        # Ingredients drawn from the bag (via draw-from-bag) awaiting cup/drink assignment.
        # Cleared when take-ingredients assigns them or when the turn advances.
        self.bag_draw_pending: list[Ingredient] = (
            bag_draw_pending if bag_draw_pending is not None else []
        )
        # Accumulates all taken records across batches this turn; included in
        # the final move payload when turn_complete=True. Reset on turn advance.
        self.taken_records_this_turn: list[dict] = (
            taken_records_this_turn if taken_records_this_turn is not None else []
        )
        # Discard pile — cards removed by refresh go here permanently (never reshuffled)
        self.discard: list[dict] = discard if discard is not None else []
        # Last-round flag: set when a player reaches 40+ points.
        # The game continues until the round completes (all players have equal turns).
        self.last_round: bool = last_round
        # Free action tracking: has the player taken their main (non-free) action this turn?
        self.main_action_taken_this_turn: bool = main_action_taken_this_turn
        # Which action it was (e.g. "take_ingredients"), so the Entrepreneur's
        # free sell can require a different main action first.
        self.main_action_this_turn: str | None = main_action_this_turn
        # Which free action types have been used this turn (e.g. ["sell_cup", "go_for_a_wee"])
        self.free_actions_used_this_turn: list[str] = (
            free_actions_used_this_turn
            if free_actions_used_this_turn is not None
            else []
        )
        # Optional rule variations selected in the lobby (immutable after start).
        # See app/game_modes.py for valid values.
        self.game_modes: list[str] = list(game_modes) if game_modes else []
        # Drink orders not on the table, drawn from the front; served or
        # cleared orders go to the back.
        self.order_deck: list[dict] = order_deck if order_deck is not None else []
        # The face each special token shows, lined up with open_display and
        # bag_draw_pending (None for spirits and mixers). See app/specials.py.
        self.display_specials: list[str | None] = _faces_for(
            self.open_display, display_specials
        )
        self.bag_draw_pending_specials: list[str | None] = _faces_for(
            self.bag_draw_pending, bag_draw_pending_specials
        )
        # Specials drawn from the bag, waiting for anyone to take them.
        self.specials_display: list[Ingredient] = (
            list(specials_display) if specials_display is not None else []
        )

    @property
    def score_to_win(self) -> int:
        return score_to_win(len(self.turn_order) or len(self.player_states))

    def has_mode(self, mode: str) -> bool:
        """Return True if the given optional rule variation is enabled."""
        return mode in self.game_modes

    @classmethod
    def new_game(cls, host: User) -> "GameState":
        return cls(None, [], {host: PlayerState.new_player(host)}, None)

    @classmethod
    def start_game(
        cls, players: list[UUID], game_modes: list[str] | None = None
    ) -> "GameState":
        """Build the initial game state when a game is started."""
        bag = list(create_initial_bag(len(players)))
        random.shuffle(bag)

        player_states: dict[UUID, PlayerState] = {
            pid: PlayerState.new_player(pid) for pid in players
        }

        # Randomise turn order; persist it for the duration of the game
        turn_order = list(players)
        random.shuffle(turn_order)
        first_player = turn_order[0]

        # Lay out the market: every karaoke card, three orders, three abilities
        card_rows, ability_deck, order_deck = deal_market(
            build_deck(), build_order_deck()
        )

        gs = cls(
            winner=None,
            bag_contents=bag,
            player_states=player_states,
            player_turn=first_player,
            open_display=[],
            card_rows=card_rows,
            deck=[c.to_dict() for c in ability_deck],
            turn_order=turn_order,
            turn_number=0,
            discard=[],
            game_modes=list(game_modes) if game_modes else [],
            order_deck=[c.to_dict() for c in order_deck],
        )
        # Draw five spirits and mixers to the open display; specials that
        # come out go to the specials display.
        while len(gs.open_display) < OPEN_DISPLAY_SIZE:
            token = draw_token(gs)
            if token is None:
                break
            gs.open_display.append(token)
            gs.display_specials.append(None)
        return gs

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
            "drunk_ingredients_this_turn": [
                i.name for i in self.drunk_ingredients_this_turn
            ],
            "bag_draw_pending": [i.name for i in self.bag_draw_pending],
            "taken_records_this_turn": self.taken_records_this_turn,
            "discard": self.discard,
            "last_round": self.last_round,
            "main_action_taken_this_turn": self.main_action_taken_this_turn,
            "main_action_this_turn": self.main_action_this_turn,
            "free_actions_used_this_turn": list(self.free_actions_used_this_turn),
            "game_modes": list(self.game_modes),
            "order_deck": self.order_deck,
            "order_deck_size": len(self.order_deck),
            "display_specials": list(self.display_specials),
            "bag_draw_pending_specials": list(self.bag_draw_pending_specials),
            "score_to_win": self.score_to_win,
            "specials_display": [i.name for i in self.specials_display],
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
            player_turn=UUID(state_data["player_turn"])
            if state_data.get("player_turn")
            else None,
            open_display=[Ingredient[i] for i in state_data.get("open_display", [])],
            card_rows=card_rows,
            deck=deck_dicts,
            turn_order=turn_order,
            turn_number=state_data.get("turn_number", 0),
            ingredients_taken_this_turn=state_data.get(
                "ingredients_taken_this_turn", 0
            ),
            drunk_ingredients_this_turn=[
                Ingredient[i] for i in state_data.get("drunk_ingredients_this_turn", [])
            ],
            bag_draw_pending=[
                Ingredient[i] for i in state_data.get("bag_draw_pending", [])
            ],
            taken_records_this_turn=state_data.get("taken_records_this_turn", []),
            discard=state_data.get("discard", []),
            last_round=state_data.get("last_round", False),
            main_action_taken_this_turn=state_data.get(
                "main_action_taken_this_turn", False
            ),
            main_action_this_turn=state_data.get("main_action_this_turn"),
            free_actions_used_this_turn=state_data.get(
                "free_actions_used_this_turn", []
            ),
            game_modes=state_data.get("game_modes", []),
            order_deck=state_data.get("order_deck", []),
            display_specials=state_data.get("display_specials"),
            bag_draw_pending_specials=state_data.get("bag_draw_pending_specials"),
            specials_display=[
                Ingredient[i] for i in state_data.get("specials_display", [])
            ],
        )
