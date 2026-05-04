"""Enumerate all legal actions for the current player given a GameState.

Mirrors the validation logic in app/actions.py without calling it.
"""

from dataclasses import dataclass, field
from itertools import combinations
from uuid import UUID

from app.game_modes import GameMode
from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import PlayerState
from app.actions import MIN_DRUNK_TO_REFRESH, _SPIRITS
from app.cocktails import drink_points, is_cocktail

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


@dataclass
class Action:
    """Represents a legal action a player can take."""

    action_type: str
    params: dict = field(default_factory=dict)
    is_free: bool = False
    description: str = ""


def _full_sell_points(
    ps: PlayerState, cup_idx: int, declared_specials: list[str]
) -> int | None:
    """Calculate full sell points including cup_doubler and specialist bonuses."""
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
        _add_sell_cup(ps, result)
        if gs.has_mode(GameMode.SELL_BOTH_CUPS.value):
            _add_sell_both_cups(ps, result)
        _add_drink_cup(ps, result)
        _add_go_for_a_wee(ps, result)
        _add_claim_card(gs, ps, result)
        _add_refresh_card_row(gs, ps, result)
        _add_reroll_specials(gs, ps, result)

    # Mark claim_card / reroll_specials as free when the relevant mode is on
    # and the matching free action hasn't been used yet this turn. Doing this
    # after collection keeps each _add_* helper focused on legality.
    used_free = set(gs.free_actions_used_this_turn or [])
    if (
        gs.has_mode(GameMode.CLAIM_CARD_FREE_ACTION.value)
        and "claim_card" not in used_free
    ):
        for a in result:
            if a.action_type == "claim_card":
                a.is_free = True
    if (
        gs.has_mode(GameMode.REROLL_SPECIALS_FREE_ACTION.value)
        and "reroll_specials" not in used_free
    ):
        for a in result:
            if a.action_type == "reroll_specials":
                a.is_free = True

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
        available = len(gs.bag_contents) + len(gs.open_display)
        if available < take_count:
            return

    result.append(
        Action(
            action_type="take_ingredients",
            params={"remaining": remaining},
            description=f"Take {remaining} ingredient(s)",
        )
    )


def _add_sell_cup(ps: PlayerState, result: list[Action]):
    specials = ps.special_ingredients

    for cup_idx in (0, 1):
        cup = ps.cups[cup_idx]
        if cup.is_empty:
            continue

        # Try selling with no specials first
        pts = _full_sell_points(ps, cup_idx, [])
        if pts is not None:
            result.append(
                Action(
                    action_type="sell_cup",
                    params={
                        "cup_index": cup_idx,
                        "declared_specials": [],
                        "points": pts,
                    },
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
                    pts = _full_sell_points(ps, cup_idx, combo_list)
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


def _cup_sell_options(ps: PlayerState, cup_idx: int) -> list[tuple[list[str], int]]:
    """Enumerate (declared_specials, points) options for selling a single cup.

    Returns an empty list when the cup is empty or no combination is sellable.
    """
    cup = ps.cups[cup_idx]
    if cup.is_empty:
        return []
    options: list[tuple[list[str], int]] = []
    pts = _full_sell_points(ps, cup_idx, [])
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
                pts = _full_sell_points(ps, cup_idx, combo_list)
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


def _add_sell_both_cups(ps: PlayerState, result: list[Action]):
    """Emit combined sell_cup actions covering both cups in one turn action.

    Only invoked when the sell_both_cups game mode is active. Each combined
    option pairs a sellable cup-0 option with a sellable cup-1 option and
    verifies the player's mat has enough specials for both declarations.
    """
    cup0_opts = _cup_sell_options(ps, 0)
    cup1_opts = _cup_sell_options(ps, 1)
    if not cup0_opts or not cup1_opts:
        return  # Need both cups sellable to combine

    mat = list(ps.special_ingredients)
    for ds0, pts0 in cup0_opts:
        for ds1, pts1 in cup1_opts:
            if not _specials_fit_mat(mat, ds0, ds1):
                continue
            total = pts0 + pts1
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
    for row in gs.card_rows:
        for card in row.cards:
            ct = card.card_type

            if ct == "karaoke":
                if card.spirit_type and _available_spirits(ps, card.spirit_type) >= 3:
                    result.append(
                        Action(
                            action_type="claim_card",
                            params={"card_id": card.id},
                            description=f"Claim karaoke '{card.name}' ({card.spirit_type})",
                        )
                    )

            elif ct == "store":
                if card.spirit_type and _bladder_spirits(ps, card.spirit_type) >= 1:
                    result.append(
                        Action(
                            action_type="claim_card",
                            params={"card_id": card.id},
                            description=f"Claim store '{card.name}' ({card.spirit_type})",
                        )
                    )

            elif ct == "refresher":
                if card.mixer_type and _bladder_mixers(ps, card.mixer_type) >= 2:
                    result.append(
                        Action(
                            action_type="claim_card",
                            params={"card_id": card.id},
                            description=f"Claim refresher '{card.name}' ({card.mixer_type})",
                        )
                    )

            elif ct == "specialist":
                # Needs 2 of matching spirit in bladder (not store)
                if card.spirit_type and _bladder_spirits(ps, card.spirit_type) >= 2:
                    result.append(
                        Action(
                            action_type="claim_card",
                            params={"card_id": card.id},
                            description=f"Claim specialist '{card.name}' ({card.spirit_type})",
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
                                    description=f"Claim cup doubler '{card.name}' with {spirit_name} on cup {cup_idx}",
                                )
                            )


def _add_refresh_card_row(gs: GameState, ps: PlayerState, result: list[Action]):
    if ps.drunk_level < MIN_DRUNK_TO_REFRESH:
        return

    for row in gs.card_rows:
        if row.position == 1:
            continue  # Row 1 never refreshable
        if row.cards:  # Only if row has cards to refresh
            result.append(
                Action(
                    action_type="refresh_card_row",
                    params={"row_position": row.position},
                    description=f"Refresh card row {row.position}",
                )
            )


def _add_reroll_specials(gs: GameState, ps: PlayerState, result: list[Action]):
    """Surface reroll_specials as a single "reroll all" action.

    This action only registers as a turn action when the player holds at least
    one special. Bots only need a single representative option — picking which
    specials to re-roll is left up to the strategy. Re-rolling all of them is
    the most common useful case, especially under the mode that makes this
    free.
    """
    if not ps.special_ingredients:
        return
    chosen = list(ps.special_ingredients)
    result.append(
        Action(
            action_type="reroll_specials",
            params={"chosen_specials": chosen},
            description=f"Re-roll all {len(chosen)} special(s)",
        )
    )
