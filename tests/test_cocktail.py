"""Tests for the recipe-directed cocktail planner and disposition.

Pure logic — no Supabase. The cocktail build is off by default (a long-game
specialist), but the situational planner/disposition must be correct when on.
"""

from uuid import uuid4

from app.GameState import GameState
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

# A bag with plenty of every spirit + mixer, so buildability passes by default.
_RICH_BAG = [GIN, GIN, GIN, RUM, RUM, WHISKEY, WHISKEY, SODA, SODA, COLA]


def _ps(cups, specials, *, drunk=0, bladder=None, capacity=7, points=0):
    return PlayerState(
        uuid4(),
        points=points,
        drunk_level=drunk,
        cups=cups,
        bladder=bladder or [],
        bladder_capacity=capacity,
        special_ingredients=list(specials),
    )


def _gs(ps, *, opponent_points=0, display=(), bag=None):
    opp = _ps([Cup(), Cup()], [], points=opponent_points)
    return GameState(
        winner=None,
        bag_contents=list(_RICH_BAG if bag is None else bag),
        player_states={ps.player_id: ps, opp.player_id: opp},
        player_turn=ps.player_id,
        open_display=list(display),
    )


def test_plan_targets_overlap_safe_recipe_when_buildable():
    # 1 gin in cup + vermouth on mat → Gin Martini (3 gin + vermouth), need 2 gin.
    # Martini is overlap-safe, so it's pursued regardless of the score.
    ps = _ps([Cup([GIN]), Cup()], ["vermouth"])
    plan = plan_cocktail(_gs(ps), ps)
    assert plan is not None
    assert plan.name == "Gin Martini"
    assert plan.cup_index == 0
    assert dict(plan.needed) == {GIN: 2}
    assert plan.overlap_safe is True


def test_no_plan_without_the_special():
    ps = _ps([Cup([GIN]), Cup()], [])
    assert plan_cocktail(_gs(ps), ps) is None


def test_no_plan_when_unbuildable():
    # Holds the special and the cup is on-path, but no gin is obtainable → hang on.
    ps = _ps([Cup([GIN]), Cup()], ["vermouth"])
    gs = _gs(ps, bag=[SODA, COLA, RUM], display=[SODA])
    assert plan_cocktail(gs, ps) is None


def test_no_plan_when_in_danger():
    assert (
        plan_cocktail(_gs(ps := _ps([Cup([GIN])], ["vermouth"], drunk=3)), ps) is None
    )
    ps2 = _ps([Cup([GIN]), Cup()], ["vermouth"], bladder=[SODA] * 6, capacity=7)
    assert plan_cocktail(_gs(ps2), ps2) is None


def test_risky_recipe_only_when_behind():
    # Mojito (2 rum + soda + sugar) is NOT overlap-safe (soda doesn't pair with
    # rum), so it strands the cup. Chase it only when behind.
    ahead = _ps([Cup(), Cup()], ["sugar"], points=20)
    assert plan_cocktail(_gs(ahead, opponent_points=5), ahead) is None

    behind = _ps([Cup(), Cup()], ["sugar"], points=5)
    plan = plan_cocktail(_gs(behind, opponent_points=20), behind)
    assert plan is not None and plan.name == "Mojito" and plan.overlap_safe is False


def test_display_takes_special_first_then_needed():
    ps = _ps([Cup([GIN]), Cup()], ["vermouth"])
    plan = plan_cocktail(_gs(ps), ps)
    asn = cocktail_display_assignments([GIN, SODA, SPECIAL], 3, plan)
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
    plan = plan_cocktail(_gs(ps), ps)
    # Draw order matters (handler pops FIFO): gin → target cup, off-plan whiskey
    # → other cup, soda → other cup (pairs with whiskey).
    asn = cocktail_pending_assignments(ps, [GIN, WHISKEY, SODA], plan)
    assert [a["disposition"] for a in asn] == ["cup", "cup", "cup"]
    assert asn[0]["cup_index"] == 0  # plan cup
    assert asn[1]["cup_index"] == 1  # other cup
    assert asn[2]["cup_index"] == 1


def test_pending_spoils_instead_of_drinking_into_danger():
    # At the drunk cap with the other cup holding rum: an off-plan whiskey can't
    # cup cleanly, so once the drink budget is spent it must be spoiled, not drunk.
    ps = _ps([Cup([GIN, GIN]), Cup([RUM])], ["vermouth"], drunk=2)
    plan = plan_cocktail(_gs(ps), ps)
    assert plan is not None and plan.cup_index == 0
    asn = cocktail_pending_assignments(ps, [WHISKEY, WHISKEY], plan)
    assert [a["disposition"] for a in asn].count("cup") >= 1
