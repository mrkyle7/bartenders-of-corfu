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
- Testing: BDD end-to-end via API. Every feature needs a positive and at least one negative scenario.
- API changes are non-breaking: add optional fields only, never remove or rename
- UI: WCAG 2.1 AA; responsive ≥320 px mobile and ≥1280 px desktop; no raw API errors shown to users; all interactive elements have descriptive `aria-label` attributes

## Working with the User
- Push back when a request looks wrong for the domain. If the user asks for something that conflicts with how the game/UI is naturally structured (e.g. sorting players alphabetically when turn order is the obvious ordering, hiding a control that's needed mid-turn, removing a guardrail), ask a clarifying question before implementing. Cheap to ask, expensive to undo.

## Architecture
- `/app` — FastAPI routes (`api.py`), business logic (`actions.py`, `gameManager.py`), domain models (`GameState.py`, `PlayerState.py`, `card.py`, `cocktails.py`)
- `/static` — frontend assets
- `/tests` — BDD tests (`features/*.feature` + `test_game_actions_bdd.py`), UI tests (`ui/`)
- `/specs` — allium specs (source of truth for game rules, see below)

## Domain Model
Formal specs live in `specs/game.allium` and `specs/cards.allium`. Use the `spec-reader` agent to extract rules before implementing game logic. Key rules to know:

**Winning:** 40+ pts OR 3 karaoke cards claimed OR last player standing
**Elimination:** `drunk_level > 5` → hospitalised; `bladder.count > bladder_capacity` → wet
**Turn:** player takes exactly ONE action per turn. `TakeIngredients` may span multiple API batches — the turn only advances when the cumulative total reaches `take_count`. No other action is permitted while a batch is in progress.
**Cards:** costs are threshold checks only — no bladder ingredients are consumed on claim. `cards.allium` rules supersede same-named rules in `game.allium` (ClaimCard, RefreshCardRow, ReplaceCard, ApplyDrunkModifier, SellCup).
**Row 1:** always contains karaoke cards, can never be refreshed.
**Discard:** permanent graveyard (`gs.discard`), never reshuffled.

## Definition of Done
A task is complete when:
1. Targeted tests pass — the PostToolUse hook runs them automatically after every file edit
2. `uv run ruff check && uv run ruff format --check` is clean
3. BDD feature file updated if any observable behaviour changed
4. No breaking API changes introduced

## Subagents
- `spec-reader` — reads allium specs and returns a precise rule briefing; invoke before implementing any game logic to avoid misreading the spec
- `bdd-test-writer` — writes BDD scenarios and step definitions matching project style; invoke when adding test coverage for new behaviour
- `ui-developer` — builds and modifies UI components; enforces the board-game interaction model (clickable elements, state at a glance, guided turn flow), mobile/desktop layout, WCAG 2.1 AA, and the theming/contrast rules in `.claude/agents/ui-developer.md` — read that doc's "Theming and contrast" section before writing any CSS for `static/`. Two contrast contexts exist (light page chrome vs. dark `.gb-board-section`); the lobby panel lives on the dark board, so page-chrome tokens like `--theme-text-primary` cause dark-on-dark there.
