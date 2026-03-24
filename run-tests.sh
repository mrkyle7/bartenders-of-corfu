#!/bin/bash
set -e

echo "=== Running unit tests ==="
uv run pytest tests/test_user.py tests/test_utils.py -v --tb=long

echo "=== Running API tests ==="
uv run pytest tests/test_api.py -v --tb=long

echo "=== Running user management tests ==="
uv run pytest tests/test_user_management.py -v --tb=long

echo "=== Running JWT tests ==="
uv run pytest tests/test_jwt_handler.py -v --tb=long

echo "=== Running game manager tests ==="
uv run pytest tests/test_game_manager.py -v --tb=long

echo "=== Running game action BDD tests ==="
uv run pytest tests/test_game_actions_bdd.py -v --tb=long

echo "=== Running theme BDD tests ==="
uv run pytest tests/test_theme_bdd.py -v --tb=long

echo "=== Running game tests ==="
uv run pytest tests/test_game.py -v --tb=long

echo "=== Running UI tests ==="
uv run pytest tests/ui/ -v --tb=long

echo "=== All tests passed ==="
