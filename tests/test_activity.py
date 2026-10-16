"""Telling the owner when a player comes back. The database and push are
faked, so these run without Supabase."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

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
