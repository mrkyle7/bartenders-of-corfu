"""The login cookie, shared across subdomains when COOKIE_DOMAIN is set.

Runs without Supabase.
"""

import pytest
from starlette.responses import Response

from app.auth_cookie import clear_auth_cookie, set_auth_cookie


def _set_cookies(response) -> list[str]:
    """Set-Cookie headers, in order, from a Starlette or test-client response."""
    if hasattr(response, "raw_headers"):
        return [
            v.decode()
            for k, v in response.raw_headers
            if k.decode().lower() == "set-cookie"
        ]
    return response.headers.get_list("set-cookie")


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setenv("COOKIE_DOMAIN", "cheetahmoongames.com")


# --- Setting and clearing ------------------------------------------------------


def test_login_cookie_is_shared_across_subdomains(shared):
    response = Response()
    set_auth_cookie(response, "tok")
    [cookie] = _set_cookies(response)
    assert cookie.startswith("userjwt=tok;")
    assert "Domain=cheetahmoongames.com" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert "Max-Age=1209600" in cookie


def test_session_cookie_has_no_max_age(shared):
    response = Response()
    set_auth_cookie(response, "tok", max_age=None)
    [cookie] = _set_cookies(response)
    assert "Max-Age" not in cookie


def test_logout_clears_the_shared_and_any_host_only_cookie(shared):
    response = Response()
    clear_auth_cookie(response)
    cookies = _set_cookies(response)
    assert len(cookies) == 2
    assert all("Max-Age=0" in c for c in cookies)
    assert sum("Domain=cheetahmoongames.com" in c for c in cookies) == 1


def test_without_cookie_domain_the_cookie_is_host_only(monkeypatch):
    monkeypatch.delenv("COOKIE_DOMAIN", raising=False)
    response = Response()
    set_auth_cookie(response, "tok")
    clear_auth_cookie(response)
    cookies = _set_cookies(response)
    assert len(cookies) == 2
    assert not any("Domain" in c for c in cookies)
