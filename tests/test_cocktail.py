"""Tests for the value/probability cocktail planner and disposition.

Pure logic — no Supabase. The cocktail build is off by default (a long-game
specialist), but the EV planner and disposition must be correct when on.
"""

from uuid import uuid4

from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import Cup, PlayerState

from ml.cocktail import (
    best_cocktail,
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

# A bag with plenty of every spirit + mixer, so completion probability is high.
_RICH_BAG = [GIN, GIN, GIN, GIN, RUM, RUM, WHISKEY, WHISKEY, SODA, SODA, COLA]


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


def test_best_cocktail_picks_buildable_recipe_with_positive_ev():
    # 1 gin in cup + vermouth → Gin Martini (3 gin), need 2 gin; bag is gin-rich.
    ps = _ps([Cup([GIN]), Cup()], ["vermouth"])
    plan, ev = best_cocktail(_gs(ps), ps)
    assert plan is not None
    assert plan.name == "Gin Martini"
    assert plan.cup_index == 0
    assert dict(plan.needed) == {GIN: 2}
    assert 0.0 < plan.probability <= 1.0
    assert ev > 0.0


def test_no_cocktail_without_the_special():
    ps = _ps([Cup([GIN]), Cup()], [])
    assert best_cocktail(_gs(ps), ps) == (None, 0.0)


def test_impossible_build_has_zero_ev():
    # Holds the special but there aren't 2 gins to be had → EV 0, no build.
    ps = _ps([Cup([GIN]), Cup()], ["vermouth"])
    gs = _gs(ps, bag=[SODA, COLA, RUM], display=[SODA])
    assert best_cocktail(gs, ps) == (None, 0.0)
    assert plan_cocktail(gs, ps) is None


def test_higher_probability_means_higher_ev():
    # Same 2-gin martini need: a gin-rich pool scores higher EV than a gin-thin one.
    ps = _ps([Cup([GIN]), Cup()], ["vermouth"])
    _, ev_rich = best_cocktail(_gs(ps, bag=[GIN, GIN, GIN, GIN, GIN, GIN]), ps)
    _, ev_thin = best_cocktail(_gs(ps, bag=[GIN, GIN]), ps)
    assert ev_rich > ev_thin > 0.0


def test_plan_requires_ev_above_build_bar():
    # A gin-thin pool (exactly 2 gins) is buildable but low-probability: best_cocktail
    # still reports it, but plan_cocktail withholds it below the build threshold.
    ps = _ps([Cup([GIN]), Cup()], ["vermouth"])
    gs = _gs(ps, bag=[GIN, GIN])
    plan, ev = best_cocktail(gs, ps)
    assert plan is not None and ev > 0.0
    # With a generous pool it clears the bar and the disposition commits.
    assert plan_cocktail(_gs(ps), ps) is not None


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
