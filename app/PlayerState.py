from uuid import UUID
from app.Ingredient import Ingredient


class PlayerState:
    
    def __init__(self, player_id: UUID, points: int, drunk_level: int, cup1: list[Ingredient], cup2: list[Ingredient]):
        self.player_id: UUID = player_id
        self.points: int = points
        self.drunk_level: int = drunk_level
        self.cup1: list[Ingredient] = cup1
        self.cup2: list[Ingredient] = cup2
    
    @classmethod
    def new_player(cls, player_id: UUID) -> 'PlayerState':
        return cls(player_id, 0, 0, [], [])
    
    def to_dict(self) -> dict:
        return {
            "player_id": str(self.player_id),
            "points": self.points,
            "drunk_level": self.drunk_level,
            "cup1": [ingredient.name for ingredient in self.cup1],
            "cup2": [ingredient.name for ingredient in self.cup2]
        }