#!/bin/bash
# Stop hook: run the full test suite before Claude finishes.
# Receives JSON on stdin from Claude Code.

INPUT=$(cat)

# Avoid re-entering if already running as a result of a previous stop hook
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  exit 0
fi

# Skip tests if no code was changed this session.
# Code is considered changed if HEAD moved (committed changes) or there are
# uncommitted modifications to source files.
INITIAL_HEAD=$(cat /tmp/claude_session_head 2>/dev/null || echo "")
CURRENT_HEAD=$(git rev-parse HEAD 2>/dev/null || echo "")

HEAD_CHANGED=false
if [ -n "$INITIAL_HEAD" ] && [ "$INITIAL_HEAD" != "$CURRENT_HEAD" ]; then
  HEAD_CHANGED=true
fi

CODE_PATTERNS='\.(py|js|html|css|feature|toml)$'
DIRTY_CODE=$(git status --short 2>/dev/null | awk '{print $2}' | grep -E "$CODE_PATTERNS" | head -1)

if [ "$HEAD_CHANGED" = "false" ] && [ -z "$DIRTY_CODE" ]; then
  echo "No code changes detected — skipping test suite." >&2
  exit 0
fi

if ! command -v supabase &>/dev/null; then
  echo "Warning: supabase CLI not installed — skipping full test suite." >&2
  exit 0
fi

SUPABASE_URL=$(supabase status -o json 2>/dev/null | jq -r '.API_URL // ""')
SUPABASE_KEY=$(supabase status -o json 2>/dev/null | jq -r '.SECRET_KEY // ""')

if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ]; then
  # Try to start Supabase before giving up
  echo "Supabase not running — attempting to start..." >&2
  if docker info >/dev/null 2>&1; then
    supabase start --network-id k3s-net >/dev/null 2>&1 || true
    SUPABASE_URL=$(supabase status -o json 2>/dev/null | jq -r '.API_URL // ""')
    SUPABASE_KEY=$(supabase status -o json 2>/dev/null | jq -r '.SECRET_KEY // ""')
  fi
fi

if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ]; then
  echo "Warning: Supabase not available in this environment — skipping full test suite." >&2
  echo "To run tests: supabase start --network-id k3s-net && uv run pytest" >&2
  exit 0
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
