"""Signing in with Google: checking the token, and finding, linking or making
the account. The database is faked, so these run without Supabase."""

import time
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import google_sign_in
from app.google_sign_in import GoogleIdentity, GoogleSignInError
from app.user import User

CLIENT_ID = "test-client.apps.googleusercontent.com"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def google_token(key=_KEY, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "ada@example.com",
        "email_verified": True,
        "given_name": "Ada",
        "name": "Ada Lovelace",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.fixture(autouse=True)
def google(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(google_sign_in, "_signing_key", lambda _t: _KEY.public_key())


class FakeDb:
    def __init__(self):
        self.users: dict[UUID, User] = {}
        self.logged_out: list[UUID] = []

    def get_user_by_google_id(self, google_id):
        return next((u for u in self.users.values() if u.google_id == google_id), None)

    def get_user_by_email(self, email):
        found = [
            u
            for u in self.users.values()
            if u.email and u.email.lower() == email.lower()
        ]
        return found[0] if len(found) == 1 else None

    def get_user_by_username(self, name):
        return next((u for u in self.users.values() if u.username == name), None)

    def get_user_by_id(self, id):
        return self.users.get(id)

    def link_google_id(self, user_id, google_id):
        user = self.users[user_id]
        if user.google_id:
            return False
        user.google_id = google_id
        return True

    def clear_password(self, user_id):
        self.users[user_id]._password_hash = None
        return True

    def mark_email_verified(self, user_id, email):
        user = self.users[user_id]
        if user.email != email:
            return False
        user.email_verified_at = "now"
        return True

    def logout_user(self, user_id):
        self.logged_out.append(user_id)
        return True

    def add_user(self, user):
        for u in self.users.values():
            if u.username == user.username or u.email == user.email:
                raise Exception("duplicate key value violates unique constraint")
        self.users[user.id] = user
        return True


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(google_sign_in, "db", fake)
    return fake


def identity(**overrides) -> GoogleIdentity:
    values = dict(
        sub="1234567890", email="ada@example.com", email_verified=True, name="Ada"
    )
    values.update(overrides)
    return GoogleIdentity(**values)


# ── Checking the token ─────────────────────────────────────────


def test_a_good_token_says_who_it_is_for():
    who = google_sign_in.verify_token(google_token())
    assert who == GoogleIdentity("1234567890", "ada@example.com", True, "Ada")


def test_the_issuer_without_https_is_accepted():
    assert google_sign_in.verify_token(google_token(iss="accounts.google.com"))


@pytest.mark.parametrize(
    "token",
    [
        google_token(key=_OTHER_KEY),
        google_token(aud="someone-else.apps.googleusercontent.com"),
        google_token(iss="https://evil.example"),
        google_token(exp=int(time.time()) - 3600),
        google_token(sub=None),
        google_token(email=None),
        "not-a-token",
        "",
    ],
    ids=[
        "wrong signature",
        "another app",
        "another issuer",
        "expired",
        "no user id",
        "no email",
        "garbage",
        "empty",
    ],
)
def test_bad_tokens_are_refused(token):
    with pytest.raises(GoogleSignInError):
        google_sign_in.verify_token(token)


def test_an_unverified_email_is_reported_as_such():
    who = google_sign_in.verify_token(google_token(email_verified=False))
    assert who.email_verified is False


def test_without_a_client_id_google_sign_in_is_off(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    with pytest.raises(google_sign_in.GoogleSignInUnavailable):
        google_sign_in.verify_token(google_token())


# ── Finding, linking or making the account ─────────────────────


def test_a_new_player_gets_an_account_without_a_password(fake_db):
    user, created = google_sign_in.sign_in(identity())
    assert created
    assert user.username == "Ada"
    assert user.email == "ada@example.com"
    assert user.google_id == "1234567890"
    assert not user._password_hash
    assert user.status == "active" and not user.is_bot
    assert fake_db.users[user.id] is user


def test_signing_in_again_finds_the_same_account(fake_db):
    first, _ = google_sign_in.sign_in(identity())
    again, created = google_sign_in.sign_in(identity(email="ada@new.example"))
    assert again.id == first.id
    assert not created


def test_an_account_with_the_same_email_is_linked(fake_db):
    existing = User("AdaL", "Ada@Example.com", "Password1")
    fake_db.add_user(existing)
    user, created = google_sign_in.sign_in(identity())
    assert user.id == existing.id
    assert not created
    assert existing.google_id == "1234567890"
    assert len(fake_db.users) == 1


def test_linking_removes_the_password_and_signs_everyone_out(fake_db):
    # Registering doesn't check the email, so the password may be someone
    # else's: they registered with this email before its owner came along.
    existing = User("AdaL", "ada@example.com", "Password1")
    fake_db.add_user(existing)
    user, _ = google_sign_in.sign_in(identity())
    assert user._password_hash is None
    assert existing._password_hash is None
    assert not user.verify_secret("Password1", existing._password_hash)
    assert fake_db.logged_out == [existing.id]


def test_linking_verifies_the_email(fake_db):
    existing = User("AdaL", "ada@example.com", "Password1")
    fake_db.add_user(existing)
    assert not existing.email_verified_at
    google_sign_in.sign_in(identity())
    assert existing.email_verified_at


def test_a_new_google_account_has_a_verified_email(fake_db):
    user, _ = google_sign_in.sign_in(identity())
    assert user.email_verified_at


def test_signing_in_to_a_linked_account_keeps_its_password(fake_db):
    existing = User("AdaL", "ada@example.com", "Password1")
    existing.google_id = "1234567890"
    fake_db.add_user(existing)
    google_sign_in.sign_in(identity())
    assert existing.verify_secret("Password1", existing._password_hash)
    assert fake_db.logged_out == []


def test_an_unverified_email_never_links_or_makes_an_account(fake_db):
    fake_db.add_user(User("AdaL", "ada@example.com", "Password1"))
    with pytest.raises(GoogleSignInError, match="hasn't confirmed"):
        google_sign_in.sign_in(identity(email_verified=False))
    assert all(not u.google_id for u in fake_db.users.values())


def test_an_account_linked_to_another_google_account_is_not_taken(fake_db):
    existing = User("AdaL", "ada@example.com", "Password1")
    existing.google_id = "someone-else"
    fake_db.add_user(existing)
    with pytest.raises(GoogleSignInError, match="different Google account"):
        google_sign_in.sign_in(identity())
    assert existing.google_id == "someone-else"


def test_a_deactivated_account_cant_sign_in(fake_db):
    existing = User("AdaL", "ada@example.com", "Password1")
    existing.status = "deactivated"
    fake_db.add_user(existing)
    with pytest.raises(GoogleSignInError, match="isn't active"):
        google_sign_in.sign_in(identity())
    existing.google_id = "1234567890"
    with pytest.raises(GoogleSignInError, match="isn't active"):
        google_sign_in.sign_in(identity())


def test_a_taken_name_gets_a_number(fake_db):
    fake_db.add_user(User("Ada", "other@example.com", "Password1"))
    user, created = google_sign_in.sign_in(identity())
    assert created
    assert user.username.startswith("Ada ")
    assert user.username[4:].isdigit()


@pytest.mark.parametrize(
    "name,email,expected",
    [
        ("Zoë O'Brien", "z@example.com", "Zo OBrien"),
        ("", "jo.bloggs@example.com", "jobloggs"),
        ("李", "li@example.com", "Player"),
        ("A" * 80, "a@example.com", "A" * 40),
    ],
)
def test_names_follow_the_name_rules(fake_db, name, email, expected):
    user, _ = google_sign_in.sign_in(identity(name=name, email=email))
    assert user.username == expected


def test_the_new_accounts_details_include_how_it_signs_in(fake_db):
    user, _ = google_sign_in.sign_in(identity())
    details = user.to_dict(include_email=True)
    assert details["google_linked"] is True
    assert details["has_password"] is False
    assert "google_linked" not in user.to_dict()
