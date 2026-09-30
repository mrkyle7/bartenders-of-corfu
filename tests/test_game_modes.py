"""The optional game modes are retired.

Selling both cups and claiming a card as a free action are standard rules
now (see tests/test_market_and_specials.py), and re-rolling specials is gone.
These tests check the old modes are no longer accepted for new games, and that
games saved with them still load and play by the standard rules.
"""

import uuid as _uuid

import pytest

from app.actions import sell_cup
from app.game import GameException
from app.game_modes import RETIRED_GAME_MODES, VALID_GAME_MODES, normalise_modes
from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import Cup


def test_no_optional_modes_are_offered():
    assert VALID_GAME_MODES == frozenset()


@pytest.mark.parametrize("mode", sorted(RETIRED_GAME_MODES))
def test_retired_modes_are_rejected_for_new_games(mode):
    with pytest.raises(ValueError):
        normalise_modes([mode])


def test_normalise_modes_handles_none_and_empty():
    assert normalise_modes(None) == []
    assert normalise_modes([]) == []


def test_game_saved_with_old_modes_still_loads_and_plays():
    """A game started with sell_both_cups loads, and selling both is just standard."""
    gs = GameState.start_game([_uuid.uuid4(), _uuid.uuid4()])
    data = gs.to_dict()
    data["game_modes"] = ["sell_both_cups", "reroll_specials_free_action"]
    loaded = GameState.from_dict(data)
    assert loaded.game_modes == ["sell_both_cups", "reroll_specials_free_action"]

    pid = loaded.player_turn
    ps = loaded.player_states[pid]
    ps.cups[0] = Cup(ingredients=[Ingredient.VODKA, Ingredient.COLA])
    ps.cups[1] = Cup(ingredients=[Ingredient.GIN, Ingredient.TONIC])
    new_state, payload = sell_cup(
        loaded,
        pid,
        cup_index=0,
        declared_specials=[],
        additional_cups=[{"cup_index": 1, "declared_specials": []}],
    )
    assert len(payload["sold_cups"]) == 2


def test_sell_cup_rejects_same_cup_twice():
    gs = GameState.start_game([_uuid.uuid4(), _uuid.uuid4()])
    pid = gs.player_turn
    gs.player_states[pid].cups[0] = Cup(ingredients=[Ingredient.VODKA, Ingredient.COLA])
    with pytest.raises(GameException) as exc:
        sell_cup(
            gs,
            pid,
            cup_index=0,
            declared_specials=[],
            additional_cups=[{"cup_index": 0, "declared_specials": []}],
        )
    assert exc.value.status_code == 400
