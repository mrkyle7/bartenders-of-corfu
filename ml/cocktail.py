"""Recipe-directed cocktail building for the lookahead bot.

The evaluator can *value* a cocktail-in-progress, but on its own that regressed:
ingredient disposition was delegated to Mastermind, whose ``CupTracker`` caps a
cup at 2 spirits — so it physically cannot assemble a 3-spirit Martini / Old
Fashioned, let alone a 4-spirit Long Island. The bot just held cups it could
never finish.

This module is the missing half, following the human strategy: **bank specials
first, let the specials you hold pick the target recipe, then build one cup
toward it** — taking the needed spirits/mixers straight from the display rather
than hoping the bag delivers them. It only ever stacks a 3rd/4th spirit into a
cup when the recipe's special is already on the mat, so the over-cap cup is
immediately sellable *as the cocktail* (a non-cocktail cup caps at 2 spirits; a
cocktail is exempt — and the 2-spirit cap is a sale rule, not a take rule, so the
take action accepts the stack). A half-built cup (e.g. 2 of 3 gins) is still
sellable as a 3-pt double, so building toward a cocktail is never a dead end.

LookaheadStrategy wires this into ``choose_take_assignments`` /
``choose_pending_assignments``; with no plan it falls back to Mastermind.
"""

from collections import Counter
from dataclasses import dataclass

from app.actions import SCORE_TO_WIN
from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import MAX_CUP_INGREDIENTS, PlayerState
from app.cocktails import _MIXERS, _RECIPES, _SPIRITS, VALID_PAIRINGS


@dataclass
class CocktailPlan:
    """A concrete, buildable cocktail target for one cup."""

    cup_index: int
    needed: Counter  # Ingredient -> how many more to put in the target cup
    points: int
    name: str
    overlap_safe: bool

    @property
    def needed_count(self) -> int:
        return sum(self.needed.values())


# Don't chase a cocktail when survival is at stake: building one means taking
# extra ingredients (off-plan ones get drunk, raising drunk/bladder), so a
# multi-turn build from a dangerous position is how the cocktail bot used to
# self-eliminate. Above these thresholds, fall back to Mastermind's safe play.
_COCKTAIL_DRUNK_CAP = 2
_COCKTAIL_MIN_BLADDER_ROOM = 2
# An opponent at/above this score is "near a win" (40 to win) → time to gamble on
# the big cocktail swing even from a cup-stranding recipe.
_OPPONENT_THREAT_SCORE = 0.65 * SCORE_TO_WIN


def _overlap_safe(r_spirits: Counter, r_mixers: Counter) -> bool:
    """Does this recipe build through *sellable* intermediate cups?

    True only for single-spirit recipes whose mixers (if any) are a valid normal
    pairing — Martini, Manhattan, Old Fashioned, Margarita, Cosmopolitan. For
    those, every partial cup is still a 1/3-pt normal drink, so building toward
    the cocktail strands nothing. Multi-spirit (Long Island) or invalid-mixer
    (Mojito's rum+soda, Tom Collins' gin+soda) recipes spoil the cup until the
    recipe is complete, so they're only worth committing to when behind.
    """
    if len(r_spirits) != 1:
        return False
    spirit = next(iter(r_spirits))
    valid = VALID_PAIRINGS.get(spirit, set())
    return all(m in valid for m in r_mixers)


def _under_pressure(gs: GameState, ps: PlayerState) -> bool:
    """Is an opponent ahead of us, or close enough to winning to force a gamble?

    Cocktails are a high-variance catch-up play, so the cup-stranding recipes are
    only worth it when we're not comfortably in front.
    """
    opp_best = max(
        (
            o.points
            for pid, o in gs.player_states.items()
            if pid != ps.player_id and not o.is_eliminated
        ),
        default=0,
    )
    return opp_best > ps.points or opp_best >= _OPPONENT_THREAT_SCORE


def plan_cocktail(gs: GameState, ps: PlayerState) -> CocktailPlan | None:
    """Pick a cocktail worth building right now, or None — the situational call.

    Cocktails are *not* the primary plan; this returns a target only when it is
    genuinely worth diverting from normal selling:

    1. **Survival first** — None when drunk/bladder is in the danger zone.
    2. **Specials in hand** — only recipes whose specials are already on the mat
       (the human banks specials, then commits). No speculative builds.
    3. **A real chance to build** — the missing spirits/mixers must actually be
       obtainable from the display + bag; otherwise hang on and wait.
    4. **Stranding risk vs. opponents** — overlap-safe recipes (sellable partials)
       can be built anytime; cup-stranding ones only when behind / under threat.

    Among the survivors, prefer overlap-safe, then more points, then fewer
    ingredients still needed, then the cup with the most progress.
    """
    if ps.drunk_level > _COCKTAIL_DRUNK_CAP:
        return None
    if ps.bladder_capacity - len(ps.bladder) < _COCKTAIL_MIN_BLADDER_ROOM:
        return None

    held = Counter(ps.special_ingredients)
    obtainable = Counter(gs.open_display) + Counter(gs.bag_contents)
    behind = _under_pressure(gs, ps)

    best: CocktailPlan | None = None
    best_key: tuple | None = None

    for r_spirits, r_mixers, r_specials, pts, name in _RECIPES:
        if any(held.get(st.value, 0) < n for st, n in r_specials.items()):
            continue
        safe = _overlap_safe(r_spirits, r_mixers)
        if not safe and not behind:
            continue  # don't strand a cup on a risky cocktail while in front
        recipe_total = sum(r_spirits.values()) + sum(r_mixers.values())

        for ci in (0, 1):
            cup = ps.cups[ci]
            if cup.is_full:
                continue
            c_spirits = Counter(i for i in cup.ingredients if i in _SPIRITS)
            c_mixers = Counter(i for i in cup.ingredients if i in _MIXERS)
            if any(c_spirits[k] > r_spirits.get(k, 0) for k in c_spirits):
                continue  # wrong/excess spirit already in cup
            if any(c_mixers[k] > r_mixers.get(k, 0) for k in c_mixers):
                continue  # wrong/excess mixer already in cup
            cup_total = len(cup.ingredients)
            needed_count = recipe_total - cup_total
            if needed_count <= 0:
                continue  # already a complete cocktail — just sell it
            if needed_count > MAX_CUP_INGREDIENTS - cup_total:
                continue  # won't fit

            needed: Counter = Counter()
            for k, n in r_spirits.items():
                if (d := n - c_spirits.get(k, 0)) > 0:
                    needed[k] = d
            for k, n in r_mixers.items():
                if (d := n - c_mixers.get(k, 0)) > 0:
                    needed[k] = d

            # A real chance to build: every missing ingredient must be obtainable.
            if any(obtainable.get(ing, 0) < n for ing, n in needed.items()):
                continue

            key = (safe, pts, -needed_count, cup_total)
            if best_key is None or key > best_key:
                best_key = key
                best = CocktailPlan(ci, needed, pts, name, safe)

    return best


def cocktail_display_assignments(
    open_display: list[Ingredient], count: int, plan: CocktailPlan
) -> list[dict]:
    """Display picks toward ``plan``: SPECIAL tokens first, then needed items.

    Returns up to ``count`` display assignments; whatever's left of the take is
    filled from the bag (and routed by cocktail_pending_assignments).
    """
    assignments: list[dict] = []
    available = list(open_display)
    need = Counter(plan.needed)
    taken = 0

    # SPECIAL tokens first — they roll onto the mat at no drunk/bladder cost and
    # are what unlocks (and can upgrade) cocktail recipes.
    for ing in list(available):
        if taken >= count:
            return assignments
        if ing == Ingredient.SPECIAL:
            available.remove(ing)
            assignments.append(
                {"ingredient": ing.name, "source": "display", "disposition": "drink"}
            )
            taken += 1

    # Recipe ingredients straight from the display into the target cup.
    for ing in list(available):
        if taken >= count:
            break
        if need.get(ing, 0) > 0:
            available.remove(ing)
            assignments.append(
                {
                    "ingredient": ing.name,
                    "source": "display",
                    "disposition": "cup",
                    "cup_index": plan.cup_index,
                }
            )
            need[ing] -= 1
            taken += 1

    return assignments


def cocktail_pending_assignments(
    ps: PlayerState, drawn: list[Ingredient], plan: CocktailPlan
) -> list[dict]:
    """Assign bag-drawn ingredients **in draw order** (the handler pops FIFO).

    Recipe ingredients go to the target cup; off-plan spirits/mixers go to the
    *other* cup when they keep it sellable, else drink (specials auto-roll to the
    mat whatever we say). ``plan.needed`` is taken as-is; callers re-plan from the
    live state before each call so it reflects ingredients already cupped.
    """
    need = Counter(plan.needed)
    other = 1 - plan.cup_index
    # Lightweight sellability tracker for the off-plan cup.
    other_cup = ps.cups[other]
    o_spirit: Ingredient | None = next(
        (i for i in other_cup.ingredients if i in _SPIRITS), None
    )
    o_spirits = sum(1 for i in other_cup.ingredients if i in _SPIRITS)
    o_mixers = {i for i in other_cup.ingredients if i in _MIXERS}
    o_fill = len(other_cup.ingredients)
    plan_fill = len(ps.cups[plan.cup_index].ingredients) + plan.needed_count

    # Spirit-drink budget: never let a build-take drink past a safe drunk level —
    # the over-cap drinks that come with assembling a cocktail are exactly how the
    # bot self-eliminated. When the budget is spent, dump an off-plan spirit into
    # a cup (spoiling it) rather than drinking it.
    drunk_budget = max(0, _COCKTAIL_DRUNK_CAP + 1 - ps.drunk_level)
    spirits_drunk = 0

    assignments: list[dict] = []
    for ing in drawn:
        if need.get(ing, 0) > 0:
            assignments.append(
                {"source": "pending", "disposition": "cup", "cup_index": plan.cup_index}
            )
            need[ing] -= 1
            continue
        if ing in _SPIRITS and o_fill < MAX_CUP_INGREDIENTS and o_spirits < 2:
            if o_spirit is None or o_spirit == ing:
                assignments.append(
                    {"source": "pending", "disposition": "cup", "cup_index": other}
                )
                o_spirit, o_spirits, o_fill = ing, o_spirits + 1, o_fill + 1
                continue
        if ing in _MIXERS and o_spirit is not None and o_fill < MAX_CUP_INGREDIENTS:
            valid = VALID_PAIRINGS.get(o_spirit, set())
            if ing in valid and (not o_mixers or ing in o_mixers):
                assignments.append(
                    {"source": "pending", "disposition": "cup", "cup_index": other}
                )
                o_mixers.add(ing)
                o_fill += 1
                continue
        # Off-plan spirit and drinking it would breach the safe cap → dump it into
        # a cup (spoiling that cup) instead of getting dangerously drunk.
        if ing in _SPIRITS and spirits_drunk >= drunk_budget:
            if o_fill < MAX_CUP_INGREDIENTS:
                assignments.append(
                    {"source": "pending", "disposition": "cup", "cup_index": other}
                )
                o_fill += 1
                continue
            if plan_fill < MAX_CUP_INGREDIENTS:  # last resort: spoil the plan cup
                assignments.append(
                    {
                        "source": "pending",
                        "disposition": "cup",
                        "cup_index": plan.cup_index,
                    }
                )
                plan_fill += 1
                continue
        if ing in _SPIRITS:
            spirits_drunk += 1
        # Mixers sober; specials auto-roll to the mat regardless of disposition.
        assignments.append({"source": "pending", "disposition": "drink"})

    return assignments
