from uuid import UUID
from app.Ingredient import Ingredient

INITIAL_BLADDER_CAPACITY = 8
INITIAL_TOILET_TOKENS = 4


class PlayerState:
    def __init__(
        self,
        player_id: UUID,
        points: int,
        drunk_level: int,
        cup1: list[Ingredient],
        cup2: list[Ingredient],
        bladder: list[Ingredient] | None = None,
        bladder_capacity: int = INITIAL_BLADDER_CAPACITY,
        toilet_tokens: int = INITIAL_TOILET_TOKENS,
        special_ingredients: list[str] | None = None,
        karaoke_cards_claimed: int = 0,
        status: str = "active",
    ):
        self.player_id: UUID = player_id
        self.points: int = points
        self.drunk_level: int = drunk_level
        self.cup1: list[Ingredient] = cup1
        self.cup2: list[Ingredient] = cup2
        self.bladder: list[Ingredient] = bladder if bladder is not None else []
        self.bladder_capacity: int = bladder_capacity
        self.toilet_tokens: int = toilet_tokens
        self.special_ingredients: list[str] = (
            special_ingredients if special_ingredients is not None else []
        )
        self.karaoke_cards_claimed: int = karaoke_cards_claimed
        self.status: str = status

    @classmethod
    def new_player(cls, player_id: UUID) -> "PlayerState":
        return cls(player_id, 0, 0, [], [])

    def to_dict(self) -> dict:
        return {
            "player_id": str(self.player_id),
            "points": self.points,
            "drunk_level": self.drunk_level,
            "cup1": [ingredient.name for ingredient in self.cup1],
            "cup2": [ingredient.name for ingredient in self.cup2],
            "bladder": [ingredient.name for ingredient in self.bladder],
            "bladder_capacity": self.bladder_capacity,
            "toilet_tokens": self.toilet_tokens,
            "special_ingredients": self.special_ingredients,
            "karaoke_cards_claimed": self.karaoke_cards_claimed,
            "status": self.status,
        }
