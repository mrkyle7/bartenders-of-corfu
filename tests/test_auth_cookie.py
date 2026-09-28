"""The login cookie, shared across subdomains when COOKIE_DOMAIN is set.

Runs without Supabase: exercises the helpers and the landing middleware on a
stand-in app.
"""

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient
from starlette.responses import Response

from app.auth_cookie import clear_auth_cookie, set_auth_cookie
from app.landing import LandingHostMiddleware


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


@pytest.fixture
def landing(monkeypatch, shared):
    monkeypatch.setenv("LANDING_HOST", "cheetahmoongames.com")
    monkeypatch.setenv("BARTENDERS_URL", "https://bartenders.cheetahmoongames.com")


def _landing_client() -> TestClient:
    app = FastAPI()

    @app.get("/")
    async def lobby():
        return PlainTextResponse("lobby")

    app.add_middleware(LandingHostMiddleware)
    return TestClient(
        app, base_url="http://cheetahmoongames.com", follow_redirects=False
    )


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


# --- Migrating old host-only cookies on the apex ------------------------------


def test_apex_moves_a_host_only_cookie_onto_the_shared_domain(landing):
    resp = _landing_client().get("/", headers={"cookie": "userjwt=old"})
    cookies = _set_cookies(resp)
    # Host-only copy deleted first, then the shared cookie set with the same token.
    assert "Max-Age=0" in cookies[0] and "Domain" not in cookies[0]
    assert cookies[1].startswith("userjwt=old;")
    assert "Domain=cheetahmoongames.com" in cookies[1]


def test_redirects_from_old_links_carry_the_login_over(landing):
    resp = _landing_client().get("/game?id=1", headers={"cookie": "userjwt=old"})
    assert resp.status_code == 307
    assert any(
        c.startswith("userjwt=old;") and "Domain=cheetahmoongames.com" in c
        for c in _set_cookies(resp)
    )


def test_with_two_copies_only_the_stale_host_only_one_is_removed(landing):
    resp = _landing_client().get("/", headers={"cookie": "userjwt=old; userjwt=new"})
    [cookie] = _set_cookies(resp)
    assert "Max-Age=0" in cookie and "Domain" not in cookie


def test_visitors_without_a_login_get_no_cookie(landing):
    resp = _landing_client().get("/", headers={"cookie": "theme=dark"})
    assert _set_cookies(resp) == []


def test_no_migration_without_cookie_domain(monkeypatch, landing):
    monkeypatch.delenv("COOKIE_DOMAIN")
    resp = _landing_client().get("/", headers={"cookie": "userjwt=old"})
    assert _set_cookies(resp) == []
