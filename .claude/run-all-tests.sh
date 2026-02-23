#!/bin/bash
# Stop hook: run the full test suite before Claude finishes.
# Receives JSON on stdin from Claude Code.

INPUT=$(cat)

# Avoid re-entering if already running as a result of a previous stop hook
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  exit 0
fi

if ! command -v supabase &>/dev/null; then
  echo "Warning: supabase CLI not installed — skipping full test suite." >&2
  exit 0
fi

SUPABASE_URL=$(supabase status -o json 2>/dev/null | jq -r '.API_URL // ""')
SUPABASE_KEY=$(supabase status -o json 2>/dev/null | jq -r '.SECRET_KEY // ""')

if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ]; then
  echo "Warning: Supabase not running — failing full test suite. run \`supabase start --network-id k3s-net\` to start" >&2
  exit 2
fi

export SUPABASE_URL SUPABASE_KEY

echo "Running full test suite before stopping..." >&2
OUTPUT=$(uv run pytest --ignore=tests/ui 2>&1)
EXIT_CODE=$?

echo "$OUTPUT" >&2

if [ $EXIT_CODE -ne 0 ]; then
  # Exit 2 prevents Claude from stopping and feeds the failure back so it can fix
  echo "$OUTPUT"
  exit 2
fi
