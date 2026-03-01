"""Pure-function game action implementations.

Each action validates preconditions, applies state changes, and returns
(new_game_state, move_payload). Raises GameException on invalid input.

Turn advancement: after every action the turn advances to the next active
(non-eliminated) player in turn_order.
"""

import random
from uuid import UUID

from app.card import Card, CardRow
from app.cocktails import drink_points
from app.game import GameException
from app.GameState import OPEN_DISPLAY_SIZE, GameState
from app.Ingredient import Ingredient, SpecialType
from app.PlayerState import MAX_CUP_INGREDIENTS, MIN_BLADDER_CAPACITY, PlayerState

_SPIRITS = {
    Ingredient.WHISKEY,
    Ingredient.GIN,
    Ingredient.RUM,
    Ingredient.TEQUILA,
    Ingredient.VODKA,
}
_MIXERS = {Ingredient.SODA, Ingredient.TONIC, Ingredient.COLA, Ingredient.CRANBERRY}

SCORE_TO_WIN = 40
KARAOKE_CARDS_TO_WIN = 3
MAX_DRUNK_LEVEL = 5
MIN_DRUNK_TO_REFRESH = 3


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _deep_copy_state(gs: GameState) -> GameState:
    """Return a deep copy of the game state so actions are free of side effects."""
    return GameState.from_dict(gs.to_dict())


def _require_turn(gs: GameState, player_id: UUID):
    if gs.player_turn != player_id:
        raise GameException("It is not your turn", status_code=409)


def _require_active(ps: PlayerState):
    if ps.status != "active":
        raise GameException("Eliminated players cannot take actions", status_code=409)


def _require_started(gs: GameState):
    # GameState itself doesn't know game status; caller should gate on Game.status.
    pass


def _advance_turn(gs: GameState) -> GameState:
    """Advance player_turn to the next active player in turn_order and reset per-turn batch state."""
    # Reset batch tracking whenever the turn advances
    gs.ingredients_taken_this_turn = 0
    gs.drunk_ingredients_this_turn = []
    gs.bag_draw_pending = []
    gs.taken_records_this_turn = []

    if not gs.turn_order:
        return gs
    order = gs.turn_order
    current = gs.player_turn
    try:
        idx = order.index(current)
    except ValueError:
        idx = -1

    for i in range(1, len(order) + 1):
        candidate = order[(idx + i) % len(order)]
        ps = gs.player_states.get(candidate)
        if ps and not ps.is_eliminated:
            gs.player_turn = candidate
            return gs

    # All players eliminated — leave turn unchanged (game should be ended)
    return gs


def _require_no_take_in_progress(gs: GameState):
    """Raise if the current player is mid-way through a TakeIngredients action."""
    if gs.ingredients_taken_this_turn > 0 or gs.bag_draw_pending:
        raise GameException(
            "Cannot perform this action while a take-ingredients action is in progress; "
            "complete the take first.",
            status_code=409,
        )


def _replenish_display(gs: GameState):
    """Randomly draw from the bag to fill the open display up to OPEN_DISPLAY_SIZE."""
    deficit = OPEN_DISPLAY_SIZE - len(gs.open_display)
    if deficit > 0 and gs.bag_contents:
        fill = min(deficit, len(gs.bag_contents))
        chosen = random.sample(gs.bag_contents, fill)
        for item in chosen:
            gs.bag_contents.remove(item)
        gs.open_display.extend(chosen)


def _check_elimination(gs: GameState, player_id: UUID):
    ps = gs.player_states[player_id]
    if ps.drunk_level > MAX_DRUNK_LEVEL:
        ps.status = "hospitalised"
    elif len(ps.bladder) > ps.bladder_capacity:
        ps.status = "wet"


def _check_victory(gs: GameState, player_id: UUID) -> bool:
    """Mark the game as ended if the player meets a win condition. Returns True if won."""
    ps = gs.player_states[player_id]
    if ps.status != "active":
        return False
    if ps.points >= SCORE_TO_WIN or ps.karaoke_cards_claimed >= KARAOKE_CARDS_TO_WIN:
        gs.winner = player_id
        return True
    return False


def _check_last_player_standing(gs: GameState) -> bool:
    """If only one active player remains, they win. Returns True if triggered."""
    if gs.winner is not None:
        return False
    active = [pid for pid, ps in gs.player_states.items() if not ps.is_eliminated]
    if len(active) == 1:
        gs.winner = active[0]
        return True
    return False


def _apply_drunk_modifier(
    gs: GameState, player_id: UUID, ingredients: list[Ingredient]
):
    """Apply drunk level changes for a batch of drunk ingredients.

    You only sober up if ALL ingredients in the batch are mixers (no spirits).
    If any spirit is present, mixers do not reduce drunk_level.
    """
    ps = gs.player_states[player_id]
    spirits = [i for i in ingredients if i in _SPIRITS]
    mixers = [i for i in ingredients if i in _MIXERS]
    ps.drunk_level += len(spirits)
    if not spirits:
        ps.drunk_level = max(0, ps.drunk_level - len(mixers))
    _check_elimination(gs, player_id)
    _check_last_player_standing(gs)


def _drink_ingredient(gs: GameState, player_id: UUID, ingredient: Ingredient):
    """Add one spirit or mixer to the bladder (drunk level is NOT adjusted here).

    Callers must call _apply_drunk_modifier after processing the full batch.
    """
    ps = gs.player_states[player_id]
    ps.bladder.append(ingredient)


def _replace_card(gs: GameState, row: CardRow):
    """Draw one card from the deck into the row, if deck has cards."""
    if gs._deck_dicts:
        from app.card import Card

        card_dict = gs._deck_dicts.pop(0)
        row.cards.append(Card.from_dict(card_dict))


# ─── Turn actions ─────────────────────────────────────────────────────────────


def draw_from_bag(
    gs: GameState,
    player_id: UUID,
    count: int,
) -> tuple[GameState, dict]:
    """DrawFromBag — reveals ingredients from the bag and holds them pending assignment.

    Draws `count` ingredients randomly from the bag and stores them in
    gs.bag_draw_pending. The player must then call take_ingredients with
    source='pending' assignments to assign each drawn ingredient to a cup or drink.
    No other action is permitted while bag_draw_pending is non-empty.
    """
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)

    if gs.bag_draw_pending:
        raise GameException(
            "You have unassigned bag ingredients — assign them before drawing again.",
            status_code=409,
        )

    take_count = ps.take_count
    already_taken = gs.ingredients_taken_this_turn
    remaining = take_count - already_taken

    if remaining <= 0:
        raise GameException(
            "You have already taken the maximum ingredients for this turn.",
            status_code=409,
        )

    if count < 1 or count > remaining:
        raise GameException(
            f"Must draw between 1 and {remaining} ingredient(s); got {count}.",
            status_code=400,
        )

    if len(gs.bag_contents) < count:
        raise GameException(
            f"Not enough ingredients in bag (need {count}, have {len(gs.bag_contents)}).",
            status_code=409,
        )

    drawn: list[Ingredient] = []
    for _ in range(count):
        ingredient = random.choice(gs.bag_contents)
        gs.bag_contents.remove(ingredient)
        drawn.append(ingredient)

    gs.bag_draw_pending = drawn
    payload = {"drawn": [i.name for i in drawn]}
    return gs, payload


def take_ingredients(
    gs: GameState,
    player_id: UUID,
    assignments: list[dict],
) -> tuple[GameState, dict]:
    """TakeIngredients action — supports multi-batch taking.

    A player's turn requires them to take take_count ingredients total.  They may
    split this across multiple API calls (batches).  Each call takes 1 or more
    ingredients and must assign every ingredient before the next batch is sent.
    The turn only advances — and the drunk modifier is applied — after the total
    across all batches reaches take_count.

    assignments: list of {
        ingredient: str,   # Ingredient enum name (required for source="display")
        source: "bag" | "display",
        disposition: "cup" | "drink",
        cup_index: 0 | 1   # required when disposition == "cup"
    }

    Returns (new_game_state, move_payload) where move_payload includes
    "turn_complete": bool indicating whether the turn has ended.
    """
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)

    take_count = ps.take_count
    already_taken = gs.ingredients_taken_this_turn
    remaining = take_count - already_taken

    # If there are pending bag ingredients, all must be assigned in this call.
    if gs.bag_draw_pending:
        pending_in_call = sum(1 for a in assignments if a.get("source") == "pending")
        if pending_in_call != len(gs.bag_draw_pending):
            raise GameException(
                f"Must assign all {len(gs.bag_draw_pending)} pending bag ingredient(s); "
                f"got {pending_in_call} pending assignment(s).",
                status_code=400,
            )
    else:
        # No pending draw — on the first batch verify enough ingredients exist
        if already_taken == 0:
            available_count = len(gs.bag_contents) + len(gs.open_display)
            if available_count < take_count:
                raise GameException(
                    f"Not enough ingredients available ({available_count} < {take_count}). "
                    "Choose a different action.",
                    status_code=409,
                )

    if len(assignments) == 0 or len(assignments) > remaining:
        raise GameException(
            f"Must take between 1 and {remaining} ingredient(s) in this batch, "
            f"got {len(assignments)}",
            status_code=400,
        )

    taken_records: list[dict] = []
    drunk_this_batch: list[Ingredient] = []

    for asn in assignments:
        raw_name = asn.get("ingredient", "")
        source = asn.get("source", "bag")
        disposition = asn.get("disposition", "drink")
        cup_index = asn.get("cup_index", 0)

        # Resolve ingredient from source
        if source == "display":
            try:
                ingredient = Ingredient[raw_name]
            except KeyError:
                raise GameException(f"Unknown ingredient: {raw_name}", status_code=400)
            if ingredient not in gs.open_display:
                raise GameException(
                    f"{raw_name} is not in the open display", status_code=400
                )
            gs.open_display.remove(ingredient)
        elif source == "pending":
            # Use the next ingredient from the pending draw (already removed from bag)
            if not gs.bag_draw_pending:
                raise GameException(
                    "No pending bag ingredient to assign.", status_code=400
                )
            ingredient = gs.bag_draw_pending.pop(0)
            raw_name = ingredient.name
        else:
            # Direct bag draw — only permitted when no pending draw exists
            if gs.bag_draw_pending:
                raise GameException(
                    "Assign your pending bag ingredients before drawing more.",
                    status_code=409,
                )
            if not gs.bag_contents:
                raise GameException("The bag is empty", status_code=400)
            ingredient = random.choice(gs.bag_contents)
            gs.bag_contents.remove(ingredient)
            raw_name = ingredient.name

        record: dict = {"ingredient": raw_name, "source": source}

        if ingredient.value.special:
            # Special token: roll the die
            rolled = SpecialType.roll()
            record["disposition"] = "special"
            record["special_type"] = rolled.value
            if rolled != SpecialType.NOTHING:
                ps.special_ingredients.append(rolled.value)
            else:
                # Token returned to bag
                gs.bag_contents.append(ingredient)
        elif disposition == "cup":
            if cup_index not in (0, 1):
                raise GameException("cup_index must be 0 or 1", status_code=400)
            cup = ps.cups[cup_index]
            if cup.is_full:
                raise GameException(
                    f"Cup {cup_index} is full (max {MAX_CUP_INGREDIENTS})",
                    status_code=400,
                )
            if ingredient not in _SPIRITS and ingredient not in _MIXERS:
                raise GameException(
                    "Only spirits and mixers may be placed in cups", status_code=400
                )
            cup.ingredients.append(ingredient)
            record["disposition"] = "cup"
            record["cup_index"] = cup_index
        elif disposition == "drink":
            if ingredient not in _SPIRITS and ingredient not in _MIXERS:
                raise GameException(
                    "Only spirits and mixers may be drunk directly", status_code=400
                )
            _drink_ingredient(gs, player_id, ingredient)
            drunk_this_batch.append(ingredient)
            record["disposition"] = "drink"
        else:
            raise GameException(f"Unknown disposition: {disposition}", status_code=400)

        taken_records.append(record)

    # Accumulate batch progress
    gs.ingredients_taken_this_turn += len(assignments)
    gs.drunk_ingredients_this_turn.extend(drunk_this_batch)
    gs.taken_records_this_turn.extend(taken_records)

    turn_complete = gs.ingredients_taken_this_turn >= take_count

    if turn_complete:
        # Apply drunk modifier once across all ingredients drunk this whole turn
        if gs.drunk_ingredients_this_turn:
            _apply_drunk_modifier(gs, player_id, gs.drunk_ingredients_this_turn)
        _replenish_display(gs)
        gs.turn_number += 1
        _advance_turn(
            gs
        )  # resets ingredients_taken_this_turn, drunk_ingredients_this_turn, taken_records_this_turn

    # Each batch is its own move record, so only emit this batch's records.
    payload = {"taken": taken_records, "turn_complete": turn_complete}
    return gs, payload


def sell_cup(
    gs: GameState,
    player_id: UUID,
    cup_index: int,
    declared_specials: list[str],
) -> tuple[GameState, dict]:
    """SellCup action."""
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)
    _require_no_take_in_progress(gs)

    if cup_index not in (0, 1):
        raise GameException("cup_index must be 0 or 1", status_code=400)

    cup = ps.cups[cup_index]
    if cup.is_empty:
        raise GameException("Cup is empty", status_code=400)

    # Validate declared specials are on the player's mat
    mat = list(ps.special_ingredients)
    for s in declared_specials:
        if s not in mat:
            raise GameException(
                f"Special '{s}' is not on your player mat", status_code=400
            )
        mat.remove(s)

    pts = drink_points(cup.ingredients, declared_specials)
    if pts is None:
        raise GameException(
            "This combination of ingredients cannot be sold", status_code=400
        )

    sold_ingredients = list(cup.ingredients)
    # Return sold ingredients + declared specials to the bag
    gs.bag_contents.extend(sold_ingredients)
    for s in declared_specials:
        # Specials are returned as SPECIAL tokens to the bag
        gs.bag_contents.append(Ingredient.SPECIAL)
        ps.special_ingredients.remove(s)

    cup.ingredients = []

    ps.points += pts
    _check_victory(gs, player_id)
    gs.turn_number += 1
    _advance_turn(gs)

    payload = {
        "cup_index": cup_index,
        "ingredients": [i.name for i in sold_ingredients],
        "declared_specials": declared_specials,
        "points_earned": pts,
    }
    return gs, payload


def drink_cup(
    gs: GameState,
    player_id: UUID,
    cup_index: int,
) -> tuple[GameState, dict]:
    """DrinkCup action."""
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)
    _require_no_take_in_progress(gs)

    if cup_index not in (0, 1):
        raise GameException("cup_index must be 0 or 1", status_code=400)

    cup = ps.cups[cup_index]
    if cup.is_empty:
        raise GameException("Cup is empty", status_code=400)

    drunk_ingredients = list(cup.ingredients)
    for ingredient in drunk_ingredients:
        _drink_ingredient(gs, player_id, ingredient)
    # Drunk cup ingredients go to the bladder (not the bag) — handled by _drink_ingredient
    # Apply drunk modifier in one batch: only sober up if all ingredients are mixers
    _apply_drunk_modifier(gs, player_id, drunk_ingredients)

    cup.ingredients = []

    gs.turn_number += 1
    _advance_turn(gs)

    payload = {
        "cup_index": cup_index,
        "ingredients": [i.name for i in drunk_ingredients],
    }
    return gs, payload


def go_for_a_wee(
    gs: GameState,
    player_id: UUID,
) -> tuple[GameState, dict]:
    """GoForAWee action."""
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)
    _require_no_take_in_progress(gs)

    excreted = list(ps.bladder)
    # Return bladder contents to the bag
    gs.bag_contents.extend(excreted)
    ps.bladder = []
    # Sober up 1 level
    ps.drunk_level = max(0, ps.drunk_level - 1)
    # Breaking the seal: uses one toilet token and shrinks bladder capacity
    if ps.toilet_tokens > 0:
        ps.toilet_tokens -= 1
        ps.bladder_capacity = max(MIN_BLADDER_CAPACITY, ps.bladder_capacity - 1)

    gs.turn_number += 1
    _advance_turn(gs)

    payload = {"excreted": [i.name for i in excreted]}
    return gs, payload


def claim_card(
    gs: GameState,
    player_id: UUID,
    card_id: str,
) -> tuple[GameState, dict]:
    """ClaimCard action."""
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)
    _require_no_take_in_progress(gs)

    # Find the card in a row
    target_card: Card | None = None
    target_row: CardRow | None = None
    for row in gs.card_rows:
        for card in row.cards:
            if card.id == card_id:
                target_card = card
                target_row = row
                break
        if target_card:
            break

    if target_card is None:
        raise GameException("Card not found in any row", status_code=404)

    # Validate bladder contents meet the cost
    bladder_spirits = sum(1 for i in ps.bladder if i in _SPIRITS)
    bladder_mixers = sum(1 for i in ps.bladder if i in _MIXERS)
    bladder_specials = len(ps.special_ingredients)

    for req in target_card.cost:
        if req.kind == "spirit" and bladder_spirits < req.count:
            raise GameException(
                f"Need {req.count} spirit(s) in bladder; have {bladder_spirits}",
                status_code=400,
            )
        elif req.kind == "mixer" and bladder_mixers < req.count:
            raise GameException(
                f"Need {req.count} mixer(s) in bladder; have {bladder_mixers}",
                status_code=400,
            )
        elif req.kind == "special" and bladder_specials < req.count:
            raise GameException(
                f"Need {req.count} special(s) on mat; have {bladder_specials}",
                status_code=400,
            )

    # Remove card from row
    target_row.cards.remove(target_card)

    # Claim the card
    ps.cards.append(target_card.to_dict())
    if target_card.is_karaoke:
        ps.karaoke_cards_claimed += 1

    # Replace the claimed card's slot from the deck (if any cards remain)
    _replace_card(gs, target_row)

    _check_victory(gs, player_id)
    gs.turn_number += 1
    _advance_turn(gs)

    payload = {
        "card_id": card_id,
        "is_karaoke": target_card.is_karaoke,
        "row_position": target_row.position,
    }
    return gs, payload


def refresh_card_row(
    gs: GameState,
    player_id: UUID,
    row_position: int,
) -> tuple[GameState, dict]:
    """RefreshCardRow action."""
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)
    _require_no_take_in_progress(gs)

    if ps.drunk_level < MIN_DRUNK_TO_REFRESH:
        raise GameException(
            f"Must be drunk level {MIN_DRUNK_TO_REFRESH}+ to refresh a row; "
            f"you are at {ps.drunk_level}",
            status_code=400,
        )

    target_row: CardRow | None = None
    for row in gs.card_rows:
        if row.position == row_position:
            target_row = row
            break

    if target_row is None:
        raise GameException(f"Row {row_position} does not exist", status_code=404)

    # Remove non-karaoke cards
    non_karaoke = [c for c in target_row.cards if not c.is_karaoke]
    target_row.cards = [c for c in target_row.cards if c.is_karaoke]

    # Replace removed slots from deck
    for _ in non_karaoke:
        _replace_card(gs, target_row)

    gs.turn_number += 1
    _advance_turn(gs)

    payload = {"row_position": row_position, "cards_removed": len(non_karaoke)}
    return gs, payload
