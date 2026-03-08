"""
UI tests for the GamePage surface (specs/ui-frontend.allium § GamePage).

Covers:
  - unauthenticated redirect to /
  - non-member redirect to /
  - player usernames rendered in #playerList
  - host sees .remove-player-btn next to non-host players
  - non-host sees no .remove-player-btn
  - host does not see remove button next to their own name
  - removing a player refreshes the player list inline
  - host sees #gbBtnStartGame in the lobby
  - non-host does not see #gbBtnStartGame
  - clicking Start Game transitions the game to the board view
  - cup ingredients shown as badges when cup has contents
  - empty cup shows no ingredient badges
  - other player's cup ingredients shown as badges
"""

from tests.ui.conftest import _api_register, _api_get, _api_post, _unique


def _game_url(base_url: str, game_id: str) -> str:
    return f"{base_url}/game?id={game_id}"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_unauthenticated_redirected(page, base_url, other_user_and_jwt):
    """No cookie: /game?id=... redirects to /."""
    game = _api_post(base_url, "/v1/games", other_user_and_jwt["jwt"])
    game_id = game["id"]

    page.goto(_game_url(base_url, game_id))
    page.wait_for_url(base_url + "/", timeout=5000)
    assert page.url == base_url + "/"


def test_non_member_redirected(page, base_url, new_user, other_user_and_jwt):
    """Authenticated user who is not a game member is redirected to /."""
    game = _api_post(base_url, "/v1/games", other_user_and_jwt["jwt"])
    game_id = game["id"]

    # new_user is authenticated but NOT a member of other_user's game
    page.on("dialog", lambda d: d.accept())  # accept the alert
    page.goto(_game_url(base_url, game_id))
    page.wait_for_url(base_url + "/", timeout=5000)
    assert page.url == base_url + "/"


# ---------------------------------------------------------------------------
# Content rendering
# ---------------------------------------------------------------------------


def test_player_usernames_shown(page, base_url, new_user, new_game):
    """Host username is rendered in #playerList (not a raw UUID)."""
    page.goto(_game_url(base_url, new_game))
    player_list = page.locator("#playerList")
    player_list.wait_for(state="visible", timeout=5000)
    text = player_list.inner_text()
    assert new_user["username"] in text
    # UUID-like strings should NOT appear
    import re

    assert not re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text
    )


# ---------------------------------------------------------------------------
# RemovePlayer button visibility
# ---------------------------------------------------------------------------


def test_host_sees_remove_buttons(page, base_url, new_user, new_game):
    """Host sees a .remove-player-btn next to each non-host player."""
    other = _unique("other")
    _, other_jwt = _api_register(base_url, other)
    _api_post(base_url, f"/v1/games/{new_game}/join", other_jwt)

    page.goto(_game_url(base_url, new_game))
    player_list = page.locator("#playerList")
    player_list.wait_for(state="visible", timeout=5000)

    remove_btns = page.locator(".remove-player-btn")
    remove_btns.first.wait_for(state="visible", timeout=5000)
    assert remove_btns.count() >= 1


def test_non_host_no_remove_buttons(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """A non-host player sees no .remove-player-btn."""
    # other_user joins the game
    _api_post(base_url, f"/v1/games/{new_game}/join", other_user_and_jwt["jwt"])

    # Log in as other_user in the browser
    page.context.clear_cookies()
    page.context.add_cookies(
        [{"name": "userjwt", "value": other_user_and_jwt["jwt"], "url": base_url}]
    )

    page.goto(_game_url(base_url, new_game))
    player_list = page.locator("#playerList")
    player_list.wait_for(state="visible", timeout=5000)

    assert page.locator(".remove-player-btn").count() == 0


def test_host_no_remove_self(page, base_url, new_user, new_game):
    """The host should not see a remove button next to their own name."""
    other = _unique("other")
    _, other_jwt = _api_register(base_url, other)
    _api_post(base_url, f"/v1/games/{new_game}/join", other_jwt)

    page.goto(_game_url(base_url, new_game))
    player_list = page.locator("#playerList")
    player_list.wait_for(state="visible", timeout=5000)

    # Find the host's player-entry and confirm it has no remove button
    entries = page.locator(".player-entry")
    count = entries.count()
    host_entries_with_remove = 0
    for i in range(count):
        entry = entries.nth(i)
        text = entry.inner_text()
        if new_user["username"] in text:
            if entry.locator(".remove-player-btn").count() > 0:
                host_entries_with_remove += 1
    assert host_entries_with_remove == 0


def test_remove_player_updates_list(page, base_url, new_user, new_game):
    """Host removes a player; that player's name disappears from #playerList."""
    other = _unique("other")
    _, other_jwt = _api_register(base_url, other)
    _api_post(base_url, f"/v1/games/{new_game}/join", other_jwt)

    page.goto(_game_url(base_url, new_game))
    player_list = page.locator("#playerList")
    player_list.wait_for(state="visible", timeout=5000)

    # Verify other user is in the list
    assert other in player_list.inner_text()

    # Click the remove button
    remove_btn = page.locator(".remove-player-btn").first
    remove_btn.wait_for(state="visible", timeout=5000)
    remove_btn.click()

    # Wait for list to refresh and other user to be gone
    page.wait_for_function(
        f"!document.getElementById('playerList').innerText.includes('{other}')",
        timeout=5000,
    )
    assert other not in player_list.inner_text()


# ---------------------------------------------------------------------------
# Start Game button
# ---------------------------------------------------------------------------


def test_host_sees_start_game_button(page, base_url, new_user, new_game):
    """Host sees the Start Game button in the lobby."""
    page.goto(_game_url(base_url, new_game))
    page.locator("#playerList").wait_for(state="visible", timeout=5000)
    btn = page.locator("#gbBtnStartGame")
    btn.wait_for(state="visible", timeout=5000)
    assert btn.is_visible()


def test_non_host_no_start_game_button(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """A non-host player does not see the Start Game button."""
    _api_post(base_url, f"/v1/games/{new_game}/join", other_user_and_jwt["jwt"])

    # Switch browser to the non-host user
    page.context.clear_cookies()
    page.context.add_cookies(
        [{"name": "userjwt", "value": other_user_and_jwt["jwt"], "url": base_url}]
    )

    page.goto(_game_url(base_url, new_game))
    page.locator("#playerList").wait_for(state="visible", timeout=5000)
    assert page.locator("#gbBtnStartGame").count() == 0


def test_start_game_transitions_to_board(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """Host clicks Start Game; lobby disappears and the game board renders."""
    _api_post(base_url, f"/v1/games/{new_game}/join", other_user_and_jwt["jwt"])

    page.goto(_game_url(base_url, new_game))
    page.locator("#playerList").wait_for(state="visible", timeout=5000)

    btn = page.locator("#gbBtnStartGame")
    btn.wait_for(state="visible", timeout=5000)
    btn.click()

    # Board content should become visible; lobby panel should be hidden
    page.locator("#gbBoardContent").wait_for(state="visible", timeout=8000)
    assert not page.locator("#gbLobbyPanel").is_visible()


# ---------------------------------------------------------------------------
# Cup content rendering
# ---------------------------------------------------------------------------


def _start_game_with_two_players(base_url, new_game, host_jwt, other_jwt):
    """Join and start a 2-player game; return game_id."""
    _api_post(base_url, f"/v1/games/{new_game}/join", other_jwt)
    _api_post(base_url, f"/v1/games/{new_game}/start", host_jwt)
    return new_game


def _put_ingredient_in_cup(base_url, game_id, jwt, cup_index=0):
    """Draw take_count (3) ingredients from the bag and assign them all to cup_index.

    Drawing and assigning the full take_count ends the turn so the next player can act.
    """
    take_count = 3  # BASE_TAKE_COUNT at drunk_level 0
    _api_post(
        base_url,
        f"/v1/games/{game_id}/actions/draw-from-bag",
        jwt,
        {"count": take_count},
    )
    _api_post(
        base_url,
        f"/v1/games/{game_id}/actions/take-ingredients",
        jwt,
        {
            "assignments": [
                {"source": "pending", "disposition": "cup", "cup_index": cup_index}
                for _ in range(take_count)
            ]
        },
    )


def test_cup_shows_ingredient_badges_when_filled(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """After putting an ingredient in cup 1, the game board renders an ingredient badge."""
    game_id = _start_game_with_two_players(
        base_url, new_game, new_user["jwt"], other_user_and_jwt["jwt"]
    )
    # Turn order is randomised — ensure the host goes first so their cup gets filled.
    _ensure_host_turn(
        base_url,
        game_id,
        new_user["jwt"],
        new_user["user"]["id"],
        other_user_and_jwt["jwt"],
        other_user_and_jwt["user"]["id"],
    )
    _put_ingredient_in_cup(base_url, game_id, new_user["jwt"], cup_index=0)

    page.goto(_game_url(base_url, game_id))
    page.locator("#gbBoardContent").wait_for(state="visible", timeout=8000)

    # At least one ingredient badge should appear inside the cup ingredients area
    badges = page.locator("#gbMyCups .gb-cup-ingredients .gb-ingredient")
    badges.first.wait_for(state="visible", timeout=5000)
    assert badges.count() >= 1


def test_empty_cup_shows_no_ingredient_badges(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """On a freshly started game both cups are empty — no ingredient badges shown."""
    _start_game_with_two_players(
        base_url, new_game, new_user["jwt"], other_user_and_jwt["jwt"]
    )

    page.goto(_game_url(base_url, new_game))
    page.locator("#gbBoardContent").wait_for(state="visible", timeout=8000)

    assert page.locator("#gbMyCups .gb-cup-ingredients .gb-ingredient").count() == 0
    # Empty cups show physical empty slots (5 per cup × 2 cups = 10)
    assert page.locator("#gbMyCups .gb-cup-slot.empty").count() == 10


def test_other_player_cup_shows_ingredient_badges(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """After both players take a turn, the other player's cup badges are visible."""
    game_id = _start_game_with_two_players(
        base_url, new_game, new_user["jwt"], other_user_and_jwt["jwt"]
    )
    # Host takes their turn (ends it), then other_user takes theirs
    _put_ingredient_in_cup(base_url, game_id, new_user["jwt"], cup_index=0)
    _put_ingredient_in_cup(base_url, game_id, other_user_and_jwt["jwt"], cup_index=0)

    # View game as host — other player's card should show ingredient badges
    page.goto(_game_url(base_url, game_id))
    page.locator("#gbBoardContent").wait_for(state="visible", timeout=8000)

    other_sheet = page.locator(".gb-other-sheet")
    other_sheet.wait_for(state="visible", timeout=5000)
    badges = other_sheet.locator(".gb-ingredient")
    badges.first.wait_for(state="visible", timeout=5000)
    assert badges.count() >= 1


# ---------------------------------------------------------------------------
# Take modal auto-open (partial batch continuation and page refresh)
# ---------------------------------------------------------------------------


def _take_partial_batch(base_url, game_id, jwt, count=1):
    """Draw `count` ingredients from the bag and assign them, leaving the turn incomplete."""
    _api_post(
        base_url,
        f"/v1/games/{game_id}/actions/draw-from-bag",
        jwt,
        {"count": count},
    )
    _api_post(
        base_url,
        f"/v1/games/{game_id}/actions/take-ingredients",
        jwt,
        {
            "assignments": [
                {"source": "pending", "disposition": "cup", "cup_index": 0}
                for _ in range(count)
            ]
        },
    )


def _ensure_host_turn(
    base_url, game_id, host_jwt, host_user_id, other_jwt, other_user_id
):
    """If the other player goes first (turn order is random), complete their turn so it
    becomes the host's turn before the browser test begins."""
    game = _api_get(base_url, f"/v1/games/{game_id}", host_jwt)
    if game["game_state"]["player_turn"] == other_user_id:
        _put_ingredient_in_cup(base_url, game_id, other_jwt, cup_index=0)


def test_take_modal_auto_opens_on_page_load_when_mid_taking(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """If the page is refreshed mid-turn (some ingredients taken but not all),
    the take modal should auto-open to prompt the player to continue."""
    game_id = _start_game_with_two_players(
        base_url, new_game, new_user["jwt"], other_user_and_jwt["jwt"]
    )
    # Turn order is random — ensure it is the host's turn before the partial take
    _ensure_host_turn(
        base_url,
        game_id,
        new_user["jwt"],
        new_user["user"]["id"],
        other_user_and_jwt["jwt"],
        other_user_and_jwt["user"]["id"],
    )
    # Host takes 1 of 3 required ingredients — turn is still theirs
    _take_partial_batch(base_url, game_id, new_user["jwt"], count=1)

    # Navigate to the game page (simulating a page refresh after a partial take)
    page.goto(_game_url(base_url, game_id))
    page.locator("#gbBoardContent").wait_for(state="visible", timeout=8000)

    # Take modal should auto-open because ingredients_taken_this_turn=1 < take_count=3
    modal = page.locator("#gbTakeModal")
    modal.wait_for(state="visible", timeout=8000)
    assert modal.is_visible()

    # Step label should indicate 2 remaining with 1 already taken
    limit_text = page.locator("#gbTakeLimit").inner_text()
    assert "1/3" in limit_text


def test_take_modal_auto_reopens_after_partial_batch_submit(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """After submitting a partial batch of ingredients via the UI,
    the take modal should automatically re-open to prompt for the remainder."""
    game_id = _start_game_with_two_players(
        base_url, new_game, new_user["jwt"], other_user_and_jwt["jwt"]
    )
    # Turn order is random — ensure it is the host's turn before browser interaction
    _ensure_host_turn(
        base_url,
        game_id,
        new_user["jwt"],
        new_user["user"]["id"],
        other_user_and_jwt["jwt"],
        other_user_and_jwt["user"]["id"],
    )

    # Navigate as host (whose turn it is)
    page.goto(_game_url(base_url, game_id))
    page.locator("#gbBoardContent").wait_for(state="visible", timeout=8000)

    # Open the take modal by clicking the interactive bag visual
    take_btn = page.locator("#gbBagVisual")
    take_btn.wait_for(state="visible", timeout=5000)
    take_btn.click()

    modal = page.locator("#gbTakeModal")
    modal.wait_for(state="visible", timeout=5000)

    # Draw 1 ingredient from the bag (not the full 3 required)
    draw_count_input = page.locator("#gbBagDrawCount")
    draw_count_input.fill("1")
    page.locator("#gbBtnDrawBag").click()

    # Wait for the draw confirmation to appear
    page.wait_for_function(
        "document.getElementById('gbBagDrawStatus').textContent.includes('Drew')",
        timeout=5000,
    )

    # Advance to the assignment step
    page.locator("#gbTakeNextBtn").click()

    # Assignment table should be visible — submit with default assignment (Cup 1)
    page.locator("#gbAssignTableBody tr").first.wait_for(state="visible", timeout=5000)
    page.locator("#gbTakeNextBtn").click()

    # After submitting, the modal closes briefly then auto-re-opens at step 0.
    # #gbTakeLimit lives inside #gbTakeStep0 which is hidden during step 1 (assign step).
    # Waiting for it to become visible avoids the close→reopen race condition.
    limit_el = page.locator("#gbTakeLimit")
    limit_el.wait_for(state="visible", timeout=8000)

    # The limit text should reflect that 1 has already been taken (2 remaining)
    assert "1/3" in limit_el.inner_text()
