"""Families: parents see how their children are doing in the Cheetah Moon games.

A parent asks for a child by the email on the child's account. Nothing is
shared until the child, signed in, says yes (cheetahmoongames.com/family,
which passes these on through its /api/family routes), so nobody can see a
child's games just by knowing their email. Either of them can undo a link.

Games ask who a parent's children are (``children``) with the parent's own
login cookie, through cheetahmoongames.com's /api/family/children, and show
only those children's results.

Every function takes the signed-in ``User`` and a ``store`` (``app.db.db``,
or a stand-in in tests). The answers are what the family page shows:
``view(user)``.
"""

import re
from uuid import UUID

from app.user import User

MAX_ASKS = 10  # emails one parent can be asking for at once
MAX_LINKS = 20  # children one parent can have, and parents one child can have
EMAIL = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}$")


class FamilyError(Exception):
    """Something the player asked for that can't be done, said for players."""


def _people(store, ids: list[UUID]) -> list[dict]:
    """``{id, name}`` for each active account, in the order given."""
    if not ids:
        return []
    users = {u.id: u for u in store.get_users_by_ids(set(ids))}
    return [
        {"id": str(i), "name": users[i].username}
        for i in ids
        if i in users and users[i].status == "active" and not users[i].deleted_at
    ]


def _email(user: User) -> str:
    return (user.email or "").strip().lower()


def view(user: User, store) -> dict:
    """Everything about ``user``: their children, the emails they're asking
    for, who's asking for them, and their parents."""
    email = _email(user)
    return {
        "me": {"id": str(user.id), "name": user.username},
        "children": _people(store, store.get_family_children(user.id)),
        "asked": store.get_family_asks_by_parent(user.id),
        "requests": _people(store, store.get_family_asks_by_email(email))
        if email
        else [],
        "parents": _people(store, store.get_family_parents(user.id)),
    }


def children(user: User, store) -> list[dict]:
    """``user``'s children, for games: ``[{id, name}]``."""
    return _people(store, store.get_family_children(user.id))


def ask(user: User, email: str, store) -> None:
    """``user`` asks to be the parent of the account with ``email``."""
    email = (email or "").strip().lower()
    if not EMAIL.match(email):
        raise FamilyError("That doesn't look like an email address.")
    if email == _email(user):
        raise FamilyError("That's your own email.")
    asked = store.get_family_asks_by_parent(user.id)
    if email in asked:
        return
    if len(asked) >= MAX_ASKS:
        raise FamilyError("That's as many as you can ask for at once.")
    store.add_family_ask(user.id, email)


def unask(user: User, email: str, store) -> None:
    store.delete_family_ask(user.id, (email or "").strip().lower())


def answer(user: User, parent_id: str, allow: bool, store) -> None:
    """A child's answer to a parent asking for their email."""
    email = _email(user)
    try:
        parent = UUID(str(parent_id))
    except ValueError:
        raise FamilyError("They aren't asking any more.") from None
    if not email or parent not in store.get_family_asks_by_email(email):
        raise FamilyError("They aren't asking any more.")
    if allow:
        if len(store.get_family_parents(user.id)) >= MAX_LINKS:
            raise FamilyError("That's as many parents as there can be.")
        if len(store.get_family_children(parent)) >= MAX_LINKS:
            raise FamilyError("They have as many children as there can be.")
        store.add_family_link(parent, user.id)
    store.delete_family_ask(parent, email)


def remove(user: User, other_id: str, store) -> None:
    """Undo a link between ``user`` and ``other_id``, whichever is the parent."""
    try:
        other = UUID(str(other_id))
    except ValueError:
        return
    store.delete_family_link(user.id, other)
    store.delete_family_link(other, user.id)
