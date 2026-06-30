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

from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import MAX_CUP_INGREDIENTS, PlayerState
from app.cocktails import _MIXERS, _RECIPES, _SPIRITS, VALID_PAIRINGS


@dataclass
class CocktailPlan:
    """A buildable cocktail target for one cup, with its completion probability."""

    cup_index: int
    needed: Counter  # Ingredient -> how many more to put in the target cup
    points: int
    name: str
    probability: float  # rough chance of obtaining the missing ingredients

    @property
    def needed_count(self) -> int:
        return sum(self.needed.values())


# Cocktail pursuit is value-driven, not rule-driven. The expected value of an
# opportunity is P(complete) * (cocktail points - what the cup would sell for as a
# normal drink). The search then trades that EV off against everything else via
# the cocktail_progress weight — so "only when behind", "don't strand a cup", and
# "play safe" all emerge from the evaluation (points are worth more head-to-head
# when behind; a stranded cup loses its _best_cup_sale value; a dangerous take is
# crushed by the safety penalty) rather than from hand-written rules. These are
# the tunable knobs of that model.
_HEADROOM = 2.0  # want ~2x the needed units available before calling it "likely"
_DISPLAY_WEIGHT = 2.0  # display units count for more — they're grabbable now
_NORMAL_SALE_BASELINE = 3.0  # a built cup would otherwise sell for ~3 (a double)
_BUILD_EV_THRESHOLD = 2.5  # the disposition only commits to a build above this EV
# Disposition drink-safety budget (mechanical, not strategy): while assembling a
# cocktail, never drink off-plan spirits past this drunk level — spoil instead.
_COCKTAIL_DRUNK_CAP = 2


def _completion_probability(needed: Counter, obtainable: Counter) -> float:
    """Rough chance of obtaining the missing ingredients from the display + bag.

    Per ingredient: ``supply / (need * HEADROOM)`` clamped to [0, 1] — you want a
    comfortable surplus to actually draw enough against bag randomness and rivals
    taking the same items. Product across ingredients. Display units are weighted
    up (you can grab them this turn). Not a true combinatorial probability — a
    cheap, monotonic proxy the weights are tuned against.
    """
    p = 1.0
    for ing, n in needed.items():
        supply = obtainable.get(ing, 0.0)
        if supply < n:
            return 0.0  # not even enough in existence to finish — impossible
        p *= min(1.0, supply / (n * _HEADROOM))
    return p


def best_cocktail(gs: GameState, ps: PlayerState) -> tuple[CocktailPlan | None, float]:
    """The highest expected-value cocktail this player could build, and its EV.

    Pure value/probability: for every recipe whose specials are already banked and
    every cup that's a sub-multiset of it, EV = P(complete) * (points - a normal
    sale). No situational rules — the caller (search via the evaluator, or the
    disposition) decides what to do with the EV. Returns (None, 0.0) if nothing.
    """
    held = Counter(ps.special_ingredients)
    obtainable: Counter = Counter()
    for ing in gs.open_display:
        obtainable[ing] += _DISPLAY_WEIGHT
    for ing in gs.bag_contents:
        obtainable[ing] += 1.0

    best_plan: CocktailPlan | None = None
    best_ev = 0.0

    for r_spirits, r_mixers, r_specials, pts, name in _RECIPES:
        if any(held.get(st.value, 0) < n for st, n in r_specials.items()):
            continue
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
                continue  # already complete — _best_cup_sale handles the sale
            if needed_count > MAX_CUP_INGREDIENTS - cup_total:
                continue  # won't fit

            needed: Counter = Counter()
            for k, n in r_spirits.items():
                if (d := n - c_spirits.get(k, 0)) > 0:
                    needed[k] = d
            for k, n in r_mixers.items():
                if (d := n - c_mixers.get(k, 0)) > 0:
                    needed[k] = d

            p = _completion_probability(needed, obtainable)
            ev = p * max(0.0, pts - _NORMAL_SALE_BASELINE)
            if ev > best_ev:
                best_ev = ev
                best_plan = CocktailPlan(ci, needed, pts, name, p)

    return best_plan, best_ev


def plan_cocktail(gs: GameState, ps: PlayerState) -> CocktailPlan | None:
    """The build target for the disposition: the best-EV cocktail, but only when
    its expected value clears the build bar (otherwise play normal). No
    ``if behind`` / ``overlap-safe`` rules — the EV and the search's evaluation do
    the judging.
    """
    plan, ev = best_cocktail(gs, ps)
    return plan if ev >= _BUILD_EV_THRESHOLD else None


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
