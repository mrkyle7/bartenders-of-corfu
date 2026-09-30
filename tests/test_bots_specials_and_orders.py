"""Bots with specials as ingredients, and bots that chase drink orders.

Pure tests (no Supabase): they drive the playtesting strategies and runner.
"""

import random
import uuid
from collections import Counter

import pytest

from app.card import Card
from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import Cup
from playtesting.runner import GameRunner
from playtesting.strategy import (
    STRATEGY_CLASSES,
    CupTracker,
    OrderChaser,
    _in_drawn_order,
    _smart_pending_assignments,
    order_needs,
    order_plans,
)

I = Ingredient  # noqa: E741


def _order(name: str, drink: str, bonus: int = 3, **kw) -> Card:
    return Card(
        id=f"o-{name}", card_type="order", name=name, drink=drink, bonus=bonus, **kw
    )


def _game(players: int = 2) -> GameState:
    return GameState.start_game([uuid.uuid4() for _ in range(players)])


def _orders_row(gs: GameState, cards: list[Card]) -> None:
    next(r for r in gs.card_rows if r.position == 2).cards = cards


# ─── Glasses on their way to a cocktail ─────────────────────────────────────


def test_a_glass_with_sugar_only_takes_what_a_sugar_cocktail_needs():
    gs = _game()
    ps = gs.player_states[gs.player_turn]
    ps.cups[0] = Cup(ingredients=[I.SUGAR])
    cups = CupTracker(ps)
    assert cups.is_cocktail_cup(0)
    # Mojito (rum, soda), Tom Collins (gin, soda), Long Island (four spirits, cola)
    assert cups._can_add_spirit(0, I.RUM)
    assert cups._can_add_spirit(0, I.GIN)
    assert not cups._can_add_spirit(0, I.WHISKEY)
    assert cups._can_add_mixer(0, I.SODA)
    assert not cups._can_add_mixer(0, I.TONIC)


def test_a_special_goes_where_it_finishes_a_cocktail():
    gs = _game()
    ps = gs.player_states[gs.player_turn]
    ps.cups[0] = Cup(ingredients=[I.GIN, I.TONIC])
    ps.cups[1] = Cup(ingredients=[I.RUM, I.RUM, I.SODA])
    cups = CupTracker(ps)
    assert cups.best_cup_for_special(I.SUGAR, available=Counter()) == 1
    # Nothing to gain from vermouth in either glass
    assert cups.best_cup_for_special(I.VERMOUTH, available=Counter()) is None


def test_bots_put_a_finishing_special_in_the_glass():
    gs = _game()
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.cups[1] = Cup(ingredients=[I.RUM, I.RUM, I.SODA])
    gs.specials_display = [I.SUGAR]
    asg = STRATEGY_CLASSES["safe"]().choose_take_assignments(gs, pid, 3)
    assert {
        "ingredient": "SUGAR",
        "source": "specials",
        "disposition": "cup",
        "cup_index": 1,
    } in asg


def test_pending_assignments_line_up_with_the_draw():
    gs = _game()
    ps = gs.player_states[gs.player_turn]
    ps.cups[0] = Cup(ingredients=[I.VODKA])
    drawn = [I.SODA, I.WHISKEY, I.VODKA]
    asg = _smart_pending_assignments(ps, drawn, CupTracker(ps))
    # The vodka (drawn last) is the one that goes into the vodka glass
    assert asg[2] == {"source": "pending", "disposition": "cup", "cup_index": 0}


def test_in_drawn_order_reorders_by_ingredient():
    drawn = [I.COLA, I.RUM, I.COLA]
    decided = [I.RUM, I.COLA, I.COLA]
    asg = [{"n": "rum"}, {"n": "cola1"}, {"n": "cola2"}]
    assert _in_drawn_order(drawn, decided, asg) == [
        {"n": "cola1"},
        {"n": "rum"},
        {"n": "cola2"},
    ]


# ─── Orders ──────────────────────────────────────────────────────────────────


def test_order_needs():
    rum_cola = _order("Rum and Cola", "simple", spirit_type="RUM", mixer_type="COLA")
    assert order_needs(rum_cola, []) == Counter({I.RUM: 1, I.COLA: 1})
    assert order_needs(rum_cola, [I.RUM]) == Counter({I.COLA: 1})
    assert order_needs(rum_cola, [I.GIN]) is None
    assert order_needs(rum_cola, [I.RUM, I.SUGAR]) is None
    slammer = _order("Slammer", "slammer")
    assert order_needs(slammer, [I.TEQUILA]) == Counter({I.TEQUILA: 1})
    mojito = _order("Mojito", "cocktail", cocktail="Mojito")
    assert order_needs(mojito, [I.RUM, I.SUGAR]) == Counter({I.RUM: 1, I.SODA: 1})


def test_each_order_is_planned_for_one_glass():
    gs = _game()
    ps = gs.player_states[gs.player_turn]
    _orders_row(
        gs,
        [
            _order("Gin and Tonic", "simple", spirit_type="GIN", mixer_type="TONIC"),
            _order("Slammer", "slammer"),
        ],
    )
    ps.cups[0] = Cup(ingredients=[I.GIN])
    ps.cups[1] = Cup(ingredients=[I.TEQUILA])
    plans = order_plans(gs, ps)
    assert plans[0][0].name == "Gin and Tonic"
    assert plans[1][0].name == "Slammer"


def test_order_chaser_takes_what_its_order_needs():
    gs = _game()
    pid = gs.player_turn
    ps = gs.player_states[pid]
    _orders_row(
        gs,
        [_order("Gin and Tonic", "simple", spirit_type="GIN", mixer_type="TONIC")],
    )
    ps.cups[0] = Cup(ingredients=[I.GIN])
    gs.open_display = [I.TONIC, I.COLA, I.COLA, I.RUM, I.WHISKEY]
    gs.display_specials = [None] * 5
    gs.specials_display = [I.LEMON]
    asg = OrderChaser().choose_take_assignments(gs, pid, 3)
    assert asg[0] == {
        "ingredient": "TONIC",
        "source": "display",
        "disposition": "cup",
        "cup_index": 0,
    }
    # No special goes into the glass kept for a Gin and Tonic
    assert not any(a.get("cup_index") == 0 and a["source"] == "specials" for a in asg)


def test_order_chaser_serves_an_order_when_it_can():
    gs = _game()
    pid = gs.player_turn
    ps = gs.player_states[pid]
    _orders_row(
        gs,
        [_order("Gin and Tonic", "simple", spirit_type="GIN", mixer_type="TONIC")],
    )
    ps.cups[0] = Cup(ingredients=[I.GIN, I.TONIC])
    ps.cups[1] = Cup(ingredients=[I.VODKA, I.VODKA, I.SODA])
    from playtesting.valid_actions import get_valid_actions

    actions = [a for a in get_valid_actions(gs, pid) if not a.is_free]
    chosen = OrderChaser().choose_action(gs, pid, actions)
    assert chosen.action_type == "sell_cup"
    assert chosen.params["cup_index"] == 0
    assert chosen.params["order"] == "Gin and Tonic"


def test_order_bots_are_registered():
    assert STRATEGY_CLASSES["orders"] is OrderChaser


# ─── Whole games ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bot", ["orders", "cocktail", "mastermind", "safe"])
def test_whole_games_finish(bot):
    for seed in range(3):
        random.seed(seed)
        strategies = {
            uuid.uuid4(): STRATEGY_CLASSES[bot](),
            uuid.uuid4(): STRATEGY_CLASSES["mastermind"](),
        }
        result = GameRunner(strategies, seed=seed).run()
        assert result.reason in ("points", "karaoke", "last_standing")
