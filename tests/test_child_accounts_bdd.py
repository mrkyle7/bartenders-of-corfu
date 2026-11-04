"""BDD tests for child accounts: made by a parent, played by switching."""

import uuid

from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from tests.accounts import register
from app.api import app

scenarios("features/child_accounts.feature")

_client = TestClient(app)
PASSWORD = "Password1"


def _player(name: str) -> dict:
    username = f"kid_{name.lower()}_{uuid.uuid4().hex[:6]}"
    resp = register(_client, username, f"{username}@example.com", PASSWORD)
    assert resp.status_code == 200, resp.text
    return {
        "username": username,
        "id": resp.json()["id"],
        "cookie": resp.cookies["userjwt"],
    }


def _post(cookie, path, body):
    return _client.post(path, json=body, cookies={"userjwt": cookie})


def _make_child(ctx, parent, name):
    unique = f"{name} {uuid.uuid4().hex[:6]}"
    resp = _post(ctx[parent]["cookie"], "/v1/family/child", {"name": unique})
    assert resp.status_code == 200, resp.text
    child = next(c for c in resp.json()["children"] if c["name"] == unique)
    ctx[name] = {"username": unique, "id": child["id"], "managed": child.get("managed")}


@given(parsers.parse('a parent "{name}"'), target_fixture="ctx")
def a_parent(name):
    return {name: _player(name), "resp": None, "cookie": None}


@given(parsers.parse('another player "{name}"'))
def another_player(ctx, name):
    ctx[name] = _player(name)


@given(parsers.parse('"{parent}" made a child account called "{name}"'))
@when(parsers.parse('"{parent}" makes a child account called "{name}"'))
def make_child(ctx, parent, name):
    _make_child(ctx, parent, name)


@then(parsers.parse('"{parent}" has the child account "{name}"'))
def has_child(ctx, parent, name):
    resp = _client.get(
        "/v1/family/children", cookies={"userjwt": ctx[parent]["cookie"]}
    )
    assert {"id": ctx[name]["id"], "name": ctx[name]["username"]} in resp.json()[
        "children"
    ]
    assert ctx[name]["managed"] is True


@when(parsers.parse('"{who}" switches to "{name}"'))
def switch(ctx, who, name):
    ctx["resp"] = _post(
        ctx[who]["cookie"], "/v1/family/switch", {"id": ctx[name]["id"]}
    )
    if ctx["resp"].status_code == 200:
        ctx["cookie"] = ctx["resp"].cookies["userjwt"]


@then(parsers.parse('the login cookie is "{name}"\'s, played for "{parent}"'))
def cookie_is_childs(ctx, name, parent):
    assert ctx["resp"].status_code == 200, ctx["resp"].text
    me = _client.get("/userDetails", cookies={"userjwt": ctx["cookie"]}).json()
    assert me["id"] == ctx[name]["id"]
    assert me["managed"] is True
    assert me["parent"]["id"] == ctx[parent]["id"]
    assert me["parent"]["has_password"] is True
    assert me["parent"]["google"] is False


@then(parsers.parse('as "{name}" they can\'t change the password'))
def no_password_change(ctx, name):
    resp = _client.patch(
        "/v1/users/me/password",
        json={"old_password": "x", "new_password": "Password2"},
        cookies={"userjwt": ctx["cookie"]},
    )
    assert resp.status_code == 403


@when(parsers.parse('they switch back with the password "{password}"'))
def switch_back_with(ctx, password):
    ctx["resp"] = _post(ctx["cookie"], "/v1/family/switch-back", {"password": password})


@when(parsers.parse('they switch back with "{parent}"\'s password'))
def switch_back(ctx, parent):
    ctx["resp"] = _post(ctx["cookie"], "/v1/family/switch-back", {"password": PASSWORD})
    if ctx["resp"].status_code == 200:
        ctx["cookie"] = ctx["resp"].cookies["userjwt"]


@then("the switch back is refused")
def switch_back_refused(ctx):
    assert ctx["resp"].status_code == 400


@then(parsers.parse('the login cookie is "{parent}"\'s own'))
def cookie_is_parents(ctx, parent):
    assert ctx["resp"].status_code == 200, ctx["resp"].text
    me = _client.get("/userDetails", cookies={"userjwt": ctx["cookie"]}).json()
    assert me["id"] == ctx[parent]["id"]
    assert "parent" not in me


@then(parsers.parse('nobody can sign in as "{name}"'))
def no_sign_in(ctx, name):
    for password in ("", PASSWORD, "None"):
        resp = _client.post(
            "/login", json={"username": ctx[name]["username"], "password": password}
        )
        assert resp.status_code in (400, 401)


@then("the switch is refused")
def switch_refused(ctx):
    assert ctx["resp"].status_code == 400
