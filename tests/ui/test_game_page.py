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
"""

from tests.ui.conftest import _api_register, _api_post, _unique


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


def test_non_host_no_start_game_button(page, base_url, new_user, new_game, other_user_and_jwt):
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


def test_start_game_transitions_to_board(page, base_url, new_user, new_game, other_user_and_jwt):
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
