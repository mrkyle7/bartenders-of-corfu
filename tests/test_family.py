"""Families (app/family.py), with a stand-in for the database."""

from uuid import uuid4

import pytest

from app import family
from app.user import User


class FakeStore:
    def __init__(self, users):
        self.users = {u.id: u for u in users}
        self.asks = []  # (parent_id, email)
        self.links = []  # (parent_id, child_id)

    def get_users_by_ids(self, ids):
        return [self.users[i] for i in ids if i in self.users]

    def get_family_asks_by_parent(self, parent_id):
        return [e for p, e in self.asks if p == parent_id]

    def get_family_asks_by_email(self, email):
        return [p for p, e in self.asks if e == email]

    def add_family_ask(self, parent_id, email):
        if (parent_id, email) not in self.asks:
            self.asks.append((parent_id, email))

    def delete_family_ask(self, parent_id, email):
        self.asks = [a for a in self.asks if a != (parent_id, email)]

    def get_family_children(self, parent_id):
        return [c for p, c in self.links if p == parent_id]

    def get_family_parents(self, child_id):
        return [p for p, c in self.links if c == child_id]

    def add_family_link(self, parent_id, child_id):
        if (parent_id, child_id) not in self.links:
            self.links.append((parent_id, child_id))

    def delete_family_link(self, parent_id, child_id):
        self.links = [x for x in self.links if x != (parent_id, child_id)]


def _user(name, email):
    # Only what family.py reads: no password to hash.
    u = User.__new__(User)
    u.id = uuid4()
    u.username = name
    u.email = email
    u.status = "active"
    u.deleted_at = None
    return u


@pytest.fixture
def people():
    mum = _user("Mum", "mum@example.com")
    zed = _user("Zed", "Zed@Example.com")
    lou = _user("Lou", "lou@example.com")
    return mum, zed, lou, FakeStore([mum, zed, lou])


def test_a_parent_sees_a_child_once_the_child_says_yes(people):
    mum, zed, _, store = people
    family.ask(mum, " ZED@example.com ", store)
    assert family.view(mum, store)["asked"] == ["zed@example.com"]
    assert family.children(mum, store) == []
    # Zed sees who's asking, whatever case his email's in.
    assert family.view(zed, store)["requests"] == [{"id": str(mum.id), "name": "Mum"}]
    family.answer(zed, str(mum.id), True, store)
    assert family.children(mum, store) == [{"id": str(zed.id), "name": "Zed"}]
    assert family.view(zed, store)["parents"] == [{"id": str(mum.id), "name": "Mum"}]
    assert family.view(zed, store)["requests"] == []
    assert family.view(mum, store)["asked"] == []


def test_a_child_can_say_no(people):
    mum, zed, _, store = people
    family.ask(mum, "zed@example.com", store)
    family.answer(zed, str(mum.id), False, store)
    assert family.children(mum, store) == []
    assert family.view(mum, store)["asked"] == []


def test_nobody_can_answer_for_someone_else(people):
    mum, _, lou, store = people
    family.ask(mum, "zed@example.com", store)
    with pytest.raises(family.FamilyError):
        family.answer(lou, str(mum.id), True, store)
    with pytest.raises(family.FamilyError):
        family.answer(lou, "not-an-id", True, store)
    assert family.children(mum, store) == []


def test_either_can_undo_a_link(people):
    mum, zed, lou, store = people
    for child in (zed, lou):
        family.ask(mum, child.email, store)
        family.answer(child, str(mum.id), True, store)
    family.remove(zed, str(mum.id), store)
    family.remove(mum, str(lou.id), store)
    assert family.children(mum, store) == []


def test_bad_asks_are_refused(people):
    mum, _, _, store = people
    for email in ("nope", "", "mum@example.com", "MUM@example.com"):
        with pytest.raises(family.FamilyError):
            family.ask(mum, email, store)
    for i in range(family.MAX_ASKS):
        family.ask(mum, f"kid{i}@example.com", store)
    with pytest.raises(family.FamilyError):
        family.ask(mum, "one-more@example.com", store)
    family.unask(mum, "kid0@example.com", store)
    family.ask(mum, "one-more@example.com", store)


def test_closed_accounts_are_not_shown(people):
    mum, zed, _, store = people
    family.ask(mum, "zed@example.com", store)
    family.answer(zed, str(mum.id), True, store)
    zed.status = "deactivated"
    assert family.children(mum, store) == []
