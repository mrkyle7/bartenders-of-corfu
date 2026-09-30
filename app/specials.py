"""Special ingredients: the purple die tokens and the specials they become.

There is one special of each type (bitters, cointreau, lemon, sugar,
vermouth). A special token is rolled as soon as it comes out of the bag,
onto the open display or into a player's hand, so everyone can see which
special it offers. The blank face is "choose any". Taking the token puts a
special of that type on your mat and the token goes back into the bag.

A player holds at most two specials. Taking a third means swapping one of
yours back, or leaving the new one.
"""

import random

from app.Ingredient import Ingredient, SpecialType

SPECIAL_TYPES: list[str] = ["bitters", "cointreau", "lemon", "sugar", "vermouth"]
WILD = "any"
MAX_SPECIALS_PER_PLAYER = 2


def special_tokens_for(num_players: int) -> int:
    """Special tokens in the bag: 4 for two players, 5 for three, 6 for four."""
    return num_players + 2


def specials_held(gs) -> set[str]:
    """Special types sitting on any player's mat."""
    return {s for ps in gs.player_states.values() for s in ps.special_ingredients}


def specials_shown(gs) -> set[str]:
    """Special types shown face up on the display or in a player's bag draw."""
    faces = list(gs.display_specials) + list(gs.bag_draw_pending_specials)
    return {f for f in faces if f and f != WILD}


def free_special_types(gs) -> list[str]:
    """Special types nobody holds and no token is showing."""
    taken = specials_held(gs) | specials_shown(gs)
    return [t for t in SPECIAL_TYPES if t not in taken]


def roll_face(gs) -> str:
    """Roll the special die for a token coming out of the bag.

    A face whose special is already held or showing is rolled again; the
    blank face is "choose any".
    """
    free = set(free_special_types(gs))
    for _ in range(20):
        rolled = SpecialType.roll()
        if rolled == SpecialType.NOTHING:
            return WILD
        if rolled.value in free:
            return rolled.value
    return WILD


def take_special(
    gs, ps, face: str, choice: str | None = None, swap: str | None = None
) -> dict:
    """A player takes a special token showing ``face``.

    ``choice`` picks the special for a "choose any" face; ``swap`` names one
    of the player's specials to give back when they already hold two.
    The token itself always goes back into the bag.

    Returns {"special_type": type or "nothing", "face": face, "swapped": ...}.
    """
    gs.bag_contents.append(Ingredient.SPECIAL)
    record: dict = {"face": face, "special_type": "nothing", "swapped": None}

    held = specials_held(gs)
    if face == WILD:
        options = free_special_types(gs)
        if not options:
            return record
        special = choice if choice in options else random.choice(options)
    else:
        if face in held:
            return record
        special = face

    if len(ps.special_ingredients) >= MAX_SPECIALS_PER_PLAYER:
        if swap not in ps.special_ingredients:
            record["left"] = True
            return record
        ps.special_ingredients.remove(swap)
        record["swapped"] = swap

    ps.special_ingredients.append(special)
    record["special_type"] = special
    return record
