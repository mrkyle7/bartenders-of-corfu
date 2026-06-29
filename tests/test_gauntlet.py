"""Tests for the win-rate gauntlet harness and the offline-play mode plumbing.

These are pure game-logic tests — no Supabase required.
"""

import pytest

from app.game_modes import VALID_GAME_MODES

from ml.gauntlet import (
    CANDIDATE,
    CHAMPION,
    _parse_strategy_spec,
    _resolve_modes,
    run_gauntlet,
    wilson_lower_bound,
)
from playtesting.strategy import Mastermind


# ---------------------------------------------------------------------------
#  Wilson lower bound
# ---------------------------------------------------------------------------


def test_wilson_zero_games_is_zero():
    assert wilson_lower_bound(0, 0) == 0.0


def test_wilson_all_wins_below_one_but_high():
    lb = wilson_lower_bound(20, 20)
    assert 0.8 < lb < 1.0


def test_wilson_more_games_tightens_bound():
    # Same 60% win rate, more games -> higher (tighter) lower bound.
    few = wilson_lower_bound(6, 10)
    many = wilson_lower_bound(60, 100)
    assert many > few


def test_wilson_fifty_fifty_below_half():
    # A coin-flip result must not clear a >50% gate.
    assert wilson_lower_bound(50, 100) < 0.5


# ---------------------------------------------------------------------------
#  Spec / mode parsing
# ---------------------------------------------------------------------------


def test_parse_known_strategy():
    factory, label = _parse_strategy_spec("mastermind")
    assert label == "mastermind"
    assert isinstance(factory(), Mastermind)


def test_parse_unknown_strategy_raises():
    with pytest.raises(ValueError):
        _parse_strategy_spec("does-not-exist")


def test_parse_mcts_spec_params():
    factory, label = _parse_strategy_spec("mcts:sims=42")
    assert "sims=42" in label
    strat = factory()
    assert strat.search_engine.num_simulations == 42
    # The gauntlet must never let a bot mutate the shared policy.
    assert strat._learn is False


def test_mcts_default_does_not_learn():
    """Production bots use MCTSStrategy() with no args; that must not mutate
    the shared OnlinePolicy."""
    from ml.mcts import MCTSStrategy

    assert MCTSStrategy()._learn is False


def test_resolve_modes_all_and_none():
    assert _resolve_modes("none") == []
    assert _resolve_modes(None) == []
    assert set(_resolve_modes("all")) == set(VALID_GAME_MODES)


def test_resolve_modes_specific():
    assert _resolve_modes("sell_both_cups") == ["sell_both_cups"]


# ---------------------------------------------------------------------------
#  Gauntlet run invariants
# ---------------------------------------------------------------------------


def test_gauntlet_mirror_match_invariants():
    res = run_gauntlet(Mastermind, Mastermind, games=6, base_seed=123, progress_every=0)
    assert res.errors == 0
    assert res.games == 6
    # Every game is decisive or a draw.
    assert res.candidate_wins + res.champion_wins + res.draws == res.games
    # Seat balance: candidate goes first in exactly half the games.
    assert res.candidate_first_games == 3


def test_gauntlet_runs_with_all_modes_enabled():
    """The whole point: optional rules must actually be exercised offline."""
    modes = list(VALID_GAME_MODES)
    res = run_gauntlet(
        Mastermind,
        Mastermind,
        games=4,
        base_seed=99,
        game_modes=modes,
        progress_every=0,
    )
    assert res.errors == 0
    assert res.games == 4
    # Points get recorded per role, proving games ran to completion.
    assert len(res.points[CANDIDATE]) == 4
    assert len(res.points[CHAMPION]) == 4


# ---------------------------------------------------------------------------
#  Runner mode plumbing
# ---------------------------------------------------------------------------


def test_runner_threads_game_modes_into_state():
    from uuid import uuid4

    from playtesting.runner import GameRunner

    pids = [uuid4(), uuid4()]
    strategies = {pid: Mastermind() for pid in pids}
    runner = GameRunner(strategies, seed=1, game_modes=["sell_both_cups"])
    assert runner.game_modes == ["sell_both_cups"]
