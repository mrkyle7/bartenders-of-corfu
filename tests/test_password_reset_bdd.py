"""BDD tests for resetting a forgotten password by email."""

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from app import email_sender, password_reset
from app.api import app
from app.db import db

scenarios("features/password_reset.feature")

_client = TestClient(app)


@pytest.fixture
def outbox(monkeypatch):
    """Emails that would have gone to Brevo."""
    sent = []

    def fake_send(to_email, to_name, subject, html, text):
        sent.append({"to": to_email, "subject": subject, "html": html, "text": text})
        return True

    monkeypatch.setattr(email_sender, "send_email", fake_send)
    return sent


def _token(mail: dict) -> str:
    return re.search(r"token=([A-Za-z0-9_\-]+)", mail["text"]).group(1)


def _confirm(token: str, password: str):
    return _client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": password},
    )


# ── Steps ──────────────────────────────────────────────────────


@given(parsers.parse('a registered player with email "{email}"'), target_fixture="ctx")
def registered_player(email, outbox):
    # Emails are unique, so each scenario's player gets its own address, and
    # the scenario's address is mapped onto it.
    unique = f"reset_{uuid.uuid4().hex[:8]}"
    real_email = f"{unique}@example.com"
    resp = _client.post(
        "/register",
        json={"username": unique, "email": real_email, "password": "Password1"},
    )
    assert resp.status_code == 201, resp.text
    return {
        "username": unique,
        "alias": email,
        "email": real_email,
        "cookie": resp.cookies["userjwt"],
        "tokens": [],
        "outbox": outbox,
        "resp": None,
    }


def _address(ctx, email: str) -> str:
    """The scenario's address, as the unique one this player really has."""
    if email == ctx["alias"]:
        return ctx["email"]
    if email.lower() == ctx["alias"].lower():
        return ctx["email"].upper()
    return email


def _ask(ctx, email, next_url=None):
    body = {"email": _address(ctx, email)}
    if next_url:
        body["next"] = next_url
    ctx["resp"] = _client.post("/v1/auth/password-reset", json=body)
    if ctx["outbox"]:
        ctx["tokens"].append(_token(ctx["outbox"][-1]))


@given("the player has asked for a reset link")
@given("the player has asked for another reset link")
def asked(ctx):
    _ask(ctx, ctx["alias"])


@given("the player is signed in on another device")
def other_device(ctx):
    ctx["other_cookie"] = ctx["cookie"]


@given("the link has expired")
def expire(ctx):
    (
        db.supabase.table("password_resets")
        .update(
            {
                "expires_at": (
                    datetime.now(timezone.utc) - timedelta(minutes=1)
                ).isoformat()
            }
        )
        .eq("token_hash", password_reset._hash(ctx["tokens"][-1]))
        .execute()
    )


@given(parsers.parse('the player has used the link with the new password "{password}"'))
def used(ctx, password):
    assert _confirm(ctx["tokens"][-1], password).status_code == 200


@when(parsers.parse('someone asks to reset the password for "{email}"'))
def ask(ctx, email):
    _ask(ctx, email)


@when(
    parsers.parse(
        'someone asks to reset the password for "{email}" returning to "{next_url}"'
    )
)
def ask_with_next(ctx, email, next_url):
    _ask(ctx, email, next_url)


@when(parsers.parse('someone asks to reset the password for "{email}" {n:d} times'))
def ask_many(ctx, email, n):
    for _ in range(n):
        _ask(ctx, email)


@when(parsers.parse('the player uses the link with the new password "{password}"'))
def use_link(ctx, password):
    ctx["resp"] = _confirm(ctx["tokens"][-1], password)


@when(
    parsers.parse('the player uses the first link with the new password "{password}"')
)
def use_first(ctx, password):
    ctx["resp"] = _confirm(ctx["tokens"][0], password)


@when(
    parsers.parse('the player uses the second link with the new password "{password}"')
)
def use_second(ctx, password):
    ctx["resp"] = _confirm(ctx["tokens"][1], password)


@when(
    parsers.parse(
        'someone uses the link token "{token}" with the new password "{password}"'
    )
)
def use_made_up(ctx, token, password):
    ctx["resp"] = _confirm(token, password)


@then(parsers.parse("the response status should be {status:d}"))
def status_is(ctx, status):
    assert ctx["resp"].status_code == status, ctx["resp"].text


@then(parsers.parse('one reset email is sent to "{email}"'))
def one_email(ctx, email):
    assert [m["to"] for m in ctx["outbox"]] == [_address(ctx, email)]
    assert ctx["outbox"][0]["subject"] == "Reset your Cheetah Moon password"


@then(parsers.parse('{n:d} reset emails are sent to "{email}"'))
def n_emails(ctx, n, email):
    assert [m["to"] for m in ctx["outbox"]] == [_address(ctx, email)] * n


@then("no email is sent")
def no_email(ctx):
    assert ctx["outbox"] == []


@then(parsers.parse('the email links to "{text}"'))
def links_to(ctx, text):
    mail = ctx["outbox"][-1]
    assert text in mail["text"]
    assert text.replace("&", "&amp;") in mail["html"]


@then("the player is signed in")
def signed_in(ctx):
    token = ctx["resp"].cookies["userjwt"]
    resp = _client.get("/userDetails", cookies={"userjwt": token})
    assert resp.status_code == 200
    assert resp.json()["username"] == ctx["username"]


@then(parsers.parse('the player can log in with "{password}"'))
def can_log_in(ctx, password):
    resp = _client.post(
        "/login", json={"username": ctx["username"], "password": password}
    )
    assert resp.status_code == 200


@then(parsers.parse('the player can\'t log in with "{password}"'))
def cannot_log_in(ctx, password):
    resp = _client.post(
        "/login", json={"username": ctx["username"], "password": password}
    )
    assert resp.status_code == 401


@then("the other device is signed out")
def other_signed_out(ctx):
    resp = _client.get("/userDetails", cookies={"userjwt": ctx["other_cookie"]})
    assert resp.status_code == 401


@then("the error says the link has expired or been used")
def expired_error(ctx):
    assert ctx["resp"].json()["error"] == password_reset.INVALID_LINK


@then(parsers.parse('the error says "{message}"'))
def error_says(ctx, message):
    assert ctx["resp"].json()["error"] == message
