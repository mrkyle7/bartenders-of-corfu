"""Telling the owner when a player comes back. The database and push are
faked, so these run without Supabase."""

import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import activity
from app.user import User

T0 = datetime(2026, 10, 16, 18, 0, tzinfo=timezone.utc)


class FakeDb:
    def __init__(self):
        self.last_seen: dict[str, datetime] = {}
        self.owner = User("kyle", "kyle@example.com", "Password1")
        self.subs = [{"endpoint": "https://push.example/1", "p256dh": "p", "auth": "a"}]
        self.writes = 0

    def mark_seen(self, user_id, now, away_since):
        self.writes += 1
        key = str(user_id)
        last = self.last_seen.get(key)
        self.last_seen[key] = max(now, last) if last else now
        return last is None or last < away_since

    def mark_guest_seen(self, key, now, away_since):
        return self.mark_seen(f"guest:{key}", now, away_since)

    def get_user_by_username(self, name):
        return self.owner if name == "kyle" else None

    def get_push_subscriptions(self, user_id):
        assert user_id == self.owner.id
        return self.subs

    def delete_push_subscription(self, endpoint):
        self.subs = [s for s in self.subs if s["endpoint"] != endpoint]


@pytest.fixture
def fake(monkeypatch):
    fake = FakeDb()
    sent = []
    monkeypatch.setattr(activity, "db", fake)
    monkeypatch.setattr(
        activity.push,
        "send_push",
        lambda **kw: sent.append(kw) or True,
    )
    monkeypatch.setenv("LOGIN_ALERTS_TO", "kyle")
    activity.forget()
    fake.sent = sent
    return fake


def player():
    return uuid.uuid4()


def test_a_player_seen_for_the_first_time_is_reported(fake):
    ada = player()
    assert activity.seen(ada, "Ada", "bezique", now=T0)
    [msg] = fake.sent
    assert msg["title"] == "Ada is here"
    assert msg["body"] == "Opened Bezique"
    assert msg["tag"] == f"seen-{ada}"


def test_everything_they_do_for_the_next_hours_is_not(fake):
    ada = player()
    activity.seen(ada, "Ada", "bezique", now=T0)
    for minutes in range(1, 5 * 60, 7):
        activity.seen(ada, "Ada", "bartenders", now=T0 + timedelta(minutes=minutes))
    activity.seen(ada, "Ada", activity.SIGN_IN, now=T0 + timedelta(hours=5))
    assert len(fake.sent) == 1


def test_coming_back_after_six_hours_away_is_reported_again(fake):
    ada = player()
    activity.seen(ada, "Ada", "bezique", now=T0)
    activity.seen(ada, "Ada", "bezique", now=T0 + timedelta(hours=2))
    # 6 hours after they were last seen, not after the first notification.
    assert not activity.seen(ada, "Ada", "the-boxer", now=T0 + timedelta(hours=7))
    assert activity.seen(ada, "Ada", "the-boxer", now=T0 + timedelta(hours=14))
    assert [m["body"] for m in fake.sent] == ["Opened Bezique", "Opened The Boxer"]


def test_a_steady_stream_of_activity_only_writes_every_few_minutes(fake):
    ada = player()
    for seconds in range(0, 600, 5):
        activity.seen(ada, "Ada", "bartenders", now=T0 + timedelta(seconds=seconds))
    assert fake.writes == 2


def test_each_player_is_reported_on_their_own(fake):
    activity.seen(player(), "Ada", "bezique", now=T0)
    activity.seen(player(), "Grace", "bezique", now=T0)
    assert [m["title"] for m in fake.sent] == ["Ada is here", "Grace is here"]


def test_the_owner_is_never_reported(fake):
    assert not activity.seen(player(), "Kyle", "bezique", now=T0)
    assert fake.sent == [] and fake.writes == 0


def test_new_accounts_and_sign_ins_say_so(fake):
    activity.seen(player(), "Ada", activity.SIGN_IN, new_account=True, now=T0)
    activity.seen(player(), "Grace", activity.SIGN_IN, now=T0)
    activity.seen(player(), "Alan", activity.HOME, now=T0)
    activity.seen(player(), "Joan", "kings-keep", now=T0)
    activity.seen(player(), "Hedy", "some-new-game", now=T0)
    assert [m["body"] for m in fake.sent] == [
        "Made a Cheetah Moon account",
        "Signed in to Cheetah Moon Games",
        "Opened cheetahmoongames.com",
        "Opened King's Keep",
        "Opened Some New Game",
    ]


def test_nothing_happens_without_an_owner(fake, monkeypatch):
    monkeypatch.delenv("LOGIN_ALERTS_TO")
    assert not activity.seen(player(), "Ada", "bezique", now=T0)
    assert fake.writes == 0


def test_a_gone_device_is_forgotten(fake, monkeypatch):
    monkeypatch.setattr(activity.push, "send_push", lambda **kw: False)
    activity.seen(player(), "Ada", "bezique", now=T0)
    assert fake.subs == []


def test_a_broken_database_never_breaks_the_request(fake, monkeypatch):
    def boom(*a):
        raise RuntimeError("db down")

    monkeypatch.setattr(fake, "mark_seen", boom)
    assert activity.seen(player(), "Ada", "bezique", now=T0) is False


def test_report_runs_in_the_background(fake):
    activity.report(player(), "Ada", "bezique")
    activity.wait()
    assert len(fake.sent) == 1


@pytest.mark.parametrize(
    "place,ok",
    [
        ("bezique", True),
        ("catch-the-flag", True),
        ("cheetahmoongames", True),
        ("", False),
        ("Bezique", False),
        ("-x", False),
        ("a" * 41, False),
        ("<script>", False),
    ],
)
def test_places_are_checked(place, ok):
    assert activity.valid_place(place) is ok


# ── Guests ─────────────────────────────────────────────────────


def test_a_guest_is_reported_by_name_and_game(fake):
    assert activity.guest_seen("the-boxer", "Bob", now=T0)
    [msg] = fake.sent
    assert msg["title"] == "Guest Bob is here"
    assert msg["body"] == "Opened The Boxer"


def test_a_guest_is_reported_once_until_away_six_hours(fake):
    activity.guest_seen("the-boxer", "Bob", now=T0)
    for minutes in range(10, 5 * 60, 10):
        activity.guest_seen("the-boxer", "bob", now=T0 + timedelta(minutes=minutes))
    assert len(fake.sent) == 1
    assert activity.guest_seen("the-boxer", "Bob", now=T0 + timedelta(hours=12))


def test_the_same_name_in_another_game_or_another_name_counts_on_its_own(fake):
    activity.guest_seen("the-boxer", "Bob", now=T0)
    activity.guest_seen("catch-the-flag", "Bob", now=T0)
    activity.guest_seen("the-boxer", "Ann", now=T0)
    assert len(fake.sent) == 3


@pytest.mark.parametrize(
    "typed,shown",
    [("  Bob  ", "Bob"), ("", "Guest"), ("a\nb\x00c", "abc"), ("x" * 50, "x" * 30)],
)
def test_guest_names_are_cleaned(typed, shown):
    assert activity.clean_guest_name(typed) == shown


# ── Games vouching for guests ──────────────────────────────────

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def game_token(**overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": activity.GAME_AUDIENCE,
        "email": "the-boxer-run@bartenders-464918.iam.gserviceaccount.com",
        "email_verified": True,
        "sub": "1234",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, overrides.pop("key", _KEY), algorithm="RS256")


@pytest.fixture
def google_keys(monkeypatch):
    from app import google_sign_in

    monkeypatch.setattr(google_sign_in, "_signing_key", lambda _t: _KEY.public_key())


def test_a_games_identity_token_names_the_game(google_keys):
    assert activity.verify_game(game_token()) == "the-boxer"
    email = "catch-the-flag-run@bartenders-464918.iam.gserviceaccount.com"
    assert activity.verify_game(game_token(email=email)) == "catch-the-flag"


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "https://someone-else.example"},
        {"iss": "https://evil.example"},
        {"exp": int(time.time()) - 3600},
        {"email": "the-boxer-run@another-project.iam.gserviceaccount.com"},
        {"email": "someone@gmail.com"},
        {"email": "the-boxer-deploy@bartenders-464918.iam.gserviceaccount.com"},
        {"email_verified": False},
    ],
    ids=[
        "another audience",
        "another issuer",
        "expired",
        "another project",
        "a person",
        "not a run account",
        "unverified",
    ],
)
def test_other_tokens_are_refused(google_keys, overrides):
    assert activity.verify_game(game_token(**overrides)) is None


def test_a_token_not_signed_by_google_is_refused(google_keys):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        jwt.decode(game_token(), options={"verify_signature": False}),
        other,
        algorithm="RS256",
    )
    assert activity.verify_game(token) is None
    assert activity.verify_game("") is None
    assert activity.verify_game("nonsense") is None
