#!/bin/bash
# Run all test groups and report which ones fail
FAILED=""

run_group() {
    local name="$1"
    shift
    echo ""
    echo "========================================"
    echo "=== $name ==="
    echo "========================================"
    if uv run pytest "$@" -v --tb=long; then
        echo "=== PASSED: $name ==="
    else
        echo "=== FAILED: $name ==="
        FAILED="$FAILED  - $name\n"
    fi
}

run_group "Unit tests"          tests/test_user.py tests/test_utils.py tests/test_game.py
run_group "API tests"           tests/test_api.py
run_group "User management"     tests/test_user_management.py
run_group "JWT tests"           tests/test_jwt_handler.py
run_group "Game manager"        tests/test_game_manager.py
run_group "Game actions BDD"    tests/test_game_actions_bdd.py
run_group "Theme BDD"           tests/test_theme_bdd.py
run_group "UI tests"            tests/ui/

echo ""
echo "========================================"
if [ -n "$FAILED" ]; then
    echo "FAILED GROUPS:"
    echo -e "$FAILED"
    exit 1
else
    echo "ALL GROUPS PASSED"
    exit 0
fi
