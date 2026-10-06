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


def test_bar_unauthenticated_redirected_to_login(
    page, base_url, other_user_and_jwt, sign_in_page
):
    """Opening /bar without a session sends the player to sign in, and back."""
    game = _api_post(base_url, "/v1/games", other_user_and_jwt["jwt"])
    page.goto(f"{base_url}/bar?id={game['id']}")
    page.wait_for_url(f"{sign_in_page}?**", timeout=10000)
    assert "bar%3Fid%3D" in page.url


def test_bar_lobby_start_disabled_for_lone_host(page, base_url, new_user, new_game):
    """A lone host sees their stool taken and can't open the bar yet."""
    page.goto(f"{base_url}/bar?id={new_game}")
    lobby = page.locator("#lobby")
    lobby.wait_for(state="visible", timeout=10000)
    assert new_user["username"] in lobby.inner_text()
    assert page.locator("#lobby .seat.is-open").count() == 3
    assert page.locator("#lobby button", has_text="Needs a second player").is_disabled()


def test_lobby_invite_link_copies(page, base_url, new_user, new_game):
    """The lobby offers the game's link to copy and share."""
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.goto(f"{base_url}/bar?id={new_game}")
    link = page.locator("#inviteLink")
    link.wait_for(state="visible", timeout=10000)
    assert link.input_value().endswith(f"/bar?id={new_game}")
    page.locator(".invite-copy").click()
    page.locator(".invite-copy", has_text="Copied!").wait_for(timeout=5000)
    assert page.evaluate("navigator.clipboard.readText()") == link.input_value()


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
    glass = page.locator(".mat.is-mine .glass").first
    assert glass.locator(".glass-body > .slot").count() == 5
    # Two spaces at the top, always on show, marked for specials only
    specials = glass.locator(".glass-specials")
    assert specials.is_visible()
    assert specials.locator(".slot.is-empty").count() == 2
    assert "specials only" in specials.inner_text().lower()
    # A fresh bladder: eight open spaces, four toilet tokens in reserve
    assert page.locator(".mat.is-mine .bladder-slots .slot.is-empty").count() == 8
    assert page.locator(".mat.is-mine .loo-reserve .loo").count() == 4
    # The score track is on the table; the drinks menu opens from the turn bar
    assert page.locator(".score-track .score-cell").count() == 41
    page.locator('[data-k="open-menu"]').click()
    page.locator("#sheet .menu .menu-item").first.wait_for(
        state="visible", timeout=5000
    )
    assert page.locator("#sheet .menu .menu-item").count() == 9


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
    # They sit under your mat, and one mat shows who went first
    assert page.evaluate(
        "document.querySelector('.mat.is-mine')"
        ".compareDocumentPosition(document.querySelector('.mat.is-theirs'))"
        " & Node.DOCUMENT_POSITION_FOLLOWING"
    )
    assert page.locator(".mat .mat-first").count() == 1
    assert page.locator(".mat .mat-first").inner_text() == "Starting player"
    assert page.locator(".overview-player .ov-first").count() == 1


def test_old_game_links_open_the_bar(page, base_url, new_user, new_game):
    """Old /game links (and invites) open the same game on the bar top."""
    page.goto(f"{base_url}/game?id={new_game}")
    page.wait_for_url(re.compile(r".*/bar\?id=.*"), timeout=10000)
    page.locator("#lobby").wait_for(state="visible", timeout=10000)


def test_bar_rules_and_actions_are_on_show(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """The rule book opens from the turn bar, and on your turn the bar says
    what your main action can be and lists only free actions you can use."""
    game = _started_game(base_url, new_user, new_game, other_user_and_jwt)
    page.goto(f"{base_url}/bar?id={new_game}")
    page.locator('[data-k="open-rules"]').click(timeout=10000)
    page.locator("#sheet .rulebook").wait_for(state="visible", timeout=10000)
    assert page.locator("#sheet .rulebook .rule-part").count() >= 6
    assert "40" in page.locator("#sheet .rulebook").inner_text()
    page.keyboard.press("Escape")
    page.locator("#sheet").wait_for(state="hidden", timeout=5000)
    if game["game_state"]["player_turn"] == new_user["user"]["id"]:
        bar = page.locator("#turnbar")
        assert "sell, drink a glass or wee" in bar.inner_text()
        # A fresh player (sober, empty bladder) has no free action to use
        assert page.locator(".action-strip").count() == 0
        assert "Needs drunk" not in bar.inner_text()


def test_bar_drinks_menu_shows_everyones_glasses(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """The drinks menu opens from the turn bar with every player's glasses
    kept in view at its top, yours first, and the specials tray is on the
    table. The header gives an overview of every player."""
    _started_game(base_url, new_user, new_game, other_user_and_jwt)
    page.goto(f"{base_url}/bar?id={new_game}")
    page.locator(".specials-tray").wait_for(state="visible", timeout=10000)
    overview = page.locator(".topline .overview-player")
    assert overview.count() == 2
    assert other_user_and_jwt["username"] in page.locator(".topline").inner_text()
    assert page.locator(".menu").count() == 0  # not on the table all the time
    page.locator('[data-k="open-menu"]').click()
    sheet = page.locator("#sheet")
    sheet.locator(".menu").wait_for(state="visible", timeout=5000)
    rows = sheet.locator(".sheet-glass")
    assert rows.count() == 2
    assert rows.first.locator(".sheet-glass-name").inner_text() == "You"
    assert other_user_and_jwt["username"] in rows.nth(1).inner_text()
    assert sheet.locator(".sheet-glass-toks").count() == 4
    assert "Mojito" in sheet.inner_text()
    page.locator('[data-k="sheet-close"]').click()
    sheet.wait_for(state="hidden", timeout=5000)


def test_bar_host_can_call_off_a_game_in_its_lobby(page, base_url, new_user, new_game):
    """The host can call off a game before it starts, after confirming."""
    page.goto(f"{base_url}/bar?id={new_game}")
    page.locator('#lobby [data-k="call-off"]').click(timeout=10000)
    page.locator(".leave-confirm").wait_for(state="visible", timeout=5000)
    page.locator('[data-k="leave-yes"]').click()
    page.locator("#lobby", has_text="This game was called off").wait_for(timeout=10000)
    assert _api_get(base_url, f"/v1/games/{new_game}", new_user["jwt"])["status"] == (
        "ENDED"
    )


def test_bar_players_can_leave_a_game_with_people(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """In a game with people, everyone playing (host included) can leave, and
    the host can also call it off; asking first works on anyone's turn."""
    _started_game(base_url, new_user, new_game, other_user_and_jwt)
    page.goto(f"{base_url}/bar?id={new_game}")
    page.locator('[data-k="leave"]').wait_for(state="visible", timeout=10000)
    assert page.locator('[data-k="call-off"]').is_visible()
    page.locator('[data-k="leave"]').click()
    page.wait_for_timeout(2500)  # a poll must not close the question
    assert page.locator(".leave-confirm").is_visible()
    page.locator('[data-k="leave-yes"]').click()
    page.locator('[data-k="leave"]').wait_for(state="detached", timeout=10000)
    state = _api_get(base_url, f"/v1/games/{new_game}", new_user["jwt"])
    me = new_user["user"]["id"]
    assert state["game_state"]["player_states"][me]["status"] == "quit"


def _take_blind(base_url, game_id, player, disposition):
    """Take a full turn's ingredients blind from the bag and end the turn."""
    gs = _api_get(base_url, f"/v1/games/{game_id}", player["jwt"])["game_state"]
    take = gs["player_states"][player["user"]["id"]]["take_count"]
    assignments = [
        {"source": "bag", "disposition": disposition, "cup_index": i % 2}
        if disposition == "cup"
        else {"source": "bag", "disposition": disposition}
        for i in range(take)
    ]
    _api_post(
        base_url,
        f"/v1/games/{game_id}/actions/take-ingredients",
        player["jwt"],
        {"assignments": assignments},
    )
    # A free action it opened up (drunk enough to clear a row) holds the turn
    gs = _api_get(base_url, f"/v1/games/{game_id}", player["jwt"])["game_state"]
    if gs["player_turn"] == player["user"]["id"]:
        _api_post(base_url, f"/v1/games/{game_id}/actions/end-turn", player["jwt"])


def test_bar_recap_says_what_happened_since_your_turn(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """As your turn starts, a panel says what the others did since your last
    one and what it changed; their mats say so too until you move. It opens
    once a turn, and the turn bar opens it again. Your first turn, with
    nobody gone before you, has nothing to tell."""
    game = _started_game(base_url, new_user, new_game, other_user_and_jwt)
    me = new_user["user"]["id"]
    other = other_user_and_jwt
    sheet = page.locator("#sheet")
    if game["game_state"]["player_turn"] == me:
        page.goto(f"{base_url}/bar?id={new_game}")
        page.locator(".turnbar.tone-you").wait_for(state="visible", timeout=10000)
        page.wait_for_timeout(500)
        assert sheet.is_hidden()
        assert page.locator('[data-k="open-recap"]').count() == 0
        _take_blind(base_url, new_game, new_user, "cup")
    _take_blind(base_url, new_game, other, "drink")
    state = _api_get(base_url, f"/v1/games/{new_game}", new_user["jwt"])
    assert state["game_state"]["player_turn"] == me

    page.goto(f"{base_url}/bar?id={new_game}")
    sheet.locator(".recap").wait_for(state="visible", timeout=10000)
    text = sheet.inner_text()
    assert f"{other['username']}’s turn" in text
    assert "drank" in text
    assert "What changed" in text
    page.locator('[data-k="recap-close"]').click()
    sheet.wait_for(state="hidden", timeout=5000)
    note = page.locator(".mat.is-theirs .mat-recap")
    assert note.is_visible()
    assert "drunk" in note.inner_text() or "bladder" in note.inner_text()

    page.locator('[data-k="open-recap"]').click()
    sheet.locator(".recap").wait_for(state="visible", timeout=5000)
    page.keyboard.press("Escape")
    sheet.wait_for(state="hidden", timeout=5000)
    # Seen this turn: it doesn't open again by itself
    page.reload()
    page.locator(".turnbar.tone-you").wait_for(state="visible", timeout=10000)
    page.wait_for_timeout(1000)
    assert sheet.is_hidden()
    assert page.locator('[data-k="open-recap"]').is_visible()


def test_bar_picking_up_keeps_the_page_still_and_your_hand_in_view(
    page, base_url, new_user, new_game, other_user_and_jwt
):
    """With the drinks menu open, picking a token off the display brings your
    hand into view, and putting it back doesn't throw the page around."""
    game = _started_game(base_url, new_user, new_game, other_user_and_jwt)
    if game["game_state"]["player_turn"] != new_user["user"]["id"]:
        _take_blind(base_url, new_game, other_user_and_jwt, "cup")
    page.set_viewport_size({"width": 1440, "height": 800})
    page.goto(f"{base_url}/bar?id={new_game}")
    page.locator(".turnbar.tone-you").wait_for(state="visible", timeout=10000)
    if page.locator("#sheet").is_visible():
        page.locator('[data-k="sheet-close"]').click()
    page.locator('[data-k="open-menu"]').click()
    display = game["game_state"]["open_display"]
    slot = next(i for i, name in enumerate(display) if name != "SPECIAL")
    token = page.locator(f'[data-k="disp-{slot}"]')
    token.scroll_into_view_if_needed()
    box = token.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.locator(".hand .tok").wait_for(state="visible", timeout=5000)
    page.wait_for_timeout(800)  # the scroll to your hand is smooth
    hand = page.locator(".mat.is-mine .hand").bounding_box()
    assert 0 <= hand["y"] < 800
    # Touch it in your hand: the page stays put
    before = page.evaluate("window.scrollY")
    held = page.locator(".hand .tok").first.bounding_box()
    page.mouse.click(held["x"] + held["width"] / 2, held["y"] + held["height"] / 2)
    page.wait_for_timeout(500)
    assert abs(page.evaluate("window.scrollY") - before) <= 2
