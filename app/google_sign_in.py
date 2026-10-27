"""Signing in with Google.

The cheetahmoongames.com sign-in page shows Google's "Sign in with Google"
button, which hands the browser a Google ID token: a JWT signed by Google that
says who the player is. The page passes it here, and ``sign_in(token)``:

1. checks the token: Google's signature, issued for our client
   (``GOOGLE_CLIENT_ID``), not expired;
2. finds the account already linked to that Google account (by Google's user
   ID, ``sub``, which stays the same if the Google email changes);
3. otherwise links the account that uses the same email, if Google has
   verified that the email is theirs. Registering never checks the email, so
   that account's password may have been set by someone else (who registered
   with this email first, to wait for the owner to arrive): linking removes the
   password and signs out everyone using the account;
4. otherwise makes a new account, with a name taken from the Google profile
   and no password (the player can set one with a reset link).
"""

import logging
import os
import re
import secrets
from dataclasses import dataclass

import jwt

from app.db import db
from app.user import User, UserValidationError

logger = logging.getLogger(__name__)

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

INVALID_TOKEN = "Google sign-in didn't work. Please try again."
UNVERIFIED_EMAIL = (
    "Google hasn't confirmed that email address is yours, so it can't be used "
    "to sign in. Sign in with your name and password instead."
)
ACCOUNT_INACTIVE = "The account for that email isn't active."
LINKED_ELSEWHERE = (
    "The account for that email is already linked to a different Google "
    "account. Sign in with your name and password instead."
)

_jwks_client: jwt.PyJWKClient | None = None


class GoogleSignInError(Exception):
    """A sign-in that can't go ahead. The message is written for players."""


class GoogleSignInUnavailable(Exception):
    """Google sign-in isn't set up on this server."""


@dataclass
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    name: str


def client_id() -> str | None:
    return os.getenv("GOOGLE_CLIENT_ID", "").strip() or None


def _signing_key(token: str):
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(GOOGLE_CERTS_URL, lifespan=3600)
    return _jwks_client.get_signing_key_from_jwt(token).key


def verify_token(token: str) -> GoogleIdentity:
    """Checks a Google ID token and returns who it is for."""
    audience = client_id()
    if not audience:
        raise GoogleSignInUnavailable()
    if not isinstance(token, str) or not token or len(token) > 4096:
        raise GoogleSignInError(INVALID_TOKEN)
    try:
        claims = jwt.decode(
            token,
            _signing_key(token),
            algorithms=["RS256"],
            audience=audience,
            issuer=GOOGLE_ISSUERS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=60,
        )
    except Exception as e:
        logger.warning("Rejected a Google ID token: %s", e)
        raise GoogleSignInError(INVALID_TOKEN)
    sub = claims.get("sub")
    email = claims.get("email")
    if not isinstance(sub, str) or not sub or not isinstance(email, str) or not email:
        raise GoogleSignInError(INVALID_TOKEN)
    verified = claims.get("email_verified")
    return GoogleIdentity(
        sub=sub,
        email=email.strip(),
        email_verified=verified is True or verified == "true",
        name=claims.get("given_name") or claims.get("name") or "",
    )


def _base_name(identity: GoogleIdentity) -> str:
    """A player name from the Google profile, fitting the name rules."""
    raw = identity.name or identity.email.split("@")[0]
    name = re.sub(r"[^A-Za-z0-9 _\-]", "", raw)
    name = re.sub(r"\s+", " ", name).strip()[:40].strip()
    return name if len(name) >= 3 else "Player"


def _candidate_names(identity: GoogleIdentity):
    base = _base_name(identity)
    yield base
    for _ in range(8):
        yield f"{base} {secrets.randbelow(9000) + 1000}"


def _link(user: User, identity: GoogleIdentity) -> User:
    if user.status != "active" or user.is_bot:
        raise GoogleSignInError(ACCOUNT_INACTIVE)
    if user.google_id and user.google_id != identity.sub:
        raise GoogleSignInError(LINKED_ELSEWHERE)
    if not user.google_id:
        if not db.link_google_id(user.id, identity.sub):
            # Linked by another request just now: only fine if it was this one.
            again = db.get_user_by_id(user.id)
            if not again or again.google_id != identity.sub:
                raise GoogleSignInError(LINKED_ELSEWHERE)
        user.google_id = identity.sub
        # Whoever set the password may not own the email. Only Google (or a
        # reset link, which goes to the email) signs in from now on.
        if user._password_hash:
            db.clear_password(user.id)
            user._password_hash = None
        db.logout_user(user.id)
        logger.info("Linked a Google account to user %s", user.id)
    return user


def sign_in(identity: GoogleIdentity) -> tuple[User, bool]:
    """The account for a Google identity, linking or making one if needed.

    Returns the user and whether the account is new.
    """
    user = db.get_user_by_google_id(identity.sub)
    if user:
        if user.status != "active" or user.is_bot:
            raise GoogleSignInError(ACCOUNT_INACTIVE)
        return user, False

    # Only an email Google has checked belongs to this person may claim an
    # account, or anyone could take over an account by its email.
    if not identity.email_verified:
        raise GoogleSignInError(UNVERIFIED_EMAIL)

    existing = db.get_user_by_email(identity.email)
    if existing:
        return _link(existing, identity), False

    for name in _candidate_names(identity):
        if db.get_user_by_username(name):
            continue
        try:
            user = User.new_google(name, identity.email, identity.sub)
        except UserValidationError:
            raise GoogleSignInError(INVALID_TOKEN)
        try:
            db.add_user(user)
        except Exception as e:
            if "duplicate key" not in str(e):
                raise
            # Another request made or linked this account at the same moment.
            if found := db.get_user_by_google_id(identity.sub):
                return found, False
            if found := db.get_user_by_email(identity.email):
                return _link(found, identity), False
            continue  # the name was taken: try another
        logger.info("Created user %s by signing in with Google", user.id)
        return user, True
    raise GoogleSignInError(INVALID_TOKEN)
