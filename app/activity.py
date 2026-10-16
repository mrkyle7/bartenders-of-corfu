"""Telling the site's owner when a player comes back.

Every Cheetah Moon game reports the signed-in players it sees: Bartenders
itself (its pages asking ``/userDetails``, its game API and the sign-in
routes), cheetahmoongames.com (its pages asking who's signed in, which reach
``/userDetails`` marked with ``HOME_HEADER``) and the other games, through
``POST /v1/activity/seen`` (their ``auth.js`` calls it via cheetahmoongames.com).
``seen()`` records when each player was last seen (``users.last_seen_at``).
A player seen after at least ``AWAY`` without being seen, or for the first
time, has come back: the account named by ``LOGIN_ALERTS_TO`` (a username)
gets a push notification on every device it turned them on for. Everything
else a player does in between is ignored, so a game night is one
notification per player, not one per move.

Guests (games that let people play under a typed name, without an account)
are reported by the game's server itself: ``guest_seen()``, through
``POST /v1/activity/guest-seen`` with a Google identity token for the game's
Cloud Run service account (``verify_game()``), which also says which game it
is. A guest is known only by their name, so the same rule applies per game
and name (``guest_visits``).

Bots and the owner themselves are never reported. Without ``LOGIN_ALERTS_TO``
nothing is recorded or sent.
"""

import logging
import os
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import jwt

from app import push
from app.db import db

logger = logging.getLogger(__name__)

AWAY = timedelta(hours=6)
# Each server writes a player's last-seen time at most this often.
RECORD_EVERY = timedelta(minutes=5)

# Where a player was seen: Bartenders, the home page, or another game (named
# by its Cloud Run service, which is its subdomain).
SIGN_IN = "sign-in"
HOME = "cheetahmoongames"
# cheetahmoongames.com's server sends this on its requests here, so its pages
# asking who's signed in count as the home page rather than Bartenders.
HOME_HEADER = "X-Cheetah-Moon-Home"
GAME_NAMES = {
    "bartenders": "Bartenders of Corfu",
    "the-boxer": "The Boxer",
    "bezique": "Bezique",
    "catch-the-flag": "Catch The Flag",
    "kings-keep": "King's Keep",
}
_PLACE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

_last_recorded: dict[str, datetime] = {}
_lock = threading.Lock()
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="activity")


def owner() -> str | None:
    return os.getenv("LOGIN_ALERTS_TO", "").strip() or None


def valid_place(place: str) -> bool:
    return isinstance(place, str) and bool(_PLACE.match(place))


def describe(place: str, new_account: bool = False) -> str:
    if new_account:
        return "Made a Cheetah Moon account"
    if place == SIGN_IN:
        return "Signed in to Cheetah Moon Games"
    if place == HOME:
        return "Opened cheetahmoongames.com"
    name = GAME_NAMES.get(place) or place.replace("-", " ").title()
    return f"Opened {name}"


def seen(
    user_id,
    username: str | None,
    place: str,
    *,
    new_account: bool = False,
    now: datetime | None = None,
) -> bool:
    """Records a player as seen; notifies the owner if they've come back.

    Returns whether the owner was notified. Never raises.
    """
    try:
        to = owner()
        if not to or not username or username.lower() == to.lower():
            return False
        now = now or datetime.now(timezone.utc)
        key = str(user_id)
        # A sign-in always counts; anything else is recorded once in a while.
        if place != SIGN_IN and not new_account:
            with _lock:
                last = _last_recorded.get(key)
                if last and now - last < RECORD_EVERY:
                    return False
                _last_recorded[key] = now
        if not db.mark_seen(user_id, now, now - AWAY) and not new_account:
            return False
        _notify(to, str(user_id), f"{username} is here", describe(place, new_account))
        return True
    except Exception:
        logger.exception("Couldn't record that player %s was seen", user_id)
        return False


def clean_guest_name(name) -> str:
    """A guest's name as typed, made safe to show: no control characters,
    at most 30 characters."""
    text = "".join(ch for ch in str(name or "") if ch.isprintable())
    return " ".join(text.split())[:30].strip() or "Guest"


def guest_seen(place: str, name: str, *, now: datetime | None = None) -> bool:
    """Records a guest as seen in a game; notifies the owner if they've come
    back (or are new). Returns whether the owner was notified. Never raises."""
    try:
        to = owner()
        if not to:
            return False
        name = clean_guest_name(name)
        now = now or datetime.now(timezone.utc)
        key = f"{place}:{name.lower()}"
        with _lock:
            last = _last_recorded.get(f"guest:{key}")
            if last and now - last < RECORD_EVERY:
                return False
            _last_recorded[f"guest:{key}"] = now
        if not db.mark_guest_seen(key, now, now - AWAY):
            return False
        _notify(to, f"guest-{key}", f"Guest {name} is here", describe(place))
        return True
    except Exception:
        logger.exception("Couldn't record that a guest was seen in %s", place)
        return False


def report_guest(place: str, name: str) -> Future:
    """``guest_seen()`` on a background thread."""
    return _worker.submit(guest_seen, place, name)


# Games vouch for their guests with a Google identity token for their Cloud
# Run service account, which Cloud Run's metadata server gives them, made out
# to this audience. Every game's account is "<service>-run@<project>".
GAME_AUDIENCE = "https://cheetahmoongames.com"


def _game_account() -> re.Pattern:
    project = os.getenv("GCP_PROJECT", "bartenders-464918")
    return re.compile(
        rf"^([a-z][a-z0-9-]{{0,39}})-run@{re.escape(project)}\.iam\.gserviceaccount\.com$"
    )


def verify_game(token: str) -> str | None:
    """The game (its Cloud Run service name) a Google identity token is from,
    or None if it isn't a valid one from one of our games' servers."""
    from app import google_sign_in

    if not isinstance(token, str) or not token or len(token) > 4096:
        return None
    try:
        claims = jwt.decode(
            token,
            google_sign_in._signing_key(token),
            algorithms=["RS256"],
            audience=GAME_AUDIENCE,
            issuer=google_sign_in.GOOGLE_ISSUERS,
            options={"require": ["exp", "iat", "iss", "aud", "email"]},
            leeway=60,
        )
    except Exception as e:
        logger.warning("Refused a game's identity token: %s", e)
        return None
    if claims.get("email_verified") not in (True, "true"):
        return None
    match = _game_account().match(str(claims.get("email", "")))
    return match.group(1) if match else None


def report(user_id, username: str | None, place: str, **kwargs) -> Future:
    """``seen()`` on a background thread, so the request isn't kept waiting."""
    return _worker.submit(seen, user_id, username, place, **kwargs)


def wait() -> None:
    """Waits for every report made so far (for tests)."""
    _worker.submit(lambda: None).result()


def forget() -> None:
    """Clears what this server remembers recording (for tests)."""
    with _lock:
        _last_recorded.clear()


def _notify(to: str, tag_id: str, title: str, what: str) -> None:
    recipient = db.get_user_by_username(to)
    if not recipient or recipient.status != "active":
        logger.warning("LOGIN_ALERTS_TO names no active account; not notifying")
        return
    logger.info("%s (%s); notifying %s", title, what, recipient.id)
    for sub in db.get_push_subscriptions(recipient.id):
        ok = push.send_push(
            subscription_info={
                "endpoint": sub["endpoint"],
                "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
            },
            title=title,
            body=what,
            url="/",
            tag=f"seen-{tag_id}",
        )
        if not ok:
            db.delete_push_subscription(sub["endpoint"])
