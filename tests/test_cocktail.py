"""Tests for the recipe-directed cocktail planner and disposition.

Pure logic — no Supabase. The cocktail build is off by default (it's a long-game
specialist that regresses vs Mastermind), but the planner/disposition must be
correct whenever it is enabled.
"""

from uuid import uuid4

from app.Ingredient import Ingredient
from app.PlayerState import Cup, PlayerState

from ml.cocktail import (
    cocktail_display_assignments,
    cocktail_pending_assignments,
    plan_cocktail,
)

GIN = Ingredient.GIN
WHISKEY = Ingredient.WHISKEY
RUM = Ingredient.RUM
SODA = Ingredient.SODA
COLA = Ingredient.COLA
SPECIAL = Ingredient.SPECIAL


def _ps(cups, specials, *, drunk=0, bladder=None, capacity=7):
    return PlayerState(
        uuid4(),
        points=0,
        drunk_level=drunk,
        cups=cups,
        bladder=bladder or [],
        bladder_capacity=capacity,
        special_ingredients=list(specials),
    )


def test_plan_targets_recipe_from_held_special():
    # 1 gin in cup + vermouth on mat → Gin Martini (3 gin + vermouth), need 2 gin.
    ps = _ps([Cup([GIN]), Cup()], ["vermouth"])
    plan = plan_cocktail(ps)
    assert plan is not None
    assert plan.name == "Gin Martini"
    assert plan.cup_index == 0
    assert dict(plan.needed) == {GIN: 2}


def test_no_plan_without_the_special():
    ps = _ps([Cup([GIN]), Cup()], [])
    assert plan_cocktail(ps) is None


def test_no_plan_when_in_danger():
    # Same buildable martini, but too drunk / bladder too full → survival first.
    assert plan_cocktail(_ps([Cup([GIN]), Cup()], ["vermouth"], drunk=3)) is None
    assert (
        plan_cocktail(
            _ps([Cup([GIN]), Cup()], ["vermouth"], bladder=[SODA] * 6, capacity=7)
        )
        is None
    )


def test_display_takes_special_first_then_needed():
    ps = _ps([Cup([GIN]), Cup()], ["vermouth"])
    plan = plan_cocktail(ps)
    asn = cocktail_display_assignments([GIN, SODA, SPECIAL], 3, plan)
    # SPECIAL banked first, then the needed gin to the target cup; soda skipped.
    assert asn[0]["ingredient"] == "SPECIAL"
    assert asn[1] == {
        "ingredient": "GIN",
        "source": "display",
        "disposition": "cup",
        "cup_index": 0,
    }
    assert all(a["ingredient"] != "SODA" for a in asn)


def test_pending_routes_needed_in_order():
    ps = _ps([Cup([GIN]), Cup()], ["vermouth"])
    plan = plan_cocktail(ps)
    # drawn order matters (handler pops FIFO): gin → target cup, off-plan whiskey
    # → other cup, soda → other cup (pairs with whiskey).
    asn = cocktail_pending_assignments(ps, [GIN, WHISKEY, SODA], plan)
    assert [a["disposition"] for a in asn] == ["cup", "cup", "cup"]
    assert asn[0]["cup_index"] == 0  # plan cup
    assert asn[1]["cup_index"] == 1  # other cup
    assert asn[2]["cup_index"] == 1


def test_pending_spoils_instead_of_drinking_into_danger():
    # Drunk 2 (the cap): an off-plan spirit that can't cleanly cup must be dumped
    # into a cup (spoiled), never drunk past the safe cap. The other cup already
    # holds rum, so a whiskey can't go there cleanly — it has to be spoiled, not
    # drunk, once the drink budget is spent.
    ps = _ps([Cup([GIN, GIN]), Cup([RUM])], ["vermouth"], drunk=2)
    plan = plan_cocktail(ps)
    assert plan is not None and plan.cup_index == 0
    asn = cocktail_pending_assignments(ps, [WHISKEY, WHISKEY], plan)
    # At least one whiskey is cupped (spoiled) rather than drunk into the cliff.
    assert [a["disposition"] for a in asn].count("cup") >= 1
