import os
import json
import logging
from pywebpush import webpush, WebPushException

logger = logging.getLogger(__name__)

_VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
_VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
_VAPID_CLAIMS = {"sub": "mailto:admin@cheetahmoongames.com"}


def get_public_key() -> str:
    return _VAPID_PUBLIC_KEY


def send_push(subscription_info: dict, title: str, body: str, url: str) -> bool:
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
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=_VAPID_PRIVATE_KEY,
            vapid_claims=_VAPID_CLAIMS,
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
