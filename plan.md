# Plan: Store Card — Use Stored Spirits in 3 Scenarios

## Context

Store cards (Gin Store, Vodka Store, etc.) hold spirits transferred from the bladder when claimed. Currently, stored spirits sit on the card but can only be drawn upon when claiming Karaoke cards (via `_available_spirits` / `_consume_spirits`). Three additional use cases need implementation.

## Current State

- `_available_spirits(ps, spirit_type)` — counts bladder + store card spirits (exists)
- `_consume_spirits(ps, spirit_type, count)` — removes from bladder first, then store cards (exists)
- These helpers are only used for Karaoke claims today

---

## Scenario 1: Use Stored Spirits When Selling Drinks

**Problem:** Currently `sell_cup` only scores what's physically in `cup.ingredients`. There's no way to add stored spirits into a cup for sale.

**Approach:** Add a new action `use_stored_spirit` that lets a player move a spirit from a store card into one of their cups. This is a free action (doesn't end the turn) performed before selling. The spirit moves from `stored_spirits` on the card → `cup.ingredients[cup_index]`.

### API Changes (`actions.py`)
- New function `use_stored_spirit(gs, player_id, store_card_index, cup_index)`:
  - Validates the player has a store card at the given index with spirits remaining
  - Validates the target cup isn't full
  - Pops one spirit from `stored_spirits`, appends to `cup.ingredients`
  - Does NOT advance turn (free action)
  - Returns the updated state and payload

### API Endpoint (`api.py`)
- New POST endpoint: `/v1/games/{game_id}/actions/use-stored-spirit`
  - Body: `{ "store_card_index": int, "cup_index": int }`

### UI Changes (`game.js`)
- On store cards in the player's hand, show a "Use" button per stored spirit
- When clicked, prompt which cup (0 or 1) to add it to
- Call the new API endpoint, then re-render

---

## Scenario 2: Use Stored Spirits When Claiming Cards (Drink Them)

**Problem:** The spec says stored spirits can be drunk "at any time" which increases drunk level. Drinking them would put them into the bladder (now counting toward claim thresholds) and increase drunk level.

**Approach:** Add a new action `drink_stored_spirit` that lets a player drink spirits from their store cards. This moves them to the bladder and applies the drunk modifier. This is a free action.

### API Changes (`actions.py`)
- New function `drink_stored_spirit(gs, player_id, store_card_index, count)`:
  - Validates the store card has enough spirits
  - Removes `count` spirits from `stored_spirits`
  - Calls `_drink_ingredient` for each (adds to bladder)
  - Calls `_apply_drunk_modifier` for the batch
  - Does NOT advance turn (free action)
  - Returns updated state and payload (including new drunk level)

### API Endpoint (`api.py`)
- New POST endpoint: `/v1/games/{game_id}/actions/drink-stored-spirit`
  - Body: `{ "store_card_index": int, "count": int }`

### UI Changes (`game.js`)
- On store cards in the player's hand, show a "Drink" button
- When clicked, let player choose how many to drink (default: 1)
- Show warning about drunk level increase
- Call the API endpoint, then re-render

---

## Scenario 3: Drink Stored Spirits to Qualify for Refresh Row

**Problem:** Refreshing a card row requires drunk level >= 3. Players should be able to drink stored spirits to reach this threshold.

**Solution:** This is automatically solved by Scenario 2. The `drink_stored_spirit` action increases drunk level, so a player can drink stored spirits to reach the MIN_DRUNK_TO_REFRESH (3) threshold, then call `refresh_card_row` as normal.

No additional API or logic changes needed — just ensure the UI makes the flow clear.

### UI Changes (`game.js`)
- When a player tries to refresh a row but drunk level < 3, show a hint: "Drink stored spirits to increase your drunk level"
- Make it easy to drink stored spirits from the same screen

---

## Implementation Steps

1. **API: `drink_stored_spirit` action** (`actions.py`)
   - Add the function with validation, spirit transfer, and drunk modifier
   - Wire up in `gameManager.py`
   - Add endpoint in `api.py`

2. **API: `use_stored_spirit` action** (`actions.py`)
   - Add the function to move spirit from store card to cup
   - Wire up in `gameManager.py`
   - Add endpoint in `api.py`

3. **UI: Store card interactions** (`game.js`)
   - Render stored spirits on claimed store cards
   - Add "Drink" and "Use in Cup" buttons
   - Wire up API calls
   - Add refresh-row hint when drunk level insufficient

4. **Tests** (`tests/`)
   - BDD scenarios for drink_stored_spirit (drunk level increases, spirits consumed)
   - BDD scenarios for use_stored_spirit (spirit moves to cup, cup full rejection)
   - Integration test: drink stored → refresh row flow
   - Integration test: use stored → sell cup flow
