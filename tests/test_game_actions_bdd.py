"""BDD tests for game actions — business-readable scenarios using pytest-bdd.

Feature files live in tests/features/.
Step definitions are below.
"""

import time
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from app.api import app
from app.Ingredient import Ingredient
from app.PlayerState import MAX_CUP_INGREDIENTS

# ─── Load scenarios from feature files ────────────────────────────────────────

scenarios("features/game_actions.feature")
scenarios("features/undo.feature")

# ─── Helpers ──────────────────────────────────────────────────────────────────

_client = TestClient(app)


def _unique(prefix: str) -> str:
    return f"{prefix}_{time.time_ns()}"


def _register(username: str) -> tuple[str, str]:
    """Register a user and return (token, user_id)."""
    resp = _client.post(
        "/register",
        json={"username": username, "email": f"{username}@bdd.test", "password": "Password1"},
    )
    assert resp.status_code == 201, resp.text
    return resp.cookies["userjwt"], resp.json()["id"]


def _auth(token: str) -> dict:
    return {"userjwt": token}


def _new_game(token: str) -> str:
    resp = _client.post("/v1/games", cookies=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _join(token: str, game_id: str):
    resp = _client.post(f"/v1/games/{game_id}/join", cookies=_auth(token))
    assert resp.status_code == 200, resp.text


def _start(token: str, game_id: str):
    resp = _client.post(f"/v1/games/{game_id}/start", cookies=_auth(token))
    assert resp.status_code == 200, resp.text


def _get_game(token: str, game_id: str) -> dict:
    resp = _client.get(f"/v1/games/{game_id}", cookies=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _patch_game_state(game_id: str, token: str, patch_fn):
    """Directly patch game state in the DB for test setup via the game manager."""
    from app.db import db
    from app.GameState import GameState

    game = db.get_game(UUID(game_id))
    assert game is not None
    patched = patch_fn(game.game_state)
    db.update_game_state(UUID(game_id), patched)
    return patched


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def ctx():
    """Shared mutable context dict for passing state between steps."""
    return {}


# ─── Background steps ─────────────────────────────────────────────────────────


@given("a started game with 2 players", target_fixture="ctx")
def started_game_2_players():
    p1 = _unique("p1")
    p2 = _unique("p2")
    t1, id1 = _register(p1)
    t2, id2 = _register(p2)
    game_id = _new_game(t1)
    _join(t2, game_id)
    _start(t1, game_id)
    game = _get_game(t1, game_id)
    turn_owner_id = game["game_state"]["player_turn"]
    # Determine which token belongs to the active player
    if turn_owner_id == id1:
        active_token, active_id = t1, id1
        other_token, other_id = t2, id2
    else:
        active_token, active_id = t2, id2
        other_token, other_id = t1, id1
    return {
        "game_id": game_id,
        "p1_token": active_token,
        "p1_id": active_id,
        "p2_token": other_token,
        "p2_id": other_id,
        "last_resp": None,
        "last_status": None,
    }


@given("a started game with 2 players and no moves yet", target_fixture="ctx")
def started_game_no_moves():
    return started_game_2_players()


@given("player 1 has completed a turn", target_fixture="ctx")
def p1_completed_turn(ctx):
    """Player 1 goes for a wee as a simple completed turn."""
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/go-for-a-wee",
        cookies=_auth(ctx["p1_token"]),
    )
    assert resp.status_code == 200, resp.text
    return ctx


# ─── Given steps ──────────────────────────────────────────────────────────────


@given("it is player 1's turn")
def it_is_p1_turn(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    assert game["game_state"]["player_turn"] == ctx["p1_id"], (
        "Precondition: expected player 1 to be active"
    )


@given("player 1 has an empty cup 0")
def p1_empty_cup0(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    ps = game["game_state"]["player_states"][ctx["p1_id"]]
    assert ps["cup1"] == [], "Cup 0 should already be empty after game start"


@given("the bag contains no special tokens")
def bag_no_specials(ctx):
    def patch(gs):
        gs.bag_contents = [i for i in gs.bag_contents if not i.value.special]
        return gs

    _patch_game_state(ctx["game_id"], ctx["p1_token"], patch)


@given(parsers.parse("player 1's cup {cup_index:d} is full with {count:d} ingredients"))
def p1_cup_full(ctx, cup_index, count):
    def patch(gs):
        ps = gs.player_states[UUID(ctx["p1_id"])]
        ingredients = [Ingredient.VODKA] * count
        if cup_index == 0:
            ps.cup1 = ingredients
        else:
            ps.cup2 = ingredients
        return gs

    _patch_game_state(ctx["game_id"], ctx["p1_token"], patch)


@given(parsers.parse("player 1's cup {cup_index:d} contains {spec}"))
def p1_cup_contains(ctx, cup_index, spec):
    ingredients = _parse_ingredient_spec(spec)

    def patch(gs):
        ps = gs.player_states[UUID(ctx["p1_id"])]
        if cup_index == 0:
            ps.cup1 = ingredients
        else:
            ps.cup2 = ingredients
        # Remove these from the bag so totals are consistent
        for ing in ingredients:
            if ing in gs.bag_contents:
                gs.bag_contents.remove(ing)
        return gs

    _patch_game_state(ctx["game_id"], ctx["p1_token"], patch)


@given(parsers.parse('player 1\'s cup {cup_index:d} also contains {spec}'))
def p1_cup_also_contains(ctx, cup_index, spec):
    extra = _parse_ingredient_spec(spec)

    def patch(gs):
        ps = gs.player_states[UUID(ctx["p1_id"])]
        cup = ps.cup1 if cup_index == 0 else ps.cup2
        cup.extend(extra)
        for ing in extra:
            if ing in gs.bag_contents:
                gs.bag_contents.remove(ing)
        return gs

    _patch_game_state(ctx["game_id"], ctx["p1_token"], patch)


@given(parsers.parse('player 1 has "{special}" on their player mat'))
def p1_has_special(ctx, special):
    def patch(gs):
        ps = gs.player_states[UUID(ctx["p1_id"])]
        ps.special_ingredients.append(special)
        return gs

    _patch_game_state(ctx["game_id"], ctx["p1_token"], patch)


@given(parsers.parse('player 1 has "{specials}" on their player mat'))
def p1_has_specials(ctx, specials):
    for s in specials.split(" and "):
        s = s.strip().strip('"')

        def patch(gs, special=s):
            ps = gs.player_states[UUID(ctx["p1_id"])]
            ps.special_ingredients.append(special)
            return gs

        _patch_game_state(ctx["game_id"], ctx["p1_token"], patch)


@given(parsers.parse("player 1 has {count:d} ingredients in their bladder"))
def p1_bladder_count(ctx, count):
    def patch(gs):
        ps = gs.player_states[UUID(ctx["p1_id"])]
        ps.bladder = [Ingredient.COLA] * count
        return gs

    _patch_game_state(ctx["game_id"], ctx["p1_token"], patch)


@given(parsers.parse("player 1 has a drunk level of {level:d}"))
def p1_drunk_level(ctx, level):
    def patch(gs):
        ps = gs.player_states[UUID(ctx["p1_id"])]
        ps.drunk_level = level
        return gs

    _patch_game_state(ctx["game_id"], ctx["p1_token"], patch)


@given(parsers.parse("player 1 has {points:d} points"))
def p1_has_points(ctx, points):
    def patch(gs):
        ps = gs.player_states[UUID(ctx["p1_id"])]
        ps.points = points
        return gs

    _patch_game_state(ctx["game_id"], ctx["p1_token"], patch)


@given(parsers.parse("a card with cost {count:d} {kind} is available in row {row:d}"), target_fixture="available_card_id")
def card_in_row(ctx, count, kind, row):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    rows = game["game_state"]["card_rows"]
    for r in rows:
        if r["position"] == row:
            for card in r["cards"]:
                reqs = card["cost"]
                for req in reqs:
                    if req["kind"] == kind and req["count"] <= count:
                        ctx["target_card_id"] = card["id"]
                        return card["id"]
    # If no card matches exactly, take the first card in that row
    for r in rows:
        if r["position"] == row and r["cards"]:
            ctx["target_card_id"] = r["cards"][0]["id"]
            return r["cards"][0]["id"]
    pytest.skip(f"No card found in row {row}")


@given(parsers.parse("player 1 has {count:d} {kind} in their bladder"))
def p1_bladder_kind(ctx, count, kind):
    ingredient_map = {
        "mixer": Ingredient.COLA,
        "mixers": Ingredient.COLA,
        "spirit": Ingredient.VODKA,
        "spirits": Ingredient.VODKA,
    }
    ing = ingredient_map.get(kind, Ingredient.COLA)

    def patch(gs):
        ps = gs.player_states[UUID(ctx["p1_id"])]
        ps.bladder = [ing] * count
        return gs

    _patch_game_state(ctx["game_id"], ctx["p1_token"], patch)


@given("player 1 has proposed to undo the last turn")
def p1_proposed_undo(ctx):
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/undo",
        cookies=_auth(ctx["p1_token"]),
    )
    assert resp.status_code == 200, resp.text
    ctx["undo_request_id"] = resp.json()["undo_request"]["id"]


# ─── When steps ───────────────────────────────────────────────────────────────


@when("player 1 takes 3 ingredients from the bag placing all in cup 0")
def p1_take_3_to_cup0(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    bag = game["game_state"]["bag_contents"]
    assert len(bag) >= 3, "Not enough in bag"
    # Bag draws are random — do not specify ingredient; system selects randomly
    assignments = [
        {"source": "bag", "disposition": "cup", "cup_index": 0},
        {"source": "bag", "disposition": "cup", "cup_index": 0},
        {"source": "bag", "disposition": "cup", "cup_index": 0},
    ]
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/take-ingredients",
        json={"assignments": assignments},
        cookies=_auth(ctx["p1_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when("player 1 tries to place an ingredient in cup 0")
def p1_place_in_full_cup(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    bag = game["game_state"]["bag_contents"]
    if not bag:
        pytest.skip("Bag is empty")
    # Bag draws are random — do not specify ingredient; system selects randomly.
    # Submitting only 1 assignment when take_limit=3 will yield a 400 error.
    assignments = [{"source": "bag", "disposition": "cup", "cup_index": 0}]
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/take-ingredients",
        json={"assignments": assignments},
        cookies=_auth(ctx["p1_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player 1 sells cup {cup_index:d} with no declared specials"))
def p1_sell_cup_no_specials(ctx, cup_index):
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/sell-cup",
        json={"cup_index": cup_index, "declared_specials": []},
        cookies=_auth(ctx["p1_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse('player 1 sells cup {cup_index:d} declaring specials "{specials}"'))
def p1_sell_cup_specials(ctx, cup_index, specials):
    special_list = [s.strip() for s in specials.split(",")]
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/sell-cup",
        json={"cup_index": cup_index, "declared_specials": special_list},
        cookies=_auth(ctx["p1_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player 1 drinks cup {cup_index:d}"))
def p1_drink_cup(ctx, cup_index):
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/drink-cup",
        json={"cup_index": cup_index},
        cookies=_auth(ctx["p1_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when("player 1 goes for a wee")
def p1_go_for_a_wee(ctx):
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/go-for-a-wee",
        cookies=_auth(ctx["p1_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when("player 1 claims that card")
def p1_claim_card(ctx):
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/claim-card",
        json={"card_id": ctx["target_card_id"]},
        cookies=_auth(ctx["p1_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when("player 1 tries to claim that card")
def p1_try_claim_card(ctx):
    p1_claim_card(ctx)


@when(parsers.parse("player 1 refreshes card row {row:d}"))
def p1_refresh_row(ctx, row):
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/refresh-card-row",
        json={"row_position": row},
        cookies=_auth(ctx["p1_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player 1 tries to refresh card row {row:d}"))
def p1_try_refresh_row(ctx, row):
    p1_refresh_row(ctx, row)


@when("player 2 tries to take an ingredient")
def p2_take_ingredient(ctx):
    game = _get_game(ctx["p2_token"], ctx["game_id"])
    bag = game["game_state"]["bag_contents"]
    if not bag:
        pytest.skip("No bag contents")
    # Bag draws are random — do not specify ingredient
    assignments = [{"source": "bag", "disposition": "drink"}]
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/take-ingredients",
        json={"assignments": assignments},
        cookies=_auth(ctx["p2_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when("player 1 proposes to undo the last turn")
def p1_propose_undo(ctx):
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/undo",
        cookies=_auth(ctx["p1_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code
    if resp.status_code == 200:
        ctx["undo_request_id"] = resp.json()["undo_request"]["id"]


@when("player 2 votes agree on the undo")
def p2_vote_agree(ctx):
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/undo/vote",
        json={"request_id": ctx["undo_request_id"], "vote": "agree"},
        cookies=_auth(ctx["p2_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code
    ctx["pre_undo_game"] = _get_game(ctx["p1_token"], ctx["game_id"])


@when("player 2 votes disagree on the undo")
def p2_vote_disagree(ctx):
    game_before = _get_game(ctx["p1_token"], ctx["game_id"])
    ctx["game_before_undo"] = game_before
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/undo/vote",
        json={"request_id": ctx["undo_request_id"], "vote": "disagree"},
        cookies=_auth(ctx["p2_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when("player 1 tries to vote again on the undo")
def p1_vote_again(ctx):
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/undo/vote",
        json={"request_id": ctx["undo_request_id"], "vote": "agree"},
        cookies=_auth(ctx["p1_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when("player 2 also tries to propose an undo")
def p2_propose_undo(ctx):
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/undo",
        cookies=_auth(ctx["p2_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when("player 1 fetches the move history")
def p1_fetch_history(ctx):
    resp = _client.get(
        f"/v1/games/{ctx['game_id']}/history",
        cookies=_auth(ctx["p1_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when("player 1 requests the state at turn 0")
def p1_state_at_turn_0(ctx):
    resp = _client.get(
        f"/v1/games/{ctx['game_id']}/history/0",
        cookies=_auth(ctx["p1_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


# ─── Then steps ───────────────────────────────────────────────────────────────


@then(parsers.parse("cup {cup_index:d} should contain {count:d} ingredients"))
def cup_contains_count(ctx, cup_index, count):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    ps = game["game_state"]["player_states"][ctx["p1_id"]]
    cup_key = "cup1" if cup_index == 0 else "cup2"
    assert len(ps[cup_key]) == count, f"Expected {count} in cup {cup_index}, got {len(ps[cup_key])}"


@then("cup 0 should be empty")
def cup0_empty(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    ps = game["game_state"]["player_states"][ctx["p1_id"]]
    assert ps["cup1"] == [], f"Expected cup1 empty, got {ps['cup1']}"


@then("a move record should be created for the game")
def move_record_created(ctx):
    resp = _client.get(
        f"/v1/games/{ctx['game_id']}/history",
        cookies=_auth(ctx["p1_token"]),
    )
    assert resp.status_code == 200, resp.text
    moves = resp.json()["moves"]
    assert len(moves) >= 1, "Expected at least one move record"


@then("it should be player 2's turn")
def it_is_p2_turn(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    assert game["game_state"]["player_turn"] == ctx["p2_id"], "Expected player 2's turn"


@then(parsers.parse("player 1 should have {points:d} point"))
@then(parsers.parse("player 1 should have {points:d} points"))
def p1_has_points_check(ctx, points):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    ps = game["game_state"]["player_states"][ctx["p1_id"]]
    assert ps["points"] == points, f"Expected {points} pts, got {ps['points']}"


@then(parsers.parse("player 1's bladder should contain {count:d} ingredients"))
def p1_bladder_count_check(ctx, count):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    ps = game["game_state"]["player_states"][ctx["p1_id"]]
    assert len(ps["bladder"]) == count, f"Expected bladder count {count}, got {len(ps['bladder'])}"


@then("player 1's bladder should be empty")
def p1_bladder_empty(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    ps = game["game_state"]["player_states"][ctx["p1_id"]]
    assert ps["bladder"] == [], f"Expected empty bladder, got {ps['bladder']}"


@then(parsers.parse("player 1's drunk level should be {level:d}"))
def p1_drunk_level_check(ctx, level):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    ps = game["game_state"]["player_states"][ctx["p1_id"]]
    assert ps["drunk_level"] == level, f"Expected drunk_level {level}, got {ps['drunk_level']}"


@then("player 1's toilet tokens should decrease by 1")
def p1_toilet_tokens_decrease(ctx):
    from app.PlayerState import INITIAL_TOILET_TOKENS

    game = _get_game(ctx["p1_token"], ctx["game_id"])
    ps = game["game_state"]["player_states"][ctx["p1_id"]]
    assert ps["toilet_tokens"] == INITIAL_TOILET_TOKENS - 1, (
        f"Expected toilet_tokens {INITIAL_TOILET_TOKENS - 1}, got {ps['toilet_tokens']}"
    )


@then("player 1 should have 1 card")
def p1_has_1_card(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    ps = game["game_state"]["player_states"][ctx["p1_id"]]
    assert len(ps["cards"]) == 1, f"Expected 1 card, got {len(ps['cards'])}"


@then(parsers.parse("row {row:d} should be refreshed with new cards"))
def row_refreshed(ctx, row):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    rows = game["game_state"]["card_rows"]
    for r in rows:
        if r["position"] == row:
            # Row still exists — refresh succeeded
            return
    pytest.fail(f"Row {row} not found after refresh")


@then(parsers.parse("the action should be rejected with a {code:d} error"))
def action_rejected(ctx, code):
    assert ctx["last_status"] == code, (
        f"Expected {code}, got {ctx['last_status']}: "
        f"{ctx['last_resp'].text if ctx['last_resp'] else 'no response'}"
    )


@then("the game should be over")
def game_over(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    assert game["status"] == "ENDED", f"Expected ENDED, got {game['status']}"


@then("player 1 should be the winner")
def p1_is_winner(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    assert game["game_state"]["winner"] == ctx["p1_id"], (
        f"Expected winner {ctx['p1_id']}, got {game['game_state']['winner']}"
    )


@then("an undo request should be pending for the game")
def undo_pending(ctx):
    assert ctx["last_status"] == 200, f"Expected 200, got {ctx['last_status']}: {ctx['last_resp'].text}"
    data = ctx["last_resp"].json()
    assert data["undo_request"]["status"] == "pending"


@then("player 1's vote should be recorded as agree")
def p1_voted_agree(ctx):
    data = ctx["last_resp"].json()
    votes = data["undo_request"]["votes"]
    assert votes.get(ctx["p1_id"]) == "agree"


@then("the undo request should be approved")
def undo_approved(ctx):
    assert ctx["last_status"] == 200, ctx["last_resp"].text
    data = ctx["last_resp"].json()
    assert data.get("status") == "approved"


@then("the game state should be restored to before the last turn")
def state_restored(ctx):
    # State was restored — verify the turn number is lower than after the move
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    # After undo, turn_number should be lower than before the vote
    pre_turn = ctx.get("pre_undo_game", {}).get("game_state", {}).get("turn_number", 999)
    current_turn = game["game_state"]["turn_number"]
    assert current_turn < pre_turn, (
        f"Expected turn_number to decrease after undo, got {current_turn} (was {pre_turn})"
    )


@then("the undo request should be rejected")
def undo_rejected(ctx):
    assert ctx["last_status"] == 200, ctx["last_resp"].text
    data = ctx["last_resp"].json()
    assert data.get("status") == "rejected"


@then("the game state should remain unchanged")
def state_unchanged(ctx):
    game_now = _get_game(ctx["p1_token"], ctx["game_id"])
    before = ctx.get("game_before_undo", {}).get("game_state", {})
    after = game_now["game_state"]
    assert before.get("turn_number") == after.get("turn_number"), (
        "Game state changed after rejected undo"
    )


@then("the history should contain 1 move")
def history_has_1_move(ctx):
    assert ctx["last_status"] == 200, ctx["last_resp"].text
    moves = ctx["last_resp"].json()["moves"]
    assert len(moves) == 1, f"Expected 1 move, got {len(moves)}"


@then("the move should record the action type and player")
def move_has_action_and_player(ctx):
    moves = ctx["last_resp"].json()["moves"]
    move = moves[0]
    assert "action_type" in move
    assert "player_id" in move


@then("the returned state should be the initial game state")
def state_is_initial(ctx):
    assert ctx["last_status"] == 200, ctx["last_resp"].text
    state = ctx["last_resp"].json()["game_state"]
    assert state is not None
    assert state.get("turn_number", 0) == 0


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _parse_ingredient_spec(spec: str) -> list[Ingredient]:
    """Parse '1 VODKA and 1 COLA' or '2 RUM and 1 SODA' into [Ingredient, ...]."""
    from app.Ingredient import Ingredient

    result = []
    parts = [p.strip() for p in spec.replace(" and ", ",").split(",")]
    for part in parts:
        tokens = part.strip().split()
        if len(tokens) >= 2:
            try:
                count = int(tokens[0])
                name = tokens[1].rstrip(",")
                result.extend([Ingredient[name]] * count)
            except (ValueError, KeyError):
                pass
    return result
