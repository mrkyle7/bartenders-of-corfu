"""BDD tests for verifying a player's email, end to end through the API."""

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from app import email_sender, email_verification
from app.api import app
from app.db import db
from tests.accounts import register

scenarios("features/email_verification.feature")

_client = TestClient(app)
PASSWORD = "Password1"


@pytest.fixture
def ctx(monkeypatch):
    sent = []

    def fake_send(to_email, to_name, subject, html, text):
        sent.append({"to": to_email, "subject": subject, "html": html, "text": text})
        return True

    monkeypatch.setattr(email_sender, "send_email", fake_send)
    unique = uuid.uuid4().hex[:10]
    return {
        "unique": unique,
        "username": f"verify_{unique}",
        "email": f"verify_{unique}@example.com",
        "outbox": sent,
        "before": 0,
        "resp": None,
        "cookie": None,
    }


def _address(ctx, label: str) -> str:
    return f"{label}_{ctx['unique']}@example.com"


def _verification_emails(ctx, to: str | None = None) -> list[dict]:
    return [
        m
        for m in ctx["outbox"]
        if m["subject"] == "Verify your Cheetah Moon email"
        and (to is None or m["to"] == to)
    ]


def _token(mail: dict) -> str:
    return re.search(r"token=([A-Za-z0-9_\-]+)", mail["text"]).group(1)


def _confirm(ctx, token: str):
    ctx["resp"] = _client.post("/v1/auth/verify-email/confirm", json={"token": token})
    return ctx["resp"]


def _log_in(ctx, password: str = PASSWORD):
    return _client.post(
        "/login", json={"username": ctx["username"], "password": password}
    )


def _register(ctx, next_url: str | None = None):
    body = {"username": ctx["username"], "email": ctx["email"], "password": PASSWORD}
    if next_url:
        body["next"] = next_url
    ctx["resp"] = _client.post("/register", json=body)
    return ctx["resp"]


def _change_email(ctx, email: str):
    ctx["before"] = len(ctx["outbox"])
    ctx["resp"] = _client.patch(
        "/v1/users/me/email",
        json={"new_email": email},
        cookies={"userjwt": ctx["cookie"]},
    )
    return ctx["resp"]


def _email_now(ctx) -> str:
    resp = _client.get("/userDetails", cookies={"userjwt": ctx["cookie"]})
    assert resp.status_code == 200, resp.text
    return resp.json()["email"]


# ── Given ──────────────────────────────────────────────────────


@given("a player has registered")
def registered(ctx):
    assert _register(ctx).status_code == 201, ctx["resp"].text
    ctx["before"] = len(ctx["outbox"])


@given("a verified player is signed in")
def verified_and_signed_in(ctx):
    resp = register(_client, ctx["username"], ctx["email"], PASSWORD)
    assert resp.status_code == 200, resp.text
    ctx["cookie"] = resp.cookies["userjwt"]
    ctx["outbox"].clear()


@given("the player has used the link")
def used_link(ctx):
    assert _confirm(ctx, _token(ctx["outbox"][-1])).status_code == 200


@given("the link has expired")
def expire(ctx):
    token = _token(ctx["outbox"][-1])
    (
        db.supabase.table("email_verifications")
        .update(
            {
                "expires_at": (
                    datetime.now(timezone.utc) - timedelta(minutes=1)
                ).isoformat()
            }
        )
        .eq("token_hash", email_verification._hash(token))
        .execute()
    )


@given("the player has asked to change their email to a new address")
def asked_change(ctx):
    assert _change_email(ctx, _address(ctx, "new")).status_code == 200


@given("the player has asked to change their email to a second new address")
def asked_second_change(ctx):
    assert _change_email(ctx, _address(ctx, "second")).status_code == 200


@given("the player has used the second link")
def used_second(ctx):
    mail = _verification_emails(ctx, _address(ctx, "second"))[-1]
    assert _confirm(ctx, _token(mail)).status_code == 200


@given(parsers.parse('another player uses the address "{label}"'))
def other_player(ctx, label):
    other = f"other_{ctx['unique']}"
    resp = register(_client, other, _address(ctx, label), PASSWORD)
    assert resp.status_code == 200, resp.text
    ctx["outbox"].clear()


# ── When ───────────────────────────────────────────────────────


@when(parsers.parse('a player registers returning to "{next_url}"'))
def registers(ctx, next_url):
    _register(ctx, next_url)


@when("the player logs in with their password")
def logs_in(ctx):
    ctx["resp"] = _log_in(ctx)


@when(parsers.parse('the player logs in with the password "{password}"'))
def logs_in_with(ctx, password):
    ctx["resp"] = _log_in(ctx, password)


@when(parsers.parse("the player logs in with their password {n:d} times"))
def logs_in_many(ctx, n):
    for _ in range(n):
        ctx["resp"] = _log_in(ctx)


@when("the player uses the link")
def uses_link(ctx):
    _confirm(ctx, _token(_verification_emails(ctx)[-1]))


@when("the player uses the first link")
def uses_first(ctx):
    _confirm(ctx, _token(_verification_emails(ctx, _address(ctx, "new"))[-1]))


@when(parsers.parse('someone uses the link token "{token}"'))
def made_up(ctx, token):
    _confirm(ctx, token)


@when(parsers.parse('the player resets their password to "{password}"'))
def resets(ctx, password):
    resp = _client.post("/v1/auth/password-reset", json={"email": ctx["email"]})
    assert resp.status_code == 202
    mail = next(
        m for m in ctx["outbox"] if m["subject"] == "Reset your Cheetah Moon password"
    )
    resp = _client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": _token(mail), "new_password": password},
    )
    assert resp.status_code == 200, resp.text


@when("the player changes their email to a new address")
def changes_email(ctx):
    _change_email(ctx, _address(ctx, "new"))


@when(parsers.parse('the player changes their email to the address "{label}"'))
def changes_email_to(ctx, label):
    _change_email(ctx, _address(ctx, label))


# ── Then ───────────────────────────────────────────────────────


@then(parsers.parse("the response status should be {status:d}"))
def status_is(ctx, status):
    assert ctx["resp"].status_code == status, ctx["resp"].text


@then("the player is not signed in")
def not_signed_in(ctx):
    assert "userjwt" not in ctx["resp"].cookies


@then("the player is signed in")
def signed_in(ctx):
    cookie = ctx["resp"].cookies["userjwt"]
    resp = _client.get("/userDetails", cookies={"userjwt": cookie})
    assert resp.status_code == 200
    assert resp.json()["username"] == ctx["username"]
    assert resp.json()["email_verified"] is True


@then("one verification email is sent to the player")
def one_email(ctx):
    assert [m["to"] for m in _verification_emails(ctx)] == [ctx["email"]]


@then("another verification email is sent to the player")
def another_email(ctx):
    assert [m["to"] for m in _verification_emails(ctx)] == [ctx["email"]] * 2


@then(parsers.parse("{n:d} verification emails are sent to the player"))
def n_emails(ctx, n):
    assert [m["to"] for m in _verification_emails(ctx)] == [ctx["email"]] * n


@then("no more emails are sent")
def no_more(ctx):
    assert len(ctx["outbox"]) == ctx["before"]


@then(parsers.parse('the email links to "{text}"'))
def links_to(ctx, text):
    mail = ctx["outbox"][-1]
    assert text in mail["text"]
    assert text.replace("&", "&amp;") in mail["html"]


@then("the player is told to verify their email")
def told_to_verify(ctx):
    assert ctx["resp"].json()["email_not_verified"] is True
    assert ctx["resp"].json()["error"] == email_verification.NOT_VERIFIED


@then("the player can log in with their password")
def can_log_in(ctx):
    resp = _log_in(ctx)
    assert resp.status_code == 200, resp.text


@then(parsers.parse('the player can log in with "{password}"'))
def can_log_in_with(ctx, password):
    resp = _log_in(ctx, password)
    assert resp.status_code == 200, resp.text


@then("the player still can't log in with their password")
def still_cant(ctx):
    assert _log_in(ctx).status_code == 403


@then("one verification email is sent to the new address")
def one_to_new(ctx):
    assert [m["to"] for m in _verification_emails(ctx)] == [_address(ctx, "new")]


@then("the player's email is still the old one")
def still_old(ctx):
    assert _email_now(ctx) == ctx["email"]


@then("the player's email is the new one")
def is_new(ctx):
    assert ctx["resp"].status_code == 200, ctx["resp"].text
    assert _email_now(ctx) == _address(ctx, "new")


@then("the player's email is the second new one")
def is_second(ctx):
    assert _email_now(ctx) == _address(ctx, "second")
