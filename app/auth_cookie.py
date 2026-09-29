"""The login cookie, optionally shared across cheetahmoongames.com subdomains.

With ``COOKIE_DOMAIN`` set (e.g. ``cheetahmoongames.com``) the cookie carries a
``Domain`` attribute, so one login works on the apex and every subdomain. With
it unset (local runs, tests, k3s) the cookie is host-only, exactly as before.

Cookies issued before ``COOKIE_DOMAIN`` existed are host-only on the apex.
The cheetahmoongames.com home page (mrkyle7/cheetahmoongames) moves them onto
the shared domain as players pass through it.
"""

import os
from typing import Optional

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
