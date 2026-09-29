"""Resetting a forgotten password by email.

1. ``request_reset(email)``: if an active account uses that email, store the
   hash of a new random token and email the account a link carrying the token.
   The caller always gets the same answer, so nobody can find out which
   emails have accounts.
2. ``complete_reset(token, new_password)``: if the token matches an unused,
   unexpired link, set the new password, use up every open link for that
   account and sign it out everywhere else. Returns the user so the caller can
   sign them in.
"""

import hashlib
import html
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from app import email_sender
from app.db import db
from app.user import User, UserValidationError

logger = logging.getLogger(__name__)

LINK_LIFETIME = timedelta(hours=1)
MAX_LINKS_PER_HOUR = 3
INVALID_LINK = (
    "This reset link has expired or has already been used. Ask for a new one."
)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _reset_url(token: str, next_url: str | None) -> str:
    base = os.getenv(
        "PASSWORD_RESET_URL", "https://cheetahmoongames.com/reset-password"
    )
    params = {"token": token}
    if next_url:
        params["next"] = next_url
    return f"{base}?{urlencode(params)}"


def _email(user: User, url: str) -> tuple[str, str, str]:
    subject = "Reset your Cheetah Moon password"
    name = html.escape(user.username or "")
    link = html.escape(url, quote=True)
    body_html = f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#0d0f1c;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;color:#f1f2f8">
<div style="max-width:480px;margin:0 auto;background:#1b2038;border:1px solid #2c3354;border-radius:12px;padding:28px">
<h1 style="margin:0 0 16px;font-size:22px">Reset your password</h1>
<p style="margin:0 0 16px;line-height:1.5">Hi {name}, someone (hopefully you) asked to reset the password for your Cheetah Moon Games account.</p>
<p style="margin:0 0 24px"><a href="{link}" style="display:inline-block;background:#f3d36b;color:#1a1405;font-weight:700;text-decoration:none;padding:12px 20px;border-radius:6px">Choose a new password</a></p>
<p style="margin:0 0 8px;color:#a6acc8;font-size:14px;line-height:1.5">The link works once, for the next hour. If you didn't ask for this, ignore this email and your password stays the same.</p>
<p style="margin:0;color:#a6acc8;font-size:13px;word-break:break-all">{link}</p>
</div></body></html>"""
    body_text = (
        f"Hi {user.username},\n\n"
        "Someone (hopefully you) asked to reset the password for your "
        "Cheetah Moon Games account. Choose a new one here:\n\n"
        f"{url}\n\n"
        "The link works once, for the next hour. If you didn't ask for this, "
        "ignore this email and your password stays the same.\n"
    )
    return subject, body_html, body_text


def request_reset(email: str, next_url: str | None = None) -> None:
    """Email a reset link if an active account uses ``email``. Never raises."""
    try:
        email = (email or "").strip()
        if not email or len(email) > 254:
            return
        user = db.get_user_by_email(email)
        if not user or user.status != "active" or user.is_bot:
            logger.info("Password reset asked for an email with no active account")
            return
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        if db.count_password_resets_since(user.id, since) >= MAX_LINKS_PER_HOUR:
            logger.warning("Too many password resets for user %s; not sending", user.id)
            return
        token = secrets.token_urlsafe(32)
        db.add_password_reset(
            user.id, _hash(token), datetime.now(timezone.utc) + LINK_LIFETIME
        )
        subject, body_html, body_text = _email(user, _reset_url(token, next_url))
        if email_sender.send_email(
            user.email, user.username, subject, body_html, body_text
        ):
            logger.info("Sent password reset email to user %s", user.id)
    except Exception:
        logger.exception("Password reset request failed")


def complete_reset(token: str, new_password: str) -> User:
    """Set a new password from a reset link.

    Raises UserValidationError with a message for the player if the link isn't
    valid or the password isn't allowed.
    """
    if not isinstance(token, str) or not token or len(token) > 200:
        raise UserValidationError(INVALID_LINK)
    reset = db.get_password_reset(_hash(token))
    if not reset:
        raise UserValidationError(INVALID_LINK)
    expires_at = datetime.fromisoformat(reset["expires_at"])
    if reset.get("used_at") or expires_at <= datetime.now(timezone.utc):
        raise UserValidationError(INVALID_LINK)
    user = db.get_user_by_id(reset["user_id"])
    if not user or user.status != "active":
        raise UserValidationError(INVALID_LINK)

    # Check the password before using up the link, so a rejected password can
    # be fixed and tried again with the same link.
    new_hash = user._hash_password(new_password)

    # Claim the link; only one request can.
    if not db.use_password_reset(reset["id"]):
        raise UserValidationError(INVALID_LINK)
    db.update_password(user.id, new_hash)
    db.use_all_password_resets(user.id)
    # Anyone signed in with the old password is signed out.
    db.logout_user(user.id)
    logger.info("Password reset for user %s", user.id)
    return user
