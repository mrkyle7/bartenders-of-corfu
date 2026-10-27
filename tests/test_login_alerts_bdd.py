"""BDD tests for telling the owner when players come back (app/activity.py)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from app import activity
from app.api import app
from tests.accounts import register
from app.db import db
from app import google_sign_in
from tests.test_activity import _KEY, game_token

scenarios("features/login_alerts.feature")

_client = TestClient(app)


def _register(prefix: str) -> dict:
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    resp = register(_client, name, f"{name}@example.com")
    assert resp.status_code == 200, resp.text
    return {"name": name, "id": resp.json()["id"], "cookie": resp.cookies["userjwt"]}


@pytest.fixture
def ctx(monkeypatch):
    # Google's keys, as far as games' identity tokens go, are the test key.
    monkeypatch.setattr(google_sign_in, "_signing_key", lambda _t: _KEY.public_key())
    sent = []
    monkeypatch.setattr(
        activity.push, "send_push", lambda **kw: sent.append(kw) or True
    )
    activity.forget()
    return {"sent": sent, "resp": None}


def _settle(ctx):
    activity.wait()


def _last_seen(user_id: str, ago: timedelta):
    when = (datetime.now(timezone.utc) - ago).isoformat()
    db.supabase.table("users").update({"last_seen_at": when}).eq(
        "id", user_id
    ).execute()


# ── Given ──────────────────────────────────────────────────────


@given("the owner gets login alerts on their phone")
def owner(ctx, monkeypatch):
    ctx["owner"] = _register("owner")
    monkeypatch.setenv("LOGIN_ALERTS_TO", ctx["owner"]["name"])
    db.save_push_subscription(
        uuid.UUID(ctx["owner"]["id"]),
        f"https://push.example.com/{uuid.uuid4().hex}",
        "p256dh",
        "auth",
    )
    _settle(ctx)
    ctx["sent"].clear()


@given(parsers.parse("a player who was last seen {hours:d} hours ago"))
def player_seen(ctx, hours):
    # Registered before alerts were on, so making the account wasn't reported.
    ctx["player"] = _register("player")
    _settle(ctx)
    ctx["sent"].clear()
    _last_seen(ctx["player"]["id"], timedelta(hours=hours))
    activity.forget()


# ── When ───────────────────────────────────────────────────────


@when("the player signs in")
def signs_in(ctx):
    ctx["resp"] = _client.post(
        "/login", json={"username": ctx["player"]["name"], "password": "Password1"}
    )
    _settle(ctx)


@when("a new player makes an account")
def new_player(ctx):
    _register("newbie")
    _settle(ctx)


def _open(ctx, who, place):
    # The test client keeps cookies from earlier responses: start clean.
    _client.cookies.clear()
    cookies = {"userjwt": who["cookie"]} if who else {}
    ctx["resp"] = _client.post(
        "/v1/activity/seen", json={"place": place}, cookies=cookies
    )
    _settle(ctx)


@when(parsers.parse('the player opens "{place}"'))
def player_opens(ctx, place):
    _open(ctx, ctx["player"], place)


@when(parsers.parse('the owner opens "{place}"'))
def owner_opens(ctx, place):
    _open(ctx, ctx["owner"], place)


@when(parsers.parse('someone without a sign-in reports opening "{place}"'))
def anonymous_opens(ctx, place):
    _open(ctx, None, place)


@when(parsers.parse("the player opens Bartenders pages {n:d} times"))
def uses_bartenders(ctx, n):
    for _ in range(n):
        resp = _client.get("/userDetails", cookies={"userjwt": ctx["player"]["cookie"]})
        assert resp.status_code == 200, resp.text
    _settle(ctx)


@when("the player opens cheetahmoongames.com")
def opens_home(ctx):
    # The home page's server asks who's signed in, marking its request.
    resp = _client.get(
        "/userDetails",
        cookies={"userjwt": ctx["player"]["cookie"]},
        headers={activity.HOME_HEADER: "1"},
    )
    assert resp.status_code == 200, resp.text
    _settle(ctx)


def _report_guest(ctx, name, email):
    _client.cookies.clear()
    token = game_token(email=email)
    # Guests are known by name: give each scenario's guest its own.
    ctx["guest"] = ctx.get("guest") or f"{name} {uuid.uuid4().hex[:6]}"
    ctx["resp"] = _client.post(
        "/v1/activity/guest-seen",
        json={"name": ctx["guest"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    _settle(ctx)
    activity.forget()  # as if each report reached a different server


@when(parsers.parse('The Boxer reports a guest called "{name}"'))
@when(parsers.parse('a while later The Boxer reports a guest called "{name}"'))
def boxer_guest(ctx, name):
    _report_guest(ctx, name, "the-boxer-run@bartenders-464918.iam.gserviceaccount.com")


@when(
    parsers.parse(
        'something that isn\'t one of our games reports a guest called "{name}"'
    )
)
def stranger_guest(ctx, name):
    _report_guest(ctx, name, "someone@gmail.com")


# ── Then ───────────────────────────────────────────────────────


@then(parsers.parse("the response status should be {status:d}"))
def status_is(ctx, status):
    assert ctx["resp"].status_code == status, ctx["resp"].text


@then(parsers.parse('the owner is told "{what}"'))
def told(ctx, what):
    assert [m["body"] for m in ctx["sent"]][-1:] == [what], ctx["sent"]


@then(parsers.parse('the owner is told "{what}" by "{title}"'))
def told_with_title(ctx, what, title):
    assert ctx["sent"], ctx["sent"]
    assert ctx["sent"][-1]["body"] == what
    assert ctx["sent"][-1]["title"] == title.replace("Bob", ctx["guest"])


@then("the owner was told once")
def told_once(ctx):
    assert len(ctx["sent"]) == 1, ctx["sent"]


@then("the owner is told nothing")
def told_nothing(ctx):
    assert ctx["sent"] == []
