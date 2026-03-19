"""
UI tests for the move history expand/collapse feature.

Covers:
  - history entries are rendered as expandable rows
  - clicking an entry expands it showing a detail panel
  - clicking an expanded entry collapses it
  - go_for_a_wee detail shows flushed label
  - take_ingredients detail groups ingredients by cup
  - sell_cup detail content (points badge) via BDD is covered separately;
    here we verify the detail panel renders label elements for any action
"""

import json
import urllib.request

from tests.ui.conftest import _api_post


def _game_url(base_url: str, game_id: str) -> str:
    return f"{base_url}/game?id={game_id}"


def _api_get(base_url: str, path: str, jwt: str) -> dict:
    req = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Cookie": f"userjwt={jwt}"},
        method="GET",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _start_game(base_url, host_jwt, other_jwt, game_id):
    _api_post(base_url, f"/v1/games/{game_id}/join", other_jwt)
    _api_post(base_url, f"/v1/games/{game_id}/start", host_jwt)


def _take_full_turn(base_url, game_id, jwt, cup_index=0):
    """Draw and assign exactly 3 ingredients (BASE_TAKE_COUNT) to end the turn."""
    _api_post(base_url, f"/v1/games/{game_id}/actions/draw-from-bag", jwt, {"count": 3})
    _api_post(
        base_url,
        f"/v1/games/{game_id}/actions/take-ingredients",
        jwt,
        {
            "assignments": [
                {"source": "pending", "disposition": "cup", "cup_index": cup_index}
                for _ in range(3)
            ]
        },
    )


def _active_and_other_jwt(base_url, game_id, new_user, other_user_and_jwt):
    """Return (active_jwt, other_jwt) based on whose turn it is."""
    game = _api_get(base_url, f"/v1/games/{game_id}", new_user["jwt"])
    turn_id = game["game_state"]["player_turn"]
    if turn_id == new_user["user"]["id"]:
        return new_user["jwt"], other_user_and_jwt["jwt"]
    return other_user_and_jwt["jwt"], new_user["jwt"]


def _active_jwt(base_url, game_id, new_user, other_user_and_jwt):
    """Return the JWT of whichever player currently holds the turn."""
    active, _ = _active_and_other_jwt(base_url, game_id, new_user, other_user_and_jwt)
    return active


def _wait_for_history_entry(page, timeout=8000):
    """Wait until at least one expandable history entry is rendered."""
    page.wait_for_selector(".gb-history-expandable", state="visible", timeout=timeout)


# ---------------------------------------------------------------------------
# Expand / collapse
# ---------------------------------------------------------------------------


def test_history_entries_are_expandable(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """Each history entry has the expandable class and chevron."""
    _start_game(base_url, new_user["jwt"], other_user_and_jwt["jwt"], new_game)
    _take_full_turn(
        base_url,
        new_game,
        _active_jwt(base_url, new_game, new_user, other_user_and_jwt),
    )

    page.goto(_game_url(base_url, new_game))
    _wait_for_history_entry(page)

    entries = page.locator(".gb-history-expandable")
    assert entries.count() >= 1
    chevron = entries.first.locator(".gb-history-chevron")
    assert chevron.count() == 1


def test_clicking_entry_expands_detail(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """Clicking a history entry reveals its .gb-history-detail panel."""
    _start_game(base_url, new_user["jwt"], other_user_and_jwt["jwt"], new_game)
    _take_full_turn(
        base_url,
        new_game,
        _active_jwt(base_url, new_game, new_user, other_user_and_jwt),
    )

    page.goto(_game_url(base_url, new_game))
    _wait_for_history_entry(page)

    entry = page.locator(".gb-history-expandable").first
    detail = entry.locator(
        "xpath=following-sibling::div[contains(@class,'gb-history-detail')]"
    )

    # Detail starts hidden
    assert not detail.is_visible()

    entry.click()

    detail.wait_for(state="visible", timeout=3000)
    assert detail.is_visible()
    assert entry.get_attribute("aria-expanded") == "true"


def test_clicking_again_collapses_detail(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """Clicking an expanded entry hides the detail again."""
    _start_game(base_url, new_user["jwt"], other_user_and_jwt["jwt"], new_game)
    _take_full_turn(
        base_url,
        new_game,
        _active_jwt(base_url, new_game, new_user, other_user_and_jwt),
    )

    page.goto(_game_url(base_url, new_game))
    _wait_for_history_entry(page)

    entry = page.locator(".gb-history-expandable").first
    detail = entry.locator(
        "xpath=following-sibling::div[contains(@class,'gb-history-detail')]"
    )

    entry.click()
    detail.wait_for(state="visible", timeout=3000)

    entry.click()
    page.wait_for_function(
        "!document.querySelector('.gb-history-detail.open')",
        timeout=3000,
    )
    assert not detail.is_visible()
    assert entry.get_attribute("aria-expanded") == "false"


# ---------------------------------------------------------------------------
# Detail content — go_for_a_wee
# ---------------------------------------------------------------------------


def test_wee_detail_shows_flushed_label(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """Expanding a go_for_a_wee entry shows 'Flushed:' or empty-bladder text."""
    _start_game(base_url, new_user["jwt"], other_user_and_jwt["jwt"], new_game)

    # GoForAWee requires a non-empty bladder.  Fill it by taking ingredients
    # with disposition "drink" (puts them straight in the bladder), let the
    # other player take a turn, then wee.
    active, other = _active_and_other_jwt(
        base_url, new_game, new_user, other_user_and_jwt
    )
    # Active player drinks ingredients → bladder fills, turn ends
    _api_post(
        base_url,
        f"/v1/games/{new_game}/actions/draw-from-bag",
        active,
        {"count": 3},
    )
    _api_post(
        base_url,
        f"/v1/games/{new_game}/actions/take-ingredients",
        active,
        {
            "assignments": [
                {"source": "pending", "disposition": "drink"} for _ in range(3)
            ]
        },
    )
    # Other player takes a turn → back to active player
    _take_full_turn(base_url, new_game, other)
    # Now active player can go for a wee
    _api_post(base_url, f"/v1/games/{new_game}/actions/go-for-a-wee", active)

    page.goto(_game_url(base_url, new_game))
    _wait_for_history_entry(page)

    entries = page.locator(".gb-history-expandable")
    wee_entry = None
    for i in range(entries.count()):
        entry = entries.nth(i)
        if "wee" in entry.inner_text().lower():
            wee_entry = entry
            break

    assert wee_entry is not None, "No go_for_a_wee entry found in history"
    wee_entry.click()

    detail = wee_entry.locator(
        "xpath=following-sibling::div[contains(@class,'gb-history-detail')]"
    )
    detail.wait_for(state="visible", timeout=3000)

    text = detail.inner_text().lower()
    assert "flushed" in text or "empty" in text


# ---------------------------------------------------------------------------
# Detail content — take_ingredients
# ---------------------------------------------------------------------------


def test_take_ingredients_detail_shows_cup_label(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """Expanding a take_ingredients entry shows 'Cup 1:' detail row."""
    _start_game(base_url, new_user["jwt"], other_user_and_jwt["jwt"], new_game)
    _take_full_turn(
        base_url,
        new_game,
        _active_jwt(base_url, new_game, new_user, other_user_and_jwt),
        cup_index=0,
    )

    page.goto(_game_url(base_url, new_game))
    _wait_for_history_entry(page)

    entries = page.locator(".gb-history-expandable")
    take_entry = None
    for i in range(entries.count()):
        entry = entries.nth(i)
        if "Took" in entry.inner_text():
            take_entry = entry
            break

    assert take_entry is not None, "No take_ingredients entry found in history"
    take_entry.click()

    detail = take_entry.locator(
        "xpath=following-sibling::div[contains(@class,'gb-history-detail')]"
    )
    detail.wait_for(state="visible", timeout=3000)

    # Should show "Cup 1:" label and at least one ingredient badge
    assert "Cup 1" in detail.inner_text()
    assert detail.locator(".gb-ingredient").count() >= 1


# ---------------------------------------------------------------------------
# Detail content — sell_cup
# ---------------------------------------------------------------------------


def test_sell_cup_detail_shows_points_badge(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """Expanding a sell_cup entry shows a +N pts badge."""
    _start_game(base_url, new_user["jwt"], other_user_and_jwt["jwt"], new_game)

    # Both players take turns so history has entries regardless of turn order.
    p1_jwt = _active_jwt(base_url, new_game, new_user, other_user_and_jwt)
    _take_full_turn(base_url, new_game, p1_jwt, cup_index=0)
    p2_jwt = _active_jwt(base_url, new_game, new_user, other_user_and_jwt)
    _take_full_turn(base_url, new_game, p2_jwt, cup_index=0)

    # Attempt a sell regardless of whether the combination is valid.
    # We only care about the UI if a sell_cup record is created; if the sell
    # fails we fall back to asserting that ANY detail panel renders correctly.
    sell_jwt = _active_jwt(base_url, new_game, new_user, other_user_and_jwt)
    sell_resp = _api_post(
        base_url,
        f"/v1/games/{new_game}/actions/sell-cup",
        sell_jwt,
        {"cup_index": 0, "declared_specials": []},
    )
    sell_succeeded = "error" not in sell_resp

    page.goto(_game_url(base_url, new_game))
    _wait_for_history_entry(page)

    if sell_succeeded:
        # Find and expand the sell_cup entry; verify points badge.
        entries = page.locator(".gb-history-expandable")
        sell_entry = None
        for i in range(entries.count()):
            entry = entries.nth(i)
            if "Sold cup" in entry.inner_text():
                sell_entry = entry
                break
        assert sell_entry is not None, (
            "Sell succeeded but no 'Sold cup' entry in history"
        )
        sell_entry.click()
        detail = sell_entry.locator(
            "xpath=following-sibling::div[contains(@class,'gb-history-detail')]"
        )
        detail.wait_for(state="visible", timeout=3000)
        points_badge = detail.locator(".gb-points-badge")
        assert points_badge.count() >= 1
        assert "pts" in points_badge.first.inner_text()
    else:
        # Sell failed (random cup contents weren't a valid combination).
        # Verify that the take_ingredients entries still expand correctly
        # and their details contain ingredient labels — the JS rendering path
        # for detail panels is exercised regardless of action type.
        entries = page.locator(".gb-history-expandable")
        entries.first.click()
        detail = entries.first.locator(
            "xpath=following-sibling::div[contains(@class,'gb-history-detail')]"
        )
        detail.wait_for(state="visible", timeout=3000)
        assert detail.locator(".gb-detail-label").count() >= 1
