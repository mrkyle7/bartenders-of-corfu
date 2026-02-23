"""Pure-function game action implementations.

Each action validates preconditions, applies state changes, and returns
(new_game_state, move_payload). Raises GameException on invalid input.

Turn advancement: after every action the turn advances to the next active
(non-eliminated) player in turn_order.
"""

import copy
import random
from uuid import UUID

from app.card import Card, CardRow
from app.cocktails import drink_points
from app.game import GameException
from app.GameState import OPEN_DISPLAY_SIZE, GameState
from app.Ingredient import Ingredient, SpecialType
from app.PlayerState import MAX_CUP_INGREDIENTS, MIN_BLADDER_CAPACITY, PlayerState

_SPIRITS = {Ingredient.WHISKEY, Ingredient.GIN, Ingredient.RUM, Ingredient.TEQUILA, Ingredient.VODKA}
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
    """Advance player_turn to the next active player in turn_order."""
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


def _replenish_display(gs: GameState):
    """Draw from the bag to fill the open display up to OPEN_DISPLAY_SIZE."""
    deficit = OPEN_DISPLAY_SIZE - len(gs.open_display)
    if deficit > 0 and gs.bag_contents:
        fill = min(deficit, len(gs.bag_contents))
        gs.open_display.extend(gs.bag_contents[:fill])
        gs.bag_contents = gs.bag_contents[fill:]


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


def _drink_ingredient(gs: GameState, player_id: UUID, ingredient: Ingredient):
    """Apply DrinkIngredient rule for one spirit or mixer."""
    ps = gs.player_states[player_id]
    if ingredient in _SPIRITS:
        ps.drunk_level = ps.drunk_level + 1
    elif ingredient in _MIXERS:
        ps.drunk_level = max(0, ps.drunk_level - 1)
    ps.bladder.append(ingredient)
    _check_elimination(gs, player_id)


def _replace_card(gs: GameState, row: CardRow):
    """Draw one card from the deck into the row, if deck has cards."""
    if gs._deck_dicts:
        from app.card import Card
        card_dict = gs._deck_dicts.pop(0)
        row.cards.append(Card.from_dict(card_dict))


# ─── Turn actions ─────────────────────────────────────────────────────────────


def take_ingredients(
    gs: GameState,
    player_id: UUID,
    assignments: list[dict],
) -> tuple[GameState, dict]:
    """TakeIngredients action.

    assignments: list of {
        ingredient: str,   # Ingredient enum name
        source: "bag" | "display",
        disposition: "cup" | "drink" | "special",
        cup_index: 0 | 1   # only when disposition == "cup"
    }

    Returns (new_game_state, move_payload).
    """
    gs = _deep_copy_state(gs)
    _require_turn(gs, player_id)
    ps = gs.player_states[player_id]
    _require_active(ps)

    take_limit = ps.take_limit
    available_count = len(gs.bag_contents) + len(gs.open_display)
    if available_count < take_limit:
        raise GameException(
            f"Not enough ingredients available ({available_count} < {take_limit}). "
            "Choose a different action.",
            status_code=409,
        )

    if len(assignments) != take_limit:
        raise GameException(
            f"Must take exactly {take_limit} ingredient(s), got {len(assignments)}",
            status_code=400,
        )

    taken_records: list[dict] = []

    for asn in assignments:
        raw_name = asn.get("ingredient", "")
        source = asn.get("source", "bag")
        disposition = asn.get("disposition", "drink")
        cup_index = asn.get("cup_index", 0)

        try:
            ingredient = Ingredient[raw_name]
        except KeyError:
            raise GameException(f"Unknown ingredient: {raw_name}", status_code=400)

        # Remove from source
        if source == "display":
            if ingredient not in gs.open_display:
                raise GameException(
                    f"{raw_name} is not in the open display", status_code=400
                )
            gs.open_display.remove(ingredient)
        else:
            if ingredient not in gs.bag_contents:
                raise GameException(
                    f"{raw_name} is not available in the bag", status_code=400
                )
            gs.bag_contents.remove(ingredient)

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
            cup = ps.cup1 if cup_index == 0 else ps.cup2
            if len(cup) >= MAX_CUP_INGREDIENTS:
                raise GameException(
                    f"Cup {cup_index} is full (max {MAX_CUP_INGREDIENTS})",
                    status_code=400,
                )
            if ingredient not in _SPIRITS and ingredient not in _MIXERS:
                raise GameException(
                    "Only spirits and mixers may be placed in cups", status_code=400
                )
            cup.append(ingredient)
            record["disposition"] = "cup"
            record["cup_index"] = cup_index
        elif disposition == "drink":
            if ingredient not in _SPIRITS and ingredient not in _MIXERS:
                raise GameException(
                    "Only spirits and mixers may be drunk directly", status_code=400
                )
            _drink_ingredient(gs, player_id, ingredient)
            record["disposition"] = "drink"
        else:
            raise GameException(f"Unknown disposition: {disposition}", status_code=400)

        taken_records.append(record)

    _replenish_display(gs)
    gs.turn_number += 1
    _advance_turn(gs)

    payload = {"taken": taken_records}
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

    if cup_index not in (0, 1):
        raise GameException("cup_index must be 0 or 1", status_code=400)

    cup = ps.cup1 if cup_index == 0 else ps.cup2
    if not cup:
        raise GameException("Cup is empty", status_code=400)

    # Validate declared specials are on the player's mat
    mat = list(ps.special_ingredients)
    for s in declared_specials:
        if s not in mat:
            raise GameException(
                f"Special '{s}' is not on your player mat", status_code=400
            )
        mat.remove(s)

    pts = drink_points(cup, declared_specials)
    if pts is None:
        raise GameException(
            "This combination of ingredients cannot be sold", status_code=400
        )

    sold_ingredients = list(cup)
    # Return sold ingredients + declared specials to the bag
    gs.bag_contents.extend(sold_ingredients)
    for s in declared_specials:
        # Specials are returned as SPECIAL tokens to the bag
        gs.bag_contents.append(Ingredient.SPECIAL)
        ps.special_ingredients.remove(s)

    if cup_index == 0:
        ps.cup1 = []
    else:
        ps.cup2 = []

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

    if cup_index not in (0, 1):
        raise GameException("cup_index must be 0 or 1", status_code=400)

    cup = ps.cup1 if cup_index == 0 else ps.cup2
    if not cup:
        raise GameException("Cup is empty", status_code=400)

    drunk_ingredients = list(cup)
    for ingredient in drunk_ingredients:
        _drink_ingredient(gs, player_id, ingredient)
    # Drunk cup ingredients go to the bladder (not the bag) — handled by _drink_ingredient

    if cup_index == 0:
        ps.cup1 = []
    else:
        ps.cup2 = []

    gs.turn_number += 1
    _advance_turn(gs)

    payload = {"cup_index": cup_index, "ingredients": [i.name for i in drunk_ingredients]}
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

    # Replace card from deck (if not karaoke — karaoke cards are never discarded)
    if not target_card.is_karaoke:
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
