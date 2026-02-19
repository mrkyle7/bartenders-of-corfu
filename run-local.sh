#!/bin/bash
SUPABASE_URL=$(supabase status -o json | jq -r '.API_URL')
SUPABASE_KEY=$(supabase status -o json | jq -r '.SECRET_KEY')
export SUPABASE_URL SUPABASE_KEY
uv run uvicorn app.api:app --host 0.0.0.0 --port 8000 --log-config ./log_conf.yaml --reload