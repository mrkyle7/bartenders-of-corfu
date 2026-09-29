"""Sending email through Brevo's transactional email API.

Configured by environment variables:

- ``BREVO_API_KEY``: the API key (Brevo → SMTP & API → API keys). Unset, or
  set to the placeholder ``not-set``, nothing is sent and a warning is logged,
  which is what local runs and tests get.
- ``EMAIL_FROM`` / ``EMAIL_FROM_NAME``: the sender. Brevo only sends from a
  verified sender or an authenticated domain.
- ``BREVO_API_URL``: only for trying things locally against a stand-in.
"""

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
_PLACEHOLDER = "not-set"


def _api_key() -> str | None:
    key = os.getenv("BREVO_API_KEY", "").strip()
    return key if key and key != _PLACEHOLDER else None


def send_email(to_email: str, to_name: str, subject: str, html: str, text: str) -> bool:
    """Send one email. Returns True if Brevo accepted it."""
    key = _api_key()
    if not key:
        logger.warning("BREVO_API_KEY not set; not sending email '%s'", subject)
        return False
    payload = {
        "sender": {
            "email": os.getenv("EMAIL_FROM", "noreply@cheetahmoongames.com"),
            "name": os.getenv("EMAIL_FROM_NAME", "Cheetah Moon Games"),
        },
        "to": [{"email": to_email, "name": to_name}],
        "subject": subject,
        "htmlContent": html,
        "textContent": text,
    }
    request = urllib.request.Request(
        os.getenv("BREVO_API_URL", BREVO_URL),
        data=json.dumps(payload).encode(),
        headers={
            "api-key": key,
            "accept": "application/json",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as e:
        # Brevo explains what's wrong (unverified sender, bad key) in the body.
        logger.error(
            "Brevo rejected email '%s': %s %s",
            subject,
            e.code,
            e.read()[:500].decode(errors="replace"),
        )
    except Exception:
        logger.exception("Couldn't reach Brevo to send email '%s'", subject)
    return False
