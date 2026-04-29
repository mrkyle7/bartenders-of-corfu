"""Unit tests for the game modes layer.

Covers:
- ``app.game_modes`` validation helpers.
- ``GameState`` serialisation round-trips ``game_modes``.
- ``playtesting.valid_actions`` surfaces combined sell options to bots
  when the ``sell_both_cups`` mode is active, and not otherwise.
- ``app.actions.sell_cup`` rejects ``additional_cups`` without the mode and
  scores both cups when the mode is enabled.
"""

import uuid as _uuid

import pytest

from app.actions import sell_cup
from app.game import GameException
from app.game_modes import GameMode, normalise_modes
from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import Cup, PlayerState
from playtesting.valid_actions import get_valid_actions


# ─── game_modes module ───────────────────────────────────────────────────────


def test_normalise_modes_preserves_valid_modes():
    assert normalise_modes(["sell_both_cups"]) == ["sell_both_cups"]


def test_normalise_modes_dedupes():
    assert normalise_modes(["sell_both_cups", "sell_both_cups"]) == ["sell_both_cups"]


def test_normalise_modes_rejects_unknown():
    with pytest.raises(ValueError):
        normalise_modes(["not_a_mode"])


def test_normalise_modes_handles_none_and_empty():
    assert normalise_modes(None) == []
    assert normalise_modes([]) == []


def test_game_mode_enum_value_matches_string():
    assert GameMode.SELL_BOTH_CUPS.value == "sell_both_cups"


# ─── GameState serialisation ─────────────────────────────────────────────────


def _two_player_state(modes: list[str] | None = None) -> GameState:
    """Build a minimal, valid two-player GameState in mid-game."""
    p1 = _uuid.uuid4()
    p2 = _uuid.uuid4()
    ps1 = PlayerState.new_player(p1)
    ps2 = PlayerState.new_player(p2)
    return GameState(
        winner=None,
        bag_contents=[],
        player_states={p1: ps1, p2: ps2},
        player_turn=p1,
        turn_order=[p1, p2],
        game_modes=modes,
    )


def test_game_state_round_trip_preserves_modes():
    gs = _two_player_state(["sell_both_cups"])
    restored = GameState.from_dict(gs.to_dict())
    assert restored.game_modes == ["sell_both_cups"]
    assert restored.has_mode("sell_both_cups") is True


def test_game_state_default_modes_empty():
    gs = _two_player_state(None)
    assert gs.game_modes == []
    assert gs.has_mode("sell_both_cups") is False


def test_from_dict_tolerates_missing_game_modes_key():
    gs = _two_player_state(None)
    state = gs.to_dict()
    state.pop("game_modes", None)  # simulate older payloads
    restored = GameState.from_dict(state)
    assert restored.game_modes == []


# ─── valid_actions: bot mode awareness ───────────────────────────────────────


def _setup_two_sellable_cups(modes: list[str]) -> tuple[GameState, _uuid.UUID]:
    gs = _two_player_state(modes)
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.cups[0] = Cup(ingredients=[Ingredient.VODKA, Ingredient.COLA])
    ps.cups[1] = Cup(ingredients=[Ingredient.RUM, Ingredient.RUM, Ingredient.COLA])
    return gs, pid


def test_valid_actions_no_combined_sell_when_mode_off():
    gs, pid = _setup_two_sellable_cups(modes=[])
    actions = get_valid_actions(gs, pid)
    sells = [a for a in actions if a.action_type == "sell_cup"]
    assert sells, "Should still have single-cup sell options"
    assert all(not a.params.get("additional_cups") for a in sells), (
        "Combined sell options must NOT appear when mode is off"
    )


def test_valid_actions_includes_combined_sell_when_mode_on():
    gs, pid = _setup_two_sellable_cups(modes=["sell_both_cups"])
    actions = get_valid_actions(gs, pid)
    combined = [
        a
        for a in actions
        if a.action_type == "sell_cup" and a.params.get("additional_cups")
    ]
    assert combined, "Expected at least one combined sell option"
    # Single-spirit (1pt) + double-spirit (3pts) = 4pts
    points = {a.params["points"] for a in combined}
    assert 4 in points, f"Expected combined sell of 4pts, got {points}"


def test_valid_actions_combined_sell_skips_when_one_cup_unsellable():
    gs = _two_player_state(["sell_both_cups"])
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.cups[0] = Cup(ingredients=[Ingredient.VODKA, Ingredient.COLA])
    ps.cups[1] = Cup(ingredients=[])  # empty
    actions = get_valid_actions(gs, pid)
    combined = [
        a
        for a in actions
        if a.action_type == "sell_cup" and a.params.get("additional_cups")
    ]
    assert combined == [], (
        "No combined sell option should exist when only one cup is sellable"
    )


# ─── actions.sell_cup with additional_cups ───────────────────────────────────


def test_sell_cup_rejects_additional_cups_without_mode():
    gs, pid = _setup_two_sellable_cups(modes=[])
    with pytest.raises(GameException) as exc:
        sell_cup(
            gs,
            pid,
            cup_index=0,
            declared_specials=[],
            additional_cups=[{"cup_index": 1, "declared_specials": []}],
        )
    assert exc.value.status_code == 400


def test_sell_cup_with_additional_cups_scores_both_when_mode_on():
    gs, pid = _setup_two_sellable_cups(modes=["sell_both_cups"])
    new_state, payload = sell_cup(
        gs,
        pid,
        cup_index=0,
        declared_specials=[],
        additional_cups=[{"cup_index": 1, "declared_specials": []}],
    )
    ps = new_state.player_states[pid]
    assert ps.points == 4, f"Expected 1 + 3 = 4 points, got {ps.points}"
    assert ps.cups[0].is_empty
    assert ps.cups[1].is_empty
    assert payload["points_earned"] == 4
    assert "sold_cups" in payload and len(payload["sold_cups"]) == 2


def test_sell_cup_rejects_same_cup_twice():
    gs, pid = _setup_two_sellable_cups(modes=["sell_both_cups"])
    with pytest.raises(GameException) as exc:
        sell_cup(
            gs,
            pid,
            cup_index=0,
            declared_specials=[],
            additional_cups=[{"cup_index": 0, "declared_specials": []}],
        )
    assert exc.value.status_code == 400


def test_sell_cup_rejects_same_special_on_both_cups():
    gs = _two_player_state(["sell_both_cups"])
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.cups[0] = Cup(ingredients=[Ingredient.RUM, Ingredient.RUM, Ingredient.SODA])
    ps.cups[1] = Cup(ingredients=[Ingredient.RUM, Ingredient.RUM, Ingredient.SODA])
    ps.special_ingredients = ["sugar"]  # only one in stock — can't double up
    with pytest.raises(GameException) as exc:
        sell_cup(
            gs,
            pid,
            cup_index=0,
            declared_specials=["sugar"],
            additional_cups=[{"cup_index": 1, "declared_specials": ["sugar"]}],
        )
    assert exc.value.status_code == 400
