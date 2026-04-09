"""Pure-function game action implementations.

Each action validates preconditions, applies state changes, and returns
(new_game_state, move_payload). Raises GameException on invalid input.

Turn advancement: after every action the turn advances to the next active
(non-eliminated) player in turn_order.
"""

import random
from uuid import UUID

from app.card import Card, CardRow
from app.cocktails import drink_points, is_cocktail
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

_SPIRIT_MAP: dict[str, Ingredient] = {
    "WHISKEY": Ingredient.WHISKEY,
    "GIN": Ingredient.GIN,
    "RUM": Ingredient.RUM,
    "TEQUILA": Ingredient.TEQUILA,
    "VODKA": Ingredient.VODKA,
}
_MIXER_MAP: dict[str, Ingredient] = {
    "COLA": Ingredient.COLA,
    "SODA": Ingredient.SODA,
    "TONIC": Ingredient.TONIC,
    "CRANBERRY": Ingredient.CRANBERRY,
}


def _spirit_ingredient(spirit_type: str) -> Ingredient:
    ing = _SPIRIT_MAP.get(spirit_type.upper())
    if ing is None:
        raise GameException(f"Unknown spirit type: {spirit_type}", status_code=400)
    return ing


def _mixer_ingredient(mixer_type: str) -> Ingredient:
    ing = _MIXER_MAP.get(mixer_type.upper())
    if ing is None:
        raise GameException(f"Unknown mixer type: {mixer_type}", status_code=400)
    return ing


def _available_spirits(ps: "PlayerState", spirit_type: str) -> int:
    """Count spirits available from bladder."""
    spirit_ing = _spirit_ingredient(spirit_type)
    count = sum(1 for i in ps.bladder if i == spirit_ing)
    return count


def _consume_spirits(ps: "PlayerState", spirit_type: str, count: int) -> None:
    """Remove `count` spirits from bladder first, then from store cards."""
    spirit_ing = _spirit_ingredient(spirit_type)
    remaining = count
    # Remove from bladder first
    new_bladder = list(ps.bladder)
    removed = 0
    for i in range(len(new_bladder) - 1, -1, -1):
        if removed >= remaining:
            break
        if new_bladder[i] == spirit_ing:
            new_bladder.pop(i)
            removed += 1
    ps.bladder = new_bladder
    remaining -= removed
    # Then from store cards
    if remaining > 0:
        for card_dict in ps.cards:
            if (
                card_dict.get("card_type") == "store"
                and card_dict.get("spirit_type") == spirit_type.upper()
            ):
                stored = card_dict.get("stored_spirits", [])
                to_remove = min(remaining, len(stored))
                card_dict["stored_spirits"] = stored[to_remove:]
                remaining -= to_remove
                if remaining == 0:
                    break


def _deep_copy_state(gs: GameState) -> GameState:
    """Return a deep copy of the game state so actions are free of side effects."""
    import copy

    d = copy.deepcopy(gs.to_dict())
    return GameState.from_dict(d)


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


def _return_player_ingredients_to_bag(gs: GameState, ps: PlayerState) -> None:
    """Return all ingredients a player is holding back to the bag.

    Covers drunk ingredients (bladder), ingredients sitting in the player's
    cups, and spirits currently stored on any of the player's Store cards.
    Each source is cleared after being added to the bag. Called when a
    player is eliminated so their ingredients re-enter play.
    """
    # Bladder — ingredients the player has drunk
    if ps.bladder:
        gs.bag_contents.extend(ps.bladder)
        ps.bladder = []

    # Cups — ingredients sitting in the player's cups
    for cup in ps.cups:
        if cup.ingredients:
            gs.bag_contents.extend(cup.ingredients)
            cup.ingredients = []

    # Store cards — spirits stashed on ability cards
    for card_dict in ps.cards:
        if card_dict.get("card_type") == "store":
            stored = card_dict.get("stored_spirits", [])
            for spirit_name in stored:
                gs.bag_contents.append(_spirit_ingredient(spirit_name))
            card_dict["stored_spirits"] = []


def _check_elimination(gs: GameState, player_id: UUID):
    ps = gs.player_states[player_id]
    was_active = ps.status == "active"
    if ps.drunk_level > MAX_DRUNK_LEVEL:
        ps.status = "hospitalised"
    elif len(ps.bladder) > ps.bladder_capacity:
        ps.status = "wet"
    # If the player just became eliminated, return their held ingredients
    # to the bag so they re-enter play for the remaining players.
    if was_active and ps.status in ("hospitalised", "wet"):
        _return_player_ingredients_to_bag(gs, ps)


def _check_victory(gs: GameState, player_id: UUID) -> bool:
    """Check win conditions. Karaoke is instant win. Points >= 40 triggers last round.

    Returns True only for an instant win (karaoke). Points victories are resolved
    at the end of the round via _check_last_round_complete.
    """
    ps = gs.player_states[player_id]
    if ps.status != "active":
        return False
    # Karaoke win — instant, overrides everything
    if ps.karaoke_cards_claimed >= KARAOKE_CARDS_TO_WIN:
        gs.winner = player_id
        return True
    # Points threshold — trigger last round (don't end game yet)
    if ps.points >= SCORE_TO_WIN and not gs.last_round:
        gs.last_round = True
    return False


def _effective_round_start(gs: GameState) -> UUID | None:
    """Return the first active (non-eliminated) player in turn_order."""
    for pid in gs.turn_order:
        ps = gs.player_states.get(pid)
        if ps and not ps.is_eliminated:
            return pid
    return None


def _check_last_round_complete(gs: GameState):
    """After advancing the turn during a last round, end the game if the round wrapped.

    The round is complete when the turn cycles back to the effective starting
    player (first active player in turn_order). The winner is the active player
    with the most points.
    """
    if not gs.last_round or gs.winner is not None:
        return
    round_start = _effective_round_start(gs)
    if round_start is None:
        return
    if gs.player_turn == round_start:
        # Round complete — winner is the player with the most points
        best_pid = None
        best_points = -1
        for pid in gs.turn_order:
            ps = gs.player_states.get(pid)
            if ps and not ps.is_eliminated and ps.points > best_points:
                best_points = ps.points
                best_pid = pid
        gs.winner = best_pid


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

    Refresher cards make their mixer type always contribute -1 (hot mixers),
    even when spirits are consumed. Plain mixers only sober when no spirits.
    """
    ps = gs.player_states[player_id]
    spirits = [i for i in ingredients if i in _SPIRITS]

    # Collect mixer types covered by player's refresher cards
    refresher_mixer_types: set[str] = set()
    for card_dict in ps.cards:
        if card_dict.get("card_type") == "refresher":
            mt = card_dict.get("mixer_type")
            if mt:
                refresher_mixer_types.add(mt.upper())

    hot_mixers = [
        i for i in ingredients if i in _MIXERS and i.name in refresher_mixer_types
    ]
    plain_mixers = [
        i for i in ingredients if i in _MIXERS and i.name not in refresher_mixer_types
    ]

    # delta = spirits - hot_mixers; plain_mixers only subtract when no spirits
    delta = len(spirits) - len(hot_mixers)
    if not spirits:
        delta -= len(plain_mixers)
    ps.drunk_level = max(0, ps.drunk_level + delta)
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
        _check_last_round_complete(gs)

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

    # CupDoubler doubling: non-cocktail drinks from a bendy-straw cup score double
    cocktail = is_cocktail(cup.ingredients, declared_specials)
    if cup.has_cup_doubler and not cocktail:
        pts *= 2

    # Specialist bonus: +2 per matching spirit type, non-cocktails only, after doubling
    if not cocktail:
        specialist_spirit_types = {
            cd.get("spirit_type")
            for cd in ps.cards
            if cd.get("card_type") == "specialist" and cd.get("spirit_type")
        }
        cup_spirit_types = {i.name for i in cup.ingredients if i in _SPIRITS}
        matching = specialist_spirit_types & cup_spirit_types
        pts += len(matching) * 2

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
    _check_last_round_complete(gs)

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
    # Drunk cup ingredients go to the bladder (not the bag) — handled by _drink_ingredient.
    # Clear the cup before applying the drunk modifier so that if the player
    # is eliminated by this drink, the cup ingredients aren't double-returned
    # to the bag (they are now tracked in the bladder).
    cup.ingredients = []
    # Apply drunk modifier in one batch: only sober up if all ingredients are mixers
    _apply_drunk_modifier(gs, player_id, drunk_ingredients)

    gs.turn_number += 1
    _advance_turn(gs)
    _check_last_round_complete(gs)

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

    if not ps.bladder:
        raise GameException(
            "Cannot go for a wee with an empty bladder", status_code=409
        )

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
    _check_last_round_complete(gs)

    payload = {"excreted": [i.name for i in excreted]}
    return gs, payload


def claim_card(
    gs: GameState,
    player_id: UUID,
    card_id: str,
    cup_index: int | None = None,
    spirit_type: str | None = None,
) -> tuple[GameState, dict]:
    """ClaimCard action.

    cup_index: required for cup_doubler cards (0 or 1).
    spirit_type: required for cup_doubler cards (declares which spirit type was used to pay).
    """
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

    card_type = target_card.card_type

    # Per-type cost validation
    if card_type == "karaoke":
        if target_card.spirit_type is None:
            raise GameException("Karaoke card has no spirit type", status_code=500)
        available = _available_spirits(ps, target_card.spirit_type)
        if available < 3:
            raise GameException(
                f"Need 3 {target_card.spirit_type} spirits available; have {available}",
                status_code=400,
            )

    elif card_type == "store":
        if target_card.spirit_type is None:
            raise GameException("Store card has no spirit type", status_code=500)
        spirit_ing = _spirit_ingredient(target_card.spirit_type)
        bladder_count = sum(1 for i in ps.bladder if i == spirit_ing)
        if bladder_count < 1:
            raise GameException(
                f"Need at least 1 {target_card.spirit_type} spirit in bladder; have {bladder_count}",
                status_code=400,
            )

    elif card_type == "refresher":
        if target_card.mixer_type is None:
            raise GameException("Refresher card has no mixer type", status_code=500)
        mixer_ing = _mixer_ingredient(target_card.mixer_type)
        bladder_mixer_count = sum(1 for i in ps.bladder if i == mixer_ing)
        if bladder_mixer_count < 2:
            raise GameException(
                f"Need 2 {target_card.mixer_type} mixers in bladder; have {bladder_mixer_count}",
                status_code=400,
            )

    elif card_type == "cup_doubler":
        if spirit_type is None:
            raise GameException(
                "Must declare spirit_type when claiming a cup doubler card",
                status_code=400,
            )
        if cup_index not in (0, 1):
            raise GameException(
                "Must declare cup_index (0 or 1) when claiming a cup doubler card",
                status_code=400,
            )
        # Spec: bladder only (cannot spend from store cards)
        spirit_ing = _spirit_ingredient(spirit_type)
        bladder_count = sum(1 for i in ps.bladder if i == spirit_ing)
        if bladder_count < 3:
            raise GameException(
                f"Need 3 {spirit_type} spirits in bladder; have {bladder_count}",
                status_code=400,
            )

    elif card_type == "specialist":
        if target_card.spirit_type is None:
            raise GameException("Specialist card has no spirit type", status_code=500)
        # Spec: bladder only, threshold check, requires 2 matching spirits
        spirit_ing = _spirit_ingredient(target_card.spirit_type)
        bladder_count = sum(1 for i in ps.bladder if i == spirit_ing)
        if bladder_count < 2:
            raise GameException(
                f"Need 2 {target_card.spirit_type} spirits in bladder; have {bladder_count}",
                status_code=400,
            )

    # Remove card from row
    target_row.cards.remove(target_card)

    # Per-type effects — cost is a threshold check only, no bladder consumption
    if card_type == "karaoke":
        ps.points += 5
        ps.karaoke_cards_claimed += 1
        ps.cards.append(target_card.to_dict())

    elif card_type == "store":
        # Effect: transfer ALL matching spirits from bladder to stored_spirits on the card
        spirit_ing = _spirit_ingredient(target_card.spirit_type)
        transferred = [i for i in ps.bladder if i == spirit_ing]
        ps.bladder = [i for i in ps.bladder if i != spirit_ing]
        card_dict = target_card.to_dict()
        card_dict["stored_spirits"] = [i.name for i in transferred]
        ps.cards.append(card_dict)
        ps.points += 1

    elif card_type == "refresher":
        ps.cards.append(target_card.to_dict())
        ps.points += 1

    elif card_type == "cup_doubler":
        cup = ps.cups[cup_index]
        cup.has_cup_doubler = True
        ps.cards.append(target_card.to_dict())
        ps.points += 2

    elif card_type == "specialist":
        ps.cards.append(target_card.to_dict())
        ps.points += 2

    # Replace the claimed card's slot from the deck (if any cards remain)
    _replace_card(gs, target_row)

    _check_victory(gs, player_id)
    gs.turn_number += 1
    _advance_turn(gs)
    _check_last_round_complete(gs)

    payload = {
        "card_id": card_id,
        "card_name": target_card.name,
        "card_type": card_type,
        "is_karaoke": target_card.is_karaoke,
        "row_position": target_row.position,
    }
    return gs, payload


def drink_stored_spirit(
    gs: GameState,
    player_id: UUID,
    store_card_index: int,
    count: int,
) -> tuple[GameState, dict]:
    """DrinkStoredSpirit — free action (does not end turn).

    Moves spirits from a store card into the bladder and applies drunk modifier.
    Players can use this at any time during their turn to increase drunk level
    (e.g. to qualify for RefreshCardRow).
    """
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)
    _require_no_take_in_progress(gs)

    if count < 1:
        raise GameException("Must drink at least 1 spirit", status_code=400)

    if store_card_index < 0 or store_card_index >= len(ps.cards):
        raise GameException("Invalid store card index", status_code=400)

    card_dict = ps.cards[store_card_index]
    if card_dict.get("card_type") != "store":
        raise GameException("Card at that index is not a store card", status_code=400)

    stored = card_dict.get("stored_spirits", [])
    if len(stored) < count:
        raise GameException(
            f"Store card only has {len(stored)} spirit(s); requested {count}",
            status_code=400,
        )

    # Remove spirits from store card and add to bladder
    drunk_ingredients: list[Ingredient] = []
    spirit_type = card_dict.get("spirit_type", "")
    spirit_ing = _spirit_ingredient(spirit_type)
    for _ in range(count):
        card_dict["stored_spirits"] = card_dict["stored_spirits"][:-1]
        _drink_ingredient(gs, player_id, spirit_ing)
        drunk_ingredients.append(spirit_ing)

    # Apply drunk modifier for the batch
    _apply_drunk_modifier(gs, player_id, drunk_ingredients)

    payload = {
        "store_card_index": store_card_index,
        "spirit_type": spirit_type,
        "count": count,
        "new_drunk_level": ps.drunk_level,
    }
    return gs, payload


def use_stored_spirit(
    gs: GameState,
    player_id: UUID,
    store_card_index: int,
    cup_index: int,
) -> tuple[GameState, dict]:
    """UseStoredSpirit — free action (does not end turn).

    Moves one spirit from a store card into a cup for selling.
    """
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)
    _require_no_take_in_progress(gs)

    if store_card_index < 0 or store_card_index >= len(ps.cards):
        raise GameException("Invalid store card index", status_code=400)

    card_dict = ps.cards[store_card_index]
    if card_dict.get("card_type") != "store":
        raise GameException("Card at that index is not a store card", status_code=400)

    stored = card_dict.get("stored_spirits", [])
    if len(stored) < 1:
        raise GameException("Store card has no spirits remaining", status_code=400)

    if cup_index not in (0, 1):
        raise GameException("cup_index must be 0 or 1", status_code=400)

    cup = ps.cups[cup_index]
    if cup.is_full:
        raise GameException(
            f"Cup {cup_index} is full (max {MAX_CUP_INGREDIENTS})",
            status_code=400,
        )

    # Pop one spirit from store card and add to cup
    spirit_name = card_dict["stored_spirits"].pop()
    spirit_ing = _spirit_ingredient(spirit_name)
    cup.ingredients.append(spirit_ing)

    payload = {
        "store_card_index": store_card_index,
        "cup_index": cup_index,
        "spirit_type": spirit_name,
    }
    return gs, payload


def reroll_specials(
    gs: GameState,
    player_id: UUID,
    chosen_specials: list[str],
) -> tuple[GameState, dict]:
    """ReRollSpecials action — re-roll selected specials from the player's mat.

    Each chosen special is removed and the special die is rolled once per chosen
    special.  If the roll is not "nothing", a new special of the rolled type is
    added.  If the roll is "nothing", the special is simply lost (nothing is
    returned to the bag).  This consumes the player's turn action.
    """
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)
    _require_no_take_in_progress(gs)

    if len(chosen_specials) < 1:
        raise GameException(
            "Must choose at least 1 special to re-roll", status_code=400
        )

    # Validate all chosen specials are on the player's mat
    mat = list(ps.special_ingredients)
    for s in chosen_specials:
        if s not in mat:
            raise GameException(
                f"Special '{s}' is not on your player mat", status_code=400
            )
        mat.remove(s)

    # Remove chosen specials from mat
    for s in chosen_specials:
        ps.special_ingredients.remove(s)

    # Roll once per chosen special
    results: list[str | None] = []
    for _ in chosen_specials:
        rolled = SpecialType.roll()
        if rolled != SpecialType.NOTHING:
            ps.special_ingredients.append(rolled.value)
            results.append(rolled.value)
        else:
            results.append(None)

    gs.turn_number += 1
    _advance_turn(gs)
    _check_last_round_complete(gs)

    payload = {
        "chosen_specials": chosen_specials,
        "results": results,
    }
    return gs, payload


def refresh_card_row(
    gs: GameState,
    player_id: UUID,
    row_position: int,
) -> tuple[GameState, dict]:
    """RefreshCardRow action.

    Row 1 (karaoke row) cannot be refreshed.
    All cards in the target row are removed to the discard pile and replaced from deck.
    """
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

    if row_position == 1:
        raise GameException(
            "Row 1 (karaoke row) cannot be refreshed",
            status_code=400,
        )

    target_row: CardRow | None = None
    for row in gs.card_rows:
        if row.position == row_position:
            target_row = row
            break

    if target_row is None:
        raise GameException(f"Row {row_position} does not exist", status_code=404)

    # Remove ALL cards → discard pile (never reshuffled)
    removed = list(target_row.cards)
    gs.discard.extend(c.to_dict() for c in removed)
    target_row.cards = []

    # Replace removed slots from deck
    for _ in removed:
        _replace_card(gs, target_row)

    gs.turn_number += 1
    _advance_turn(gs)
    _check_last_round_complete(gs)

    payload = {"row_position": row_position, "cards_removed": len(removed)}
    return gs, payload


def quit_game(
    gs: GameState,
    player_id: UUID,
) -> tuple[GameState, dict]:
    """QuitGame — a player voluntarily leaves the game.

    Sets the player's status to 'quit'. If only one active player remains,
    that player wins by last-player-standing. If it was the quitting player's
    turn, the turn advances to the next active player.
    """
    gs = _deep_copy_state(gs)
    ps = gs.player_states.get(player_id)
    if ps is None:
        raise GameException("Player not found in this game", status_code=404)
    _require_active(ps)

    ps.status = "quit"
    # Return any ingredients the quitting player was holding to the bag
    # so they re-enter play for the remaining players.
    _return_player_ingredients_to_bag(gs, ps)

    # If it was this player's turn, reset batch state and advance
    if gs.player_turn == player_id:
        gs.ingredients_taken_this_turn = 0
        gs.drunk_ingredients_this_turn = []
        gs.bag_draw_pending = []
        gs.taken_records_this_turn = []
        gs.turn_number += 1
        _advance_turn(gs)
        _check_last_round_complete(gs)

    _check_last_player_standing(gs)

    payload = {"player_id": str(player_id)}
    return gs, payload


def cancel_game(
    gs: GameState,
) -> tuple[GameState, dict]:
    """CancelGame — the host cancels the game. No winner is declared."""
    gs = _deep_copy_state(gs)

    # Mark all active players as quit
    for ps in gs.player_states.values():
        if not ps.is_eliminated:
            ps.status = "quit"

    payload = {"cancelled": True}
    return gs, payload
