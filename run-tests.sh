#!/bin/bash
SUPABASE_URL=$(supabase status -o json | jq -r '.API_URL')
SUPABASE_KEY=$(supabase status -o json | jq -r '.SECRET_KEY')
export SUPABASE_URL SUPABASE_KEY
python -m unittest discover tests