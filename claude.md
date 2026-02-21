# Project: bartenders of corfu
Python FastAPI backend, Supabase DB, HTML/JS frontend, k3s deployment, uv for dependency management, ruff for formatting and linting.

## Useful Commands
- Start supabase: `supabase start --network-id k3s-net`
- Run tests: `./run-tests.sh`
- Run locally: `./run-local.sh`
- Lint/Format: `uv run ruff check && uv run ruff format`
- Test local k3s deployment: `./k-apply.sh`

## Code Style & Standards
- Backend: Use type hints in FastAPI; follow PEP8
- Database: Supabase logic stays in `app/db.py`
- UI: Keep JS and HTML files in `static/`
- Testing: Prefer end to end tests using API. Ensure tests cover positive and negative tests for features.
- Ensure backend app is stateless and API changes are non-breaking

## Architecture notes
- `/app`: FastAPI routes and logic
- `/k3s`: K3s YAML files
- `/static`: frontend assets
- `/tests`: end to end and unit tests
- `/terraform`: GCP terraform files

