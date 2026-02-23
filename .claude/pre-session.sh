#!/bin/bash
# SessionStart hook: ensure Supabase is installed and running before any session begins.
# Called by Claude Code on session start.

set -euo pipefail

# ─── Check supabase CLI is installed ──────────────────────────────────────────
if ! command -v supabase &>/dev/null; then
  echo "ERROR: The 'supabase' CLI is not installed." >&2
  echo "" >&2
  echo "Install it with:" >&2
  echo "  brew install supabase/tap/supabase   (macOS)" >&2
  echo "  or: https://supabase.com/docs/guides/cli/getting-started" >&2
  echo "" >&2
  echo "Tests require a running Supabase instance. Start it with:" >&2
  echo "  supabase start --network-id k3s-net" >&2
  exit 1
fi

# ─── Check Supabase is running ────────────────────────────────────────────────
STATUS_JSON=$(supabase status -o json 2>/dev/null || echo "{}")
API_URL=$(echo "$STATUS_JSON" | jq -r '.API_URL // ""' 2>/dev/null || echo "")

if [ -z "$API_URL" ]; then
  echo "Supabase is not running. Starting it now..." >&2
  if supabase start --network-id k3s-net 2>&1; then
    echo "Supabase started successfully." >&2
  else
    echo "ERROR: Failed to start Supabase." >&2
    echo "Try running manually: supabase start --network-id k3s-net" >&2
    exit 1
  fi
else
  echo "Supabase is already running at $API_URL" >&2
fi

# ─── Export env vars for the session ─────────────────────────────────────────
STATUS_JSON=$(supabase status -o json 2>/dev/null)
API_URL=$(echo "$STATUS_JSON" | jq -r '.API_URL // ""')
SECRET_KEY=$(echo "$STATUS_JSON" | jq -r '.SECRET_KEY // ""')

if [ -z "$API_URL" ] || [ -z "$SECRET_KEY" ]; then
  echo "ERROR: Could not read Supabase credentials from 'supabase status'." >&2
  exit 1
fi

export SUPABASE_URL="$API_URL"
export SUPABASE_KEY="$SECRET_KEY"
echo "Session ready. SUPABASE_URL=$SUPABASE_URL" >&2
