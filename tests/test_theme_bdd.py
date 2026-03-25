"""BDD tests for the color theme feature."""

import uuid

from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from app.api import app

scenarios("features/theme.feature")

_client = TestClient(app)
_counter = 0


def _unique(prefix: str) -> str:
    global _counter
    _counter += 1
    return f"{prefix}_{uuid.uuid4().hex[:8]}_{_counter}"


def _register(username: str) -> tuple[str, str]:
    resp = _client.post(
        "/register",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "Password1",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.cookies["userjwt"], resp.json()["id"]


def _auth(token: str) -> dict:
    return {"userjwt": token}


# ── Steps ──────────────────────────────────────────────────────


@given("a registered user", target_fixture="ctx")
def registered_user():
    username = _unique("theme_user")
    token, user_id = _register(username)
    return {
        "p1_token": token,
        "p1_id": user_id,
        "last_resp": None,
        "last_status": None,
    }


@when(parsers.parse('the user changes their theme to "{theme}"'))
def change_theme(ctx, theme):
    resp = _client.patch(
        "/v1/users/me/theme",
        json={"theme": theme},
        cookies=_auth(ctx["p1_token"]),
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when("the user fetches their details")
def fetch_user_details(ctx):
    resp = _client.get("/userDetails", cookies=_auth(ctx["p1_token"]))
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@when(parsers.parse('an unauthenticated user changes their theme to "{theme}"'))
def change_theme_unauthenticated(ctx, theme):
    resp = _client.patch(
        "/v1/users/me/theme",
        json={"theme": theme},
    )
    ctx["last_resp"] = resp
    ctx["last_status"] = resp.status_code


@then(parsers.parse("the response status should be {code:d}"))
def response_status(ctx, code):
    assert ctx["last_status"] == code, (
        f"Expected {code}, got {ctx['last_status']}: "
        f"{ctx['last_resp'].text if ctx['last_resp'] else 'no response'}"
    )


@then(parsers.parse('the response should confirm the theme is "{theme}"'))
def response_confirms_theme(ctx, theme):
    data = ctx["last_resp"].json()
    assert data["message"] == "Theme updated successfully"
    assert data["theme"] == theme


@then(parsers.parse('the user details should show the theme as "{theme}"'))
def user_details_theme(ctx, theme):
    assert ctx["last_status"] == 200, ctx["last_resp"].text
    data = ctx["last_resp"].json()
    assert data["theme"] == theme, (
        f"Expected theme '{theme}', got '{data.get('theme')}'"
    )
