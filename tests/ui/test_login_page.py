"""
UI tests for the LoginPage surface (specs/ui-frontend.allium § LoginPage).

Covers:
  - both forms visible simultaneously
  - successful registration redirects to home
  - successful login redirects to home
  - invalid login shows inline error, no alert()
  - duplicate registration shows inline error
"""

from tests.ui.conftest import _api_register, _unique


def test_both_forms_visible(page, base_url):
    """#loginForm and #registerForm are both present on /login."""
    page.goto(f"{base_url}/login")
    assert page.locator("#loginForm").is_visible()
    assert page.locator("#registerForm").is_visible()


def test_register_redirects_home(page, base_url):
    """Filling the register form and submitting redirects to /."""
    username = _unique("reg")
    page.goto(f"{base_url}/login")
    page.fill("#registerForm input[name='username']", username)
    page.fill("#registerForm input[name='email']", f"{username}@test.invalid")
    page.fill("#registerForm input[name='password']", "Password1")
    page.click("#registerForm button[type='submit']")
    page.wait_for_url(base_url + "/", timeout=5000)
    assert page.url == base_url + "/"


def test_login_redirects_home(page, base_url):
    """Registering via API then logging in via the form redirects to /."""
    username = _unique("logintest")
    _api_register(base_url, username)

    page.goto(f"{base_url}/login")
    page.fill("#loginForm input[name='username']", username)
    page.fill("#loginForm input[name='password']", "Password1")
    page.click("#loginForm button[type='submit']")
    page.wait_for_url(base_url + "/", timeout=5000)
    assert page.url == base_url + "/"


def test_invalid_login_inline_error(page, base_url):
    """Wrong password shows inline #message text; no alert() fires."""
    page.on(
        "dialog",
        lambda d: (_ for _ in ()).throw(
            AssertionError(f"Unexpected alert: {d.message}")
        ),
    )

    page.goto(f"{base_url}/login")
    page.fill("#loginForm input[name='username']", "nobody")
    page.fill("#loginForm input[name='password']", "wrongpassword")
    page.click("#loginForm button[type='submit']")

    msg = page.locator("#message")
    msg.wait_for(state="visible", timeout=5000)
    assert msg.inner_text().strip() != ""


def test_invalid_register_inline_error(page, base_url):
    """Duplicate username shows inline #message text."""
    username = _unique("dup")
    _api_register(base_url, username)

    page.goto(f"{base_url}/login")
    page.fill("#registerForm input[name='username']", username)
    page.fill("#registerForm input[name='email']", f"{username}2@test.invalid")
    page.fill("#registerForm input[name='password']", "Password1")
    page.click("#registerForm button[type='submit']")

    msg = page.locator("#message")
    msg.wait_for(state="visible", timeout=5000)
    assert msg.inner_text().strip() != ""
