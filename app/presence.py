"""Who is looking at which game, so they aren't notified about it.

Game pages poll the game only while they're showing, and tell the server when
they're hidden (``POST /v1/games/{id}/away``). A player who polled a game in
the last ``WATCHING_SECONDS`` is taken to be watching it: they see their turn
on screen, so no notification is sent.

This is kept in each server's memory. With more than one instance a player's
polls may have gone to another one; then this one sends the notification, as
it did before presence was tracked.
"""

import threading
import time
from uuid import UUID

WATCHING_SECONDS = 15.0

_lock = threading.Lock()
_seen: dict[tuple[str, str], float] = {}


def _key(game_id: UUID | str, user_id: UUID | str) -> tuple[str, str]:
    return (str(game_id), str(user_id))


def mark_watching(game_id: UUID | str, user_id: UUID | str) -> None:
    now = time.monotonic()
    with _lock:
        _seen[_key(game_id, user_id)] = now
        # Forget old entries now and then so the map doesn't grow forever
        if len(_seen) > 10_000:
            cutoff = now - WATCHING_SECONDS
            for k in [k for k, t in _seen.items() if t < cutoff]:
                del _seen[k]


def mark_away(game_id: UUID | str, user_id: UUID | str) -> None:
    with _lock:
        _seen.pop(_key(game_id, user_id), None)


def is_watching(game_id: UUID | str, user_id: UUID | str) -> bool:
    with _lock:
        seen = _seen.get(_key(game_id, user_id))
    return seen is not None and time.monotonic() - seen < WATCHING_SECONDS


def clear() -> None:
    """For tests."""
    with _lock:
        _seen.clear()
