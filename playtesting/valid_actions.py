"""Enumerate all legal actions for the current player given a GameState.

Mirrors the validation logic in app/actions.py without calling it.
"""

from dataclasses import dataclass, field
from itertools import combinations
from uuid import UUID

from app.GameState import GameState, regular_in_bag
from app.Ingredient import SPECIALIST_SPECIAL, Ingredient
from app.PlayerState import PlayerState
from app.actions import (
    CLAIM_CARD,
    CLEAR_ORDERS,
    MIN_DRUNK_TO_REFRESH,
    MIN_DRUNK_TO_SWIPE,
    SWIPE_ABILITIES,
    _SPIRITS,
    card_payment,
)
from app.card import ABILITY_ROW, FREE_ACTION_TYPES, KARAOKE_ROW, ORDERS_ROW
from app.cocktails import drink_points, is_cocktail, matches_order

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

# Held FreeActionCards turn their spirit's matching action into a
# once-per-turn free action (see app.card.FREE_ACTION_TYPES).
_CARD_FREE_ACTION_MAP: dict[str, str] = FREE_ACTION_TYPES


@dataclass
class Action:
    """Represents a legal action a player can take."""

    action_type: str
    params: dict = field(default_factory=dict)
    is_free: bool = False
    description: str = ""


def _order_served(
    gs: GameState | None,
    ps: PlayerState,
    cup_idx: int,
    declared_specials: list[str],
    skip: set[str] = frozenset(),
):
    """The order on the table this sale would serve, if any (first match)."""
    if gs is None:
        return None
    cup = ps.cups[cup_idx]
    for row in gs.card_rows:
        if row.position != ORDERS_ROW:
            continue
        for card in row.cards:
            if card.card_type != "order" or card.id in skip:
                continue
            if matches_order(card.to_dict(), cup.ingredients, declared_specials):
                return card
    return None


def _full_sell_points(
    ps: PlayerState,
    cup_idx: int,
    declared_specials: list[str],
    gs: GameState | None = None,
    skip_orders: set[str] = frozenset(),
) -> int | None:
    """Calculate full sell points including cup_doubler, specialist and order bonuses."""
    cup = ps.cups[cup_idx]
    pts = drink_points(cup.ingredients, declared_specials)
    if pts is None:
        return None

    cocktail = is_cocktail(cup.ingredients, declared_specials)

    # CupDoubler doubling (non-cocktails only)
    if cup.has_cup_doubler and not cocktail:
        pts *= 2

    # Specialist bonus: +2 per matching spirit type (non-cocktails only, after doubling)
    if not cocktail:
        specialist_spirit_types = {
            cd.get("spirit_type")
            for cd in ps.cards
            if cd.get("card_type") == "specialist" and cd.get("spirit_type")
        }
        cup_spirit_types = {i.name for i in cup.ingredients if i in _SPIRITS}
        matching = specialist_spirit_types & cup_spirit_types
        pts += len(matching) * 2

    order = _order_served(gs, ps, cup_idx, declared_specials, skip_orders)
    if order is not None:
        pts += order.bonus

    return pts


def _take_in_progress(gs: GameState) -> bool:
    return gs.ingredients_taken_this_turn > 0 or bool(gs.bag_draw_pending)


def _bladder_spirits(ps: PlayerState, spirit_type: str) -> int:
    ing = _SPIRIT_MAP.get(spirit_type.upper())
    if ing is None:
        return 0
    return sum(1 for i in ps.bladder if i == ing)


def _available_spirits(ps: PlayerState, spirit_type: str) -> int:
    """Count spirits from bladder + store cards (for karaoke/cup_doubler threshold)."""
    ing = _SPIRIT_MAP.get(spirit_type.upper())
    if ing is None:
        return 0
    count = sum(1 for i in ps.bladder if i == ing)
    return count


def _bladder_mixers(ps: PlayerState, mixer_type: str) -> int:
    ing = _MIXER_MAP.get(mixer_type.upper())
    if ing is None:
        return 0
    return sum(1 for i in ps.bladder if i == ing)


def get_valid_actions(gs: GameState, player_id: UUID) -> list[Action]:
    """Return all legal actions for the given player."""
    if gs.player_turn != player_id:
        return []

    ps = gs.player_states.get(player_id)
    if ps is None or ps.is_eliminated:
        return []

    result: list[Action] = []
    tip = _take_in_progress(gs)

    # --- Free actions (always available, even mid-take) ---
    # Actually, free actions require no take in progress per actions.py
    if not tip:
        _add_free_actions(gs, ps, player_id, result)

    # --- Turn actions ---
    if tip:
        # Mid-take: only take_ingredients is valid
        _add_take_ingredients(gs, ps, result, mid_batch=True)
    else:
        _add_take_ingredients(gs, ps, result, mid_batch=False)
        _add_sell_cup(ps, result, gs)
        _add_sell_both_cups(ps, result, gs)
        _add_drink_cup(ps, result)
        _add_go_for_a_wee(ps, result)
        used = set(gs.free_actions_used_this_turn or [])
        if CLAIM_CARD not in used:
            _add_claim_card(gs, ps, result)
        _add_refresh_card_row(
            gs,
            ps,
            result,
            swiped=SWIPE_ABILITIES in used,
            cleared=CLEAR_ORDERS in used,
        )

    used_free = set(gs.free_actions_used_this_turn or [])

    # FreeActionCards held by the player turn matching turn actions into free
    # actions (RUM→take_ingredients, VODKA→sell_cup, GIN→go_for_a_wee), once
    # per turn. Mark them so callers — UI and bots —
    # can route them through the free-action slot before the main action.
    card_free_types: set[str] = set()
    for cd in ps.cards:
        if cd.get("card_type") != "free_action":
            continue
        spirit = cd.get("spirit_type")
        action_type = _CARD_FREE_ACTION_MAP.get(spirit) if spirit else None
        if action_type and action_type not in used_free:
            card_free_types.add(action_type)
    if card_free_types:
        for a in result:
            if a.action_type in card_free_types:
                a.is_free = True

    # Once the main action has been taken, only free actions are legal — any
    # non-free turn action would 409 if attempted. Filter them out so the UI
    # reflects the real availability rather than greyless "active" buttons.
    # Mid-take is preserved by the `tip` short-circuit above (continuing a
    # batch doesn't re-consume the main action).
    if gs.main_action_taken_this_turn and not tip:
        result = [a for a in result if a.is_free]
    # The Entrepreneur's free sale is the only sale of the turn.
    if "sell_cup" in used_free:
        result = [a for a in result if a.action_type != "sell_cup"]

    return result


def _add_free_actions(
    gs: GameState, ps: PlayerState, player_id: UUID, result: list[Action]
):
    # drink_stored_spirit
    for idx, card_dict in enumerate(ps.cards):
        if card_dict.get("card_type") != "store":
            continue
        stored = card_dict.get("stored_spirits", [])
        if not stored:
            continue
        spirit_type = card_dict.get("spirit_type", "")
        for count in range(1, len(stored) + 1):
            result.append(
                Action(
                    action_type="drink_stored_spirit",
                    params={"store_card_index": idx, "count": count},
                    is_free=True,
                    description=f"Drink {count} {spirit_type} from store card {idx}",
                )
            )

    # use_stored_spirit
    for idx, card_dict in enumerate(ps.cards):
        if card_dict.get("card_type") != "store":
            continue
        stored = card_dict.get("stored_spirits", [])
        if not stored:
            continue
        spirit_type = card_dict.get("spirit_type", "")
        for cup_idx in (0, 1):
            if not ps.cups[cup_idx].is_full:
                result.append(
                    Action(
                        action_type="use_stored_spirit",
                        params={"store_card_index": idx, "cup_index": cup_idx},
                        is_free=True,
                        description=f"Move {spirit_type} from store {idx} to cup {cup_idx}",
                    )
                )


def _add_take_ingredients(
    gs: GameState, ps: PlayerState, result: list[Action], mid_batch: bool
):
    take_count = ps.take_count
    already = gs.ingredients_taken_this_turn
    remaining = take_count - already

    if remaining <= 0:
        return

    if not mid_batch:
        available = regular_in_bag(gs) + len(gs.open_display) + len(gs.specials_display)
        if available < take_count:
            return

    result.append(
        Action(
            action_type="take_ingredients",
            params={"remaining": remaining},
            description=f"Take {remaining} ingredient(s)",
        )
    )


def _add_sell_cup(ps: PlayerState, result: list[Action], gs: GameState | None = None):
    specials = ps.special_ingredients

    for cup_idx in (0, 1):
        cup = ps.cups[cup_idx]
        if cup.is_empty:
            continue

        # Try selling with no specials first
        pts = _full_sell_points(ps, cup_idx, [], gs)
        if pts is not None:
            params = {"cup_index": cup_idx, "declared_specials": [], "points": pts}
            order = _order_served(gs, ps, cup_idx, [])
            if order is not None:
                params["order"] = order.name
                params["order_bonus"] = order.bonus
            result.append(
                Action(
                    action_type="sell_cup",
                    params=params,
                    description=f"Sell cup {cup_idx} for {pts}pts (no specials)",
                )
            )

        # Try all non-empty subsets of specials
        if specials:
            seen: set[tuple[str, ...]] = set()
            for r in range(1, len(specials) + 1):
                for combo in combinations(specials, r):
                    key = tuple(sorted(combo))
                    if key in seen:
                        continue
                    seen.add(key)
                    combo_list = list(combo)
                    pts = _full_sell_points(ps, cup_idx, combo_list, gs)
                    if pts is not None:
                        result.append(
                            Action(
                                action_type="sell_cup",
                                params={
                                    "cup_index": cup_idx,
                                    "declared_specials": combo_list,
                                    "points": pts,
                                },
                                description=f"Sell cup {cup_idx} for {pts}pts with {combo_list}",
                            )
                        )


def _cup_sell_options(
    ps: PlayerState, cup_idx: int, gs: GameState | None = None
) -> list[tuple[list[str], int]]:
    """Enumerate (declared_specials, points) options for selling a single cup.

    Returns an empty list when the cup is empty or no combination is sellable.
    """
    cup = ps.cups[cup_idx]
    if cup.is_empty:
        return []
    options: list[tuple[list[str], int]] = []
    pts = _full_sell_points(ps, cup_idx, [], gs)
    if pts is not None:
        options.append(([], pts))
    specials = ps.special_ingredients
    if specials:
        seen: set[tuple[str, ...]] = set()
        for r in range(1, len(specials) + 1):
            for combo in combinations(specials, r):
                key = tuple(sorted(combo))
                if key in seen:
                    continue
                seen.add(key)
                combo_list = list(combo)
                pts = _full_sell_points(ps, cup_idx, combo_list, gs)
                if pts is not None:
                    options.append((combo_list, pts))
    return options


def _specials_fit_mat(mat: list[str], used_a: list[str], used_b: list[str]) -> bool:
    """Return True if combined specials usage is a sub-multiset of the mat."""
    remaining = list(mat)
    for s in (*used_a, *used_b):
        if s not in remaining:
            return False
        remaining.remove(s)
    return True


def _add_sell_both_cups(
    ps: PlayerState, result: list[Action], gs: GameState | None = None
):
    """Emit combined sell_cup actions covering both cups in one turn action.

    Each combined option pairs a sellable cup-0 option with a sellable cup-1
    option and verifies the player's mat has enough specials for both
    declarations. An order served by cup 0 can't also be served by cup 1.
    """
    cup0_opts = _cup_sell_options(ps, 0, gs)
    cup1_opts = _cup_sell_options(ps, 1, gs)
    if not cup0_opts or not cup1_opts:
        return  # Need both cups sellable to combine

    mat = list(ps.special_ingredients)
    for ds0, pts0 in cup0_opts:
        for ds1, pts1 in cup1_opts:
            if not _specials_fit_mat(mat, ds0, ds1):
                continue
            first = _order_served(gs, ps, 0, ds0)
            if first is not None:
                pts1 = _full_sell_points(ps, 1, ds1, gs, {first.id})
            second = _order_served(gs, ps, 1, ds1, {first.id} if first else set())
            total = pts0 + pts1
            # Which order each glass serves, for showing the bonus
            orders = [
                {"cup_index": ci, "name": o.name, "bonus": o.bonus}
                for ci, o in ((0, first), (1, second))
                if o is not None
            ]
            result.append(
                Action(
                    action_type="sell_cup",
                    params={
                        "cup_index": 0,
                        "declared_specials": list(ds0),
                        "additional_cups": [
                            {"cup_index": 1, "declared_specials": list(ds1)}
                        ],
                        "points": total,
                        "orders": orders,
                    },
                    description=(
                        f"Sell both cups for {total}pts "
                        f"(cup 0 {pts0}pts, cup 1 {pts1}pts)"
                    ),
                )
            )


def _add_drink_cup(ps: PlayerState, result: list[Action]):
    for cup_idx in (0, 1):
        if not ps.cups[cup_idx].is_empty:
            result.append(
                Action(
                    action_type="drink_cup",
                    params={"cup_index": cup_idx},
                    description=f"Drink cup {cup_idx}",
                )
            )


def _add_go_for_a_wee(ps: PlayerState, result: list[Action]):
    if ps.bladder:
        result.append(
            Action(
                action_type="go_for_a_wee",
                params={},
                description="Go for a wee",
            )
        )


def _add_claim_card(gs: GameState, ps: PlayerState, result: list[Action]):
    """Claimable karaoke and ability cards. Claiming is always a free action."""
    for row in gs.card_rows:
        if row.position == ORDERS_ROW:
            continue
        for card in row.cards:
            ct = card.card_type

            if ct == "karaoke":
                # Drunk 3+ and 2 of its spirit in the bladder
                if card_payment(ps, card) is not None:
                    result.append(
                        Action(
                            action_type="claim_card",
                            params={"card_id": card.id},
                            is_free=True,
                            description=f"Claim karaoke '{card.name}' ({card.spirit_type})",
                        )
                    )

            elif ct == "store":
                if card.spirit_type and _bladder_spirits(ps, card.spirit_type) >= 1:
                    result.append(
                        Action(
                            action_type="claim_card",
                            params={"card_id": card.id},
                            is_free=True,
                            description=f"Claim store '{card.name}' ({card.spirit_type})",
                        )
                    )

            elif ct == "refresher":
                if card.mixer_type and _bladder_mixers(ps, card.mixer_type) >= 2:
                    result.append(
                        Action(
                            action_type="claim_card",
                            params={"card_id": card.id},
                            is_free=True,
                            description=f"Claim refresher '{card.name}' ({card.mixer_type})",
                        )
                    )

            elif ct == "specialist":
                # Pay with 2 of its spirit, or 1 of its special (not store)
                special = SPECIALIST_SPECIAL.get(card.spirit_type or "")
                for pay in (special.name if special else None, card.spirit_type):
                    if pay and card_payment(ps, card, pay) is not None:
                        result.append(
                            Action(
                                action_type="claim_card",
                                params={"card_id": card.id, "spirit_type": pay},
                                is_free=True,
                                description=f"Claim specialist '{card.name}' paying {pay}",
                            )
                        )

            elif ct == "free_action":
                if card.spirit_type and _bladder_spirits(ps, card.spirit_type) >= 3:
                    result.append(
                        Action(
                            action_type="claim_card",
                            params={"card_id": card.id},
                            is_free=True,
                            description=f"Claim free action '{card.name}' ({card.spirit_type})",
                        )
                    )

            elif ct == "cup_doubler":
                # Needs 3 of same spirit in bladder (not store)
                for spirit_name, spirit_ing in _SPIRIT_MAP.items():
                    bladder_count = sum(1 for i in ps.bladder if i == spirit_ing)
                    if bladder_count >= 3:
                        for cup_idx in (0, 1):
                            result.append(
                                Action(
                                    action_type="claim_card",
                                    params={
                                        "card_id": card.id,
                                        "cup_index": cup_idx,
                                        "spirit_type": spirit_name,
                                    },
                                    is_free=True,
                                    description=f"Claim cup doubler '{card.name}' with {spirit_name} on cup {cup_idx}",
                                )
                            )


def _add_refresh_card_row(
    gs: GameState,
    ps: PlayerState,
    result: list[Action],
    swiped: bool = False,
    cleared: bool = False,
):
    """Clearing the orders row (drunk 3+) and swiping the ability row (drunk
    2+): each a free action once a turn. The karaoke row is never cleared."""
    for row in gs.card_rows:
        if row.position == KARAOKE_ROW:
            continue
        if row.position == ABILITY_ROW:
            if swiped or ps.drunk_level < MIN_DRUNK_TO_SWIPE:
                continue
            if row.cards or gs._deck_dicts:
                result.append(
                    Action(
                        action_type="refresh_card_row",
                        params={"row_position": row.position},
                        is_free=True,
                        description="Swipe the ability cards",
                    )
                )
        elif not cleared and ps.drunk_level >= MIN_DRUNK_TO_REFRESH and row.cards:
            result.append(
                Action(
                    action_type="refresh_card_row",
                    params={"row_position": row.position},
                    is_free=True,
                    description="Clear the orders",
                )
            )
