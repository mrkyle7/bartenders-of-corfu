"""Shared pytest configuration for all tests.

Test files are split into two groups:

* **Pure** tests that exercise game logic only — they pass without Supabase.
* **Supabase-dependent** tests that import modules which talk to the database
  at import time (e.g. ``app.api`` initialises ``JWTHandler``, which registers
  a signing key) or that exercise the API/UI end-to-end.

When Supabase is running locally, all tests collect and run as before. When
it isn't, the Supabase-dependent files are skipped at collection time so
``pytest`` still gives fast feedback on the rest. CI starts Supabase before
running tests, so coverage there is unchanged.
"""

import json
import os
import subprocess

# Files that require a live Supabase to even import or instantiate. These are
# skipped when Supabase isn't reachable from this environment.
_SUPABASE_DEPENDENT_FILES = {
    "test_api.py",
    "test_user_management.py",
    "test_user_manager.py",
    "test_jwt_handler.py",
    "test_theme_bdd.py",
    "test_game_manager.py",
    "test_game_actions_bdd.py",
}

SUPABASE_AVAILABLE = False


def pytest_configure(config):
    """Detect Supabase and populate env vars; never raise."""
    global SUPABASE_AVAILABLE
    config.addinivalue_line(
        "markers",
        "requires_supabase: test needs a running Supabase stack",
    )
    if os.environ.get("SUPABASE_URL"):
        SUPABASE_AVAILABLE = True
        return
    try:
        result = subprocess.run(
            ["supabase", "status", "-o", "json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "supabase status failed")
        status = json.loads(result.stdout)
        os.environ["SUPABASE_URL"] = status["API_URL"]
        os.environ["SUPABASE_KEY"] = status["SECRET_KEY"]
        SUPABASE_AVAILABLE = True
    except Exception:
        # No Supabase available: set placeholders so module imports that
        # construct supabase.Client at module scope don't error out, and let
        # pytest_ignore_collect skip the dependent files.
        os.environ.setdefault("SUPABASE_URL", "http://placeholder.invalid")
        os.environ.setdefault("SUPABASE_KEY", "placeholder")
        SUPABASE_AVAILABLE = False


def pytest_ignore_collect(collection_path, config):
    """Skip Supabase-dependent files when Supabase isn't available."""
    if SUPABASE_AVAILABLE:
        return False
    parts = collection_path.parts
    if "ui" in parts:
        return True
    return collection_path.name in _SUPABASE_DEPENDENT_FILES


def pytest_collection_modifyitems(config, items):
    """Skip individual tests marked ``requires_supabase`` when not available."""
    if SUPABASE_AVAILABLE:
        return
    import pytest

    skip_marker = pytest.mark.skip(reason="Supabase not available")
    for item in items:
        if "requires_supabase" in item.keywords:
            item.add_marker(skip_marker)


def pytest_report_header(config):
    """Surface the Supabase state at the top of the pytest run."""
    if SUPABASE_AVAILABLE:
        return "supabase: available — all tests will run"
    return (
        "supabase: NOT available — Supabase-dependent files skipped "
        "(start it with `supabase start` to run the full suite)"
    )
