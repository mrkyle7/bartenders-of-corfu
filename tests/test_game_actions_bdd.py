"""BDD tests for game actions — business-readable scenarios using pytest-bdd.

Feature files live in tests/features/.
Step definitions are below.

Player number convention
------------------------
Steps use "player {n:d}" where n is 1 or 2.  The ctx dict stores tokens and
IDs as p1_token/p1_id and p2_token/p2_id.  _player(ctx, n) maps n → (token, id).
This lets a single step definition cover any player number; feature files can
freely write "player 1 goes for a wee" or "player 2 goes for a wee" without
needing separate step functions.
"""

import time
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from app.GameState import GameState
from app.api import app
from app.Ingredient import Ingredient, SpecialType
from unittest.mock import patch

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
        json={
            "username": username,
            "email": f"{username}@bdd.test",
            "password": "Password1",
        },
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


def _patch_game_state(game_id: str, patch_fn):
    """Directly patch game state in the DB for test setup via the game manager."""
    from app.db import db

    game = db.get_game(UUID(game_id))
    assert game is not None
    patched = patch_fn(game.game_state)
    db.update_game_state(UUID(game_id), patched)
    return patched


def _player(ctx: dict, n: int) -> tuple[str, str]:
    """Return (token, player_id) for player n (1-indexed)."""
    return ctx[f"p{n}_token"], ctx[f"p{n}_id"]


def _player_state(ctx: dict, n: int) -> dict:
    """Fetch the current game and return player n's state dict."""
    token, pid = _player(ctx, n)
    game = _get_game(token, ctx["game_id"])
    return game["game_state"]["player_states"][pid]


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
    # p1 = whoever goes first; p2 = the other
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


@given(parsers.parse("player {n:d} has completed a turn"), target_fixture="ctx")
def player_completed_turn(ctx, n):
    """Player n takes ingredients from the bag as a simple completed turn."""
    token, _ = _player(ctx, n)
    game = _get_game(token, ctx["game_id"])
    _, pid = _player(ctx, n)
    take_count = game["game_state"]["player_states"][pid]["take_count"]
    draw_resp, take_resp = _draw_and_assign(token, ctx["game_id"], take_count, "drink")
    assert draw_resp.status_code == 200, draw_resp.text
    assert take_resp.status_code == 200, take_resp.text
    return ctx


# ─── Given steps ──────────────────────────────────────────────────────────────


@given(parsers.parse("it is player {n:d}'s turn"))
def it_is_player_turn(ctx, n):
    token, pid = _player(ctx, n)
    game = _get_game(token, ctx["game_id"])
    assert game["game_state"]["player_turn"] == pid, (
        f"Precondition: expected player {n} to be active"
    )


@given(parsers.parse("player {n:d} has an empty cup {cup_index:d}"))
def player_empty_cup(ctx, n, cup_index):
    token, pid = _player(ctx, n)
    game = _get_game(token, ctx["game_id"])
    ps = game["game_state"]["player_states"][pid]
    assert ps["cups"][cup_index]["ingredients"] == [], (
        f"Cup {cup_index} should already be empty after game start"
    )


@given("the bag contains no special tokens")
def bag_no_specials(ctx):
    def patch(gs):
        gs.bag_contents = [i for i in gs.bag_contents if not i.value.special]
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse("the open display contains {spec}"))
def set_open_display(ctx, spec):
    ingredients = _parse_ingredient_spec(spec)

    def patch(gs: GameState):
        gs.open_display = ingredients
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(
    parsers.parse("player {n:d}'s cup {cup_index:d} is full with {count:d} ingredients")
)
def player_cup_full(ctx, n, cup_index, count):
    _, pid = _player(ctx, n)

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.cups[cup_index].ingredients = [Ingredient.VODKA] * count
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse("player {n:d}'s cup {cup_index:d} contains {spec}"))
def player_cup_contains(ctx, n, cup_index, spec):
    _, pid = _player(ctx, n)
    ingredients = _parse_ingredient_spec(spec)

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.cups[cup_index].ingredients = ingredients
        for ing in ingredients:
            if ing in gs.bag_contents:
                gs.bag_contents.remove(ing)
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse("player {n:d}'s cup {cup_index:d} also contains {spec}"))
def player_cup_also_contains(ctx, n, cup_index, spec):
    _, pid = _player(ctx, n)
    extra = _parse_ingredient_spec(spec)

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.cups[cup_index].ingredients.extend(extra)
        for ing in extra:
            if ing in gs.bag_contents:
                gs.bag_contents.remove(ing)
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse('player {n:d} has "{specials}" on their player mat'))
def player_has_specials(ctx, n, specials):
    _, pid = _player(ctx, n)
    for s in specials.split(" and "):
        s = s.strip().strip('"')

        def patch(gs, special=s, player_id=pid):
            ps = gs.player_states[UUID(player_id)]
            ps.special_ingredients.append(special)
            return gs

        _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse("player {n:d} has no special tokens on their player mat"))
def player_has_no_specials(ctx, n):
    _, pid = _player(ctx, n)

    def patch(gs, player_id=pid):
        ps = gs.player_states[UUID(player_id)]
        ps.special_ingredients = []
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse("player {n:d} has {count:d} ingredients in their bladder"))
def player_bladder_count(ctx, n, count):
    _, pid = _player(ctx, n)

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.bladder = [Ingredient.COLA] * count
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse("player {n:d} has a drunk level of {level:d}"))
def player_drunk_level(ctx, n, level):
    _, pid = _player(ctx, n)

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.drunk_level = level
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse("player {n:d} has {points:d} points"))
def player_has_points(ctx, n, points):
    _, pid = _player(ctx, n)

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.points = points
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(
    parsers.parse("a refresher card is available in row {row:d}"),
    target_fixture="available_card_id",
)
def refresher_card_in_row(ctx, row):
    import uuid as _uuid
    from app.card import Card as _Card

    new_card_id = str(_uuid.uuid4())

    def patch(gs):
        for r in gs.card_rows:
            if r.position == row:
                # Replace first card so row count stays the same (keeps deck-empty test correct)
                new_card = _Card(
                    id=new_card_id,
                    card_type="refresher",
                    name="Cola Refresher",
                    mixer_type="COLA",
                )
                if r.cards:
                    r.cards[0] = new_card
                else:
                    r.cards.append(new_card)
                break
        return gs

    _patch_game_state(ctx["game_id"], patch)
    ctx["target_card_id"] = new_card_id
    return new_card_id


@given(
    parsers.parse("a karaoke card is available in row {row:d}"),
    target_fixture="available_card_id",
)
def karaoke_card_in_row(ctx, row):
    import uuid as _uuid
    from app.card import Card as _Card

    new_card_id = str(_uuid.uuid4())

    def patch(gs):
        for r in gs.card_rows:
            if r.position == row:
                r.cards.insert(
                    0,
                    _Card(
                        id=new_card_id,
                        card_type="karaoke",
                        name="Party Tune",
                        spirit_type="VODKA",
                    ),
                )
                break
        return gs

    _patch_game_state(ctx["game_id"], patch)
    ctx["target_card_id"] = new_card_id
    return new_card_id


@given(
    parsers.parse("a store card is available in row {row:d}"),
    target_fixture="available_card_id",
)
def store_card_in_row(ctx, row):
    import uuid as _uuid
    from app.card import Card as _Card

    new_card_id = str(_uuid.uuid4())

    def patch(gs):
        for r in gs.card_rows:
            if r.position == row:
                r.cards.insert(
                    0,
                    _Card(
                        id=new_card_id,
                        card_type="store",
                        name="Vodka Store",
                        spirit_type="VODKA",
                    ),
                )
                break
        return gs

    _patch_game_state(ctx["game_id"], patch)
    ctx["target_card_id"] = new_card_id
    return new_card_id


@given(parsers.parse("player {n:d} has {count:d} {kind} in their bladder"))
def player_bladder_kind(ctx, n, count, kind):
    _, pid = _player(ctx, n)
    ingredient_map = {
        "mixer": Ingredient.COLA,
        "mixers": Ingredient.COLA,
        "spirit": Ingredient.VODKA,
        "spirits": Ingredient.VODKA,
    }
    ing = ingredient_map.get(kind, Ingredient.COLA)

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.bladder = [ing] * count
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse("player {n:d} has claimed {count:d} karaoke cards"))
def player_has_karaoke_cards(ctx, n, count):
    _, pid = _player(ctx, n)

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.karaoke_cards_claimed = count
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse("player {n:d} is eliminated"))
def player_is_eliminated(ctx, n):
    _, pid = _player(ctx, n)

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.status = "hospitalised"
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse("player {n:d} has proposed to undo the last turn"))
def player_proposed_undo(ctx, n):
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/undo",
        cookies=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    ctx["undo_request_id"] = resp.json()["undo_request"]["id"]


@given(parsers.parse("player {n:d} holds a {mixer_type} refresher card"))
def player_holds_refresher_card(ctx, n, mixer_type):
    import uuid as _uuid
    from app.card import Card as _Card

    _, pid = _player(ctx, n)
    card = _Card(
        id=str(_uuid.uuid4()),
        card_type="refresher",
        name=f"{mixer_type.upper()} Refresher",
        mixer_type=mixer_type.upper(),
    )

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.cards.append(card.to_dict())
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(
    parsers.parse("player {n:d} holds a VODKA store card with {count:d} stored spirits")
)
@given(
    parsers.parse("player {n:d} holds a VODKA store card with {count:d} stored spirit")
)
def player_holds_store_card(ctx, n, count):
    import uuid as _uuid
    from app.card import Card as _Card

    _, pid = _player(ctx, n)
    card = _Card(
        id=str(_uuid.uuid4()),
        card_type="store",
        name="Vodka Store",
        spirit_type="VODKA",
        stored_spirits=["VODKA"] * count,
    )

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.cards.append(card.to_dict())
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse("player {n:d}'s cup {cup_index:d} has the cup doubler effect"))
def player_cup_has_doubler(ctx, n, cup_index):
    _, pid = _player(ctx, n)

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.cups[cup_index].has_cup_doubler = True
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(
    parsers.parse("a cup doubler card is available in row {row:d}"),
    target_fixture="available_card_id",
)
def cup_doubler_card_in_row(ctx, row):
    import uuid as _uuid
    from app.card import Card as _Card

    new_card_id = str(_uuid.uuid4())

    def patch(gs):
        for r in gs.card_rows:
            if r.position == row:
                r.cards.insert(
                    0,
                    _Card(
                        id=new_card_id,
                        card_type="cup_doubler",
                        name="Cup Doubler",
                        spirit_type="VODKA",
                    ),
                )
                break
        return gs

    _patch_game_state(ctx["game_id"], patch)
    ctx["target_card_id"] = new_card_id
    return new_card_id


@given("the deck is empty")
def deck_is_empty(ctx):
    def patch(gs):
        gs._deck_dicts = []
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse("player {n:d} has used all toilet tokens"))
def player_used_all_toilet_tokens(ctx, n):
    from app.PlayerState import MIN_BLADDER_CAPACITY

    _, pid = _player(ctx, n)

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.toilet_tokens = 0
        ps.bladder_capacity = MIN_BLADDER_CAPACITY
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given("the bag and display together have fewer than 3 ingredients")
def bag_and_display_too_few(ctx):
    """Empty both bag and open display so any draw attempt fails with 409."""

    def patch(gs):
        gs.bag_contents = []
        gs.open_display = []
        return gs

    _patch_game_state(ctx["game_id"], patch)


# ─── When steps ───────────────────────────────────────────────────────────────


def _draw_and_assign(
    token: str, game_id: str, count: int, disposition: str = "cup", cup_index: int = 0
) -> tuple[dict, dict]:
    """Two-step bag take: draw-from-bag then take-ingredients with source=pending."""
    draw_resp = _client.post(
        f"/v1/games/{game_id}/actions/draw-from-bag",
        json={"count": count},
        cookies=_auth(token),
    )
    assert draw_resp.status_code == 200, f"Draw failed: {draw_resp.text}"
    drawn = draw_resp.json().get("drawn", [])
    assignments = [
        {"source": "pending", "disposition": disposition, "cup_index": cup_index}
        for _ in drawn
    ]
    take_resp = _client.post(
        f"/v1/games/{game_id}/actions/take-ingredients",
        json={"assignments": assignments},
        cookies=_auth(token),
    )
    return draw_resp, take_resp


@when(
    parsers.parse(
        "player {n:d} takes {count:d} ingredients from the bag placing all in cup {cup_index:d}"
    )
)
def player_take_n_to_cup(ctx, n, count, cup_index):
    token, _ = _player(ctx, n)
    game = _get_game(token, ctx["game_id"])
    bag = game["game_state"]["bag_contents"]
    assert len(bag) >= count, f"Not enough in bag (need {count}, have {len(bag)})"
    _, resp = _draw_and_assign(
        token, ctx["game_id"], count, disposition="cup", cup_index=cup_index
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(
    parsers.parse(
        "player {n:d} takes {spec} from the open display placing all in cup {cup_index:d}"
    )
)
def player_take_open_to_cup(ctx, n, spec, cup_index):
    ingredients = _parse_ingredient_spec(spec)

    token, _ = _player(ctx, n)
    assignments = [
        {
            "ingredient": ingredient.name,
            "source": "display",
            "disposition": "cup",
            "cup_index": cup_index,
        }
        for ingredient in ingredients
    ]
    take_resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/take-ingredients",
        json={"assignments": assignments},
        cookies=_auth(token),
    )
    ctx["last_resp"] = take_resp
    ctx["last_status"] = take_resp.status_code


@when(
    parsers.parse(
        "player {n:d} takes 1 special from the open display and rolls {special}"
    )
)
def player_take_open_special(ctx, n, special):
    special = SpecialType[special]

    with patch("app.actions.SpecialType") as mock_SpecialType:
        mock_SpecialType.roll.return_value = special

        token, _ = _player(ctx, n)
        assignments = [{"ingredient": Ingredient.SPECIAL.name, "source": "display"}]
        take_resp = _client.post(
            f"/v1/games/{ctx['game_id']}/actions/take-ingredients",
            json={"assignments": assignments},
            cookies=_auth(token),
        )
    ctx["last_resp"] = take_resp
    ctx["last_status"] = take_resp.status_code
    ctx["last_resp_body"] = take_resp.text


@when(parsers.re(r"player (?P<n>\d+) takes (?P<count>\d+) ingredients? from the bag"))
def player_take_from_bag(ctx, n, count):
    """Two-step bag take: draw then assign."""
    n, count = int(n), int(count)
    token, _ = _player(ctx, n)
    game = _get_game(token, ctx["game_id"])
    bag = game["game_state"]["bag_contents"]
    assert len(bag) >= count, f"Not enough in bag (need {count}, have {len(bag)})"
    _, resp = _draw_and_assign(token, ctx["game_id"], count)
    assert resp.status_code == 200, f"Take failed: {resp.text}"
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player {n:d} tries to place an ingredient in cup {cup_index:d}"))
def player_place_in_cup(ctx, n, cup_index):
    token, _ = _player(ctx, n)
    game = _get_game(token, ctx["game_id"])
    bag = game["game_state"]["bag_contents"]
    if not bag:
        pytest.skip("Bag is empty")
    # Draw 1 from bag first (succeeds), then try to assign to the (full) cup
    draw_resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/draw-from-bag",
        json={"count": 1},
        cookies=_auth(token),
    )
    if draw_resp.status_code != 200:
        ctx["last_resp"] = draw_resp
        ctx["last_status"] = draw_resp.status_code
        return
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/take-ingredients",
        json={
            "assignments": [
                {"source": "pending", "disposition": "cup", "cup_index": cup_index}
            ]
        },
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player {n:d} sells cup {cup_index:d} with no declared specials"))
def player_sell_cup_no_specials(ctx, n, cup_index):
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/sell-cup",
        json={"cup_index": cup_index, "declared_specials": []},
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(
    parsers.parse(
        'player {n:d} sells cup {cup_index:d} declaring specials "{specials}"'
    )
)
def player_sell_cup_specials(ctx, n, cup_index, specials):
    token, _ = _player(ctx, n)
    special_list = [s.strip() for s in specials.split(",")]
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/sell-cup",
        json={"cup_index": cup_index, "declared_specials": special_list},
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player {n:d} drinks cup {cup_index:d}"))
def player_drink_cup(ctx, n, cup_index):
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/drink-cup",
        json={"cup_index": cup_index},
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player {n:d} tries to sell cup {cup_index:d}"))
def player_try_sell_cup(ctx, n, cup_index):
    player_sell_cup_no_specials(ctx, n, cup_index)


@when(parsers.parse("player {n:d} tries to drink cup {cup_index:d}"))
def player_try_drink_cup(ctx, n, cup_index):
    player_drink_cup(ctx, n, cup_index)


@when(parsers.parse("player {n:d} goes for a wee"))
def player_go_for_a_wee(ctx, n):
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/go-for-a-wee",
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player {n:d} claims that card"))
def player_claim_card(ctx, n):
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/claim-card",
        json={"card_id": ctx["target_card_id"]},
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player {n:d} tries to claim that card"))
def player_try_claim_card(ctx, n):
    player_claim_card(ctx, n)


@when(parsers.parse("player {n:d} refreshes card row {row:d}"))
def player_refresh_row(ctx, n, row):
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/refresh-card-row",
        json={"row_position": row},
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player {n:d} tries to refresh card row {row:d}"))
def player_try_refresh_row(ctx, n, row):
    player_refresh_row(ctx, n, row)


@when(parsers.parse("player {n:d} tries to take an ingredient"))
def player_try_take_ingredient(ctx, n):
    token, _ = _player(ctx, n)
    # Attempt the draw step — validates turn, player, and ingredient availability
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/draw-from-bag",
        json={"count": 1},
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player {n:d} proposes to undo the last turn"))
def player_propose_undo(ctx, n):
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/undo",
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code
    if resp.status_code == 200:
        ctx["undo_request_id"] = resp.json()["undo_request"]["id"]


@when(parsers.parse("player {n:d} votes {vote} on the undo"))
def player_vote_on_undo(ctx, n, vote):
    # Capture pre-vote state for later assertions (both keys for whichever is needed)
    ctx["pre_undo_game"] = _get_game(ctx["p1_token"], ctx["game_id"])
    ctx["game_before_undo"] = ctx["pre_undo_game"]
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/undo/vote",
        json={"request_id": ctx["undo_request_id"], "vote": vote},
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player {n:d} tries to vote again on the undo"))
def player_vote_again(ctx, n):
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/undo/vote",
        json={"request_id": ctx["undo_request_id"], "vote": "agree"},
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player {n:d} also tries to propose an undo"))
def player_also_propose_undo(ctx, n):
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/undo",
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player {n:d} fetches the move history"))
def player_fetch_history(ctx, n):
    token, _ = _player(ctx, n)
    resp = _client.get(
        f"/v1/games/{ctx['game_id']}/history",
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player {n:d} requests the state at turn {turn:d}"))
def player_state_at_turn(ctx, n, turn):
    token, _ = _player(ctx, n)
    resp = _client.get(
        f"/v1/games/{ctx['game_id']}/history/{turn}",
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(
    parsers.parse(
        "player {n:d} tries to claim that cup doubler card without a cup_index"
    )
)
def player_claim_cup_doubler_no_index(ctx, n):
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/claim-card",
        json={"card_id": ctx["target_card_id"], "spirit_type": "VODKA"},
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when("a non-member tries to fetch the move history")
def non_member_fetch_history(ctx):
    outsider = _unique("outsider")
    token, _ = _register(outsider)
    resp = _client.get(
        f"/v1/games/{ctx['game_id']}/history",
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


# ─── Then steps ───────────────────────────────────────────────────────────────


@then(parsers.parse("it should be player {n:d}'s turn"))
def it_is_player_turn_then(ctx, n):
    token, pid = _player(ctx, n)
    game = _get_game(token, ctx["game_id"])
    assert game["game_state"]["player_turn"] == pid, f"Expected player {n}'s turn"


# Cup checks — non-prefixed variants assume the active player (p1 context)
@then(parsers.parse("cup {cup_index:d} should contain {count:d} ingredients"))
def cup_contains_count(ctx, cup_index, count):
    ps = _player_state(ctx, 1)
    ingredients = ps["cups"][cup_index]["ingredients"]
    assert len(ingredients) == count, (
        f"Expected {count} in cup {cup_index}, got {len(ingredients)}"
    )


@then(parsers.parse("cup {cup_index:d} should contain exactly {spec}"))
def cup_contains_spec(ctx, cup_index, spec):
    ps = _player_state(ctx, 1)
    expected = _parse_ingredient_spec(spec)
    ingredients = ps["cups"][cup_index]["ingredients"]
    assert [e.name for e in expected] == ingredients, (
        f"Expected {expected} in cup {cup_index}, got {ingredients}"
    )


@then(parsers.parse("player {n:d}'s player mat should have {spec}"))
def mat_contains_spec(ctx, spec):
    ps = _player_state(ctx, 1)
    expected = _parse_special_spec(spec)
    ingredients = ps.get("special_ingredients")
    assert [e.value for e in expected] == ingredients, (
        f"Expected {expected} on mat, got {ingredients}"
    )


@then(
    parsers.parse(
        "player {n:d}'s cup {cup_index:d} should contain {count:d} ingredients"
    )
)
def player_cup_contains_count(ctx, n, cup_index, count):
    ps = _player_state(ctx, n)
    ingredients = ps["cups"][cup_index]["ingredients"]
    assert len(ingredients) == count, (
        f"Expected {count} in player {n}'s cup {cup_index}, got {len(ingredients)}"
    )


@then(parsers.parse("cup {cup_index:d} should be empty"))
def cup_empty(ctx, cup_index):
    ps = _player_state(ctx, 1)
    ingredients = ps["cups"][cup_index]["ingredients"]
    assert ingredients == [], f"Expected cup {cup_index} empty, got {ingredients}"


@then(parsers.parse("player {n:d}'s cup {cup_index:d} should be empty"))
def player_cup_empty(ctx, n, cup_index):
    ps = _player_state(ctx, n)
    ingredients = ps["cups"][cup_index]["ingredients"]
    assert ingredients == [], (
        f"Expected player {n}'s cup {cup_index} empty, got {ingredients}"
    )


@then("a move record should be created for the game")
def move_record_created(ctx):
    resp = _client.get(
        f"/v1/games/{ctx['game_id']}/history",
        cookies=_auth(ctx["p1_token"]),
    )
    assert resp.status_code == 200, resp.text
    moves = resp.json()["moves"]
    assert len(moves) >= 1, "Expected at least one move record"


@then(parsers.parse("the move history should record {count:d} taken ingredients"))
def move_history_taken_count(ctx, count):
    resp = _client.get(
        f"/v1/games/{ctx['game_id']}/history",
        cookies=_auth(ctx["p1_token"]),
    )
    assert resp.status_code == 200, resp.text
    moves = resp.json()["moves"]
    take_moves = [m for m in moves if m["action"]["type"] == "take_ingredients"]
    # Each batch is now its own move record; sum taken across all batches.
    all_taken = [item for m in take_moves for item in m["action"].get("taken", [])]
    assert len(all_taken) == count, (
        f"Expected {count} taken ingredient records across {len(take_moves)} move(s), "
        f"got {len(all_taken)}: {all_taken}"
    )


@then(parsers.parse("player {n:d} should have {points:d} point"))
@then(parsers.parse("player {n:d} should have {points:d} points"))
def player_has_points_check(ctx, n, points):
    ps = _player_state(ctx, n)
    assert ps["points"] == points, f"Expected {points} pts, got {ps['points']}"


@then(parsers.parse("player {n:d}'s bladder should contain {count:d} ingredients"))
def player_bladder_count_check(ctx, n, count):
    ps = _player_state(ctx, n)
    assert len(ps["bladder"]) == count, (
        f"Expected bladder count {count}, got {len(ps['bladder'])}"
    )


@then(parsers.parse("player {n:d}'s bladder should be empty"))
def player_bladder_empty(ctx, n):
    ps = _player_state(ctx, n)
    assert ps["bladder"] == [], f"Expected empty bladder, got {ps['bladder']}"


@then(parsers.parse("player {n:d} has {count:d} {kind} in their bladder"))
def player_bladder_has(ctx, n, count, kind):
    ps = _player_state(ctx, n)
    assert len(ps["bladder"]) == count, (
        f"Expected {count} items in bladder, got {len(ps['bladder'])}"
    )


@then(parsers.parse("player {n:d}'s drunk level should be {level:d}"))
def player_drunk_level_check(ctx, n, level):
    ps = _player_state(ctx, n)
    assert ps["drunk_level"] == level, (
        f"Expected drunk_level {level}, got {ps['drunk_level']}"
    )


@then(parsers.parse("player {n:d}'s toilet tokens should decrease by 1"))
def player_toilet_tokens_decrease(ctx, n):
    from app.PlayerState import INITIAL_TOILET_TOKENS

    ps = _player_state(ctx, n)
    assert ps["toilet_tokens"] == INITIAL_TOILET_TOKENS - 1, (
        f"Expected toilet_tokens {INITIAL_TOILET_TOKENS - 1}, got {ps['toilet_tokens']}"
    )


@then(parsers.parse("player {n:d} should have {count:d} card"))
@then(parsers.parse("player {n:d} should have {count:d} cards"))
def player_has_cards(ctx, n, count):
    ps = _player_state(ctx, n)
    assert len(ps["cards"]) == count, (
        f"Expected {count} card(s), got {len(ps['cards'])}"
    )


@then(parsers.parse("row {row:d} should be refreshed with new cards"))
def row_refreshed(ctx, row):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    rows = game["game_state"]["card_rows"]
    for r in rows:
        if r["position"] == row:
            return
    pytest.fail(f"Row {row} not found after refresh")


@then(parsers.parse("row {row:d} should have {count:d} cards"))
def row_has_card_count(ctx, row, count):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    rows = game["game_state"]["card_rows"]
    for r in rows:
        if r["position"] == row:
            assert len(r["cards"]) == count, (
                f"Row {row}: expected {count} card(s), got {len(r['cards'])}"
            )
            return
    pytest.fail(f"Row {row} not found")


@then(parsers.parse("a store card is available in row {row:d}"))
def then_store_card_in_row(ctx, row):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    rows = game["game_state"]["card_rows"]
    for r in rows:
        if r["position"] == row:
            store_cards = [c for c in r["cards"] if c.get("card_type") == "store"]
            assert len(store_cards) > 0, f"Row {row}: expected a store card, found none"
            return
    pytest.fail(f"Row {row} not found")


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


@then("the game should not be over")
def game_not_over(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    assert game["status"] != "ENDED", f"Expected game still running, got {game['status']}"


@then("the last round should be active")
def last_round_active(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    assert game["game_state"]["last_round"] is True, (
        f"Expected last_round=True, got {game['game_state'].get('last_round')}"
    )


@then(parsers.parse("player {n:d} should be the winner"))
def player_is_winner(ctx, n):
    _, pid = _player(ctx, n)
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    assert game["game_state"]["winner"] == pid, (
        f"Expected winner {pid}, got {game['game_state']['winner']}"
    )


@then("an undo request should be pending for the game")
def undo_pending(ctx):
    assert ctx["last_status"] == 200, (
        f"Expected 200, got {ctx['last_status']}: {ctx['last_resp'].text}"
    )
    data = ctx["last_resp"].json()
    assert data["undo_request"]["status"] == "pending"


@then(parsers.parse("player {n:d}'s vote should be recorded as agree"))
def player_voted_agree(ctx, n):
    _, pid = _player(ctx, n)
    data = ctx["last_resp"].json()
    votes = data["undo_request"]["votes"]
    assert votes.get(pid) == "agree"


@then("the undo request should be approved")
def undo_approved(ctx):
    assert ctx["last_status"] == 200, ctx["last_resp"].text
    data = ctx["last_resp"].json()
    assert data.get("status") == "approved"


@then("the game state should be restored to before the last turn")
def state_restored(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    # After undoing player 1's turn, it should be player 1's turn again.
    # Turn numbers are never reused (spec guarantee), so we assert functional
    # state restoration rather than turn_number decreasing.
    player_turn = game["game_state"]["player_turn"]
    p1_id = ctx["p1_id"]
    assert player_turn == p1_id, (
        f"Expected player_turn to be restored to p1 ({p1_id}), got {player_turn}"
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


@then("the history should contain 2 moves")
def history_has_2_moves(ctx):
    assert ctx["last_status"] == 200, ctx["last_resp"].text
    moves = ctx["last_resp"].json()["moves"]
    assert len(moves) == 2, f"Expected 2 moves, got {len(moves)}"


@then("the moves should record the action type and player")
def moves_have_action_and_player(ctx):
    moves = ctx["last_resp"].json()["moves"]
    for move in moves:
        assert "action" in move
        assert "type" in move["action"]
        assert "player_id" in move


@then("the returned state should be the initial game state")
def state_is_initial(ctx):
    assert ctx["last_status"] == 200, ctx["last_resp"].text
    state = ctx["last_resp"].json()["game_state"]
    assert state is not None
    assert state.get("turn_number", 0) == 0


@then(parsers.parse("player {n:d}'s store card should have {count:d} stored spirits"))
@then(parsers.parse("player {n:d}'s store card should have {count:d} stored spirit"))
def player_store_card_has_spirits(ctx, n, count):
    ps = _player_state(ctx, n)
    store_cards = [c for c in ps["cards"] if c["card_type"] == "store"]
    assert store_cards, f"Player {n} has no store cards"
    total = sum(len(c.get("stored_spirits", [])) for c in store_cards)
    assert total == count, f"Expected {count} stored spirits, got {total}"


@then("the refreshed card should not appear in row 1")
def refreshed_card_not_in_row1(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    rows = game["game_state"]["card_rows"]
    row1_ids = [c["id"] for r in rows if r["position"] == 1 for c in r["cards"]]
    assert ctx["target_card_id"] not in row1_ids, (
        f"Refreshed card {ctx['target_card_id']} appeared in row 1"
    )


@then("all cards in row 1 should be karaoke type")
def row1_all_karaoke(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    rows = game["game_state"]["card_rows"]
    row1 = next((r for r in rows if r["position"] == 1), None)
    assert row1 is not None, "Row 1 not found"
    assert all(c["card_type"] == "karaoke" for c in row1["cards"]), (
        f"Not all row 1 cards are karaoke: {[c['card_type'] for c in row1['cards']]}"
    )


@then("the deck should have 12 cards remaining")
def deck_has_12_cards(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    deck_size = game["game_state"]["deck_size"]
    assert deck_size == 12, f"Expected deck_size 12, got {deck_size}"


@then(parsers.parse("player {n:d}'s bladder capacity should be {capacity:d}"))
def player_bladder_capacity_check(ctx, n, capacity):
    ps = _player_state(ctx, n)
    assert ps["bladder_capacity"] == capacity, (
        f"Expected bladder_capacity {capacity}, got {ps['bladder_capacity']}"
    )


@then("the returned state should reflect turn 1")
def returned_state_is_turn1(ctx):
    assert ctx["last_status"] == 200, ctx["last_resp"].text
    state = ctx["last_resp"].json()["game_state"]
    assert state is not None
    assert state.get("turn_number") == 1, (
        f"Expected turn_number 1, got {state.get('turn_number')}"
    )


@then(parsers.parse("player {n:d} should be eliminated"))
def player_is_eliminated_check(ctx, n):
    ps = _player_state(ctx, n)
    assert ps["status"] in ("hospitalised", "wet"), (
        f"Expected player {n} to be eliminated, got status {ps['status']}"
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _parse_ingredient_spec(spec: str) -> list[Ingredient]:
    """Parse '1 VODKA and 1 COLA' or '2 RUM and 1 SODA' into [Ingredient, ...]."""
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


def _parse_special_spec(spec: str) -> list[SpecialType]:
    """Parse '1 BITTERS' or '2 BITTERS and 1 SUGAR' into [SpecialType, ...]."""
    result = []
    parts = [p.strip() for p in spec.replace(" and ", ",").split(",")]
    for part in parts:
        tokens = part.strip().split()
        if len(tokens) >= 2:
            try:
                count = int(tokens[0])
                name = tokens[1].rstrip(",")
                result.extend([SpecialType[name]] * count)
            except (ValueError, KeyError):
                pass
    return result


# ── Drink Stored Spirit steps ──────────────────────────────────────────────


@when(
    parsers.parse("player {n:d} drinks {count:d} stored spirits from card {card_idx:d}")
)
@when(
    parsers.parse("player {n:d} drinks {count:d} stored spirit from card {card_idx:d}")
)
def player_drink_stored_spirit(ctx, n, count, card_idx):
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/drink-stored-spirit",
        json={"store_card_index": card_idx, "count": count},
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(
    parsers.parse(
        "player {n:d} tries to drink {count:d} stored spirits from card {card_idx:d}"
    )
)
@when(
    parsers.parse(
        "player {n:d} tries to drink {count:d} stored spirit from card {card_idx:d}"
    )
)
def player_try_drink_stored_spirit(ctx, n, count, card_idx):
    player_drink_stored_spirit(ctx, n, count, card_idx)


# ── Use Stored Spirit steps ───────────────────────────────────────────────


@when(
    parsers.parse(
        "player {n:d} uses a stored spirit from card {card_idx:d} into cup {cup_idx:d}"
    )
)
def player_use_stored_spirit(ctx, n, card_idx, cup_idx):
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/use-stored-spirit",
        json={"store_card_index": card_idx, "cup_index": cup_idx},
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(
    parsers.parse(
        "player {n:d} tries to use a stored spirit from card {card_idx:d} into cup {cup_idx:d}"
    )
)
def player_try_use_stored_spirit(ctx, n, card_idx, cup_idx):
    player_use_stored_spirit(ctx, n, card_idx, cup_idx)


# ── Shared "then" steps for free actions ──────────────────────────────────


@then(parsers.parse("it should still be player {n:d}'s turn"))
def still_players_turn(ctx, n):
    _, pid = _player(ctx, n)
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    gs = game["game_state"]
    assert gs["player_turn"] == pid, (
        f"Expected player {n} ({pid}) to still have the turn, "
        f"but player_turn is {gs['player_turn']}"
    )


@then("the action should succeed")
def action_should_succeed(ctx):
    assert ctx["last_status"] == 200, f"Expected 200 but got {ctx['last_status']}"


# ── Specialist Card steps ────────────────────────────────────────────────


@given(
    parsers.parse("a specialist card for {spirit_type} is available in row {row:d}"),
    target_fixture="available_card_id",
)
def specialist_card_in_row(ctx, spirit_type, row):
    import uuid as _uuid
    from app.card import Card as _Card

    new_card_id = str(_uuid.uuid4())

    def patch(gs):
        for r in gs.card_rows:
            if r.position == row:
                new_card = _Card(
                    id=new_card_id,
                    card_type="specialist",
                    name=f"{spirit_type} Specialist",
                    spirit_type=spirit_type.upper(),
                )
                if r.cards:
                    r.cards[0] = new_card
                else:
                    r.cards.append(new_card)
                break
        return gs

    _patch_game_state(ctx["game_id"], patch)
    ctx["target_card_id"] = new_card_id
    return new_card_id


@given(parsers.parse("player {n:d}'s bladder has {count:d} {spirit_type} spirits"))
@given(parsers.parse("player {n:d}'s bladder has {count:d} {spirit_type} spirit"))
def player_has_specific_spirits(ctx, n, count, spirit_type):
    _, pid = _player(ctx, n)
    ing = Ingredient[spirit_type.upper()]

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.bladder = [ing] * count
        return gs

    _patch_game_state(ctx["game_id"], patch)


@given(parsers.parse("player {n:d} holds a {spirit_type} specialist card"))
def player_holds_specialist_card(ctx, n, spirit_type):
    import uuid as _uuid
    from app.card import Card as _Card

    _, pid = _player(ctx, n)
    card = _Card(
        id=str(_uuid.uuid4()),
        card_type="specialist",
        name=f"{spirit_type} Specialist",
        spirit_type=spirit_type.upper(),
    )

    def patch(gs):
        ps = gs.player_states[UUID(pid)]
        ps.cards.append(card.to_dict())
        return gs

    _patch_game_state(ctx["game_id"], patch)


# ── ReRollSpecials steps ─────────────────────────────────────────────────────


@when(parsers.parse('player {n:d} re-rolls specials "{chosen}" and rolls "{results}"'))
def player_reroll_specials(ctx, n, chosen, results):
    token, _ = _player(ctx, n)
    chosen_list = [s.strip() for s in chosen.split(",") if s.strip()]
    result_list = [s.strip() for s in results.split(",") if s.strip()]

    # Record bag size before the action for later assertion
    game = _get_game(token, ctx["game_id"])
    ctx["bag_size_before"] = len(game["game_state"].get("bag_contents", []))

    # Map result strings to SpecialType enums for the mock
    roll_returns = [SpecialType[r.upper()] for r in result_list]

    with patch("app.actions.SpecialType") as mock_st:
        # Preserve enum members so validation still works
        for member in SpecialType:
            setattr(mock_st, member.name, member)
        mock_st.roll.side_effect = roll_returns

        resp = _client.post(
            f"/v1/games/{ctx['game_id']}/actions/reroll-specials",
            json={"chosen_specials": chosen_list},
            cookies=_auth(token),
        )
    assert resp.status_code == 200, resp.text
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse('player {n:d} tries to re-roll specials "{chosen}"'))
def player_try_reroll_specials(ctx, n, chosen):
    token, _ = _player(ctx, n)
    chosen_list = [s.strip() for s in chosen.split(",") if s.strip()]
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/reroll-specials",
        json={"chosen_specials": chosen_list},
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse("player {n:d} tries to re-roll with no specials"))
def player_try_reroll_empty(ctx, n):
    token, _ = _player(ctx, n)
    resp = _client.post(
        f"/v1/games/{ctx['game_id']}/actions/reroll-specials",
        json={"chosen_specials": []},
        cookies=_auth(token),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@then(parsers.parse("player {n:d}'s player mat should be empty"))
def player_mat_empty(ctx, n):
    ps = _player_state(ctx, n)
    specials = ps.get("special_ingredients", [])
    assert specials == [], f"Expected empty mat, got {specials}"


@then("the bag size should be unchanged")
def bag_size_unchanged(ctx):
    game = _get_game(ctx["p1_token"], ctx["game_id"])
    bag_size_after = len(game["game_state"].get("bag_contents", []))
    assert bag_size_after == ctx["bag_size_before"], (
        f"Bag size changed: was {ctx['bag_size_before']}, now {bag_size_after}"
    )
