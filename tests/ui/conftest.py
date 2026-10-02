"""
Playwright UI test fixtures.

Starts a live uvicorn server on port 8765, provides HTTP helpers for
operations that don't need a browser context (e.g. setting up a second
user, creating games via the API).

Supabase env vars are configured by tests/conftest.py pytest_configure hook.
"""

import json
import time
import threading
import urllib.request
import urllib.error
import urllib.parse

import pytest

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
# Signing in happens on cheetahmoongames.com. Under test, /login sends the
# browser here instead (a page the test server doesn't have), so a redirect to
# sign in can be seen without leaving the machine: Playwright can't intercept
# the second hop of a redirect.
SIGN_IN_URL = f"{BASE}/__sign-in"


# ---------------------------------------------------------------------------
# Live server fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def base_url():
    """Start a uvicorn server and yield the base URL."""
    import os

    import uvicorn
    from app.api import app as fastapi_app

    saved_login_url = os.environ.get("LOGIN_URL")
    os.environ["LOGIN_URL"] = SIGN_IN_URL

    server = uvicorn.Server(
        uvicorn.Config(fastapi_app, host="127.0.0.1", port=PORT, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Poll until ready
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{BASE}/health", timeout=1)
            break
        except (urllib.error.URLError, ConnectionRefusedError):
            time.sleep(0.2)
    else:
        raise RuntimeError(f"Server on port {PORT} did not start in time")

    yield BASE

    server.should_exit = True
    thread.join(timeout=5)
    if saved_login_url is None:
        os.environ.pop("LOGIN_URL", None)
    else:
        os.environ["LOGIN_URL"] = saved_login_url


# ---------------------------------------------------------------------------
# Raw HTTP helpers (no browser)
# ---------------------------------------------------------------------------


def _api_register(base_url: str, username: str) -> tuple[dict, str]:
    """Register a new user; returns (user_dict, jwt_token)."""
    body = json.dumps(
        {
            "username": username,
            "email": f"{username}@test.invalid",
            "password": "Password1",
        }
    ).encode()
    req = urllib.request.Request(
        f"{base_url}/register",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        user = json.loads(resp.read())
        # Extract cookie
        cookie_header = resp.headers.get("Set-Cookie", "")
        jwt = ""
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("userjwt="):
                jwt = part[len("userjwt=") :]
                break
        return user, jwt


def _api_get(base_url: str, path: str, jwt: str) -> dict:
    """Make an authenticated GET request and return parsed JSON."""
    req = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Cookie": f"userjwt={jwt}"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


def _api_post(base_url: str, path: str, jwt: str, body: dict | None = None) -> dict:
    """Make an authenticated POST request and return parsed JSON."""
    data = json.dumps(body).encode() if body else b""
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Cookie": f"userjwt={jwt}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


# ---------------------------------------------------------------------------
# Browser-level fixtures
# ---------------------------------------------------------------------------


def _unique(prefix: str) -> str:
    return f"{prefix}_{time.time_ns()}"


@pytest.fixture
def new_user(page, base_url):
    """Register a fresh user through the API and sign the browser in with
    its cookie (signing in happens on cheetahmoongames.com, not here)."""
    username = _unique("u")
    user, jwt = _api_register(base_url, username)
    page.context.add_cookies([{"name": "userjwt", "value": jwt, "url": base_url}])
    user_data = _api_get(base_url, "/userDetails", jwt)
    return {"user": user_data, "jwt": jwt, "username": username}


@pytest.fixture
def sign_in_page(base_url):
    """Where tests expect to be sent to sign in (see SIGN_IN_URL)."""
    return SIGN_IN_URL


@pytest.fixture
def new_game(page, base_url, new_user):
    """Create a game as new_user (browser has the cookie after new_user fixture)."""
    data = _api_post(base_url, "/v1/games", new_user["jwt"])
    return data["id"]


@pytest.fixture
def other_user_and_jwt(base_url):
    """Register a second user without a browser context."""
    username = _unique("other")
    user, jwt = _api_register(base_url, username)
    return {"user": user, "jwt": jwt, "username": username}
