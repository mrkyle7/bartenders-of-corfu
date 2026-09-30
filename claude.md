# Project: bartenders of corfu
Python FastAPI backend, Supabase DB, HTML/JS frontend, k3s deployment, uv for dependency management, ruff for formatting and linting.

## Useful Commands
- Start supabase: `supabase start --network-id k3s-net`
- Run tests: `uv run pytest`
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
- `/static` — frontend assets. Three game UIs share the same API; players pick one on the home page (`bocUi` in localStorage) and `/game` redirects to it:
  - classic: `/game` (`game.html`, `game.js`)
  - table view: `/play` (`play.html`, `play/`, `css/play.css`)
  - bar top: `/bar` (`bar.html`, `bar/`, `css/bar.css`) — the physical box on a table: every mat, card and token on show; you act by touching the piece. The drinks menu and rules open in a panel from the turn bar. Legality comes from `/valid-actions`.
- `/tests` — BDD tests (`features/*.feature` + `test_game_actions_bdd.py`), UI tests (`ui/`)
- `/specs` — allium specs (source of truth for game rules, see below)

## Domain Model
Formal specs live in `specs/game.allium` and `specs/cards.allium`. Use the `spec-reader` agent to extract rules before implementing game logic. Key rules to know:

**Winning:** reaching the target (40 / 35 / 30 pts for 2 / 3 / 4 players) starts a last round, most points then wins; OR 3 karaoke cards claimed (instant); OR last player standing
**Elimination:** `drunk_level > 5` → hospitalised; `bladder.count > bladder_capacity` → wet
**Turn:** one MAIN action (take ingredients, sell one or both cups, drink a cup, wee) plus FREE actions, each once a turn: claim a card (always free), clear the orders row (drunk 3+), swipe the ability row (drunk 2+), and those granted by free-action cards. A free action only holds the turn open while it could be used. `TakeIngredients` may span multiple API batches — the turn only advances when the cumulative total reaches `take_count`.
**Market:** row 1 = all 5 karaoke cards (never cleared or refilled); row 2 = 3 drink orders (serve one by selling a matching drink for its bonus); row 3 = 3 ability cards. Cleared or served cards go to the bottom of their deck (`order_deck`, `deck`).
**Cards:** costs are threshold checks only — no bladder ingredients are consumed on claim. `cards.allium` rules supersede same-named rules in `game.allium`.
**Specials:** ingredients in the bag, 2 each of bitters/cointreau/lemon/sugar/vermouth (`Ingredient.BITTERS`…). One drawn from the bag goes to `specials_display` and the draw carries on (`draw_token`), so the display holds 5 spirits/mixers and blind draws never give a special. Taking one (source `"specials"`) counts toward the take: into a cup (max 2 per cup, on top of its 5) or drunk (sobers like a mixer, never counts toward card costs). Cocktails read specials from the cup. Games started with the old special dice (`Ingredient.SPECIAL`, mat specials, `app/specials.py`) keep those rules.
**Rules text:** `Game Rules.md` is the player-facing rulebook and the bar top view shows the same rules (`static/bar/data.js`); keep all three in step with the specs.

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
