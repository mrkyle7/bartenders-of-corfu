"""Pure-function game action implementations.

Each action validates preconditions, applies state changes, and returns
(new_game_state, move_payload). Raises GameException on invalid input.

Turn advancement: after every action the turn advances to the next active
(non-eliminated) player in turn_order.
"""

from uuid import UUID

from app.card import (
    ABILITY_ROW,
    FREE_ACTION_TYPES,
    KARAOKE_ROW,
    ORDERS_ROW,
    ROW_SIZE,
    Card,
    CardRow,
)
from app.cocktails import drink_points, is_cocktail, matches_order
from app.game import GameException
from app.GameState import OPEN_DISPLAY_SIZE, GameState, draw_token, regular_in_bag
from app.Ingredient import (
    BOOZY_SPECIALS,
    SPECIALIST_SPECIAL,
    Ingredient,
    is_special,
)
from app.PlayerState import (
    MAX_CUP_INGREDIENTS,
    MAX_CUP_SPECIALS,
    MIN_BLADDER_CAPACITY,
    PlayerState,
)
from app.specials import roll_face, take_special

_SPIRITS = {
    Ingredient.WHISKEY,
    Ingredient.GIN,
    Ingredient.RUM,
    Ingredient.TEQUILA,
    Ingredient.VODKA,
}
_MIXERS = {Ingredient.SODA, Ingredient.TONIC, Ingredient.COLA, Ingredient.CRANBERRY}

# The two-player target; games with more players aim lower (see
# GameState.score_to_win).
SCORE_TO_WIN = 40
KARAOKE_CARDS_TO_WIN = 3
MAX_DRUNK_LEVEL = 5
# Clearing the orders row is your main action and needs drunk 3+; swiping the
# ability row is a free action once a turn and needs drunk 2+.
MIN_DRUNK_TO_REFRESH = 3
MIN_DRUNK_TO_SWIPE = 2


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


def _reset_take_batch_state(gs: GameState):
    """Reset multi-batch TakeIngredients tracking. Called when a take action completes."""
    gs.ingredients_taken_this_turn = 0
    gs.drunk_ingredients_this_turn = []
    gs.bag_draw_pending = []
    gs.bag_draw_pending_specials = []
    gs.taken_records_this_turn = []


def _advance_turn(gs: GameState) -> GameState:
    """Advance player_turn to the next active player in turn_order and reset per-turn state."""
    # Reset all per-turn tracking whenever the turn advances
    _reset_take_batch_state(gs)
    gs.main_action_taken_this_turn = False
    gs.free_actions_used_this_turn = []

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


# ─── Free action helpers ─────────────────────────────────────────────────────

# Free actions every player has, once a turn: claiming a card, and clearing
# the orders row or swiping the ability row away when drunk enough.
CLAIM_CARD = "claim_card"
CLEAR_ORDERS = "refresh_orders_row"
SWIPE_ABILITIES = "refresh_ability_row"


def _usable_now(gs: GameState, ps: "PlayerState", action_type: str) -> bool:
    """Whether an always-there free action has anything to do right now."""
    if action_type == CLAIM_CARD:
        return any(
            _can_afford(ps, card)
            for row in gs.card_rows
            if row.position != ORDERS_ROW
            for card in row.cards
        )
    if action_type == SWIPE_ABILITIES:
        row = _row(gs, ABILITY_ROW)
        return (
            ps.drunk_level >= MIN_DRUNK_TO_SWIPE
            and row is not None
            and (bool(row.cards) or bool(gs._deck_dicts))
        )
    if action_type == CLEAR_ORDERS:
        row = _row(gs, ORDERS_ROW)
        return (
            ps.drunk_level >= MIN_DRUNK_TO_REFRESH
            and row is not None
            and bool(row.cards)
        )
    return True


def _available_free_actions(
    gs: GameState, ps: "PlayerState", used: list[str], usable_only: bool = False
) -> set[str]:
    """The free action types the player may still use this turn.

    Each is once a turn: those granted by the player's free-action cards,
    plus claiming a card, clearing the orders row and swiping the ability
    row, which everyone has.
    With ``usable_only`` the everyone-has ones count only when they could be
    done right now, so they don't hold the turn open for nothing.
    """
    actions = set()
    for card_dict in ps.cards:
        if card_dict.get("card_type") == "free_action":
            spirit = card_dict.get("spirit_type")
            action_type = FREE_ACTION_TYPES.get(spirit) if spirit else None
            if action_type and action_type not in used:
                actions.add(action_type)
    for action_type in (CLAIM_CARD, CLEAR_ORDERS, SWIPE_ABILITIES):
        if action_type in used:
            continue
        if usable_only and not _usable_now(gs, ps, action_type):
            continue
        actions.add(action_type)
    return actions


def _require_action_eligible(gs: GameState, player_id: UUID, action_type: str) -> None:
    """Raise 409 if `action_type` is not currently permitted for the player.

    Permitted iff the action is available as an unused free action, or the
    player has not yet taken their main action this turn. Use this BEFORE
    mutating state in multi-step actions (TakeIngredients, DrawFromBag),
    where the eligibility check would otherwise only fire on the final batch.
    """
    ps = gs.player_states[player_id]
    available_free = _available_free_actions(gs, ps, gs.free_actions_used_this_turn)
    if action_type in available_free:
        return
    if not gs.main_action_taken_this_turn:
        return
    raise GameException(
        "You have already taken your main action this turn",
        status_code=409,
    )


def _finish_turn_action(gs: GameState, player_id: UUID, action_type: str) -> bool:
    """Handle turn advancement after a turn action is performed.

    Determines whether this action is a free action or the main action,
    and advances the turn when appropriate.

    Returns True if the action was used as a free action, False if it was the main action.
    Raises GameException if the player has already taken their main action and
    this isn't an available free action.
    """
    ps = gs.player_states[player_id]
    available_free = _available_free_actions(gs, ps, gs.free_actions_used_this_turn)

    if action_type in available_free:
        # Use as free action
        gs.free_actions_used_this_turn.append(action_type)
        is_free = True
    elif not gs.main_action_taken_this_turn:
        # Use as main action
        gs.main_action_taken_this_turn = True
        is_free = False
    else:
        raise GameException(
            "You have already taken your main action this turn",
            status_code=409,
        )

    # Advance turn when main action is done and no unused free actions remain.
    # An eliminated player can no longer use their free actions, so the turn
    # must advance regardless — otherwise the game stalls on a hospitalised
    # or wet player who still holds unused free action cards.
    if gs.main_action_taken_this_turn:
        remaining_free = _available_free_actions(
            gs, ps, gs.free_actions_used_this_turn, usable_only=True
        )
        if len(remaining_free) == 0 or ps.is_eliminated:
            gs.turn_number += 1
            _advance_turn(gs)
            _check_last_round_complete(gs)

    return is_free


def _require_no_take_in_progress(gs: GameState):
    """Raise if the current player is mid-way through a TakeIngredients action."""
    if gs.ingredients_taken_this_turn > 0 or gs.bag_draw_pending:
        raise GameException(
            "Cannot perform this action while a take-ingredients action is in progress; "
            "complete the take first.",
            status_code=409,
        )


def _replenish_display(gs: GameState):
    """Draw from the bag until the open display shows OPEN_DISPLAY_SIZE tokens.

    Specials that come out go to the specials display and the drawing carries
    on. (An old special die token is rolled as it comes out.)
    """
    while len(gs.open_display) < OPEN_DISPLAY_SIZE:
        item = draw_token(gs)
        if item is None:
            return
        gs.open_display.append(item)
        gs.display_specials.append(
            roll_face(gs) if item == Ingredient.SPECIAL else None
        )


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

    # Specials on the mat go back to the supply for others to take
    ps.special_ingredients = []


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
    if ps.points >= gs.score_to_win and not gs.last_round:
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
    Bitters, cointreau and vermouth count as spirits; lemon and sugar as
    plain mixers.
    """
    ps = gs.player_states[player_id]
    spirits = [i for i in ingredients if i in _SPIRITS or i in BOOZY_SPECIALS]

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
    plain_mixers += [
        i for i in ingredients if is_special(i) and i not in BOOZY_SPECIALS
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


def _row(gs: GameState, position: int) -> CardRow | None:
    return next((r for r in gs.card_rows if r.position == position), None)


def _deck_for_row(gs: GameState, row: CardRow) -> list[dict] | None:
    """The deck a row refills from: orders for the orders row, abilities for
    the ability row, and nothing for the karaoke row.

    Games dealt before the orders row existed hold ability cards in row 2;
    those rows keep refilling from the ability deck.
    """
    if row.position == KARAOKE_ROW:
        return None
    if row.position == ORDERS_ROW and (
        gs.order_deck or any(c.card_type == "order" for c in row.cards)
    ):
        return gs.order_deck
    return gs._deck_dicts


def _replace_card(gs: GameState, row: CardRow):
    """Deal the top card of the row's deck into the row, if there is one."""
    deck = _deck_for_row(gs, row)
    if deck:
        row.cards.append(Card.from_dict(deck.pop(0)))


def _rotate_row(gs: GameState, row: CardRow) -> int:
    """Put every card in the row on the bottom of its deck and deal a fresh row."""
    deck = _deck_for_row(gs, row)
    removed = list(row.cards)
    row.cards = []
    if deck is None:
        return 0
    deck.extend(c.to_dict() for c in removed)
    for _ in range(ROW_SIZE):
        _replace_card(gs, row)
    return len(removed)


def card_payment(
    ps: PlayerState, card: Card, pay_with: str | None = None
) -> list[Ingredient] | None:
    """The bladder ingredients that pay for a card, or None if it can't be paid.

    Claiming a karaoke or ability card takes its cost out of the bladder and
    back into the bag. ``pay_with`` picks how to pay where there's a choice:
    the spirit for a cup doubler (any spirit with three will do without it),
    and for a specialist either its spirit (two) or its special (one; the
    special is used by default when held).
    """
    counts: dict[str, int] = {}
    for i in ps.bladder:
        counts[i.name] = counts.get(i.name, 0) + 1

    def take(name: str | None, n: int) -> list[Ingredient] | None:
        if not name or counts.get(name, 0) < n:
            return None
        return [Ingredient[name]] * n

    ct = card.card_type
    if ct in ("karaoke", "free_action"):
        return take(card.spirit_type, 3)
    if ct == "store":
        return take(card.spirit_type, 1)
    if ct == "refresher":
        return take(card.mixer_type, 2)
    if ct == "specialist":
        special = SPECIALIST_SPECIAL.get(card.spirit_type or "")
        with_special = take(special.name, 1) if special else None
        with_spirit = take(card.spirit_type, 2)
        if pay_with and pay_with.upper() == (card.spirit_type or ""):
            return with_spirit
        if pay_with and special and pay_with.upper() == special.name:
            return with_special
        return with_special or with_spirit
    if ct == "cup_doubler":
        if pay_with:
            return take(pay_with.upper(), 3)
        for s in _SPIRITS:
            paid = take(s.name, 3)
            if paid:
                return paid
        return None
    return None


def _can_afford(ps: PlayerState, card: Card, spirit_type: str | None = None) -> bool:
    """Whether the player's bladder can pay for the card (see card_payment)."""
    return card_payment(ps, card, spirit_type) is not None


def _pay_for_card(gs: GameState, ps: PlayerState, paid: list[Ingredient]) -> None:
    """Move a card's cost out of the bladder and into the bag."""
    for ing in paid:
        ps.bladder.remove(ing)
        gs.bag_contents.append(ing)


# ─── Turn actions ─────────────────────────────────────────────────────────────


def draw_from_bag(
    gs: GameState,
    player_id: UUID,
    count: int,
) -> tuple[GameState, dict]:
    """DrawFromBag — reveals ingredients from the bag and holds them pending assignment.

    Draws `count` ingredients randomly from the bag and stores them in
    gs.bag_draw_pending. Specials that come out go to the specials display
    and don't count: the draw carries on. The player must then call take_ingredients with
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

    # Validate up front that take_ingredients is permitted (as a free action or
    # the main action). Without this check, draw_from_bag would mutate state
    # and the rejection would only fire later — when take_ingredients tried to
    # finish the turn — leaving the game stuck mid-batch.
    if gs.ingredients_taken_this_turn == 0:
        _require_action_eligible(gs, player_id, "take_ingredients")

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

    in_bag = regular_in_bag(gs)
    if in_bag < count:
        raise GameException(
            f"Not enough ingredients in bag (need {count}, have {in_bag}).",
            status_code=409,
        )

    specials_before = len(gs.specials_display)
    drawn: list[Ingredient] = []
    for _ in range(count):
        drawn.append(draw_token(gs))

    gs.bag_draw_pending = drawn
    # Special tokens are rolled as they come out of the bag
    gs.bag_draw_pending_specials = []
    for i in drawn:
        gs.bag_draw_pending_specials.append(
            roll_face(gs) if i == Ingredient.SPECIAL else None
        )
    payload = {
        "drawn": [i.name for i in drawn],
        "specials": list(gs.bag_draw_pending_specials),
        "to_specials_display": [i.name for i in gs.specials_display[specials_before:]],
    }
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
        ingredient: str,   # Ingredient enum name (required for source="display"/"specials")
        source: "bag" | "display" | "pending" | "specials",
        disposition: "cup" | "drink",
        cup_index: 0 | 1   # required when disposition == "cup"
        display_index: int # optional: which display slot (tells specials apart)
        special_type: str  # optional: the special to take from a "choose any" token
        swap_special: str  # optional: a special to give back when holding two
    }

    Specials (bitters, cointreau, lemon, sugar, vermouth) are taken from the
    specials display (source="specials") into a glass, where up to
    MAX_CUP_SPECIALS sit on top of its spirits and mixers, or drunk like a
    mixer. A blind bag draw never hands you one: specials that come out go
    to the specials display and the draw carries on.

    An old special die token (games started before specials were
    ingredients) puts the special it shows on the player's mat (see
    app/specials.py); disposition is ignored for it.

    Returns (new_game_state, move_payload) where move_payload includes
    "turn_complete": bool indicating whether the turn has ended.
    """
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)

    # First batch of a take must pass the same eligibility check that other
    # turn actions perform via _finish_turn_action. Doing it here prevents the
    # batch from succeeding only to be rejected on a later batch's
    # turn-completion path — which would leave the take half-done.
    if gs.ingredients_taken_this_turn == 0 and not gs.bag_draw_pending:
        _require_action_eligible(gs, player_id, "take_ingredients")

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
            available_count = (
                regular_in_bag(gs) + len(gs.open_display) + len(gs.specials_display)
            )
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

        # Resolve ingredient from source; a special token also has its face
        face: str | None = None
        if source == "display":
            try:
                ingredient = Ingredient[raw_name]
            except KeyError:
                raise GameException(f"Unknown ingredient: {raw_name}", status_code=400)
            slot = asn.get("display_index")
            if not (
                isinstance(slot, int)
                and 0 <= slot < len(gs.open_display)
                and gs.open_display[slot] == ingredient
            ):
                if ingredient not in gs.open_display:
                    raise GameException(
                        f"{raw_name} is not in the open display", status_code=400
                    )
                slot = gs.open_display.index(ingredient)
            gs.open_display.pop(slot)
            face = gs.display_specials.pop(slot)
        elif source == "pending":
            # Use the next ingredient from the pending draw (already removed from bag)
            if not gs.bag_draw_pending:
                raise GameException(
                    "No pending bag ingredient to assign.", status_code=400
                )
            ingredient = gs.bag_draw_pending.pop(0)
            face = gs.bag_draw_pending_specials.pop(0)
            raw_name = ingredient.name
        elif source == "specials":
            try:
                ingredient = Ingredient[raw_name]
            except KeyError:
                raise GameException(f"Unknown ingredient: {raw_name}", status_code=400)
            if ingredient not in gs.specials_display:
                raise GameException(
                    f"{raw_name} is not on the specials display", status_code=400
                )
            gs.specials_display.remove(ingredient)
        elif source == "bag":
            # Direct bag draw — only permitted when no pending draw exists
            if gs.bag_draw_pending:
                raise GameException(
                    "Assign your pending bag ingredients before drawing more.",
                    status_code=409,
                )
            drawn = draw_token(gs)
            if drawn is None:
                raise GameException(
                    "There are no spirits or mixers left in the bag", status_code=400
                )
            ingredient = drawn
            raw_name = ingredient.name
            if ingredient == Ingredient.SPECIAL:
                face = roll_face(gs)
        else:
            raise GameException(f"Unknown source: {source}", status_code=400)

        record: dict = {"ingredient": raw_name, "source": source}

        if ingredient == Ingredient.SPECIAL:
            # Special token: its special goes on the mat, the token back in the bag
            result = take_special(
                gs,
                ps,
                face or "any",
                choice=asn.get("special_type"),
                swap=asn.get("swap_special"),
            )
            record["disposition"] = "special"
            record.update(result)
        elif disposition == "cup":
            if cup_index not in (0, 1):
                raise GameException("cup_index must be 0 or 1", status_code=400)
            cup = ps.cups[cup_index]
            if is_special(ingredient):
                if cup.specials_full:
                    raise GameException(
                        f"Cup {cup_index} already holds {MAX_CUP_SPECIALS} specials",
                        status_code=400,
                    )
            elif cup.is_full:
                raise GameException(
                    f"Cup {cup_index} is full (max {MAX_CUP_INGREDIENTS})",
                    status_code=400,
                )
            elif ingredient not in _SPIRITS and ingredient not in _MIXERS:
                raise GameException(
                    "Only spirits, mixers and specials may be placed in cups",
                    status_code=400,
                )
            cup.ingredients.append(ingredient)
            record["disposition"] = "cup"
            record["cup_index"] = cup_index
        elif disposition == "drink":
            if (
                ingredient not in _SPIRITS
                and ingredient not in _MIXERS
                and not is_special(ingredient)
            ):
                raise GameException(
                    "Only spirits, mixers and specials may be drunk directly",
                    status_code=400,
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

    is_free = False
    if turn_complete:
        # Apply drunk modifier once across all ingredients drunk this whole turn
        if gs.drunk_ingredients_this_turn:
            _apply_drunk_modifier(gs, player_id, gs.drunk_ingredients_this_turn)
        _replenish_display(gs)
        # Reset take batch state before handling turn action (since _advance_turn
        # may or may not be called depending on free actions)
        _reset_take_batch_state(gs)
        is_free = _finish_turn_action(gs, player_id, "take_ingredients")

    # Each batch is its own move record, so only emit this batch's records.
    payload = {
        "taken": taken_records,
        "turn_complete": turn_complete,
        "is_free_action": is_free,
    }
    return gs, payload


def _sell_one_cup(
    ps: PlayerState,
    gs: GameState,
    cup_index: int,
    declared_specials: list[str],
    mat_remaining: list[str],
) -> dict:
    """Validate and resolve a single cup sale.

    ``mat_remaining`` is mutated to reflect specials consumed by this sale —
    callers selling multiple cups in one action share the same list so the
    same special token cannot be declared twice.
    Mutates ``ps`` (cup, points, specials) and ``gs.bag_contents``.
    Raises GameException on validation failure.
    """
    if cup_index not in (0, 1):
        raise GameException("cup_index must be 0 or 1", status_code=400)

    cup = ps.cups[cup_index]
    if cup.is_empty:
        raise GameException("Cup is empty", status_code=400)

    # Validate declared specials against the shared remaining-mat budget
    for s in declared_specials:
        if s not in mat_remaining:
            raise GameException(
                f"Special '{s}' is not on your player mat", status_code=400
            )
        mat_remaining.remove(s)

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

    # A matching order on the table pays its bonus to whoever serves it first
    served = None
    orders = _row(gs, ORDERS_ROW)
    if orders is not None:
        for card in orders.cards:
            if card.card_type == "order" and matches_order(
                card.to_dict(), cup.ingredients, declared_specials
            ):
                served = card
                break
    if served is not None:
        pts += served.bonus
        orders.cards.remove(served)
        gs.order_deck.append(served.to_dict())
        _replace_card(gs, orders)

    sold_ingredients = list(cup.ingredients)
    gs.bag_contents.extend(sold_ingredients)
    # Specials go back to the supply (their tokens went back in the bag when taken)
    for s in declared_specials:
        ps.special_ingredients.remove(s)

    cup.ingredients = []
    ps.points += pts

    result = {
        "cup_index": cup_index,
        "ingredients": [i.name for i in sold_ingredients],
        "declared_specials": list(declared_specials),
        "points_earned": pts,
    }
    if served is not None:
        result["order"] = {"name": served.name, "bonus": served.bonus}
    return result


def sell_cup(
    gs: GameState,
    player_id: UUID,
    cup_index: int,
    declared_specials: list[str],
    additional_cups: list[dict] | None = None,
) -> tuple[GameState, dict]:
    """SellCup action.

    When ``additional_cups`` is provided the action sells both cups in one
    action. Each cup is validated and scored independently (each may serve an
    order); points stack and a single ``_finish_turn_action`` call advances
    the turn.
    """
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)
    _require_no_take_in_progress(gs)

    # Build the full list of (cup_index, declared_specials) to sell, in order.
    sales: list[tuple[int, list[str]]] = [(cup_index, list(declared_specials))]
    for extra in additional_cups or []:
        ci = extra.get("cup_index")
        if ci is None:
            raise GameException(
                "Each additional cup must specify cup_index", status_code=400
            )
        ds = extra.get("declared_specials", []) or []
        sales.append((ci, list(ds)))

    seen_indices: set[int] = set()
    for ci, _ in sales:
        if ci in seen_indices:
            raise GameException(
                "Cannot sell the same cup twice in one action", status_code=400
            )
        seen_indices.add(ci)

    mat_remaining = list(ps.special_ingredients)
    sold: list[dict] = []
    total_points = 0
    for ci, ds in sales:
        result = _sell_one_cup(ps, gs, ci, ds, mat_remaining)
        sold.append(result)
        total_points += result["points_earned"]

    _check_victory(gs, player_id)
    is_free = _finish_turn_action(gs, player_id, "sell_cup")

    primary = sold[0]
    payload = {
        "cup_index": primary["cup_index"],
        "ingredients": primary["ingredients"],
        "declared_specials": primary["declared_specials"],
        "points_earned": total_points,
        "is_free_action": is_free,
    }
    orders_served = [c["order"] for c in sold if "order" in c]
    if orders_served:
        payload["orders"] = orders_served
    if len(sold) > 1:
        payload["sold_cups"] = sold
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

    is_free = _finish_turn_action(gs, player_id, "drink_cup")

    payload = {
        "cup_index": cup_index,
        "ingredients": [i.name for i in drunk_ingredients],
        "is_free_action": is_free,
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

    is_free = _finish_turn_action(gs, player_id, "go_for_a_wee")

    payload = {"excreted": [i.name for i in excreted], "is_free_action": is_free}
    return gs, payload


def claim_card(
    gs: GameState,
    player_id: UUID,
    card_id: str,
    cup_index: int | None = None,
    spirit_type: str | None = None,
) -> tuple[GameState, dict]:
    """ClaimCard — a free action, once a turn, before or after your main action.

    Karaoke cards come from row 1 (not replaced); ability cards from row 3,
    replaced from the top of the ability deck. Orders can't be claimed: they
    are served by selling the drink.

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
    if card_type == "order":
        raise GameException(
            "Orders aren't claimed: sell the drink to serve one", status_code=400
        )
    if CLAIM_CARD in gs.free_actions_used_this_turn:
        raise GameException("You've already claimed a card this turn", status_code=409)

    # Per-type checks, then the cost: it comes out of the bladder into the bag
    if card_type == "cup_doubler":
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
    if card_type not in (
        "karaoke",
        "store",
        "refresher",
        "cup_doubler",
        "specialist",
        "free_action",
    ):
        raise GameException(f"Unknown card type: {card_type}", status_code=500)
    needs_spirit = ("karaoke", "store", "specialist", "free_action")
    if card_type in needs_spirit and target_card.spirit_type is None:
        raise GameException("Card has no spirit type", status_code=500)
    paid = card_payment(ps, target_card, spirit_type)
    if paid is None:
        raise GameException(
            f"Your bladder doesn't hold what {target_card.name} costs",
            status_code=400,
        )
    _pay_for_card(gs, ps, paid)

    # Remove card from row
    target_row.cards.remove(target_card)

    # Per-type effects (the cost has been paid into the bag)
    if card_type == "karaoke":
        ps.points += 5
        ps.karaoke_cards_claimed += 1
        ps.cards.append(target_card.to_dict())

    elif card_type == "store":
        # Effect: the rest of that spirit in the bladder moves onto the card
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

    elif card_type == "free_action":
        ps.cards.append(target_card.to_dict())
        ps.points += 2

    # Replace the claimed card's slot from the deck (if any cards remain)
    _replace_card(gs, target_row)

    _check_victory(gs, player_id)
    is_free = _finish_turn_action(gs, player_id, "claim_card")

    payload = {
        "card_id": card_id,
        "card_name": target_card.name,
        "card_type": card_type,
        "paid": [i.name for i in paid],
        "is_karaoke": target_card.is_karaoke,
        "row_position": target_row.position,
        "is_free_action": is_free,
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

    # If drinking from the store hospitalised this player, advance the turn
    # so the game doesn't get stuck (this is a free action and would
    # otherwise leave player_turn pointing at an eliminated player).
    if ps.is_eliminated and gs.player_turn == player_id:
        _reset_take_batch_state(gs)
        gs.turn_number += 1
        _advance_turn(gs)
        _check_last_round_complete(gs)

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
    """ReRollSpecials — retired.

    Specials are now rolled as their tokens come out of the bag, so there is
    nothing to re-roll. Kept so old clients get a clear answer.
    """
    raise GameException(
        "Re-rolling specials is no longer part of the game", status_code=400
    )


def refresh_card_row(
    gs: GameState,
    player_id: UUID,
    row_position: int,
) -> tuple[GameState, dict]:
    """Clear a row of the market and deal a fresh one.

    Row 1 (karaoke) is never cleared.
    Row 2 (orders): a free action once a turn, at drunk 3+. Nothing like
    wiping out the order a rival was one ingredient away from.
    Row 3 (abilities): a free action once a turn, at drunk 2+.
    Cleared cards go to the bottom of their deck.
    """
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)
    _require_no_take_in_progress(gs)

    if row_position == KARAOKE_ROW:
        raise GameException(
            "Row 1 (karaoke row) cannot be refreshed",
            status_code=400,
        )

    target_row = _row(gs, row_position)
    if target_row is None:
        raise GameException(f"Row {row_position} does not exist", status_code=404)

    if row_position == ABILITY_ROW:
        needed, action_type = MIN_DRUNK_TO_SWIPE, SWIPE_ABILITIES
        if SWIPE_ABILITIES in gs.free_actions_used_this_turn:
            raise GameException(
                "You've already swiped the ability cards this turn", status_code=409
            )
    else:
        needed, action_type = MIN_DRUNK_TO_REFRESH, CLEAR_ORDERS
        if CLEAR_ORDERS in gs.free_actions_used_this_turn:
            raise GameException(
                "You've already cleared the orders this turn", status_code=409
            )

    if ps.drunk_level < needed:
        raise GameException(
            f"Must be drunk level {needed}+ to clear row {row_position}; "
            f"you are at {ps.drunk_level}",
            status_code=400,
        )

    removed = _rotate_row(gs, target_row)
    is_free = _finish_turn_action(gs, player_id, action_type)

    payload = {
        "row_position": row_position,
        "cards_removed": removed,
        "is_free_action": is_free,
    }
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
        _reset_take_batch_state(gs)
        gs.turn_number += 1
        _advance_turn(gs)
        _check_last_round_complete(gs)

    _check_last_player_standing(gs)

    payload = {"player_id": str(player_id)}
    return gs, payload


def end_turn(
    gs: GameState,
    player_id: UUID,
) -> tuple[GameState, dict]:
    """EndTurn — player explicitly ends their turn, forfeiting unused free actions.

    Only available after the main action has been taken but free actions remain.
    """
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)

    if not gs.main_action_taken_this_turn:
        raise GameException(
            "You must take an action before ending your turn", status_code=409
        )

    remaining_free = _available_free_actions(
        gs, ps, gs.free_actions_used_this_turn, usable_only=True
    )
    if len(remaining_free) == 0:
        raise GameException(
            "Your turn is already complete — no free actions to forfeit",
            status_code=409,
        )

    gs.turn_number += 1
    _advance_turn(gs)
    _check_last_round_complete(gs)

    payload = {"forfeited_free_actions": sorted(remaining_free)}
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
