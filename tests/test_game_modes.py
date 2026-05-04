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
    assert GameMode.CLAIM_CARD_FREE_ACTION.value == "claim_card_free_action"
    assert GameMode.REROLL_SPECIALS_FREE_ACTION.value == "reroll_specials_free_action"


def test_normalise_modes_accepts_new_modes():
    assert normalise_modes(["claim_card_free_action"]) == ["claim_card_free_action"]
    assert normalise_modes(["reroll_specials_free_action"]) == [
        "reroll_specials_free_action"
    ]


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


# ─── claim_card_free_action mode ─────────────────────────────────────────────

from app.actions import claim_card, reroll_specials  # noqa: E402
from app.card import Card, CardRow, build_deck  # noqa: E402


def _state_with_card_in_row(modes: list[str], card: Card) -> GameState:
    gs = _two_player_state(modes)
    gs.card_rows = [
        CardRow(position=1, cards=[]),
        CardRow(position=2, cards=[card]),
        CardRow(position=3, cards=[]),
    ]
    return gs


def test_claim_card_uses_free_slot_when_mode_on():
    """With claim_card_free_action enabled, a claim doesn't burn the main action."""
    card = Card(id="c1", card_type="store", name="Vodka Store", spirit_type="VODKA")
    gs = _state_with_card_in_row(["claim_card_free_action"], card)
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.bladder = [Ingredient.VODKA]  # 1 needed for store

    new_state, payload = claim_card(gs, pid, "c1")

    assert payload["is_free_action"] is True
    assert new_state.main_action_taken_this_turn is False
    assert "claim_card" in new_state.free_actions_used_this_turn
    # Turn does not advance because the player still has their main action
    assert new_state.player_turn == pid


def test_claim_card_is_normal_main_action_without_mode():
    card = Card(id="c1", card_type="store", name="Vodka Store", spirit_type="VODKA")
    gs = _state_with_card_in_row([], card)
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.bladder = [Ingredient.VODKA]

    new_state, payload = claim_card(gs, pid, "c1")

    assert payload["is_free_action"] is False
    # No free actions available, so turn advances
    assert new_state.player_turn != pid


def test_claim_card_free_only_once_per_turn():
    """Second claim same turn falls through to main action when the free slot is spent."""
    c1 = Card(id="c1", card_type="store", name="Vodka Store", spirit_type="VODKA")
    c2 = Card(id="c2", card_type="store", name="Rum Store", spirit_type="RUM")
    gs = _two_player_state(["claim_card_free_action"])
    gs.card_rows = [
        CardRow(position=1, cards=[]),
        CardRow(position=2, cards=[c1, c2]),
        CardRow(position=3, cards=[]),
    ]
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.bladder = [Ingredient.VODKA, Ingredient.RUM]

    state_after_first, p1 = claim_card(gs, pid, "c1")
    assert p1["is_free_action"] is True
    state_after_second, p2 = claim_card(state_after_first, pid, "c2")
    assert p2["is_free_action"] is False  # used as main action this time
    # Turn now advances — main taken AND no remaining free actions.
    assert state_after_second.player_turn != pid


def test_claim_card_blocked_mid_take_even_with_mode():
    """Partial-take in progress must still block ClaimCard (mode does not lift this)."""
    card = Card(id="c1", card_type="store", name="Vodka Store", spirit_type="VODKA")
    gs = _state_with_card_in_row(["claim_card_free_action"], card)
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.bladder = [Ingredient.VODKA]
    gs.ingredients_taken_this_turn = 1  # mid-batch

    with pytest.raises(GameException) as exc:
        claim_card(gs, pid, "c1")
    assert exc.value.status_code == 409


def test_claim_card_blocked_after_main_action_when_mode_off():
    """Without the mode, after main is taken claim_card must be rejected."""
    card = Card(id="c1", card_type="store", name="Vodka Store", spirit_type="VODKA")
    gs = _state_with_card_in_row([], card)
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.bladder = [Ingredient.VODKA]
    gs.main_action_taken_this_turn = True  # already taken

    with pytest.raises(GameException) as exc:
        claim_card(gs, pid, "c1")
    assert exc.value.status_code == 409


def test_claim_card_after_main_action_allowed_when_mode_on():
    """With the mode, claim_card is still allowed after the main action — as free."""
    card = Card(id="c1", card_type="store", name="Vodka Store", spirit_type="VODKA")
    gs = _state_with_card_in_row(["claim_card_free_action"], card)
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.bladder = [Ingredient.VODKA]
    gs.main_action_taken_this_turn = True  # main already taken

    new_state, payload = claim_card(gs, pid, "c1")
    assert payload["is_free_action"] is True
    # Main taken AND free action used → turn now advances
    assert new_state.player_turn != pid


# ─── reroll_specials_free_action mode ────────────────────────────────────────


def test_reroll_specials_uses_free_slot_when_mode_on():
    gs = _two_player_state(["reroll_specials_free_action"])
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.special_ingredients = ["sugar", "lemon"]

    new_state, payload = reroll_specials(gs, pid, ["sugar"])
    assert payload["is_free_action"] is True
    assert new_state.main_action_taken_this_turn is False
    assert "reroll_specials" in new_state.free_actions_used_this_turn
    assert new_state.player_turn == pid


def test_reroll_specials_main_action_without_mode():
    gs = _two_player_state([])
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.special_ingredients = ["sugar"]

    new_state, payload = reroll_specials(gs, pid, ["sugar"])
    assert payload["is_free_action"] is False
    # Turn advances because no free actions remain
    assert new_state.player_turn != pid


def test_reroll_specials_blocked_mid_take_even_with_mode():
    gs = _two_player_state(["reroll_specials_free_action"])
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.special_ingredients = ["sugar"]
    gs.ingredients_taken_this_turn = 1  # mid-batch

    with pytest.raises(GameException) as exc:
        reroll_specials(gs, pid, ["sugar"])
    assert exc.value.status_code == 409


# ─── Deck composition mode-driven changes ───────────────────────────────────


def _has_card_named(deck: list[Card], name: str) -> bool:
    return any(c.name == name for c in deck)


def test_build_deck_includes_cocktail_shaker_by_default():
    deck = build_deck()
    assert _has_card_named(deck, "Cocktail Shaker")
    assert len(deck) == 25


def test_build_deck_excludes_cocktail_shaker_when_reroll_mode_on():
    deck = build_deck(["reroll_specials_free_action"])
    assert not _has_card_named(deck, "Cocktail Shaker")
    assert len(deck) == 24
    # Other free-action cards still present
    assert _has_card_named(deck, "Greedy Bartender")
    assert _has_card_named(deck, "Entrepreneur")
    assert _has_card_named(deck, "Weak Bladder")


def test_build_deck_unchanged_for_claim_card_mode():
    """The claim_card_free_action mode does not alter the deck."""
    deck = build_deck(["claim_card_free_action"])
    assert len(deck) == 25
    assert _has_card_named(deck, "Cocktail Shaker")


# ─── valid_actions surfaces mode-driven free actions ─────────────────────────


def test_valid_actions_marks_claim_as_free_under_mode():
    card = Card(id="c1", card_type="store", name="Vodka Store", spirit_type="VODKA")
    gs = _state_with_card_in_row(["claim_card_free_action"], card)
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.bladder = [Ingredient.VODKA] * 3  # affordable

    actions = get_valid_actions(gs, pid)
    claims = [a for a in actions if a.action_type == "claim_card"]
    assert claims, "Expected claim_card to surface"
    assert all(a.is_free for a in claims), (
        "claim_card should be marked is_free under mode"
    )


def test_valid_actions_does_not_mark_claim_as_free_without_mode():
    card = Card(id="c1", card_type="store", name="Vodka Store", spirit_type="VODKA")
    gs = _state_with_card_in_row([], card)
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.bladder = [Ingredient.VODKA] * 3

    actions = get_valid_actions(gs, pid)
    claims = [a for a in actions if a.action_type == "claim_card"]
    assert claims and all(not a.is_free for a in claims)


def test_valid_actions_marks_reroll_as_free_under_mode():
    gs = _two_player_state(["reroll_specials_free_action"])
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.special_ingredients = ["sugar"]

    actions = get_valid_actions(gs, pid)
    rerolls = [a for a in actions if a.action_type == "reroll_specials"]
    assert rerolls, "Expected reroll_specials to surface"
    assert all(a.is_free for a in rerolls)


def test_valid_actions_reroll_not_marked_free_after_used():
    gs = _two_player_state(["reroll_specials_free_action"])
    pid = gs.player_turn
    ps = gs.player_states[pid]
    ps.special_ingredients = ["sugar"]
    gs.free_actions_used_this_turn = ["reroll_specials"]

    actions = get_valid_actions(gs, pid)
    rerolls = [a for a in actions if a.action_type == "reroll_specials"]
    if rerolls:
        # Once-per-turn semantics: not free anymore
        assert all(not a.is_free for a in rerolls)
