"""BDD tests for families: parents seeing how their children are doing."""

import uuid

from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from app.api import app
from tests.accounts import register

scenarios("features/family.feature")

_client = TestClient(app)


def _player(name: str) -> dict:
    username = f"fam_{name.lower()}_{uuid.uuid4().hex[:6]}"
    email = f"{username}@example.com"
    resp = register(_client, username, email)
    assert resp.status_code == 200, resp.text
    return {
        "username": username,
        "email": email,
        "id": resp.json()["id"],
        "cookie": resp.cookies["userjwt"],
    }


def _get(ctx, name, path):
    return _client.get(path, cookies={"userjwt": ctx[name]["cookie"]})


def _post(ctx, name, path, body):
    ctx["resp"] = _client.post(
        path, json=body, cookies={"userjwt": ctx[name]["cookie"]}
    )
    return ctx["resp"]


def _names(ctx, people):
    by_id = {p["id"]: n for n, p in ctx.items() if isinstance(p, dict) and "id" in p}
    return [by_id.get(p["id"]) for p in people]


# ── Steps ──────────────────────────────────────────────────────


@given(parsers.parse('a parent "{parent}" and a child "{child}"'), target_fixture="ctx")
def parent_and_child(parent, child):
    return {parent: _player(parent), child: _player(child), "resp": None}


@given(parsers.parse('another player "{name}"'))
def another_player(ctx, name):
    ctx[name] = _player(name)


@when(parsers.parse('"{parent}" asks for "{child}" by email'))
def ask_for(ctx, parent, child):
    assert (
        _post(
            ctx, parent, "/v1/family/ask", {"email": ctx[child]["email"].upper()}
        ).status_code
        == 200
    )


@when(parsers.parse('"{parent}" asks for the email "{email}"'))
def ask_for_email(ctx, parent, email):
    _post(ctx, parent, "/v1/family/ask", {"email": email})


@when(parsers.parse('"{child}" says yes to "{parent}"'))
def say_yes(ctx, child, parent):
    _post(ctx, child, "/v1/family/answer", {"parent": ctx[parent]["id"], "allow": True})


@when(parsers.parse('"{child}" says no to "{parent}"'))
def say_no(ctx, child, parent):
    _post(
        ctx, child, "/v1/family/answer", {"parent": ctx[parent]["id"], "allow": False}
    )


@when(parsers.parse('"{child}" stops sharing with "{parent}"'))
def stop_sharing(ctx, child, parent):
    assert (
        _post(ctx, child, "/v1/family/remove", {"id": ctx[parent]["id"]}).status_code
        == 200
    )


@when("someone signed out asks for their family")
def signed_out(ctx):
    # A client of its own: the shared one keeps the cookies from signing in.
    ctx["resp"] = TestClient(app).get("/v1/family")


@then(parsers.parse("the response status should be {status:d}"))
def status_is(ctx, status):
    assert ctx["resp"].status_code == status, ctx["resp"].text


@then(parsers.parse('"{parent}" has no children'))
def no_children(ctx, parent):
    assert _get(ctx, parent, "/v1/family").json()["children"] == []


@then(parsers.parse('"{parent}" is asking for nobody'))
def asking_nobody(ctx, parent):
    assert _get(ctx, parent, "/v1/family").json()["asked"] == []


@then(parsers.parse('"{child}" sees "{parent}" asking'))
def sees_asking(ctx, child, parent):
    assert _names(ctx, _get(ctx, child, "/v1/family").json()["requests"]) == [parent]


@then(parsers.parse('"{parent}" has the child "{child}"'))
def has_child(ctx, parent, child):
    assert _names(ctx, _get(ctx, parent, "/v1/family").json()["children"]) == [child]


@then(parsers.parse('"{child}" has the parent "{parent}"'))
def has_parent(ctx, child, parent):
    assert _names(ctx, _get(ctx, child, "/v1/family").json()["parents"]) == [parent]


@then(parsers.parse('a game asking with "{parent}"\'s cookie hears of "{child}"'))
def game_hears(ctx, parent, child):
    kids = _get(ctx, parent, "/v1/family/children").json()["children"]
    assert kids == [{"id": ctx[child]["id"], "name": ctx[child]["username"]}]
