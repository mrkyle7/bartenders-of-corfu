"""Verifying that a player owns their email.

Registering doesn't sign the player in: it emails them a link, and they can
sign in with their password once they've clicked it. Otherwise anyone could
register with someone else's email and keep the account when its owner later
signs in with Google or resets the password.

1. ``send_link(user)``: store the hash of a new random token and email the
   account a link carrying it. Sent on registering, and again whenever the
   player signs in with the right password but hasn't verified yet.
2. ``request_email_change(user, new_email)``: the same, to a new address. The
   account's email only changes when that link is clicked.
3. ``complete(token)``: if the token matches an unused, unexpired link, mark
   the email verified (or change to the new one) and return the user so the
   caller can sign them in.

Signing in with Google and resetting a password also verify the email (both
show the player owns it), in ``google_sign_in`` and ``password_reset``.
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

LINK_LIFETIME = timedelta(hours=24)
MAX_LINKS_PER_HOUR = 3
NOT_VERIFIED = (
    "Please verify your email first. We've sent you a link: click it to sign in."
)
INVALID_LINK = (
    "This link has expired or has already been used. Sign in with your name "
    "and password and we'll send you a new one."
)
EMAIL_TAKEN = "That email is already used by another account."


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _verify_url(token: str, next_url: str | None) -> str:
    base = os.getenv("VERIFY_EMAIL_URL", "https://cheetahmoongames.com/verify-email")
    params = {"token": token}
    if next_url:
        params["next"] = next_url
    return f"{base}?{urlencode(params)}"


def _email(user: User, url: str, changing: bool) -> tuple[str, str, str]:
    subject = "Verify your Cheetah Moon email"
    name = html.escape(user.username or "")
    link = html.escape(url, quote=True)
    if changing:
        why = "asked to use this email for your Cheetah Moon Games account"
        ignore = "your account keeps its current email"
    else:
        why = "made a Cheetah Moon Games account with this email"
        ignore = "no account will use this email"
    body_html = f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#0d0f1c;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;color:#f1f2f8">
<div style="max-width:480px;margin:0 auto;background:#1b2038;border:1px solid #2c3354;border-radius:12px;padding:28px">
<h1 style="margin:0 0 16px;font-size:22px">Verify your email</h1>
<p style="margin:0 0 16px;line-height:1.5">Hi {name}, someone (hopefully you) {why}.</p>
<p style="margin:0 0 24px"><a href="{link}" style="display:inline-block;background:#f3d36b;color:#1a1405;font-weight:700;text-decoration:none;padding:12px 20px;border-radius:6px">Verify my email</a></p>
<p style="margin:0 0 8px;color:#a6acc8;font-size:14px;line-height:1.5">The link works once, for the next 24 hours. If this wasn't you, ignore this email and {ignore}.</p>
<p style="margin:0;color:#a6acc8;font-size:13px;word-break:break-all">{link}</p>
</div></body></html>"""
    body_text = (
        f"Hi {user.username},\n\n"
        f"Someone (hopefully you) {why}. Verify it here:\n\n"
        f"{url}\n\n"
        "The link works once, for the next 24 hours. If this wasn't you, "
        f"ignore this email and {ignore}.\n"
    )
    return subject, body_html, body_text


def _send(user: User, email: str, next_url: str | None) -> None:
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    if db.count_email_verifications_since(user.id, since) >= MAX_LINKS_PER_HOUR:
        logger.warning("Too many verification emails for user %s; not sending", user.id)
        return
    token = secrets.token_urlsafe(32)
    db.add_email_verification(
        user.id, email, _hash(token), datetime.now(timezone.utc) + LINK_LIFETIME
    )
    changing = email.lower() != (user.email or "").lower()
    subject, body_html, body_text = _email(user, _verify_url(token, next_url), changing)
    if email_sender.send_email(email, user.username, subject, body_html, body_text):
        logger.info("Sent a verification email to user %s", user.id)


def send_link(user: User, next_url: str | None = None) -> None:
    """Email the account a link to verify its email. Never raises."""
    try:
        if user.is_bot or not user.email or user.status != "active":
            return
        _send(user, user.email, next_url)
    except Exception:
        logger.exception("Sending a verification email failed")


def request_email_change(user: User, new_email: str) -> bool:
    """Email a link that changes the account's email to ``new_email``.

    Returns False if there was nothing to do: it is already the account's
    verified email. Raises UserValidationError with a message for the player.
    """
    email = user._validate_email(new_email)
    if email.lower() == (user.email or "").lower() and user.email_verified_at:
        return False
    other = db.get_user_by_email(email)
    if other and other.id != user.id:
        raise UserValidationError(EMAIL_TAKEN)
    _send(user, email, None)
    return True


def complete(token: str) -> User:
    """Verify an email from a link.

    Raises UserValidationError with a message for the player if the link isn't
    valid.
    """
    if not isinstance(token, str) or not token or len(token) > 200:
        raise UserValidationError(INVALID_LINK)
    link = db.get_email_verification(_hash(token))
    if not link:
        raise UserValidationError(INVALID_LINK)
    expires_at = datetime.fromisoformat(link["expires_at"])
    if link.get("used_at") or expires_at <= datetime.now(timezone.utc):
        raise UserValidationError(INVALID_LINK)
    user = db.get_user_by_id(link["user_id"])
    if not user or user.status != "active" or user.is_bot:
        raise UserValidationError(INVALID_LINK)

    email = link["email"]
    changing = email.lower() != (user.email or "").lower()
    if changing:
        other = db.get_user_by_email(email)
        if other and other.id != user.id:
            raise UserValidationError(EMAIL_TAKEN)

    # Claim the link; only one request can.
    if not db.use_email_verification(link["id"]):
        raise UserValidationError(INVALID_LINK)
    if changing:
        try:
            db.change_verified_email(user.id, email)
        except Exception as e:
            if "duplicate key" in str(e):
                raise UserValidationError(EMAIL_TAKEN)
            raise
        # Links to the old email (or other new ones) would now change it back.
        db.use_all_email_verifications(user.id)
        logger.info("Changed the email for user %s", user.id)
    else:
        db.mark_email_verified(user.id, user.email)
        logger.info("Verified the email for user %s", user.id)
    user.email = email
    user.email_verified_at = datetime.now(timezone.utc).isoformat()
    return user
