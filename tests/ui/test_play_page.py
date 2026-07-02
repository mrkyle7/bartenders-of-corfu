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


def _make_it_my_turn(base_url, new_game, new_user, other_user_and_jwt):
    """Start from a fresh game and ensure it is new_user's turn."""
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


def _assign_through_sheets(page, count):
    """Complete `count` assignment sheets by picking the first enabled option."""
    for _ in range(count):
        page.wait_for_selector(
            "#sheet.open .sheet-option:not([disabled])", timeout=5000
        )
        page.locator("#sheet .sheet-option:not([disabled])").first.click()
        page.wait_for_timeout(300)


def test_take_select_tokens_then_assign(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """Tapping face-up ingredients picks them up; Assign walks through each."""
    _api_post(base_url, f"/v1/games/{new_game}/join", other_user_and_jwt["jwt"])
    _api_post(base_url, f"/v1/games/{new_game}/start", new_user["jwt"])
    _make_it_my_turn(base_url, new_game, new_user, other_user_and_jwt)

    page.goto(f"{base_url}/play?id={new_game}")
    tokens = page.locator("#market .market-tokens button.tok")
    tokens.first.wait_for(state="visible", timeout=10000)
    tokens.nth(0).click()
    tokens.nth(1).click()

    # Two tokens picked up: dock offers Assign 2 / Put back
    dock = page.locator("#dock")
    assert "Assign 2" in dock.inner_text()
    assert page.locator("#market .market-slot.selected").count() == 2

    # Deselecting works before committing
    tokens.nth(1).click()
    assert "Assign 1" in dock.inner_text()
    tokens.nth(1).click()

    page.click("#dock >> text=Assign 2")
    page.wait_for_selector("#sheet.open .sheet-option", timeout=5000)
    assert "(1 of 2)" in page.locator("#sheet .sheet-title").inner_text()
    _assign_through_sheets(page, 2)

    # One batch of two was submitted in a single call
    game = _api_get(base_url, f"/v1/games/{new_game}", new_user["jwt"])
    gs = game["game_state"]
    my_turn_over = gs["player_turn"] != new_user["user"]["id"]
    assert my_turn_over or gs["ingredients_taken_this_turn"] == 2


def test_bag_draw_choose_count_and_assign_all(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """The bag asks how many to draw; every drawn ingredient must be assigned
    through a locked sheet (no close button, Escape does nothing)."""
    _api_post(base_url, f"/v1/games/{new_game}/join", other_user_and_jwt["jwt"])
    _api_post(base_url, f"/v1/games/{new_game}/start", new_user["jwt"])
    _make_it_my_turn(base_url, new_game, new_user, other_user_and_jwt)

    page.goto(f"{base_url}/play?id={new_game}")
    page.locator("#market .tok").first.wait_for(state="visible", timeout=10000)
    page.click("#bagChip")
    page.wait_for_selector("#sheet.open .count-btn", timeout=5000)
    # Sober player must take 3: offered counts are 1, 2 and 3
    assert page.locator("#sheet .count-btn").count() == 3
    assert "No going back" in page.locator("#sheet").inner_text()

    page.click('#sheet .count-btn >> text="2"')
    page.wait_for_selector("#sheet.open .sheet-option", timeout=5000)
    # Locked: no close button, Escape keeps the sheet open
    assert page.locator("#sheet .sheet-close").count() == 0
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert page.locator("#sheet.open").count() == 1

    _assign_through_sheets(page, 2)
    game = _api_get(base_url, f"/v1/games/{new_game}", new_user["jwt"])
    gs = game["game_state"]
    assert gs["bag_draw_pending"] == []
    my_turn_over = gs["player_turn"] != new_user["user"]["id"]
    assert my_turn_over or gs["ingredients_taken_this_turn"] == 2


def test_history_sheet_lists_moves(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """The History footer button opens the move list."""
    _api_post(base_url, f"/v1/games/{new_game}/join", other_user_and_jwt["jwt"])
    _api_post(base_url, f"/v1/games/{new_game}/start", new_user["jwt"])
    page.goto(f"{base_url}/play?id={new_game}")
    page.locator("#market .tok").first.wait_for(state="visible", timeout=10000)
    page.click("#footHistory")
    # The sheet opens only after the history fetch resolves; wait for its title
    page.wait_for_selector("#sheet.open .sheet-title", state="visible", timeout=10000)
    assert "History" in page.locator("#sheet").inner_text()
    # A started game always has at least the game-start state; entries render
    page.wait_for_selector("#sheet .history-item, #sheet .sheet-note", timeout=5000)


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
