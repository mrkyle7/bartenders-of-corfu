#!/bin/bash
# SessionStart hook: ensure Supabase is installed and running before any session begins.
# Called by Claude Code on session start.

set -euo pipefail

# ─── Install supabase CLI if not present ──────────────────────────────────────
if ! command -v supabase &>/dev/null; then
  echo "Supabase CLI not found. Installing..." >&2
  OS=$(uname -s | tr '[:upper:]' '[:lower:]')
  ARCH=$(uname -m)
  if [ "$ARCH" = "x86_64" ]; then ARCH="amd64"; elif [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi

  LATEST=$(curl -fsSL https://api.github.com/repos/supabase/cli/releases/latest \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])" 2>/dev/null || echo "")

  if [ -z "$LATEST" ]; then
    echo "ERROR: Could not determine latest Supabase CLI version." >&2
    exit 1
  fi

  TARBALL="supabase_${OS}_${ARCH}.tar.gz"
  curl -fsSL "https://github.com/supabase/cli/releases/download/${LATEST}/${TARBALL}" \
    -o /tmp/supabase_install.tar.gz
  tar -xzf /tmp/supabase_install.tar.gz -C /tmp supabase
  mv /tmp/supabase /usr/local/bin/supabase
  chmod +x /usr/local/bin/supabase
  rm -f /tmp/supabase_install.tar.gz
  echo "Supabase CLI ${LATEST} installed successfully." >&2
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
