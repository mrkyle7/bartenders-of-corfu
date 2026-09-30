"""UI tests for the Bar Top view (/bar): the game laid out like the real box.

Runs against the live server fixture from conftest.py, alongside the classic
and table views.
"""

import re

from tests.ui.conftest import _api_get, _api_post


def _started_game(base_url, new_user, new_game, other_user_and_jwt):
    _api_post(base_url, f"/v1/games/{new_game}/join", other_user_and_jwt["jwt"])
    _api_post(base_url, f"/v1/games/{new_game}/start", new_user["jwt"])
    return _api_get(base_url, f"/v1/games/{new_game}", new_user["jwt"])


def test_bar_unauthenticated_redirected_to_login(page, base_url, other_user_and_jwt):
    """Opening /bar without a session must bounce to the login page."""
    game = _api_post(base_url, "/v1/games", other_user_and_jwt["jwt"])
    page.goto(f"{base_url}/bar?id={game['id']}")
    page.wait_for_url(re.compile(r".*/login"), timeout=10000)


def test_bar_lobby_start_disabled_for_lone_host(page, base_url, new_user, new_game):
    """A lone host sees their stool taken and can't open the bar yet."""
    page.goto(f"{base_url}/bar?id={new_game}")
    lobby = page.locator("#lobby")
    lobby.wait_for(state="visible", timeout=10000)
    assert new_user["username"] in lobby.inner_text()
    assert page.locator("#lobby .seat.is-open").count() == 3
    assert page.locator("#lobby button", has_text="Needs a second player").is_disabled()


def test_bar_lobby_start_lays_out_the_table(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """Opening the bar from the lobby lays out cards, bag, display and mats."""
    _api_post(base_url, f"/v1/games/{new_game}/join", other_user_and_jwt["jwt"])
    page.goto(f"{base_url}/bar?id={new_game}")
    start = page.locator("#lobby button", has_text="Open the bar")
    start.wait_for(state="visible", timeout=10000)
    start.click()
    page.locator(".display .tok").first.wait_for(state="visible", timeout=10000)
    assert page.locator(".display .tok").count() == 5
    assert page.locator(".bag").is_visible()
    # Every karaoke card, three orders and three ability cards
    assert page.locator(".market .card-row").count() == 3
    assert page.locator(".market .row-cards .card").count() == 11
    assert page.locator(".market .row-cards .kind-karaoke").count() == 5
    assert page.locator(".market .row-cards .kind-order").count() == 3
    # Both mats are on show, each with two glasses of five spaces
    assert page.locator(".mat").count() == 2
    assert page.locator(".mat.is-mine .glass").count() == 2
    assert page.locator(".mat.is-mine .glass").first.locator(".slot").count() == 5
    # A fresh bladder: eight open spaces, four toilet tokens in reserve
    assert page.locator(".mat.is-mine .bladder-slots .slot.is-empty").count() == 8
    assert page.locator(".mat.is-mine .loo-reserve .loo").count() == 4
    # The drinks menu and score track are always on the table
    assert page.locator(".menu .menu-item").count() == 9
    assert page.locator(".score-track .score-cell").count() == 41


def test_bar_take_from_display_into_a_glass(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """On your turn, tokens go from the display to your hand, then into a glass."""
    game = _started_game(base_url, new_user, new_game, other_user_and_jwt)
    gs = game["game_state"]
    me = new_user["user"]["id"]
    if gs["player_turn"] != me:
        # The other player goes first: they pour blind bag draws into
        # their glasses, which passes the turn over.
        other = other_user_and_jwt
        take = gs["player_states"][gs["player_turn"]]["take_count"]
        _api_post(
            base_url,
            f"/v1/games/{new_game}/actions/take-ingredients",
            other["jwt"],
            {
                "assignments": [
                    {"source": "bag", "disposition": "cup", "cup_index": i % 2}
                    for i in range(take)
                ]
            },
        )
        gs = _api_get(base_url, f"/v1/games/{new_game}", new_user["jwt"])["game_state"]
    assert gs["player_turn"] == me

    page.goto(f"{base_url}/bar?id={new_game}")
    page.locator(".turnbar.tone-you").wait_for(state="visible", timeout=10000)
    display = gs["open_display"]
    # Pick up the first spirit or mixer (specials roll instead of pouring)
    slot = next(i for i, name in enumerate(display) if name != "SPECIAL")
    page.locator(f'[data-k="disp-{slot}"]').click()
    hand = page.locator(".hand .tok")
    assert hand.count() == 1
    page.locator(".mat.is-mine button.glass").first.click()
    assert page.locator(".mat.is-mine .glass .tok.is-placed").count() == 1
    page.locator('[data-k="done-placing"]').click()
    # The token lands in glass 1 on the server
    page.wait_for_function(
        "() => !document.querySelector('.mat.is-mine .glass .tok.is-placed')"
        " && document.querySelectorAll('.mat.is-mine .glass .tok').length === 1",
        timeout=10000,
    )
    after = _api_get(base_url, f"/v1/games/{new_game}", new_user["jwt"])["game_state"]
    assert after["player_states"][me]["cups"][0]["ingredients"] == [display[slot]]
    assert after["ingredients_taken_this_turn"] == 1


def test_bar_everyone_mat_on_show(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """Other players' mats are laid out in full, not tucked away."""
    _started_game(base_url, new_user, new_game, other_user_and_jwt)
    page.goto(f"{base_url}/bar?id={new_game}")
    theirs = page.locator(".mat.is-theirs")
    theirs.wait_for(state="visible", timeout=10000)
    assert theirs.locator(".glass").count() == 2
    assert theirs.locator(".bladder-slots .slot").count() == 8
    assert theirs.locator(".drunk-step").count() == 7


def test_home_choice_sends_game_page_to_bar(page, base_url, new_user, new_game):
    """Picking bar top on the home page sends /game on to /bar for the same game."""
    page.goto(f"{base_url}/")
    choice = page.locator(".ui-choice label", has_text="Bar top")
    choice.wait_for(state="visible", timeout=10000)
    choice.click()
    assert page.is_checked("#uiBar")
    page.goto(f"{base_url}/game?id={new_game}")
    page.wait_for_url(re.compile(r".*/bar\?id=.*"), timeout=10000)


def test_bar_rules_and_actions_are_on_show(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """The rule book is on the table, and on your turn the action strip shows
    your main action and the free ones."""
    game = _started_game(base_url, new_user, new_game, other_user_and_jwt)
    page.goto(f"{base_url}/bar?id={new_game}")
    page.locator(".rulebook").wait_for(state="visible", timeout=10000)
    assert page.locator(".rulebook .rule-part").count() >= 6
    assert "40" in page.locator(".rulebook").inner_text()
    if game["game_state"]["player_turn"] == new_user["user"]["id"]:
        strip = page.locator(".action-strip")
        strip.wait_for(state="visible", timeout=10000)
        assert "Main action" in strip.inner_text()
        assert "Claim a card" in strip.inner_text()
