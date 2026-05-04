---
name: add-game-mode
description: Add a new optional rule-variation game mode end-to-end (backend, bots, UI, specs, tests). Use when the user asks to "add a game mode option", "add an optional rule", or "add a lobby toggle for X". Walks through every layer the existing modes (`sell_both_cups`, `claim_card_free_action`, `reroll_specials_free_action`) touch.
argument-hint: "[mode_key] [short description of behaviour]"
---

# Add a game mode option

Use this skill when the user wants a new lobby toggle that changes some game rule. The codebase already has three modes (`sell_both_cups`, `claim_card_free_action`, `reroll_specials_free_action`) — match their pattern exactly. Don't invent new infrastructure unless the new behaviour cannot be expressed in any existing layer.

## 0. Before starting

- Confirm with the user:
  1. **Mode key** — short snake_case identifier (e.g. `silent_specials`).
  2. **Behaviour** — exactly which rule(s) change when it's enabled.
  3. **Card-deck impact** — does enabling the mode add or remove any card from the deck?
  4. **Free-action interaction** — does it convert an action into a once-per-turn free action?
  5. **Bot strategy guidance** — which existing strategies benefit?
- Read the spec for the affected rules first via the `spec-reader` agent (target topic is the action(s) the mode changes).

## 1. Backend: register the mode

`app/game_modes.py`
- Add a new value to the `GameMode` enum. Keep the docstring above it explaining the user-visible effect and any deck-side effect.

`app/GameState.py`
- The `game_modes` field already round-trips. Only edit if the new mode needs additional persisted state (rare).
- If the mode changes deck composition, ensure `start_game` continues to forward modes to `build_deck(game_modes)`.

## 2. Backend: action / turn logic

`app/actions.py`
- If the mode turns an action into a free action, add an entry to `_MODE_FREE_ACTION_MAP`. `_available_free_actions(gs, ps, used)` will pick it up automatically.
- If the mode changes an action's validation or effect, gate the change on `gs.has_mode("...")` inside the relevant action function. Use a single early `if not gs.has_mode(...): raise GameException(...)` style guard for "this only works when the mode is on" cases (mirrors `sell_cup`'s `additional_cups` check).
- Partial-take blocking (`_require_no_take_in_progress`) **always** stays in effect — even if the mode makes an action free, it must still be blocked while a take batch is in progress.

`app/gameManager.py`
- Only edit if the action exposes a new request param that needs a new GameManager method signature.

`app/api.py`
- Add a request-body field if the mode introduces a new parameter to an existing endpoint. Keep API non-breaking: add optional fields, never remove or rename.

## 3. Backend: deck composition (if needed)

`app/card.py`
- `build_deck(game_modes: list[str] | None = None)` — extend the gating block where `Cocktail Shaker` is excluded under `reroll_specials_free_action`. Stick to a single `if "<mode_key>" in modes: continue` per excluded card.
- Update the docstring with the new total card count when mode is on.

## 4. Bot enablement

`playtesting/valid_actions.py`
- If the mode adds a new turn action, write `_add_<action>(gs, ps, result)` and call it from `get_valid_actions`.
- If the mode changes an action's *is_free* status, mark matching `Action` entries `is_free=True` after collection (see how `claim_card_free_action` and `reroll_specials_free_action` are handled at the bottom of `get_valid_actions`).

`app/bot_player.py`
- Add a new `elif t == "<action>"` branch in `_execute_action` if a new action_type is now reachable from bots.

`playtesting/strategy.py`
- Update the relevant strategy's `choose_free_action` (and `choose_action` if needed) to take advantage of the mode. Use the `_free_claim_action` / `_free_reroll_action` helpers as a template — strategy-specific preferences (e.g. KaraokeRusher prefers `karaoke`) should be passed via `prefer_card_types`.
- The base `Strategy.choose_free_action` provides a sensible default for new free claim/reroll modes; only override if the strategy needs different priorities.

## 5. UI layer

`static/game.js`
- Add an entry to `GAME_MODE_INFO` with `label` and `description`. The lobby and the active-modes tab pick it up automatically.
- If the mode changes which actions are enabled mid-turn, update the action-bar block that builds `myFreeActions` (search for `enabledModes.includes(`). Mirror the once-per-turn gating against `freeUsed`.
- If the mode introduces a new client-initiated action, add a new `do<Action>` handler and wire its button. Avoid raw API errors — funnel through `showError`.

`static/game.html`
- No changes for typical modes; the lobby checkbox renders from `/v1/game-modes`.
- Only edit if you need a new action button (then add it to the action bar with an `aria-label`).

`static/css/game.css`
- No changes for typical modes. Active-modes tab styles already exist (`gb-active-mode-row` etc.).

## 6. Specs

`specs/cards.allium`
- Add the new value to the `GameMode` enum (under "Game modes" section).
- Add a `guarantee:` line stating the user-visible promise.
- If the mode changes a rule (e.g. claim cost, free-action eligibility, deck composition), reference it in the relevant rule's text or in a new `amendment`.

`specs/game.allium`
- Edit only if the mode changes a rule that lives there (most modes don't; cards.allium covers card-related rules).

If deck composition changes, fix any deck-size totals you can see in the comments. The `SetupCardRows` rule's row math should describe the standard and mode-on counts.

## 7. Tests

`tests/test_game_modes.py`
- Add `test_normalise_modes_accepts_<mode_key>`.
- Add `test_game_mode_enum_value_matches_string` for the new enum value.
- Add unit tests for the behavioural change. Mirror the structure of the existing `claim_card_free_action` tests (positive case, negative case without mode, partial-take interaction, deck composition assertion if applicable).

`tests/features/game_modes.feature`
- Scenario: mode on → behaviour visible.
- Scenario: mode off → behaviour absent (negative test).
- Scenario: partial-take in progress still blocks the action.
- Scenario: mode appears in `/v1/game-modes`.
- Scenario: deck composition asserts removed/added cards (if applicable).

`tests/test_game_actions_bdd.py`
- Add a `_started_game_with_modes(["<mode_key>"])` fixture if a per-mode helper is more readable; otherwise reuse the generic helper.
- Add any missing step definitions (e.g. `the X should be recorded as a free action`).

## 8. Verify

- Run `./run-tests.sh` or `uv run pytest tests/test_game_modes.py tests/test_game_actions_bdd.py -k <mode_key>`.
- Run `uv run ruff check && uv run ruff format --check`.
- Manually exercise the mode in the dev server: enable in lobby → start game → verify behaviour.

## Common pitfalls

- **Forgetting `gs.has_mode("...")`** — the mode key is the enum **value** (string), not the enum member itself. Always pass the string.
- **Free action that bypasses the partial-take block** — don't lift `_require_no_take_in_progress`. Free actions still wait for the take to finish.
- **Marking is_free without honouring `free_actions_used_this_turn`** — once-per-turn semantics are the universal contract. Any new mode-driven free action must check `used` before marking.
- **Deck math** — the comment block at the top of `cards.allium` is normative. Update it whenever you change `build_deck` filtering.
- **GAME_MODE_INFO key drift** — the JS dictionary key MUST exactly equal the enum value or the lobby and active-modes tab will silently render the raw key.
