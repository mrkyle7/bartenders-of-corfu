from uuid import UUID

from app.Ingredient import Ingredient

INITIAL_BLADDER_CAPACITY = 8
INITIAL_TOILET_TOKENS = 4
BASE_TAKE_COUNT = 3
MAX_CUP_INGREDIENTS = 5
MIN_BLADDER_CAPACITY = 4


class Cup:
    def __init__(
        self,
        ingredients: list[Ingredient] | None = None,
        has_cup_doubler: bool = False,
    ):
        self.ingredients: list[Ingredient] = (
            ingredients if ingredients is not None else []
        )
        self.has_cup_doubler: bool = has_cup_doubler

    @property
    def spirit_count(self) -> int:
        return sum(1 for i in self.ingredients if i.value.alcohol)

    @property
    def is_full(self) -> bool:
        return len(self.ingredients) >= MAX_CUP_INGREDIENTS

    @property
    def is_empty(self) -> bool:
        return len(self.ingredients) == 0

    def to_dict(self) -> dict:
        return {
            "ingredients": [i.name for i in self.ingredients],
            "spirit_count": self.spirit_count,
            "is_full": self.is_full,
            "is_empty": self.is_empty,
            "has_cup_doubler": self.has_cup_doubler,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Cup":
        return cls(
            ingredients=[Ingredient[i] for i in data.get("ingredients", [])],
            has_cup_doubler=data.get("has_cup_doubler", False),
        )


class PlayerState:
    def __init__(
        self,
        player_id: UUID,
        points: int,
        drunk_level: int,
        cups: list[Cup] | None = None,
        bladder: list[Ingredient] | None = None,
        bladder_capacity: int = INITIAL_BLADDER_CAPACITY,
        toilet_tokens: int = INITIAL_TOILET_TOKENS,
        special_ingredients: list[str] | None = None,
        karaoke_cards_claimed: int = 0,
        status: str = "active",
        cards: list[dict] | None = None,
    ):
        self.player_id: UUID = player_id
        self.points: int = points
        self.drunk_level: int = drunk_level
        self.cups: list[Cup] = cups if cups is not None else [Cup(), Cup()]
        self.bladder: list[Ingredient] = bladder if bladder is not None else []
        self.bladder_capacity: int = bladder_capacity
        self.toilet_tokens: int = toilet_tokens
        # Resolved special types sitting on the player mat (list of SpecialType.value strings)
        self.special_ingredients: list[str] = (
            special_ingredients if special_ingredients is not None else []
        )
        self.karaoke_cards_claimed: int = karaoke_cards_claimed
        self.status: str = status
        # Claimed ability cards (serialised dicts)
        self.cards: list[dict] = cards if cards is not None else []

    @property
    def take_count(self) -> int:
        """Number of ingredients the player must take per turn (drunk_level + base_take_count)."""
        return self.drunk_level + BASE_TAKE_COUNT

    @property
    def is_eliminated(self) -> bool:
        return self.status in ("hospitalised", "wet")

    @classmethod
    def new_player(cls, player_id: UUID) -> "PlayerState":
        return cls(player_id, 0, 0, cups=[Cup(), Cup()])

    def to_dict(self) -> dict:
        return {
            "player_id": str(self.player_id),
            "points": self.points,
            "drunk_level": self.drunk_level,
            "take_count": self.take_count,
            "cups": [cup.to_dict() for cup in self.cups],
            "bladder": [ingredient.name for ingredient in self.bladder],
            "bladder_capacity": self.bladder_capacity,
            "toilet_tokens": self.toilet_tokens,
            "special_ingredients": self.special_ingredients,
            "karaoke_cards_claimed": self.karaoke_cards_claimed,
            "status": self.status,
            "cards": [dict(c) for c in self.cards],
        }
