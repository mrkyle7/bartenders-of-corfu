#!/bin/bash
# PostToolUse hook: run tests relevant to the file just changed.
# Receives JSON on stdin from Claude Code.

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')

# Only act on Python files inside app/ or tests/
if ! echo "$FILE_PATH" | grep -qE '/(app|tests)/[^/]+\.py$'; then
  exit 0
fi

# Get Supabase credentials (same method as run-tests.sh)
SUPABASE_URL=$(supabase status -o json 2>/dev/null | jq -r '.API_URL // ""')
SUPABASE_KEY=$(supabase status -o json 2>/dev/null | jq -r '.SECRET_KEY // ""')

if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ]; then
  echo "Warning: Supabase not running — skipping targeted tests for $(basename "$FILE_PATH")" >&2
  exit 0
fi

export SUPABASE_URL SUPABASE_KEY

# Map changed file to the relevant test file(s)
TESTS=()
BASENAME=$(basename "$FILE_PATH")

case "$BASENAME" in
  game.py|gameManager.py|GameState.py|PlayerState.py|Ingredient.py)
    TESTS+=("tests/test_game_manager.py" "tests/test_api.py")
    ;;
  actions.py|cocktails.py|card.py)
    TESTS+=("tests/test_game_actions_bdd.py" "tests/test_game_manager.py")
    ;;
  db.py)
    TESTS+=("tests/test_game_manager.py" "tests/test_api.py" "tests/test_user_management.py")
    ;;
  user.py)
    TESTS+=("tests/test_user.py" "tests/test_user_management.py")
    ;;
  UserManager.py)
    TESTS+=("tests/test_user_manager.py" "tests/test_user_management.py")
    ;;
  api.py)
    TESTS+=("tests/test_api.py" "tests/test_user_management.py" "tests/test_game_manager.py" "tests/test_game_actions_bdd.py")
    ;;
  utils.py|JWTHandler.py)
    TESTS+=("tests/test_utils.py" "tests/test_user_management.py")
    ;;
  test_*.py)
    TESTS+=("$FILE_PATH")
    ;;
  *)
    exit 0
    ;;
esac

if [ ${#TESTS[@]} -eq 0 ]; then
  exit 0
fi

# Deduplicate
UNIQUE_TESTS=($(printf '%s\n' "${TESTS[@]}" | sort -u))

echo "Running targeted tests for: $BASENAME (${UNIQUE_TESTS[*]})" >&2

OUTPUT=$(uv run pytest "${UNIQUE_TESTS[@]}" -v 2>&1)
EXIT_CODE=$?

echo "$OUTPUT" >&2

if [ $EXIT_CODE -ne 0 ]; then
  # Exit 2 feeds the failure back to Claude so it can fix the problem
  echo "$OUTPUT"
  exit 2
fi
