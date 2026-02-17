from dataclasses import dataclass
from enum import Enum

@dataclass(frozen=True)
class IngredientProps():
    name: str
    alcohol: bool
    special: bool
        
class Ingredient(Enum):
    WHISKEY = IngredientProps("Whiskey", True, False)
    GIN = IngredientProps("Gin", True, False)
    RUM = IngredientProps("Rum", True, False)
    TEQUILA = IngredientProps("Tequila", True, False)
    VODKA = IngredientProps("Vodka", True, False)
    SODA = IngredientProps("Soda", False, False)
    TONIC = IngredientProps("Tonic", False, False)
    COLA = IngredientProps("Cola", False, False)
    CRANBERRY = IngredientProps("Cranberry", False, False)
    SPECIAL = IngredientProps("Special Mixer", False, True)
