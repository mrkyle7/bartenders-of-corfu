"""BDD tests for signing in on the shared cheetahmoongames.com page."""

import uuid

import jwt
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from app.api import app

scenarios("features/shared_login.feature")

_client = TestClient(app, base_url="http://bartenders.cheetahmoongames.com")
_HTTPS = {"x-forwarded-proto": "https"}


def _register() -> str:
    username = f"shared_{uuid.uuid4().hex[:8]}"
    resp = _client.post(
        "/register",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "Password1",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.cookies["userjwt"]


# ── Steps ──────────────────────────────────────────────────────


@given(parsers.parse('the shared sign-in page is "{url}"'))
def shared_sign_in(monkeypatch, url):
    monkeypatch.setenv("LOGIN_URL", url)


@given("there is no shared sign-in page")
def no_shared_sign_in(monkeypatch):
    monkeypatch.delenv("LOGIN_URL", raising=False)


@given("there is no shared profile page")
def no_shared_profile(monkeypatch):
    monkeypatch.delenv("PROFILE_URL", raising=False)


@given("a registered user", target_fixture="ctx")
def registered_user():
    return {"token": _register()}


@when("a player opens the login page", target_fixture="resp")
def open_login():
    return _client.get("/login", headers=_HTTPS, follow_redirects=False)


@when(
    parsers.parse('a player is sent to the login page from "{referer}"'),
    target_fixture="resp",
)
def open_login_from(referer):
    return _client.get(
        "/login", headers={**_HTTPS, "referer": referer}, follow_redirects=False
    )


@when(
    parsers.parse('a player opens the login page with next "{next_path}"'),
    target_fixture="resp",
)
def open_login_next(next_path):
    return _client.get(
        "/login", params={"next": next_path}, headers=_HTTPS, follow_redirects=False
    )


@when("a player opens the profile page", target_fixture="resp")
def open_profile():
    return _client.get("/profile", headers=_HTTPS, follow_redirects=False)


@when(
    "a game fetches the public key for the user's login cookie", target_fixture="resp"
)
def fetch_key_for_cookie(ctx):
    kid = jwt.decode(ctx["token"], options={"verify_signature": False})["kid"]
    return _client.get(f"/v1/auth/keys/{kid}")


@when(parsers.parse('a game fetches the public key "{kid}"'), target_fixture="resp")
def fetch_key(kid):
    return _client.get(f"/v1/auth/keys/{kid}")


@then(parsers.parse('they are redirected to "{location}"'))
def redirected(resp, location):
    assert resp.status_code == 302
    assert resp.headers["location"] == location


@then(parsers.parse("the response status should be {status:d}"))
def status_is(resp, status):
    assert resp.status_code == status


@then("the key verifies the user's login cookie")
def key_verifies(resp, ctx):
    body = resp.json()
    assert body["alg"] == "RS256"
    claims = jwt.decode(ctx["token"], body["pem"], algorithms=["RS256"])
    assert claims["kid"] == body["kid"]
