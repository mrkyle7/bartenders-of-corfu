"""UI tests for the Table View (/play) — the redesigned one-screen game UI.

Runs against the live server fixture from conftest.py. The classic UI tests
in test_game_page.py are unchanged; the table view works alongside it.
"""

import re

from tests.ui.conftest import _api_get, _api_post


def test_play_unauthenticated_redirected_to_login(page, base_url, other_user_and_jwt):
    """Opening /play without a session must bounce to the login page."""
    game = _api_post(base_url, "/v1/games", other_user_and_jwt["jwt"])
    page.goto(f"{base_url}/play?id={game['id']}")
    page.wait_for_url(re.compile(r".*/login"), timeout=10000)


def test_lobby_shows_players_and_start_disabled(page, base_url, new_user, new_game):
    """A lone host sees the lobby with their name and a disabled start button."""
    page.goto(f"{base_url}/play?id={new_game}")
    lobby = page.locator("#lobby")
    lobby.wait_for(state="visible", timeout=10000)
    assert new_user["username"] in lobby.inner_text()
    start = page.locator("#lobby button", has_text="Need at least 2 players")
    assert start.is_disabled()


def test_lobby_start_transitions_to_board(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """Host starts the game from the lobby and the board renders in place."""
    _api_post(base_url, f"/v1/games/{new_game}/join", other_user_and_jwt["jwt"])
    page.goto(f"{base_url}/play?id={new_game}")
    start = page.locator("#lobby button", has_text="Open the bar!")
    start.wait_for(state="visible", timeout=10000)
    start.click()
    # Board appears: five face-up ingredients and the bag
    page.locator("#market .tok").first.wait_for(state="visible", timeout=10000)
    assert page.locator("#market .market-tokens .tok").count() == 5
    assert page.locator("#bagChip").is_visible()
    # Three card rows of three cards
    assert page.locator("#cards .card-row").count() == 3


def test_dock_reflects_whose_turn(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """The action dock shows actions on your turn and a waiting message otherwise."""
    _api_post(base_url, f"/v1/games/{new_game}/join", other_user_and_jwt["jwt"])
    _api_post(base_url, f"/v1/games/{new_game}/start", new_user["jwt"])
    page.goto(f"{base_url}/play?id={new_game}")
    page.locator("#market .tok").first.wait_for(state="visible", timeout=10000)

    game = _api_get(base_url, f"/v1/games/{new_game}", new_user["jwt"])
    my_turn = game["game_state"]["player_turn"] == new_user["user"]["id"]
    dock_text = page.locator("#dock").inner_text()
    if my_turn:
        assert "Your turn" in dock_text
        assert "Take" in dock_text
    else:
        assert "is at the bar" in dock_text
        assert "Take" not in dock_text


def test_take_tap_token_opens_assignment_sheet(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """On your turn, tapping a face-up ingredient offers cup/drink choices."""
    _api_post(base_url, f"/v1/games/{new_game}/join", other_user_and_jwt["jwt"])
    _api_post(base_url, f"/v1/games/{new_game}/start", new_user["jwt"])

    game = _api_get(base_url, f"/v1/games/{new_game}", new_user["jwt"])
    if game["game_state"]["player_turn"] != new_user["user"]["id"]:
        # Other player takes their ingredients first so it becomes our turn
        take = {"assignments": [{"source": "bag", "disposition": "drink"}] * 3}
        _api_post(
            base_url,
            f"/v1/games/{new_game}/actions/take-ingredients",
            other_user_and_jwt["jwt"],
            take,
        )

    page.goto(f"{base_url}/play?id={new_game}")
    token = page.locator("#market .market-tokens button.tok").first
    token.wait_for(state="visible", timeout=10000)
    token.click()
    sheet = page.locator("#sheet")
    sheet.wait_for(state="visible", timeout=5000)
    text = sheet.inner_text()
    # Special die tokens roll instead of pouring; either sheet is valid
    assert "Pour into Cup 1" in text or "Roll the special die" in text


def test_history_sheet_lists_moves(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """The History footer button opens the move list."""
    _api_post(base_url, f"/v1/games/{new_game}/join", other_user_and_jwt["jwt"])
    _api_post(base_url, f"/v1/games/{new_game}/start", new_user["jwt"])
    page.goto(f"{base_url}/play?id={new_game}")
    page.locator("#market .tok").first.wait_for(state="visible", timeout=10000)
    page.click("#footHistory")
    sheet = page.locator("#sheet")
    sheet.wait_for(state="visible", timeout=5000)
    assert "History" in sheet.inner_text()


def test_home_toggle_redirects_classic_game_page(page, base_url, new_user, new_game):
    """With the table-view toggle on, /game redirects to /play for the same game."""
    page.goto(f"{base_url}/")
    toggle = page.locator("#tableViewToggle")
    toggle.wait_for(state="visible", timeout=10000)
    toggle.check()
    page.goto(f"{base_url}/game?id={new_game}")
    page.wait_for_url(re.compile(r".*/play\?id=.*"), timeout=10000)

    # Toggle off: classic page stays put
    page.evaluate("localStorage.setItem('bocTableView', '0')")
    page.goto(f"{base_url}/game?id={new_game}")
    page.wait_for_timeout(500)
    assert "/game?id=" in page.url
