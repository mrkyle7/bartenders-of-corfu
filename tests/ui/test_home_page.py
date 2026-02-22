"""
UI tests for the HomePage surface (specs/ui-frontend.allium § HomePage).

Covers:
  - game list visible without auth
  - login/logout header links
  - create game redirects to login when unauthenticated
  - join redirects to login when unauthenticated
  - authenticated header shows username
  - create game adds entry to list ("Go to Game")
  - join game shows "Go to Game"
  - logout switches header back to login link
  - joining a full game shows an inline error, no alert()
"""

import json
import time
import pytest
from tests.ui.conftest import _api_register, _api_post, _unique


# ---------------------------------------------------------------------------
# Unauthenticated visitor tests
# ---------------------------------------------------------------------------

def test_game_list_visible_without_auth(page, base_url):
    """#gameList is rendered even without a session cookie."""
    page.goto(base_url)
    game_list = page.locator("#gameList")
    game_list.wait_for(state="visible")
    assert game_list.is_visible()


def test_login_link_shown_unauthenticated(page, base_url):
    """Unauthenticated: #loginLink is visible, #logoutLink is hidden."""
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    assert page.locator("#loginLink").is_visible()
    assert not page.locator("#logoutLink").is_visible()


def test_create_game_redirects_to_login(page, base_url):
    """Clicking Start without auth should redirect to /login."""
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    page.click("button[aria-label='Start new game']")
    page.wait_for_url(f"{base_url}/login")
    assert "/login" in page.url


def test_join_redirects_to_login(page, base_url, other_user_and_jwt):
    """Unauthenticated visitor: clicking 'Login to Join' navigates to /login."""
    # Other user creates a game
    _api_post(base_url, "/v1/games", other_user_and_jwt["jwt"])

    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    # Expect a "Login to Join" button
    btn = page.locator("button", has_text="Login to Join").first
    btn.wait_for(state="visible")
    btn.click()
    page.wait_for_url(f"{base_url}/login")
    assert "/login" in page.url


# ---------------------------------------------------------------------------
# Authenticated visitor tests
# ---------------------------------------------------------------------------

def test_authenticated_header(page, base_url, new_user):
    """Authenticated: #helloUser contains the username."""
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    hello = page.locator("#helloUser")
    hello.wait_for(state="visible")
    assert new_user["username"] in hello.inner_text()


def test_logout_shown_authenticated(page, base_url, new_user):
    """Authenticated: logout is visible, login is hidden."""
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    assert page.locator("#logoutLink").is_visible()
    assert not page.locator("#loginLink").is_visible()


def test_create_game_adds_to_list(page, base_url, new_user):
    """Creating a game adds a 'Go to Game' button to the list."""
    page.goto(base_url)
    # new_user fixture leaves the page at / (home) after registration
    page.wait_for_load_state("networkidle")
    page.click("button[aria-label='Start new game']")
    # Poll until "Go to Game" appears (avoids networkidle/microtask race)
    page.wait_for_function(
        "Array.from(document.querySelectorAll('button')).some(b => b.textContent === 'Go to Game')",
        timeout=30000,
    )
    go_btn = page.locator("button", has_text="Go to Game").first
    assert go_btn.is_visible()


def test_join_game_shows_go_to_game(page, base_url, new_user, other_user_and_jwt):
    """Joining another user's game replaces 'Join Game' with 'Go to Game'."""
    game = _api_post(base_url, "/v1/games", other_user_and_jwt["jwt"])
    game_id = game["id"]
    page.goto(base_url)
    page.wait_for_load_state("networkidle")

    # Wait for this specific game's Join button to appear
    page.wait_for_function(
        f"Array.from(document.querySelectorAll('li')).some(li => "
        f"li.dataset.gameId === '{game_id}' && "
        f"li.querySelector('button') && li.querySelector('button').textContent === 'Join Game')",
        timeout=30000,
    )
    join_btn = page.locator(f"li[data-game-id='{game_id}'] button", has_text="Join Game")
    join_btn.click()

    go_btn = page.locator("button", has_text="Go to Game").first
    go_btn.wait_for(state="visible", timeout=30000)
    assert go_btn.is_visible()


def test_logout_switches_header(page, base_url, new_user):
    """Clicking logout hides the logout link and shows the login link."""
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    page.locator("#logoutLink").click()
    login_link = page.locator("#loginLink")
    login_link.wait_for(state="visible", timeout=5000)
    assert login_link.is_visible()
    assert not page.locator("#logoutLink").is_visible()


def test_full_game_shows_game_full(page, base_url, new_user):
    """A full game (4 players) shows 'Game Full' instead of a join button."""
    # Create a game as new_user and fill it with 3 more players (4 total = full)
    game = _api_post(base_url, "/v1/games", new_user["jwt"])
    game_id = game["id"]
    for i in range(3):
        filler = _unique(f"filler{i}")
        _, filler_jwt = _api_register(base_url, filler)
        _api_post(base_url, f"/v1/games/{game_id}/join", filler_jwt)

    # Switch to a different user by registering via the login form
    another = _unique("another")
    page.goto(f"{base_url}/login")
    page.fill("#registerForm input[name='username']", another)
    page.fill("#registerForm input[name='email']", f"{another}@test.invalid")
    page.fill("#registerForm input[name='password']", "Password1")
    page.click("#registerForm button[type='submit']")
    page.wait_for_url(base_url + "/", timeout=10000)

    page.wait_for_load_state("networkidle")

    # Poll until the specific game's entry shows "Game Full"
    page.wait_for_function(
        f"Array.from(document.querySelectorAll('li')).some(li => "
        f"li.dataset.gameId === '{game_id}' && "
        f"li.textContent.includes('Game Full'))",
        timeout=30000,
    )
    game_li = page.locator(f"li[data-game-id='{game_id}']")
    assert "Game Full" in game_li.inner_text()
    # No join button should be present for a full game
    assert game_li.locator("button", has_text="Join Game").count() == 0
