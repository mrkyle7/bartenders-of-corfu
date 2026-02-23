"""Cocktail recipe validation and drink scoring.

Implements the drink_points() function per the scoring rules in game.allium.
"""

from collections import Counter

from app.Ingredient import Ingredient, SpecialType

_SPIRITS = {Ingredient.WHISKEY, Ingredient.GIN, Ingredient.RUM, Ingredient.TEQUILA, Ingredient.VODKA}
_MIXERS = {Ingredient.SODA, Ingredient.TONIC, Ingredient.COLA, Ingredient.CRANBERRY}

# Valid spirit → valid mixers for non-cocktail standard drinks
VALID_PAIRINGS: dict[Ingredient, set[Ingredient]] = {
    Ingredient.VODKA: {Ingredient.COLA, Ingredient.SODA, Ingredient.TONIC, Ingredient.CRANBERRY},
    Ingredient.RUM: {Ingredient.COLA},
    Ingredient.WHISKEY: {Ingredient.COLA, Ingredient.SODA},
    Ingredient.GIN: {Ingredient.TONIC},
    Ingredient.TEQUILA: set(),  # slammer only; no valid mixer pairings
}

# Cocktail recipes: (spirits_counter, mixers_counter, specials_counter, points, name)
# Long Island Iced Tea is listed first so it is checked before the generic 10-pt pass.
_RECIPES: list[tuple[Counter, Counter, Counter, int, str]] = [
    (
        Counter([Ingredient.GIN, Ingredient.VODKA, Ingredient.TEQUILA, Ingredient.RUM]),
        Counter([Ingredient.COLA]),
        Counter([SpecialType.SUGAR, SpecialType.LEMON]),
        15,
        "Long Island Iced Tea",
    ),
    (
        Counter([Ingredient.RUM, Ingredient.RUM]),
        Counter([Ingredient.SODA]),
        Counter([SpecialType.SUGAR]),
        10,
        "Mojito",
    ),
    (
        Counter([Ingredient.WHISKEY, Ingredient.WHISKEY, Ingredient.WHISKEY]),
        Counter(),
        Counter([SpecialType.BITTERS]),
        10,
        "Old Fashioned",
    ),
    (
        Counter([Ingredient.TEQUILA, Ingredient.TEQUILA]),
        Counter(),
        Counter([SpecialType.COINTREAU, SpecialType.LEMON]),
        10,
        "Margarita",
    ),
    (
        Counter([Ingredient.VODKA]),
        Counter([Ingredient.CRANBERRY]),
        Counter([SpecialType.COINTREAU, SpecialType.LEMON]),
        10,
        "Cosmopolitan",
    ),
    (
        Counter([Ingredient.GIN, Ingredient.GIN, Ingredient.GIN]),
        Counter(),
        Counter([SpecialType.VERMOUTH]),
        10,
        "Gin Martini",
    ),
    (
        Counter([Ingredient.VODKA, Ingredient.VODKA, Ingredient.VODKA]),
        Counter(),
        Counter([SpecialType.VERMOUTH]),
        10,
        "Vodka Martini",
    ),
    (
        Counter([Ingredient.GIN]),
        Counter([Ingredient.SODA]),
        Counter([SpecialType.LEMON, SpecialType.SUGAR]),
        10,
        "Tom Collins",
    ),
    (
        Counter([Ingredient.WHISKEY, Ingredient.WHISKEY]),
        Counter(),
        Counter([SpecialType.VERMOUTH, SpecialType.BITTERS]),
        10,
        "Manhattan",
    ),
]


def drink_points(cup_ingredients: list[Ingredient], declared_specials: list[str]) -> int | None:
    """Return points for selling the cup, or None if the cup is not sellable.

    Categories checked in order (first match wins):
      1. Long Island Iced Tea  → 15 pts
      2. Any other cocktail    → 10 pts
      3. Tequila Slammer       → 3 pts
      4. Double spirit drink   → 3 pts
      5. Single spirit drink   → 1 pt
    """
    cup_spirits = [i for i in cup_ingredients if i in _SPIRITS]
    cup_mixers = [i for i in cup_ingredients if i in _MIXERS]

    if not cup_spirits:
        return None  # no spirits → not sellable

    spirits_count = Counter(cup_spirits)
    mixers_count = Counter(cup_mixers)

    # Parse declared specials (ignore "nothing")
    parsed_specials: list[SpecialType] = []
    for s in declared_specials:
        try:
            st = SpecialType(s)
            if st != SpecialType.NOTHING:
                parsed_specials.append(st)
        except ValueError:
            return None  # unknown special type
    specials_count = Counter(parsed_specials)

    # Check cocktail recipes (Long Island first, then rest)
    for r_spirits, r_mixers, r_specials, pts, _name in _RECIPES:
        if spirits_count == r_spirits and mixers_count == r_mixers and specials_count == r_specials:
            return pts

    # Non-cocktail drinks: specials are not permitted
    if parsed_specials:
        return None

    total_spirits = len(cup_spirits)

    # Cocktails are exempt from the 2-spirit cap; non-cocktails are not
    if total_spirits > 2:
        return None

    # Tequila Slammer: exactly 2×tequila, no mixers, no specials
    if (
        total_spirits == 2
        and spirits_count.get(Ingredient.TEQUILA, 0) == 2
        and not cup_mixers
    ):
        return 3

    # All other non-cocktail drinks require at least one mixer
    if not cup_mixers:
        return None

    # Mixed spirits without a matching cocktail recipe → not sellable
    if len(spirits_count) != 1:
        return None

    spirit_type = next(iter(spirits_count))
    valid_mixers = VALID_PAIRINGS.get(spirit_type, set())

    # Every mixer in the cup must be valid for this spirit
    if not all(m in valid_mixers for m in cup_mixers):
        return None

    # Double spirit drink (2 of the same spirit + valid mixers)
    if total_spirits == 2:
        return 3

    # Single spirit drink
    return 1
