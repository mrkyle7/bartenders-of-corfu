"""Unit tests for app/presence.py: who is looking at which game."""

from unittest.mock import patch
from uuid import uuid4

from app import presence


def setup_function():
    presence.clear()


def test_a_player_whose_page_says_so_is_watching():
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


def test_watching_ends_when_the_page_stops_saying_so():
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


def test_each_page_says_for_itself():
    game, player = uuid4(), uuid4()
    presence.look(game, player, "t1", True)
    presence.look(game, player, "t2", True)
    presence.look(game, player, "t1", False)
    assert presence.is_watching(game, player), "still looking on t2"
    presence.look(game, player, "t2", False)
    assert not presence.is_watching(game, player)
