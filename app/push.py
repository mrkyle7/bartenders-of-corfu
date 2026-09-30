import os
import json
import logging
import re
from urllib.parse import urlsplit
from pywebpush import webpush, WebPushException

logger = logging.getLogger(__name__)

_VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
_VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
_VAPID_CLAIMS = {"sub": "mailto:admin@cheetahmoongames.com"}
# Keep a notification for a day while the device is offline or asleep
# (pywebpush's default of 0 drops it unless the device is reachable now),
# and don't wait forever on a slow push service.
_TTL_SECONDS = 24 * 60 * 60
_TIMEOUT_SECONDS = 10


def get_public_key() -> str:
    return _VAPID_PUBLIC_KEY


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

    Returns True if the push was sent (or if VAPID is not configured).
    Returns False if the subscription is expired/invalid (caller should delete it).
    """
    if not _VAPID_PRIVATE_KEY:
        logger.debug("VAPID_PRIVATE_KEY not set — skipping push")
        return True
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(
                {"title": title, "body": body, "url": url, "tag": tag or "turn-push"}
            ),
            vapid_private_key=_VAPID_PRIVATE_KEY,
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
