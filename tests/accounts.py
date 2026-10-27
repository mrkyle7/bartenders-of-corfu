"""Making signed-in players for tests that need a Supabase stack.

Registering doesn't sign a player in until they verify their email, so this
registers, marks the email verified as clicking the emailed link would, and
signs in with the password.
"""

from uuid import UUID

from app.db import db


def register(client, username: str, email: str, password: str = "Password1"):
    """Registers and signs in a player; returns the /login response.

    If registering fails, returns that response instead.
    """
    resp = client.post(
        "/register", json={"username": username, "email": email, "password": password}
    )
    if resp.status_code != 201:
        return resp
    assert db.mark_email_verified(UUID(resp.json()["id"]), email.strip())
    return client.post("/login", json={"username": username, "password": password})
