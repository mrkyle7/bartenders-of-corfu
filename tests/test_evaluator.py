"""Tests for the static state evaluator and the lookahead strategy.

Pure game-logic tests — no Supabase required.
"""

from uuid import uuid4

from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import Cup, PlayerState

from ml.evaluator import (
    LOSS_VALUE,
    WIN_VALUE,
    _best_cup_sale,
    _safety_penalty,
    evaluate,
    player_potential,
)


def _two_player_state() -> tuple[GameState, list]:
    pids = [uuid4(), uuid4()]
    gs = GameState.start_game(pids)
    return gs, pids


# ---------------------------------------------------------------------------
#  Terminal overrides
# ---------------------------------------------------------------------------


def test_winner_is_max_value():
    gs, pids = _two_player_state()
    gs.winner = pids[0]
    assert evaluate(gs, pids[0]) == WIN_VALUE
    assert evaluate(gs, pids[1]) == LOSS_VALUE


def test_eliminated_player_is_loss():
    gs, pids = _two_player_state()
    gs.player_states[pids[0]].status = "hospitalised"
    assert evaluate(gs, pids[0]) == LOSS_VALUE


# ---------------------------------------------------------------------------
#  Cup sale valuation
# ---------------------------------------------------------------------------


def _ps_with_cup(cup: Cup, cards=None) -> PlayerState:
    ps = PlayerState(uuid4(), points=0, drunk_level=0, cups=[cup, Cup()])
    ps.cards = cards or []
    return ps


def test_single_spirit_drink_is_one_point():
    cup = Cup([Ingredient.VODKA, Ingredient.COLA])
    assert _best_cup_sale(_ps_with_cup(cup), cup) == 1


def test_doubler_doubles_non_cocktail():
    cup = Cup([Ingredient.VODKA, Ingredient.COLA], has_cup_doubler=True)
    assert _best_cup_sale(_ps_with_cup(cup), cup) == 2


def test_double_spirit_drink_is_three_points():
    cup = Cup([Ingredient.VODKA, Ingredient.VODKA, Ingredient.COLA])
    assert _best_cup_sale(_ps_with_cup(cup), cup) == 3


def test_specialist_adds_bonus():
    cup = Cup([Ingredient.VODKA, Ingredient.COLA])
    cards = [{"card_type": "specialist", "spirit_type": "VODKA"}]
    # 1 (base) + 2 (specialist) = 3
    assert _best_cup_sale(_ps_with_cup(cup, cards), cup) == 3


def test_empty_cup_has_no_sale_value():
    cup = Cup([])
    assert _best_cup_sale(_ps_with_cup(cup), cup) == 0


# Cocktail-progress is exercised in tests/test_cocktail.py (the planner it
# delegates to needs full game state, not just a cup).


# ---------------------------------------------------------------------------
#  Safety penalties are monotonic
# ---------------------------------------------------------------------------


def test_drunk_penalty_increases_with_drunk():
    low = PlayerState(uuid4(), points=0, drunk_level=1)
    high = PlayerState(uuid4(), points=0, drunk_level=4)
    assert _safety_penalty(high) > _safety_penalty(low)


def test_full_bladder_penalised():
    capacity = 8
    empty = PlayerState(uuid4(), points=0, drunk_level=0)
    full = PlayerState(
        uuid4(),
        points=0,
        drunk_level=0,
        bladder=[Ingredient.COLA] * (capacity - 1),
        bladder_capacity=capacity,
    )
    assert _safety_penalty(full) > _safety_penalty(empty)


def test_more_points_scores_higher():
    gs, pids = _two_player_state()
    low_ps = gs.player_states[pids[0]]
    low_val = player_potential(gs, low_ps, full=True)
    low_ps.points = 20
    high_val = player_potential(gs, low_ps, full=True)
    assert high_val > low_val
