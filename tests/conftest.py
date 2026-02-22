"""Shared pytest configuration for all tests."""

import json
import os
import subprocess

import pytest


def pytest_configure(config):
    """Set Supabase env vars before any app module is collected/imported."""
    if not os.environ.get("SUPABASE_URL"):
        try:
            result = subprocess.run(
                ["supabase", "status", "-o", "json"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            status = json.loads(result.stdout)
            os.environ["SUPABASE_URL"] = status["API_URL"]
            os.environ["SUPABASE_KEY"] = status["SECRET_KEY"]
        except Exception as exc:
            raise RuntimeError(
                "Supabase is not running. Start it with: "
                "supabase start --network-id k3s-net"
            ) from exc
