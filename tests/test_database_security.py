"""Nothing in the database is public except the public keys.

Supabase serves every table in `public` over its REST API. The server uses
the service role key, which bypasses all of this, but anyone holding the
project's publishable key (the `anon` role) could read or change any table
that isn't locked. So every table must have row level security, the public
roles must have no grants, and the only policy is "anyone can read
public_keys" (which the games use to check login cookies). See "Database
security" in claude.md.

The first tests read the migrations, so they run anywhere. The rest try the
real thing against the local Supabase with its publishable key.
"""

import os
import re
from pathlib import Path

import httpx
import pytest

MIGRATIONS = Path(__file__).parent.parent / "supabase" / "migrations"
# The migration that took every grant away from the public roles. Migrations
# before it are history (Supabase's own default grants among them).
LOCKDOWN = "20261105000001_public_keys_readable.sql"
PUBLIC_TABLE = "public_keys"
PUBLIC_ROLES = r"(anon|authenticated|public)"


def _migrations() -> list[tuple[str, str]]:
    """(file name, SQL without comments), oldest first."""
    found = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        sql = re.sub(r"--[^\n]*", "", path.read_text())
        found.append((path.name, sql))
    return found


def _statements(sql: str) -> list[str]:
    return [" ".join(s.split()) for s in sql.split(";") if s.strip()]


def _created_tables() -> set[str]:
    tables = set()
    for _, sql in _migrations():
        for m in re.finditer(
            r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?\"?(\w+)\"?",
            sql,
            re.IGNORECASE,
        ):
            tables.add(m.group(1).lower())
    return tables


# ── The migrations ─────────────────────────────────────────────


def test_the_lockdown_migration_exists():
    assert (MIGRATIONS / LOCKDOWN).exists()


def test_every_table_gets_row_level_security():
    secured = set()
    for _, sql in _migrations():
        for m in re.finditer(
            r"alter\s+table\s+(?:only\s+)?(?:public\.)?\"?(\w+)\"?\s+enable\s+row\s+level\s+security",
            sql,
            re.IGNORECASE,
        ):
            secured.add(m.group(1).lower())
    missing = _created_tables() - secured
    assert not missing, f"tables without row level security: {sorted(missing)}"


def test_row_level_security_is_never_turned_off():
    for name, sql in _migrations():
        assert not re.search(
            r"(disable|no\s+force)\s+row\s+level\s+security", sql, re.IGNORECASE
        ), f"{name} turns row level security off"


def test_the_only_policy_lets_anyone_read_public_keys():
    for name, sql in _migrations():
        for stmt in _statements(sql):
            if not re.match(r"create\s+policy", stmt, re.IGNORECASE):
                continue
            ok = re.search(
                rf"\bon\s+(public\.)?{PUBLIC_TABLE}\s+for\s+select\s+to\s+anon\s+using\s*\(\s*true\s*\)$",
                stmt,
                re.IGNORECASE,
            )
            assert ok, f"{name} has a policy other than reading public keys: {stmt}"


def test_no_new_grants_to_the_public_roles():
    names = [name for name, _ in _migrations()]
    later = names[names.index(LOCKDOWN) :]
    allowed = re.compile(
        rf"^grant\s+select\s+on\s+(table\s+)?(public\.)?{PUBLIC_TABLE}\s+to\s+anon$",
        re.IGNORECASE,
    )
    for name, sql in _migrations():
        if name not in later:
            continue
        for stmt in _statements(sql):
            if not re.search(rf"\bgrant\b.*\bto\s+{PUBLIC_ROLES}\b", stmt, re.I):
                continue
            assert allowed.match(stmt), f"{name} grants to a public role: {stmt}"


def test_no_security_definer_functions():
    # A security definer function runs as its owner, past row level security.
    for name, sql in _migrations():
        assert not re.search(r"security\s+definer", sql, re.IGNORECASE), (
            f"{name} makes a security definer function"
        )


# ── The real database ──────────────────────────────────────────

pytestmark_live = pytest.mark.requires_supabase


def _settings():
    url = os.environ.get("SUPABASE_URL", "")
    anon = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
    service = os.environ.get("SUPABASE_KEY", "")
    if not url or "placeholder" in url or not service:
        pytest.skip("needs the local Supabase")
    if not anon:
        pytest.fail(
            "Supabase is running but SUPABASE_PUBLISHABLE_KEY isn't set "
            "(conftest.py reads it from `supabase status`)"
        )
    return url.rstrip("/"), anon, service


def _headers(key: str) -> dict:
    return {"apikey": key, "Content-Type": "application/json"}


def _live_tables_and_functions(url: str, service: str) -> tuple[set, set]:
    """Every table and function the REST API knows of (from its OpenAPI)."""
    spec = httpx.get(f"{url}/rest/v1/", headers=_headers(service), timeout=10)
    spec.raise_for_status()
    paths = spec.json().get("paths", {})
    tables = {p.strip("/") for p in paths if p != "/" and not p.startswith("/rpc/")}
    functions = {}  # name -> its argument names
    for path, ops in paths.items():
        if not path.startswith("/rpc/"):
            continue
        args = []
        for param in ops.get("post", {}).get("parameters", []):
            args += list(param.get("schema", {}).get("properties", {}))
        functions[path[len("/rpc/") :]] = args
    return tables | _created_tables(), functions


@pytestmark_live
def test_the_public_api_cannot_read_or_write_any_other_table():
    url, anon, service = _settings()
    tables, _ = _live_tables_and_functions(url, service)
    assert "users" in tables and PUBLIC_TABLE in tables
    for table in sorted(tables - {PUBLIC_TABLE}):
        read = httpx.get(
            f"{url}/rest/v1/{table}?select=*&limit=1", headers=_headers(anon)
        )
        assert read.status_code in (401, 403, 404), (
            f"{table} answered the public key with {read.status_code}: {read.text[:200]}"
        )
        write = httpx.post(f"{url}/rest/v1/{table}", headers=_headers(anon), json={})
        assert write.status_code in (401, 403, 404), (
            f"{table} let the public key write ({write.status_code})"
        )


@pytestmark_live
def test_the_public_api_cannot_run_any_function():
    url, anon, service = _settings()
    _, functions = _live_tables_and_functions(url, service)
    assert functions, "expected the game functions to be listed"
    for fn, args in sorted(functions.items()):
        # Its own argument names, so "no such function" can't pass for "denied".
        body = {arg: None for arg in args}
        r = httpx.post(f"{url}/rest/v1/rpc/{fn}", headers=_headers(anon), json=body)
        assert r.status_code in (401, 403), (
            f"the public key can run {fn} ({r.status_code}: {r.text[:200]})"
        )


@pytestmark_live
def test_anyone_can_read_public_keys_but_not_change_them():
    url, anon, service = _settings()
    kid = "00000000-0000-4000-8000-0000000000ab"
    pem_hex = "\\x" + b"-----BEGIN PUBLIC KEY-----test".hex()
    httpx.post(
        f"{url}/rest/v1/{PUBLIC_TABLE}",
        headers={**_headers(service), "Prefer": "resolution=merge-duplicates"},
        json={"kid": kid, "public_key": pem_hex},
    ).raise_for_status()

    read = httpx.get(
        f"{url}/rest/v1/{PUBLIC_TABLE}?select=public_key&kid=eq.{kid}",
        headers=_headers(anon),
    )
    assert read.status_code == 200, read.text
    assert read.json() == [{"public_key": pem_hex}]

    other = "00000000-0000-4000-8000-0000000000ac"
    insert = httpx.post(
        f"{url}/rest/v1/{PUBLIC_TABLE}",
        headers=_headers(anon),
        json={"kid": other, "public_key": pem_hex},
    )
    assert insert.status_code in (401, 403), insert.text
    update = httpx.patch(
        f"{url}/rest/v1/{PUBLIC_TABLE}?kid=eq.{kid}",
        headers=_headers(anon),
        json={"valid": False},
    )
    assert update.status_code in (401, 403), update.text
    delete = httpx.delete(
        f"{url}/rest/v1/{PUBLIC_TABLE}?kid=eq.{kid}", headers=_headers(anon)
    )
    assert delete.status_code in (401, 403), delete.text
    still = httpx.get(
        f"{url}/rest/v1/{PUBLIC_TABLE}?select=valid&kid=eq.{kid}",
        headers=_headers(service),
    )
    assert still.json() == [{"valid": True}]
