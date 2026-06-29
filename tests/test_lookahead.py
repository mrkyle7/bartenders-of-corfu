"""Tests for the lookahead strategy wiring.

Pure game-logic tests — no Supabase required.
"""

from uuid import uuid4

from app.GameState import GameState

from ml.lookahead import LookaheadStrategy
from playtesting.strategy import STRATEGY_CLASSES
from playtesting.valid_actions import get_valid_actions


def test_registered_in_strategy_classes():
    assert STRATEGY_CLASSES.get("lookahead") is LookaheadStrategy


def test_choose_action_returns_a_valid_action():
    pids = [uuid4(), uuid4()]
    gs = GameState.start_game(pids)
    me = gs.player_turn
    actions = [a for a in get_valid_actions(gs, me) if not a.is_free]

    strat = LookaheadStrategy(depth=1, samples=1)
    chosen = strat.choose_action(gs, me, actions)
    assert chosen in actions


def test_single_action_is_returned_without_search():
    pids = [uuid4(), uuid4()]
    gs = GameState.start_game(pids)
    me = gs.player_turn
    actions = [a for a in get_valid_actions(gs, me) if not a.is_free]
    only = actions[:1]

    strat = LookaheadStrategy(depth=1, samples=1)
    assert strat.choose_action(gs, me, only) is only[0]
