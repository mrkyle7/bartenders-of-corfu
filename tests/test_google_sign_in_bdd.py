"""BDD tests for signing in with Google, end to end through the API.

Google's tokens are made here with a test key that stands in for Google's.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from app import google_sign_in
from app.api import app
from tests.test_google_sign_in import CLIENT_ID, _KEY, google_token

scenarios("features/google_sign_in.feature")

_client = TestClient(app)


@pytest.fixture(autouse=True)
def google(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(google_sign_in, "_signing_key", lambda _t: _KEY.public_key())


@pytest.fixture
def ctx():
    unique = uuid.uuid4().hex[:10]
    return {
        "sub": f"google-{unique}",
        "email": f"google_{unique}@example.com",
        "unique": unique,
        "resp": None,
    }


def _sign_in(ctx, **claims):
    claims.setdefault("sub", ctx["sub"])
    claims.setdefault("email", ctx["email"])
    ctx["resp"] = _client.post(
        "/v1/auth/google", json={"credential": google_token(**claims)}
    )
    return ctx["resp"]


def _details(cookie: str) -> dict:
    resp = _client.get("/userDetails", cookies={"userjwt": cookie})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Given ──────────────────────────────────────────────────────


@given("Google sign-in is not set up")
def not_set_up(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID")


@given("a player has signed in with Google before")
def signed_in_before(ctx):
    resp = _sign_in(ctx, name=f"Grace {ctx['unique']}")
    assert resp.status_code == 201, resp.text
    ctx["first_id"] = resp.json()["id"]


@given(parsers.parse('a registered player with password "{password}"'))
def registered(ctx, password):
    username = f"reg_{ctx['unique']}"
    resp = _client.post(
        "/register",
        json={"username": username, "email": ctx["email"], "password": password},
    )
    assert resp.status_code == 201, resp.text
    ctx["username"] = username
    ctx["registered_id"] = resp.json()["id"]
    ctx["registered_cookie"] = resp.cookies["userjwt"]


# ── When ───────────────────────────────────────────────────────


@when(parsers.parse('a new player signs in with Google as "{name}"'))
def new_player(ctx, name):
    _sign_in(ctx, name=name, given_name=None)


@when("the player signs in with Google")
@when("the player signs in with Google using the same email")
def same_email(ctx):
    _sign_in(ctx)


@when("the player signs in with Google using the same email in capitals")
def same_email_capitals(ctx):
    _sign_in(ctx, email=ctx["email"].upper())


@when("someone signs in with Google using the same email, unverified")
def unverified(ctx):
    _sign_in(ctx, email_verified=False)


@when("someone signs in with a Google token made for another app")
def another_app(ctx):
    _sign_in(ctx, aud="another-app.apps.googleusercontent.com")


# ── Then ───────────────────────────────────────────────────────


@then(parsers.parse("the response status should be {status:d}"))
def status_is(ctx, status):
    assert ctx["resp"].status_code == status, ctx["resp"].text


@then("the player is signed in")
def signed_in(ctx):
    cookie = ctx["resp"].cookies.get("userjwt")
    assert cookie
    assert _details(cookie)["id"] == ctx["resp"].json()["id"]


@then("the player is not signed in")
def not_signed_in(ctx):
    assert "userjwt" not in ctx["resp"].cookies


@then("the account is new")
def is_new(ctx):
    assert ctx["resp"].json()["created"] is True


@then("the account has the Google email")
def has_email(ctx):
    details = _details(ctx["resp"].cookies["userjwt"])
    assert details["email"] == ctx["email"]
    assert details["username"].startswith("Ada Lovelace")


@then("the account has no password")
def no_password(ctx):
    details = _details(ctx["resp"].cookies["userjwt"])
    assert details["has_password"] is False
    assert details["google_linked"] is True
    resp = _client.post(
        "/login", json={"username": details["username"], "password": ""}
    )
    assert resp.status_code == 401


@then("it is the same account as before")
def same_account(ctx):
    assert ctx["resp"].json()["id"] == ctx["first_id"]
    assert ctx["resp"].json()["created"] is False


@then("it is the registered player's account")
def registered_account(ctx):
    assert ctx["resp"].status_code == 200, ctx["resp"].text
    assert ctx["resp"].json()["id"] == ctx["registered_id"]
    assert ctx["resp"].json()["created"] is False


@then(parsers.parse('the player can still log in with "{password}"'))
def password_works(ctx, password):
    resp = _client.post(
        "/login", json={"username": ctx["username"], "password": password}
    )
    assert resp.status_code == 200, resp.text


@then("the player's account is linked to Google")
def linked(ctx):
    details = _details(ctx["registered_cookie"])
    assert details["google_linked"] is True
    assert details["has_password"] is True


@then("the player's account is not linked to Google")
def not_linked(ctx):
    assert _details(ctx["registered_cookie"])["google_linked"] is False
