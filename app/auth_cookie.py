"""The login cookie, optionally shared across cheetahmoongames.com subdomains.

With ``COOKIE_DOMAIN`` set (e.g. ``cheetahmoongames.com``) the cookie carries a
``Domain`` attribute, so one login works on the apex and every subdomain. With
it unset (local runs, tests, k3s) the cookie is host-only, exactly as before.

Cookies issued before ``COOKIE_DOMAIN`` existed are host-only on the apex and
never reach a subdomain. ``migrate_legacy_cookie`` moves such a cookie onto the
shared domain when its owner next visits the apex (the landing middleware calls
it), so existing players stay logged in when they follow a link to the game.
"""

import os
from typing import Optional

from starlette.requests import Request
from starlette.responses import Response

COOKIE_NAME = "userjwt"
MAX_AGE = 14 * 24 * 60 * 60  # 14 days


def cookie_domain() -> Optional[str]:
    domain = os.getenv("COOKIE_DOMAIN", "").strip().lstrip(".").lower()
    return domain or None


def set_auth_cookie(
    response: Response, token: str, max_age: Optional[int] = MAX_AGE
) -> None:
    """Set the login cookie. ``max_age=None`` makes it a browser-session cookie."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=False,
        samesite="Strict",
        max_age=max_age,
        domain=cookie_domain(),
    )


def clear_auth_cookie(response: Response) -> None:
    """Remove the login cookie, including any host-only copy from before sharing."""
    domain = cookie_domain()
    if domain:
        response.delete_cookie(key=COOKIE_NAME)
    response.delete_cookie(key=COOKIE_NAME, domain=domain)


def _login_cookie_values(request: Request) -> list[str]:
    # request.cookies collapses duplicates, so read the raw header: a browser
    # holding both a host-only and a shared cookie sends the name twice.
    values = []
    for part in request.headers.get("cookie", "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name == COOKIE_NAME:
            values.append(value)
    return values


def migrate_legacy_cookie(request: Request, response: Response) -> None:
    """On the apex, move a host-only login cookie onto the shared domain."""
    if not cookie_domain():
        return
    values = _login_cookie_values(request)
    if not values:
        return
    # Delete the host-only cookie first, then (re)set the shared one. Browsers
    # disagree on whether the two are the same cookie; in this order every
    # browser ends up with just the shared cookie.
    response.delete_cookie(key=COOKIE_NAME)
    if len(values) == 1:
        set_auth_cookie(response, values[0])
    # With two copies the shared cookie already exists and is the newer login,
    # so only the stale host-only copy is removed.
