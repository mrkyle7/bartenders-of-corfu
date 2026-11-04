"""Families: parents see how their children are doing in the Cheetah Moon games.

A parent asks for a child by the email on the child's account. Nothing is
shared until the child, signed in, says yes (cheetahmoongames.com/family,
which passes these on through its /api/family routes), so nobody can see a
child's games just by knowing their email. Either of them can undo a link.

A parent can also make a child account (``make_child``): it has no email or
password, so the child can't sign in to it on their own. The parent switches
to it to let the child play (``child_to_play``), and the games keep the
child's results against it; switching back needs the parent's own password
(api.py). It's linked to the parent as their child when it's made.

Games ask who a parent's children are (``children``) with the parent's own
login cookie, through cheetahmoongames.com's /api/family/children, and show
only those children's results.

Every function takes the signed-in ``User`` and a ``store`` (``app.db.db``,
or a stand-in in tests). The answers are what the family page shows:
``view(user)``.
"""

import re
from uuid import UUID

from app.user import User, UserValidationError

MAX_ASKS = 10  # emails one parent can be asking for at once
MAX_LINKS = 20  # children one parent can have, and parents one child can have
MAX_CHILD_ACCOUNTS = 10  # child accounts one parent can make
EMAIL = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}$")


class FamilyError(Exception):
    """Something the player asked for that can't be done, said for players."""


def _people(store, ids: list[UUID], managed_by: UUID | None = None) -> list[dict]:
    """``{id, name}`` for each active account, in the order given. With
    ``managed_by``, the child accounts that parent made are marked ``managed``
    (they can switch to them)."""
    if not ids:
        return []
    users = {u.id: u for u in store.get_users_by_ids(set(ids))}
    people = []
    for i in ids:
        if i not in users or users[i].status != "active" or users[i].deleted_at:
            continue
        person = {"id": str(i), "name": users[i].username}
        if (
            managed_by is not None
            and getattr(users[i], "managed_by", None) == managed_by
        ):
            person["managed"] = True
        people.append(person)
    return people


def is_child_account(user: User) -> bool:
    return bool(getattr(user, "managed_by", None))


def _email(user: User) -> str:
    return (user.email or "").strip().lower()


def view(user: User, store) -> dict:
    """Everything about ``user``: their children, the emails they're asking
    for, who's asking for them, and their parents."""
    email = _email(user)
    return {
        "me": {"id": str(user.id), "name": user.username},
        "children": _people(
            store, store.get_family_children(user.id), managed_by=user.id
        ),
        "childAccount": is_child_account(user),
        "asked": store.get_family_asks_by_parent(user.id),
        "requests": _people(store, store.get_family_asks_by_email(email))
        if email
        else [],
        "parents": _people(store, store.get_family_parents(user.id)),
    }


def children(user: User, store) -> list[dict]:
    """``user``'s children, for games: ``[{id, name}]``."""
    return _people(store, store.get_family_children(user.id))


def _not_a_child_account(user: User) -> None:
    if is_child_account(user):
        raise FamilyError("A grown-up needs to do that from their own account.")


def make_child(user: User, name: str, store) -> User:
    """``user`` makes a child account called ``name``, linked to them as
    their child."""
    _not_a_child_account(user)
    made = [c for c in store.get_family_children(user.id)]
    mine = [
        u
        for u in store.get_users_by_ids(set(made))
        if getattr(u, "managed_by", None) == user.id
    ]
    if len(mine) >= MAX_CHILD_ACCOUNTS:
        raise FamilyError("That's as many child accounts as you can make.")
    if len(made) >= MAX_LINKS:
        raise FamilyError("You have as many children as there can be.")
    try:
        child = User.new_child((name or "").strip(), user.id)
    except UserValidationError as e:
        raise FamilyError(str(e).rstrip(".") + ".") from None
    if store.get_user_by_username(child.username):
        raise FamilyError(
            "That name's taken. Try another, like adding a letter or a number."
        )
    store.add_user(child)
    store.add_family_link(user.id, child.id)
    return child


def child_to_play(user: User, child_id: str, store) -> User:
    """The child account ``user`` may switch to: one they made, still linked
    to them as their child."""
    _not_a_child_account(user)
    try:
        cid = UUID(str(child_id))
    except ValueError:
        raise FamilyError("That isn't one of your child accounts.") from None
    child = next(iter(store.get_users_by_ids({cid})), None)
    if (
        not child
        or getattr(child, "managed_by", None) != user.id
        or cid not in store.get_family_children(user.id)
        or child.status != "active"
        or child.deleted_at
    ):
        raise FamilyError("That isn't one of your child accounts.")
    return child


def ask(user: User, email: str, store) -> None:
    """``user`` asks to be the parent of the account with ``email``."""
    _not_a_child_account(user)
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
    _not_a_child_account(user)
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
    _not_a_child_account(user)
    try:
        other = UUID(str(other_id))
    except ValueError:
        return
    store.delete_family_link(user.id, other)
    store.delete_family_link(other, user.id)
