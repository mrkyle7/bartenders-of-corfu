"""Web Push notifications: when it's a player's turn, and when a game ends.

The key pair that signs them (VAPID keys) lives in the database
(``vapid_keys``), so there are no secrets to set up: the first server that
needs it makes it and saves it, and every later server uses the same pair.

A database without a pair yet is given the one the server used to read from
Secret Manager (``VAPID_PUBLIC_KEY`` and ``VAPID_PRIVATE_KEY``) if it still
has it, so devices that already get notifications keep getting them.
"""

import base64
import json
import logging
import os
import re
import threading
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pywebpush import WebPushException, webpush

logger = logging.getLogger(__name__)

_VAPID_CLAIMS = {"sub": "mailto:admin@cheetahmoongames.com"}
# Keep a notification for a day while the device is offline or asleep
# (pywebpush's default of 0 drops it unless the device is reachable now),
# and don't wait forever on a slow push service.
_TTL_SECONDS = 24 * 60 * 60
_TIMEOUT_SECONDS = 10
# Terraform used to create the key secrets with this value until they were set.
_PLACEHOLDER = "not-set"

_keys: dict | None = None
_lock = threading.Lock()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate_keys() -> dict:
    """A new VAPID key pair, as base64url strings."""
    key = generate_private_key(SECP256R1())
    return {
        "public_key": _b64url(
            key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        ),
        "private_key": _b64url(key.private_numbers().private_value.to_bytes(32, "big")),
    }


def keys_from_env() -> dict | None:
    """The pair from VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY, if both are set."""
    public_key = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    private_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if not public_key or not private_key or _PLACEHOLDER in (public_key, private_key):
        return None
    return {"public_key": public_key, "private_key": private_key}


def _db():
    from app.db import db

    return db


def get_keys() -> dict | None:
    """The database's key pair, making and saving one if there isn't one yet.

    None (no notifications) if the database can't be read; it's tried again
    next time.
    """
    global _keys
    if _keys:
        return _keys
    with _lock:
        if _keys:
            return _keys
        try:
            db = _db()
            keys = db.get_vapid_keys()
            if not keys:
                # Two servers starting at once may both get here: only the
                # first pair is saved, and both use it.
                db.save_vapid_keys(keys_from_env() or generate_keys())
                keys = db.get_vapid_keys()
        except Exception as exc:
            logger.warning("Couldn't get the notification keys: %s", exc)
            return None
        _keys = keys
        return _keys


def get_public_key() -> str:
    keys = get_keys()
    return keys["public_key"] if keys else ""


def valid_endpoint(endpoint: str) -> bool:
    """Whether a browser's push endpoint is safe for the server to send to.

    The server POSTs to it, so it must be an https URL on a named host on the
    internet, not an address on the server's own network.
    """
    if not isinstance(endpoint, str) or len(endpoint) > 1000:
        return False
    try:
        parts = urlsplit(endpoint)
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username or parts.password:
        return False
    if (
        "." not in host
        or host == "localhost"
        or host.endswith((".localhost", ".internal", ".local"))
    ):
        return False
    # IP addresses: IPv4 dotted numbers, or IPv6 (hostname drops the brackets)
    if re.fullmatch(r"[\d.]+", host) or ":" in host:
        return False
    return True


def send_push(
    subscription_info: dict, title: str, body: str, url: str, tag: str | None = None
) -> bool:
    """Send a Web Push notification to one subscription.

    Returns True if the push was sent (or if there are no keys to sign it).
    Returns False if the subscription is expired/invalid (caller should delete it).
    """
    keys = get_keys()
    if not keys:
        logger.debug("No notification keys — skipping push")
        return True
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(
                {"title": title, "body": body, "url": url, "tag": tag or "turn-push"}
            ),
            vapid_private_key=keys["private_key"],
            vapid_claims=dict(_VAPID_CLAIMS),
            ttl=_TTL_SECONDS,
            timeout=_TIMEOUT_SECONDS,
            headers={"Urgency": "high"},
        )
        return True
    except WebPushException as exc:
        if exc.response is not None and exc.response.status_code in (404, 410):
            # Subscription has been unregistered by the browser
            return False
        logger.warning("Push failed (transient): %s", exc)
        return True
    except Exception as exc:
        logger.warning("Push error: %s", exc)
        return True
