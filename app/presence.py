"""Who is looking at which game, so they aren't notified about it.

Looking means a game page is shown and in focus. The page says so
(``POST /v1/games/{id}/looking`` with its ``tab`` and ``looking: true``) every
15 seconds while it is, and straight away when it's hidden, loses focus or
goes away (``looking: false``, or ``POST /v1/games/{id}/away``). A page that
hasn't said so in the last ``WATCHING_SECONDS`` (a phone locked, say) stops
counting. A page that's merely open, or polling, doesn't count.

This is kept in each server's memory. With more than one instance a player's
reports may have gone to another one; then this one sends the notification.
"""

import threading
import time
from uuid import UUID

WATCHING_SECONDS = 30.0
_MAX_TABS = 50

_lock = threading.Lock()
# (game id, user id) -> {tab: when its word that they're looking runs out}
_seen: dict[tuple[str, str], dict[str, float]] = {}


def _key(game_id: UUID | str, user_id: UUID | str) -> tuple[str, str]:
    return (str(game_id), str(user_id))


def look(game_id: UUID | str, user_id: UUID | str, tab: str, looking: bool) -> None:
    """A page (``tab``) says whether its player is looking at the game."""
    now = time.monotonic()
    key = _key(game_id, user_id)
    with _lock:
        tabs = {t: until for t, until in _seen.get(key, {}).items() if until > now}
        if looking and (tab in tabs or len(tabs) < _MAX_TABS):
            tabs[tab] = now + WATCHING_SECONDS
        elif not looking:
            tabs.pop(tab, None)
        if tabs:
            _seen[key] = tabs
        else:
            _seen.pop(key, None)
        # Forget old entries now and then so the map doesn't grow forever
        if len(_seen) > 10_000:
            for k in [k for k, ts in _seen.items() if max(ts.values()) <= now]:
                del _seen[k]


def mark_watching(game_id: UUID | str, user_id: UUID | str, tab: str = "") -> None:
    look(game_id, user_id, tab, True)


def mark_away(game_id: UUID | str, user_id: UUID | str) -> None:
    """None of the player's pages on the game are looking at it."""
    with _lock:
        _seen.pop(_key(game_id, user_id), None)


def is_watching(game_id: UUID | str, user_id: UUID | str) -> bool:
    now = time.monotonic()
    with _lock:
        tabs = _seen.get(_key(game_id, user_id), {})
        return any(until > now for until in tabs.values())


def clear() -> None:
    """For tests."""
    with _lock:
        _seen.clear()
