import random
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class IngredientProps:
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
    # The old special die token (games started before specials were
    # ingredients). New games put the five specials below in the bag instead.
    SPECIAL = IngredientProps("Special Mixer", False, True)
    # Specials: two of each in the bag. Drawn ones wait on the specials
    # display; a player takes one into a glass or drinks it (like a mixer).
    BITTERS = IngredientProps("Bitters", False, True)
    COINTREAU = IngredientProps("Cointreau", False, True)
    LEMON = IngredientProps("Lemon", False, True)
    SUGAR = IngredientProps("Sugar", False, True)
    VERMOUTH = IngredientProps("Vermouth", False, True)


class SpecialType(Enum):
    """Resolved special ingredient types — rolled when a SPECIAL token is drawn."""

    BITTERS = "bitters"
    COINTREAU = "cointreau"
    LEMON = "lemon"
    SUGAR = "sugar"
    VERMOUTH = "vermouth"
    NOTHING = "nothing"  # token returned to bag immediately

    @classmethod
    def roll(cls) -> "SpecialType":
        """Simulate rolling the special die — equal probability for each face."""
        return random.choice(
            [
                cls.BITTERS,
                cls.COINTREAU,
                cls.LEMON,
                cls.SUGAR,
                cls.VERMOUTH,
                cls.NOTHING,
            ]
        )


SPECIAL_INGREDIENTS: tuple[Ingredient, ...] = (
    Ingredient.BITTERS,
    Ingredient.COINTREAU,
    Ingredient.LEMON,
    Ingredient.SUGAR,
    Ingredient.VERMOUTH,
)
SPECIALS_PER_TYPE = 2


def is_special(ingredient: Ingredient) -> bool:
    """A special ingredient (bitters, cointreau, lemon, sugar, vermouth)."""
    return ingredient in SPECIAL_INGREDIENTS


def special_type_of(ingredient: Ingredient) -> str | None:
    """The special type name ("bitters", ...) of a special ingredient."""
    return ingredient.name.lower() if ingredient in SPECIAL_INGREDIENTS else None


# Drinking a special: the boozy ones count like a spirit, the rest like a mixer.
BOOZY_SPECIALS: frozenset[Ingredient] = frozenset(
    {Ingredient.BITTERS, Ingredient.COINTREAU, Ingredient.VERMOUTH}
)

# A specialist card can be claimed with one of its spirit's special instead
# of two of the spirit.
SPECIALIST_SPECIAL: dict[str, Ingredient] = {
    "WHISKEY": Ingredient.BITTERS,
    "TEQUILA": Ingredient.COINTREAU,
    "VODKA": Ingredient.VERMOUTH,
    "RUM": Ingredient.SUGAR,
    "GIN": Ingredient.LEMON,
}
