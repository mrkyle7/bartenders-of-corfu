"""Unit tests for app/presence.py: who is looking at which game."""

from unittest.mock import patch
from uuid import uuid4

from app import presence


def setup_function():
    presence.clear()


def test_a_player_who_polled_just_now_is_watching():
    game, player, other = uuid4(), uuid4(), uuid4()
    presence.mark_watching(game, player)
    assert presence.is_watching(game, player)
    assert presence.is_watching(str(game), str(player))
    assert not presence.is_watching(game, other)
    assert not presence.is_watching(uuid4(), player)


def test_watching_ends_when_the_page_is_hidden():
    game, player = uuid4(), uuid4()
    presence.mark_watching(game, player)
    presence.mark_away(str(game), str(player))
    assert not presence.is_watching(game, player)


def test_watching_ends_when_the_polls_stop():
    game, player = uuid4(), uuid4()
    with patch("app.presence.time.monotonic", return_value=1000.0):
        presence.mark_watching(game, player)
    later = 1000.0 + presence.WATCHING_SECONDS + 1
    with patch("app.presence.time.monotonic", return_value=later):
        assert not presence.is_watching(game, player)


def test_old_entries_are_forgotten():
    with patch("app.presence.time.monotonic", return_value=0.0):
        for _ in range(10_001):
            presence.mark_watching(uuid4(), uuid4())
    with patch("app.presence.time.monotonic", return_value=1000.0):
        presence.mark_watching(uuid4(), uuid4())
    assert len(presence._seen) == 1
