"""Strategy ABC and implementations for automated play-testing.

Survival model
--------------
The drunk modifier batches ALL ingredients drunk in a single take_ingredients
call.  The formula:

    delta = spirits_drunk - hot_mixers_drunk
    if spirits_drunk == 0:
        delta -= plain_mixers_drunk

So drinking 1 spirit + 2 plain mixers → delta = +1  (mixers WASTED).
Drinking 0 spirits + 3 plain mixers → delta = -3   (great!).

Lesson: spirits go in cups (never drink them); drink only mixers.
Hot mixers (refresher-covered) always subtract even when spirits are present.

Cup rules
---------
Non-cocktail drinks (the main scoring path) require:
  - Max 2 spirits of the SAME type
  - At least 1 valid mixer for that spirit type
  - All mixers must be valid for that spirit type
  - Only ONE mixer type (e.g. all COLA, not COLA + SODA)
  - No mixed spirit types

So CupTracker must be strict: never mix spirit types, never put invalid
mixers, never mix mixer types, max 2 spirits per cup.
"""

import random
from abc import ABC, abstractmethod
from collections import Counter
from uuid import UUID

from app.GameState import GameState, drawable_in_bag
from app.Ingredient import (
    BOOZY_SPECIALS,
    SPECIAL_INGREDIENTS,
    SPECIALIST_SPECIAL,
    Ingredient,
    SpecialType,
    is_special,
)
from app.PlayerState import MAX_CUP_INGREDIENTS, MAX_CUP_SPECIALS, PlayerState
from app.actions import _MIXERS, _SPIRITS
from app.card import ORDERS_ROW
from app.cocktails import VALID_PAIRINGS, _RECIPES, drink_points, matches_order

from playtesting.valid_actions import Action

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

BASE_TAKE_COUNT = 3


# ---------------------------------------------------------------------------
#  Cocktail recipes as ingredient counts (specials are ingredients now)
# ---------------------------------------------------------------------------


class Recipe:
    def __init__(self, name, pts, spirits, mixers, specials):
        self.name: str = name
        self.pts: int = pts
        self.spirits: Counter = spirits
        self.mixers: Counter = mixers
        self.specials: Counter = specials  # Counter[Ingredient]

    @property
    def size(self) -> int:
        return (
            sum(self.spirits.values())
            + sum(self.mixers.values())
            + sum(self.specials.values())
        )

    def allows(self, spirits: Counter, mixers: Counter, specials: Counter) -> bool:
        """Whether a glass holding these could still become this cocktail."""
        return (
            all(self.spirits.get(i, 0) >= n for i, n in spirits.items())
            and all(self.mixers.get(i, 0) >= n for i, n in mixers.items())
            and all(self.specials.get(i, 0) >= n for i, n in specials.items())
        )

    def missing(self, spirits: Counter, mixers: Counter, specials: Counter) -> Counter:
        return (
            (self.spirits - spirits)
            + (self.mixers - mixers)
            + (self.specials - specials)
        )


RECIPES: list[Recipe] = [
    Recipe(
        name,
        pts,
        Counter(r_spirits),
        Counter(r_mixers),
        Counter({Ingredient[st.name]: n for st, n in r_specials.items()}),
    )
    for r_spirits, r_mixers, r_specials, pts, name in _RECIPES
]
RECIPE_BY_NAME: dict[str, Recipe] = {r.name: r for r in RECIPES}


def _glass_counts(ingredients: list[Ingredient]) -> tuple[Counter, Counter, Counter]:
    return (
        Counter(i for i in ingredients if i in _SPIRITS),
        Counter(i for i in ingredients if i in _MIXERS),
        Counter(i for i in ingredients if is_special(i)),
    )


def recipes_for_glass(ingredients: list[Ingredient]) -> list[Recipe]:
    """Cocktails this glass could still become."""
    sp, mx, sc = _glass_counts(ingredients)
    return [r for r in RECIPES if r.allows(sp, mx, sc)]


# ---------------------------------------------------------------------------
#  Shared helpers
# ---------------------------------------------------------------------------


class CupTracker:
    """Tracks cup contents during assignment building within a single batch.

    Enforces sellability rules:
    - Max 2 spirits per cup, all same type
    - Only valid mixer pairings for the cup's spirit type
    - Only one mixer type per cup (non-cocktail rule)
    """

    def __init__(self, ps: PlayerState):
        self.fill = [ps.cups[0].base_count, ps.cups[1].base_count]
        # Every cup as ingredient counts, for cocktail checks
        self.spirits: list[Counter] = [Counter(), Counter()]
        self.mixers: list[Counter] = [Counter(), Counter()]
        self.specials: list[Counter] = [Counter(), Counter()]
        # A cocktail a bot has decided this cup is for (see aim_at)
        self.aim: list[Recipe | None] = [None, None]
        # A cup kept for a plain drink (e.g. an order): no specials in it
        self.plain: list[bool] = [False, False]
        self.spirit_counts: list[int] = [0, 0]
        self.spirit_type: list[Ingredient | None] = [None, None]
        self.mixer_count: list[int] = [0, 0]
        self.mixer_types: list[set[Ingredient]] = [set(), set()]
        # Cup is "spoiled" when adding more ingredients can't make it sellable
        # (mixed spirit types, mixed mixer types, or mixer that doesn't pair
        # with the cup's spirit). Used so later passes don't waste picks on a
        # cup that's already a write-off.
        self.is_spoiled: list[bool] = [False, False]

        for ci in (0, 1):
            sp, mx, sc = _glass_counts(ps.cups[ci].ingredients)
            self.spirits[ci], self.mixers[ci], self.specials[ci] = sp, mx, sc
            for ing in ps.cups[ci].ingredients:
                if ing in _SPIRITS:
                    self.spirit_counts[ci] += 1
                    if self.spirit_type[ci] is None:
                        self.spirit_type[ci] = ing
                    elif self.spirit_type[ci] != ing:
                        # Mixed spirits — cup is already ruined
                        self.spirit_type[ci] = ing  # just track latest
                        self.is_spoiled[ci] = True
                elif ing in _MIXERS:
                    self.mixer_count[ci] += 1
                    self.mixer_types[ci].add(ing)
            # Detect cups already spoiled by mixed mixer types or invalid pairing
            if len(self.mixer_types[ci]) > 1:
                self.is_spoiled[ci] = True
            if self.spirit_type[ci] is not None and self.mixer_count[ci] > 0:
                valid = VALID_PAIRINGS.get(self.spirit_type[ci], set())
                if any(m not in valid for m in self.mixer_types[ci]):
                    self.is_spoiled[ci] = True
            # A glass with specials can only be sold as a cocktail
            if self.specials[ci]:
                self.is_spoiled[ci] = not self.recipes(ci)

    # --- Cocktail mode: a cup with specials, or one aimed at a recipe ---

    def is_cocktail_cup(self, cup_idx: int) -> bool:
        return bool(self.specials[cup_idx]) or self.aim[cup_idx] is not None

    def recipes(self, cup_idx: int, add: Ingredient | None = None) -> list[Recipe]:
        """Cocktails this cup could still become (after adding ``add``)."""
        sp = Counter(self.spirits[cup_idx])
        mx = Counter(self.mixers[cup_idx])
        sc = Counter(self.specials[cup_idx])
        if add is not None:
            (sp if add in _SPIRITS else mx if add in _MIXERS else sc)[add] += 1
        pool = [self.aim[cup_idx]] if self.aim[cup_idx] is not None else RECIPES
        return [r for r in pool if r.allows(sp, mx, sc)]

    def aim_at(self, cup_idx: int, recipe: Recipe) -> bool:
        """Commit a cup to a cocktail, if what's in it allows that."""
        if not recipe.allows(
            self.spirits[cup_idx], self.mixers[cup_idx], self.specials[cup_idx]
        ):
            return False
        self.aim[cup_idx] = recipe
        self.is_spoiled[cup_idx] = False
        return True

    def still_needs(self, cup_idx: int) -> Counter:
        """Ingredients the cup's closest cocktail still needs (empty if none)."""
        options = self.recipes(cup_idx)
        if not options:
            return Counter()
        sp, mx, sc = self.spirits[cup_idx], self.mixers[cup_idx], self.specials[cup_idx]
        best = min(options, key=lambda r: (sum(r.missing(sp, mx, sc).values()), -r.pts))
        return best.missing(sp, mx, sc)

    def can_add_special(self, cup_idx: int, special: Ingredient) -> bool:
        if self.plain[cup_idx]:
            return False
        if sum(self.specials[cup_idx].values()) >= MAX_CUP_SPECIALS:
            return False
        return bool(self.recipes(cup_idx, add=special))

    def best_cup_for_special(
        self,
        special: Ingredient,
        allow_empty: bool = False,
        available: Counter | None = None,
    ) -> int | None:
        """The cup a special would help most toward a cocktail.

        An empty cup counts only with ``allow_empty``. With ``available``
        (specials that can be had now), a cup counts only if the cocktail's
        other specials are all among them — so the special doesn't leave the
        glass waiting on luck.
        """
        best, best_key = None, None
        for ci in (0, 1):
            empty = self.fill[ci] == 0 and not self.specials[ci]
            if empty and not allow_empty:
                continue
            if not self.can_add_special(ci, special):
                continue
            options = self.recipes(ci, add=special)
            sc = Counter(self.specials[ci])
            sc[special] += 1
            if available is not None:
                options = [
                    r
                    for r in options
                    if all(
                        available.get(i, 0) >= n for i, n in (r.specials - sc).items()
                    )
                ]
                if not options:
                    continue
            progress = max(
                r.size - sum(r.missing(self.spirits[ci], self.mixers[ci], sc).values())
                for r in options
            )
            key = (progress, max(r.pts for r in options))
            if best_key is None or key > best_key:
                best, best_key = ci, key
        return best

    def add_special(self, cup_idx: int, special: Ingredient):
        self.specials[cup_idx][special] += 1
        self.is_spoiled[cup_idx] = not self.recipes(cup_idx)

    def can_add(self, cup_idx: int) -> bool:
        if self.is_spoiled[cup_idx]:
            return False  # don't waste picks on a write-off cup
        return self.fill[cup_idx] < MAX_CUP_INGREDIENTS

    def _can_add_spirit(self, cup_idx: int, spirit: Ingredient) -> bool:
        """Can this spirit be added without ruining the cup's sellability?"""
        if not self.can_add(cup_idx):
            return False
        if self.is_cocktail_cup(cup_idx):
            return bool(self.recipes(cup_idx, add=spirit))
        if self.spirit_counts[cup_idx] >= 2:
            return False  # max 2 spirits
        if (
            self.spirit_type[cup_idx] is not None
            and self.spirit_type[cup_idx] != spirit
        ):
            return False  # can't mix spirit types
        return True

    def _can_add_mixer(self, cup_idx: int, mixer: Ingredient) -> bool:
        """Can this mixer be added without ruining the cup's sellability?"""
        if not self.can_add(cup_idx):
            return False
        if self.is_cocktail_cup(cup_idx):
            return bool(self.recipes(cup_idx, add=mixer))
        # Non-cocktail drinks may only contain a single mixer type
        existing = self.mixer_types[cup_idx]
        if existing and mixer not in existing:
            return False
        st = self.spirit_type[cup_idx]
        if st is None:
            return True  # empty cup, mixer can go in (spirit comes later)
        valid = VALID_PAIRINGS.get(st, set())
        return mixer in valid

    def add_spirit(self, cup_idx: int, spirit: Ingredient):
        self.fill[cup_idx] += 1
        self.spirit_counts[cup_idx] += 1
        self.spirit_type[cup_idx] = spirit
        self.spirits[cup_idx][spirit] += 1

    def add_mixer(self, cup_idx: int, mixer: Ingredient):
        self.fill[cup_idx] += 1
        self.mixer_count[cup_idx] += 1
        self.mixer_types[cup_idx].add(mixer)
        self.mixers[cup_idx][mixer] += 1

    def can_spoil_with(self, cup_idx: int, spirit: Ingredient) -> bool:
        """Can this spirit be dumped into the cup, accepting it becomes
        unsellable? Only legal if the cup already has a different spirit
        (mixed spirit types is what spoils it) and there's room within the
        2-spirit game rule.
        """
        if self.is_spoiled[cup_idx]:
            return False  # already a write-off; don't keep dumping into it
        if self.fill[cup_idx] >= MAX_CUP_INGREDIENTS:
            return False
        if self.spirit_counts[cup_idx] >= 2:
            return False  # game rule: max 2 spirits per cup
        if self.spirit_type[cup_idx] is None:
            return False  # empty cup → not a spoil, would be a clean add
        if self.spirit_type[cup_idx] == spirit:
            return False  # matches existing spirit → clean add, not a spoil
        if self.is_cocktail_cup(cup_idx) and self.recipes(cup_idx):
            return False  # still on its way to a cocktail

        # Don't spoil a cup that's still on a viable sellable path: it has a
        # spirit + a paired mixer (or tequila slammer in progress).
        spirit_in = self.spirit_type[cup_idx]
        if self.mixer_count[cup_idx] > 0:
            valid = VALID_PAIRINGS.get(spirit_in, set())
            if all(m in valid for m in self.mixer_types[cup_idx]):
                return False  # cup is on a valid sellable path
        if (
            spirit_in == Ingredient.TEQUILA
            and self.spirit_counts[cup_idx] >= 1
            and self.mixer_count[cup_idx] == 0
        ):
            return False  # tequila slammer in progress

        return True

    def spoil_with(self, cup_idx: int, spirit: Ingredient):
        """Dump an incompatible spirit into the cup. Marks it as a write-off
        so further passes don't keep adding to it.
        """
        self.fill[cup_idx] += 1
        self.spirit_counts[cup_idx] += 1
        self.spirit_type[cup_idx] = spirit
        self.spirits[cup_idx][spirit] += 1
        self.aim[cup_idx] = None
        self.is_spoiled[cup_idx] = True

    def best_spoil_cup(self, spirit: Ingredient) -> int | None:
        """Pick the least-bad cup to spoil with this spirit. Prefer cups with
        the smallest sunk cost (fewer ingredients), since we're writing the
        cup off entirely.
        """
        candidates = [
            (self.fill[i], i) for i in (0, 1) if self.can_spoil_with(i, spirit)
        ]
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][1]

    def any_open(self) -> int | None:
        for i in (0, 1):
            if self.can_add(i):
                return i
        return None

    def best_cup_for_spirit(self, spirit: Ingredient) -> int | None:
        """Find the best cup for this spirit, respecting sellability rules."""
        # A cocktail cup that still needs this spirit comes first
        for i in (0, 1):
            if self.is_cocktail_cup(i) and self.still_needs(i).get(spirit, 0) > 0:
                if self._can_add_spirit(i, spirit):
                    return i
        # Prefer cup that already has this same spirit type (and room for more)
        for i in (0, 1):
            if self._can_add_spirit(i, spirit) and self.spirit_type[i] == spirit:
                return i
        # Prefer empty cup
        for i in (0, 1):
            if self._can_add_spirit(i, spirit) and self.fill[i] == 0:
                return i
        # Any cup where this spirit is legal
        for i in (0, 1):
            if self._can_add_spirit(i, spirit):
                return i
        return None

    def best_cup_for_mixer(self, mixer: Ingredient) -> int | None:
        """Find a cup where this mixer is a valid pairing."""
        for i in (0, 1):
            if self.is_cocktail_cup(i) and self.still_needs(i).get(mixer, 0) > 0:
                if self._can_add_mixer(i, mixer):
                    return i
        # Prefer cup that has a spirit this mixer pairs with
        for i in (0, 1):
            if self._can_add_mixer(i, mixer) and self.spirit_type[i] is not None:
                return i
        # Any cup where it's legal
        for i in (0, 1):
            if self._can_add_mixer(i, mixer):
                return i
        return None

    def has_sellable_cup(self) -> bool:
        """Is there at least one cup that could be sold (has spirit + mixer)?"""
        for i in (0, 1):
            if self.spirit_counts[i] > 0 and self.mixer_count[i] > 0:
                return True
            # Tequila slammer: 2 tequila, no mixer
            if (
                self.spirit_type[i] == Ingredient.TEQUILA
                and self.spirit_counts[i] == 2
                and self.mixer_count[i] == 0
            ):
                return True
        return False


def _hot_mixer_types(ps: PlayerState) -> set[str]:
    """Return mixer type names covered by held refresher cards."""
    return {
        cd.get("mixer_type", "").upper()
        for cd in ps.cards
        if cd.get("card_type") == "refresher" and cd.get("mixer_type")
    }


def _projected_take_count(ps: PlayerState) -> int:
    """How many ingredients the player will have to take next turn."""
    return ps.drunk_level + BASE_TAKE_COUNT


def _should_wee(ps: PlayerState, extra_headroom: int = 0) -> bool:
    """Should the player wee to make room for next turn's take?"""
    if not ps.bladder:
        return False
    projected = _projected_take_count(ps)
    return len(ps.bladder) + projected + extra_headroom > ps.bladder_capacity


def _is_in_danger(ps: PlayerState) -> bool:
    """Player is at risk of elimination (drunk >= 4 or bladder nearly full)."""
    return ps.drunk_level >= 4 or len(ps.bladder) >= ps.bladder_capacity - 1


# ---------------------------------------------------------------------------
#  Drink orders
# ---------------------------------------------------------------------------

_ALL_INGREDIENTS: list[Ingredient] = [*_SPIRITS, *_MIXERS, *SPECIAL_INGREDIENTS]


def _order_cards(gs: GameState) -> list:
    return [
        card
        for row in gs.card_rows
        if row.position == ORDERS_ROW
        for card in row.cards
        if card.card_type == "order"
    ]


def _serves(order: dict, ingredients: list[Ingredient]) -> bool:
    return drink_points(ingredients, []) is not None and matches_order(
        order, ingredients, []
    )


def _order_finishers(gs: GameState, ingredients: list[Ingredient]) -> set[Ingredient]:
    """Ingredients that, added to this glass, would serve an order on the table."""
    if not ingredients:
        return set()
    orders = [c.to_dict() for c in _order_cards(gs)]
    return {
        ing
        for ing in _ALL_INGREDIENTS
        for order in orders
        if _serves(order, [*ingredients, ing])
    }


def order_needs(order, ingredients: list[Ingredient]) -> Counter | None:
    """What a glass still needs to serve this order, or None if it can't.

    A simple order needs its spirit and mixer (a second spirit makes it a
    double, worth more); a slammer two tequilas; a cocktail its recipe.
    """
    sp, mx, sc = _glass_counts(ingredients)
    if order.drink == "cocktail":
        recipe = RECIPE_BY_NAME.get(order.cocktail or "")
        if recipe is None or not recipe.allows(sp, mx, sc):
            return None
        return recipe.missing(sp, mx, sc)
    if sc:
        return None  # a special makes it a cocktail
    if order.drink == "slammer":
        if set(sp) - {Ingredient.TEQUILA} or mx or sp[Ingredient.TEQUILA] > 2:
            return None
        return Counter({Ingredient.TEQUILA: 2 - sp[Ingredient.TEQUILA]})
    spirit = _SPIRIT_MAP.get((order.spirit_type or "").upper())
    mixer = _MIXER_MAP.get((order.mixer_type or "").upper())
    if spirit is None or mixer is None:
        return None
    if set(sp) - {spirit} or set(mx) - {mixer} or sp[spirit] > 2:
        return None
    needs = Counter()
    if not sp:
        needs[spirit] = 1
    if not mx:
        needs[mixer] = 1
    return needs


def order_plans(gs: GameState, ps: PlayerState) -> dict[int, tuple]:
    """For each cup, the order it's best placed to serve: {cup: (order, needs)}.

    A glass already on its way is matched to the order it's closest to; an
    empty one to the order whose ingredients are most within reach now.
    Each order is planned for at most one cup.
    """
    orders = _order_cards(gs)
    if not orders:
        return {}
    in_reach = Counter(gs.open_display) + Counter(gs.specials_display)
    options = []
    for ci, cup in enumerate(ps.cups):
        if cup.is_full:
            continue
        for order in orders:
            needs = order_needs(order, cup.ingredients)
            if needs is None:
                continue
            short = sum(needs.values())
            reachable = sum(min(n, in_reach.get(i, 0)) for i, n in needs.items())
            score = order.bonus * 2 - short * 3 + reachable * 2
            if cup.is_empty:
                score -= 2
            options.append((score, ci, order, needs))
    plans: dict[int, tuple] = {}
    used: set[str] = set()
    for score, ci, order, needs in sorted(options, key=lambda o: -o[0]):
        if ci in plans or order.id in used:
            continue
        plans[ci] = (order, needs)
        used.add(order.id)
    return plans


def _worth_clearing_orders(gs: GameState, ps: PlayerState) -> bool:
    """A rival could serve an order with one more ingredient, and none of
    our glasses is that close to one."""
    ours = order_plans(gs, ps)
    if any(sum(needs.values()) <= 1 for _order, needs in ours.values()):
        return False
    return any(
        _order_finishers(gs, cup.ingredients)
        for pid, opp in gs.player_states.items()
        if pid != ps.player_id and not opp.is_eliminated
        for cup in opp.cups
    )


def _clear_orders_action(free_actions: list[Action]) -> Action | None:
    return next(
        (
            a
            for a in free_actions
            if a.action_type == "refresh_card_row"
            and a.params.get("row_position") == ORDERS_ROW
        ),
        None,
    )


def _opponent_threats(gs: GameState, ps: PlayerState) -> dict[Ingredient, float]:
    """Score each ingredient by how much taking it would deny opponents.

    Higher score = more strategic to deny. Used as a tie-breaker when picking
    from the open display, so the bot prefers ingredients opponents need.

    Signals (visible state per app/PlayerState.to_dict):
      - Specialist/store cards held → opponent wants that spirit
      - Refresher card held → opponent wants that mixer (especially close to claim)
      - Specials on opponent mat → infer cocktail recipe → spirits/mixers needed
      - Karaoke cards in market + opponent's bladder progress → close to claim
      - Partial drink in opponent's cup → wants matching spirit / valid mixer
    """
    threats: dict[Ingredient, float] = {}

    def bump(ing: Ingredient | None, delta: float) -> None:
        if ing is None or delta <= 0:
            return
        threats[ing] = threats.get(ing, 0.0) + delta

    # Karaoke spirit types currently claimable from the market
    karaoke_spirits: set[str] = set()
    for row in gs.card_rows:
        for card in row.cards:
            if card.card_type == "karaoke" and card.spirit_type:
                karaoke_spirits.add(card.spirit_type.upper())

    for opp_id, opp in gs.player_states.items():
        if opp_id == ps.player_id or opp.is_eliminated:
            continue

        # 1. Cards held → ingredient ambitions
        for cd in opp.cards:
            ctype = cd.get("card_type")
            st_name = (cd.get("spirit_type") or "").upper()
            mt_name = (cd.get("mixer_type") or "").upper()
            if ctype == "specialist":
                # +2 pts per matching spirit when selling — they will hoard this spirit
                bump(_SPIRIT_MAP.get(st_name), 0.6)
            elif ctype == "store":
                bump(_SPIRIT_MAP.get(st_name), 0.4)
            elif ctype == "cup_doubler":
                # No specific ingredient ambition (no spirit_type)
                pass
            elif ctype == "refresher":
                mixer = _MIXER_MAP.get(mt_name)
                if mixer is not None:
                    in_bladder = sum(1 for i in opp.bladder if i == mixer)
                    # Only block while they still need more (cap at threshold of 2)
                    needed = max(0, 2 - in_bladder)
                    bump(mixer, 0.4 * needed)

        # 2. Specials on opponent's mat → cocktail recipe candidates
        opp_specials: list[SpecialType] = []
        for s in opp.special_ingredients:
            try:
                st = SpecialType(s)
            except ValueError:
                continue
            if st != SpecialType.NOTHING:
                opp_specials.append(st)
        if opp_specials:
            opp_special_counter = Counter(opp_specials)
            for r_spirits, r_mixers, r_specials, _pts, _name in _RECIPES:
                # Recipe is a candidate if opponent has all required specials
                if all(
                    opp_special_counter.get(sp, 0) >= n for sp, n in r_specials.items()
                ):
                    for ing, n in r_spirits.items():
                        bump(ing, 0.7 * n)
                    for ing, n in r_mixers.items():
                        bump(ing, 0.4 * n)

        # 2b. Glasses on their way to a cocktail: a glass holding specials,
        # or two or more of a cocktail's ingredients → what it still needs
        for cup in opp.cups:
            if not cup.ingredients:
                continue
            sp, mx, sc = _glass_counts(cup.ingredients)
            if not sc and len(cup.ingredients) < 2:
                continue
            for recipe in RECIPES:
                if not recipe.allows(sp, mx, sc):
                    continue
                for ing, n in recipe.missing(sp, mx, sc).items():
                    bump(ing, (0.7 if is_special(ing) else 0.4) * n)

        # 2c. Orders they could serve with one more ingredient
        for cup in opp.cups:
            for ing in _order_finishers(gs, cup.ingredients):
                bump(ing, 0.8)

        # 3. Karaoke progress — opponent close to claiming
        for spirit_name in karaoke_spirits:
            spirit = _SPIRIT_MAP.get(spirit_name)
            if spirit is None:
                continue
            in_bladder = sum(1 for i in opp.bladder if i == spirit)
            if in_bladder == 1:
                # One more of it sings the song; more so once they're drunk
                bump(spirit, 0.4 if opp.drunk_level < 2 else 0.8)

        # 4. Partial drinks in opponent's cups
        for cup in opp.cups:
            spirits_in = [i for i in cup.ingredients if i in _SPIRITS]
            mixers_in = [i for i in cup.ingredients if i in _MIXERS]
            if not spirits_in or len(cup.ingredients) >= MAX_CUP_INGREDIENTS:
                continue
            # Most-common spirit they're committed to
            main_spirit = Counter(spirits_in).most_common(1)[0][0]
            bump(main_spirit, 0.3)
            if mixers_in:
                # They've committed to a mixer type — only that one helps them
                bump(mixers_in[0], 0.3)
            else:
                for mx in VALID_PAIRINGS.get(main_spirit, set()):
                    bump(mx, 0.15)

    return threats


def _smart_take_assignments(
    gs: GameState,
    ps: PlayerState,
    count: int,
    cups: CupTracker,
    *,
    prefer_spirit: Ingredient | None = None,
    spirit_to_cup: bool = True,
    mixer_to_cup_if_paired: bool = True,
    prioritize_specials: bool = False,
    drunk_aware: bool = True,
    drunk_cap: int = 3,
    special_mode: str = "fit",
    prefix: list[dict] | None = None,
    drink_first: set[Ingredient] | None = None,
) -> list[dict]:
    """Shared smart assignment builder — returns display-only assignments.

    Picks from the open display up to `count` items. Remaining items
    will come from the bag via draw_from_bag + choose_pending_assignments.

    Core rules:
    1. Spirits → cups (respecting sellability: same type, max 2)
    2. Paired mixers → cups (only valid pairings)
    3. Other mixers → drink (sobering effect when no spirits drunk)
    4. Stops when display is exhausted (remaining come from bag)

    When ``prioritize_specials`` is True (cocktail bot), SPECIAL tokens are
    taken before anything else — they always roll to the mat regardless of
    disposition and are required for 10–15 pt cocktail recipes.

    Specials on the specials display (source "specials") go into a cup
    whose cocktail they help: ``special_mode`` "fit" only when the cocktail's
    other specials can be had now, "eager" also into an empty cup (the
    cocktail bot), "off" never. A special an opponent needs may be drunk to
    deny them (it sobers like a mixer).

    ``prefix`` holds assignments a strategy already chose; they count toward
    ``count`` and their ingredients are no longer available.

    ``drink_first`` names spirits to drink from the display before anything
    else (a karaoke singer's song spirits), while the drunk cap allows.

    Within each priority class, ingredients opponents need are picked
    first as a denial play (see `_opponent_threats`).
    """
    assignments: list[dict] = list(prefix or [])
    display_available = list(gs.open_display)
    specials_available = list(gs.specials_display)
    for a in assignments:
        pool = (
            specials_available if a.get("source") == "specials" else display_available
        )
        ing = Ingredient[a["ingredient"]]
        if ing in pool:
            pool.remove(ing)
    hot = _hot_mixer_types(ps)
    threats = _opponent_threats(gs, ps)
    # Track spirit drinks committed this batch so the safety gate can decide
    # between drinking, spoiling a stuck cup, or bailing to the bag.
    spirits_drunk_so_far = 0
    spirit_drink_budget = max(0, drunk_cap - ps.drunk_level)

    # Pre-sort display: spirits we can cup first, then paired mixers,
    # then hot mixers (great to drink), then plain mixers, then specials.
    # Tie-breaker: higher opponent threat picked first.
    def _display_priority(ing: Ingredient) -> tuple[int, float]:
        if prefer_spirit and ing == prefer_spirit:
            base = 0
        elif ing in _SPIRITS:
            base = 1
        elif ing in _MIXERS and ing.name in hot:
            base = 2
        elif ing in _MIXERS:
            base = 3
        else:
            base = 4
        return (base, -threats.get(ing, 0.0))

    display_available.sort(key=_display_priority)
    specials_available.sort(key=lambda i: -threats.get(i, 0.0))

    def _take_special(ing: Ingredient, disposition: str, cup_idx: int | None = None):
        specials_available.remove(ing)
        entry = {
            "ingredient": ing.name,
            "source": "specials",
            "disposition": disposition,
        }
        if cup_idx is not None:
            entry["cup_index"] = cup_idx
            cups.add_special(cup_idx, ing)
        assignments.append(entry)

    for _ in range(max(0, count - len(assignments))):
        placed = False

        # Pass 0: spirits we want in the bladder (e.g. for a karaoke song)
        if drink_first and spirits_drunk_so_far < spirit_drink_budget:
            ing = next((i for i in display_available if i in drink_first), None)
            if ing is not None:
                display_available.remove(ing)
                assignments.append(
                    {
                        "ingredient": ing.name,
                        "source": "display",
                        "disposition": "drink",
                    }
                )
                spirits_drunk_so_far += 1
                placed = True

        # Pass 1: preferred spirit → cup (specialist bot: keep focus spirit
        # ahead of specials so the +2 specialist bonus path stays primary)
        if not placed and spirit_to_cup and prefer_spirit:
            if prefer_spirit in display_available:
                cup_idx = cups.best_cup_for_spirit(prefer_spirit)
                if cup_idx is not None:
                    display_available.remove(prefer_spirit)
                    cups.add_spirit(cup_idx, prefer_spirit)
                    assignments.append(
                        {
                            "ingredient": prefer_spirit.name,
                            "source": "display",
                            "disposition": "cup",
                            "cup_index": cup_idx,
                        }
                    )
                    placed = True

        # Pass 1.5 (cocktail/safe/specialist bots): SPECIAL tokens → mat.
        # They auto-roll onto the mat regardless of disposition (no drunk
        # cost, no bladder fill), so they're a free pickup once the
        # preferred spirit (if any) is already secured.
        if not placed and prioritize_specials:
            for ing in list(display_available):
                if ing == Ingredient.SPECIAL:
                    display_available.remove(ing)
                    assignments.append(
                        {
                            "ingredient": ing.name,
                            "source": "display",
                            "disposition": "drink",
                        }
                    )
                    placed = True
                    break

        # Pass 1.6: a special into a cup whose cocktail it helps
        if not placed and special_mode != "off":
            for ing in list(specials_available):
                others = Counter(specials_available)
                others[ing] -= 1
                cup_idx = cups.best_cup_for_special(
                    ing,
                    allow_empty=special_mode == "eager",
                    available=None if special_mode == "eager" else others,
                )
                if cup_idx is not None:
                    _take_special(ing, "cup", cup_idx)
                    placed = True
                    break

        # Pass 2: any spirit from display → cup
        if not placed and spirit_to_cup:
            for ing in list(display_available):
                if ing in _SPIRITS:
                    cup_idx = cups.best_cup_for_spirit(ing)
                    if cup_idx is not None:
                        display_available.remove(ing)
                        cups.add_spirit(cup_idx, ing)
                        assignments.append(
                            {
                                "ingredient": ing.name,
                                "source": "display",
                                "disposition": "cup",
                                "cup_index": cup_idx,
                            }
                        )
                        placed = True
                        break

        # Pass 3: mixer → cup if valid pairing with cup's spirit
        if not placed and mixer_to_cup_if_paired:
            for ing in list(display_available):
                if ing in _MIXERS:
                    cup_idx = cups.best_cup_for_mixer(ing)
                    if cup_idx is not None and cups.spirit_type[cup_idx] is not None:
                        display_available.remove(ing)
                        cups.add_mixer(cup_idx, ing)
                        assignments.append(
                            {
                                "ingredient": ing.name,
                                "source": "display",
                                "disposition": "cup",
                                "cup_index": cup_idx,
                            }
                        )
                        placed = True
                        break

        # Pass 4: drink mixers from display (sobering). A special an
        # opponent needs sobers just the same, and denies them.
        if not placed:
            mixer = next((i for i in display_available if i in _MIXERS), None)
            wanted = next(
                (
                    i
                    for i in specials_available
                    if threats.get(i, 0.0) > 0 and i not in BOOZY_SPECIALS
                ),
                None,
            )
            if wanted is not None and (
                mixer is None or threats[wanted] > threats.get(mixer, 0.0)
            ):
                _take_special(wanted, "drink")
                placed = True
            elif mixer is not None:
                display_available.remove(mixer)
                assignments.append(
                    {
                        "ingredient": mixer.name,
                        "source": "display",
                        "disposition": "drink",
                    }
                )
                placed = True

        # Pass 5: handle spirits that can't be cupped. When drunk_aware, try
        # to (a) spoil a stuck cup with the spirit, or (b) bail to the bag —
        # both avoid certain drunk increase. Only drink as a true last resort
        # when bailing isn't an option (used for KaraokeRusher's drink mode).
        if not placed:
            spirit_to_handle = next(
                (i for i in display_available if i in _SPIRITS), None
            )
            if spirit_to_handle is not None:
                would_overflow = (
                    drunk_aware and spirits_drunk_so_far + 1 > spirit_drink_budget
                )
                if would_overflow:
                    # First option: spoil a stuck cup that can't be sold
                    cup_to_spoil = cups.best_spoil_cup(spirit_to_handle)
                    if cup_to_spoil is not None:
                        display_available.remove(spirit_to_handle)
                        cups.spoil_with(cup_to_spoil, spirit_to_handle)
                        assignments.append(
                            {
                                "ingredient": spirit_to_handle.name,
                                "source": "display",
                                "disposition": "cup",
                                "cup_index": cup_to_spoil,
                            }
                        )
                        placed = True
                    elif drawable_in_bag(gs) >= count - len(assignments):
                        # Bail: leave display alone, let the bag fill the rest
                        # of the take (random — may give mixers or specials
                        # instead of certain drunk). Only safe when bag has
                        # enough items to cover the remaining picks.
                        return assignments
                    else:
                        # Bag too small to bail; have to drink the spirit
                        display_available.remove(spirit_to_handle)
                        assignments.append(
                            {
                                "ingredient": spirit_to_handle.name,
                                "source": "display",
                                "disposition": "drink",
                            }
                        )
                        spirits_drunk_so_far += 1
                        placed = True
                else:
                    display_available.remove(spirit_to_handle)
                    assignments.append(
                        {
                            "ingredient": spirit_to_handle.name,
                            "source": "display",
                            "disposition": "drink",
                        }
                    )
                    spirits_drunk_so_far += 1
                    placed = True

        # Pass 6: any remaining display item (SPECIAL tokens etc.)
        if not placed and display_available:
            chosen = display_available.pop(0)
            assignments.append(
                {
                    "ingredient": chosen.name,
                    "source": "display",
                    "disposition": "drink",
                }
            )
            placed = True

        # Pass 7: drink a special when the bag can't cover the rest
        if (
            not placed
            and specials_available
            and drawable_in_bag(gs) < count - len(assignments)
        ):
            _take_special(
                min(specials_available, key=lambda i: i in BOOZY_SPECIALS), "drink"
            )
            placed = True

        # No more display items — stop here, remaining come from bag
        if not placed:
            break

    return assignments


def _smart_pending_assignments(
    ps: PlayerState,
    drawn: list[Ingredient],
    cups: CupTracker,
    *,
    spirit_to_cup: bool = True,
    drunk_aware: bool = True,
    drunk_cap: int = 3,
    spirits_already_drunk: int = 0,
) -> list[dict]:
    """Assign bag-drawn ingredients after seeing what was drawn.

    Since we know what each ingredient is, we can make optimal decisions:
    - Spirits → cup (if valid slot exists) to avoid raising drunk level
    - Mixers → drink (sobering effect when no spirits drunk in batch)
    - If no cup room for a spirit and drinking would push drunk over the cap,
      spoil a stuck cup instead. Otherwise drink it (unavoidable).
    """
    assignments: list[dict] = []

    # Separate spirits and mixers for batch-aware assignment
    spirits = [i for i in drawn if i in _SPIRITS]
    mixers = [i for i in drawn if i in _MIXERS]
    others = [i for i in drawn if i not in _SPIRITS and i not in _MIXERS]

    spirits_drunk_so_far = spirits_already_drunk
    spirit_drink_budget = max(0, drunk_cap - ps.drunk_level)

    # Assign spirits first (to cups if possible)
    for spirit in spirits:
        if spirit_to_cup:
            cup_idx = cups.best_cup_for_spirit(spirit)
            if cup_idx is not None:
                cups.add_spirit(cup_idx, spirit)
                assignments.append(
                    {
                        "source": "pending",
                        "disposition": "cup",
                        "cup_index": cup_idx,
                    }
                )
                continue
        # Can't cup legally — drinking would raise drunk. Try spoiling a
        # stuck cup if drinking would now exceed the safe cap.
        would_overflow = drunk_aware and spirits_drunk_so_far + 1 > spirit_drink_budget
        if would_overflow:
            cup_to_spoil = cups.best_spoil_cup(spirit)
            if cup_to_spoil is not None:
                cups.spoil_with(cup_to_spoil, spirit)
                assignments.append(
                    {
                        "source": "pending",
                        "disposition": "cup",
                        "cup_index": cup_to_spoil,
                    }
                )
                continue
        # Drink it (unavoidable: no cup, no spoil target)
        spirits_drunk_so_far += 1
        assignments.append({"source": "pending", "disposition": "drink"})

    # Assign mixers — prefer cupping if valid pairing, otherwise drink
    for mixer in mixers:
        cup_idx = cups.best_cup_for_mixer(mixer)
        if cup_idx is not None and cups.spirit_type[cup_idx] is not None:
            cups.add_mixer(cup_idx, mixer)
            assignments.append(
                {
                    "source": "pending",
                    "disposition": "cup",
                    "cup_index": cup_idx,
                }
            )
        else:
            # Drink for sobering effect
            assignments.append({"source": "pending", "disposition": "drink"})

    # Others (specials) — drink
    for _ in others:
        assignments.append({"source": "pending", "disposition": "drink"})

    return _in_drawn_order(drawn, spirits + mixers + others, assignments)


def _in_drawn_order(
    drawn: list[Ingredient], decided: list[Ingredient], assignments: list[dict]
) -> list[dict]:
    """Line assignments up with the draw.

    The engine applies pending assignments to the drawn ingredients in the
    order they came out of the bag; ``assignments[i]`` was decided for
    ``decided[i]`` (the same ingredients, grouped by kind).
    """
    pool = list(zip(decided, assignments))
    ordered = []
    for ing in drawn:
        k = next(i for i, (d, _) in enumerate(pool) if d == ing)
        ordered.append(pool.pop(k)[1])
    return ordered


def _specialist_unlock(gs: GameState, ps: PlayerState) -> Ingredient | None:
    """A special on the tray that, drunk, would pay for a specialist card on
    the table we don't hold yet (bitters → whisky specialist, and so on)."""
    held = {
        cd.get("spirit_type") for cd in ps.cards if cd.get("card_type") == "specialist"
    }
    in_bladder = set(ps.bladder)
    for row in gs.card_rows:
        for card in row.cards:
            if card.card_type != "specialist" or card.spirit_type in held:
                continue
            special = SPECIALIST_SPECIAL.get(card.spirit_type or "")
            if special and special in gs.specials_display and special not in in_bladder:
                if special in BOOZY_SPECIALS and ps.drunk_level >= 3:
                    continue  # not worth the drink this late
                return special
    return None


def _safe_specials_take(
    gs: GameState, ps: PlayerState, valid_actions: list[Action], eager: bool = False
) -> Action | None:
    """Return the take_ingredients action when taking is safe (drunk stays
    ≤ 3) and there's a special worth having: an old die token on the
    display, or a special that helps one of our cups toward a cocktail
    (``eager``: an empty cup counts). Otherwise None.

    Used by every strategy to prefer banking specials over
    selling for points — specials enable 10–15 pt cocktails next turn.
    """
    if not (
        any(ing == Ingredient.SPECIAL for ing in gs.open_display)
        or _useful_special(gs, ps, eager)
    ):
        return None
    if not _safe_to_take(gs, ps):
        return None
    return _find_action(valid_actions, "take_ingredients")


def _useful_special(gs: GameState, ps: PlayerState, eager: bool = False) -> bool:
    """A special on the specials display that would help one of our cups
    toward a cocktail (see CupTracker.best_cup_for_special)."""
    cups = CupTracker(ps)
    showing = Counter(gs.specials_display)
    for ing in showing:
        others = showing.copy()
        others[ing] -= 1
        if (
            cups.best_cup_for_special(
                ing, allow_empty=eager, available=None if eager else others
            )
            is not None
        ):
            return True
    return False


def _safe_to_take(gs: GameState, ps: PlayerState, drunk_cap: int = 3) -> bool:
    """Estimate whether take_ingredients keeps drunk_level ≤ drunk_cap.

    Conservative: SPECIAL tokens roll to the mat (no drunk cost), spirits
    can be cupped (no drunk cost), and anything that doesn't fit is treated
    as a forced spirit drink. Mixers are counted as drinks too even though
    they often sober — the bias is toward not taking when uncertain.
    """
    cup_slots = sum(MAX_CUP_INGREDIENTS - c.base_count for c in ps.cups)
    # Old die tokens go to the mat; specials go in a glass or sober you up
    specials_avail = sum(
        1 for ing in gs.open_display if ing == Ingredient.SPECIAL
    ) + len(gs.specials_display)

    if ps.drunk_level >= drunk_cap:
        # At cap: only safe if every take can be absorbed with no drinks
        return ps.take_count <= cup_slots + specials_avail

    headroom = drunk_cap - ps.drunk_level
    forced_drinks = max(0, ps.take_count - cup_slots - specials_avail)
    return forced_drinks <= headroom


def _find_action(actions: list[Action], action_type: str) -> Action | None:
    for a in actions:
        if a.action_type == action_type:
            return a
    return None


def _find_actions(actions: list[Action], action_type: str) -> list[Action]:
    return [a for a in actions if a.action_type == action_type]


def _best_sell(actions: list[Action], min_pts: int = 0) -> Action | None:
    sells = [
        a
        for a in actions
        if a.action_type == "sell_cup" and a.params.get("points", 0) >= min_pts
    ]
    if not sells:
        return None
    sells.sort(key=lambda a: a.params.get("points", 0), reverse=True)
    return sells[0]


def _card_claims_by_type(actions: list[Action], card_type: str) -> list[Action]:
    return [
        a
        for a in actions
        if a.action_type == "claim_card" and card_type in a.description.lower()
    ]


def _free_claim_action(
    free_actions: list[Action], prefer_card_types: list[str] | None = None
) -> Action | None:
    """Pick a free claim_card action (claiming is always a free action).

    When several are available, prefer claim types in ``prefer_card_types``
    (in order). Falls back to the first claim_card found, with karaoke
    deprioritised below other types unless explicitly preferred (since
    karaoke claims usually want to be the main action of the turn so the
    win-condition check is the headline event).
    """
    claims = [a for a in free_actions if a.action_type == "claim_card"]
    if not claims:
        return None
    if prefer_card_types:
        for ct in prefer_card_types:
            for c in claims:
                if ct in c.description.lower():
                    return c
    # Default ordering: karaoke last (a free karaoke is fine but we don't
    # over-prefer it); everything else first-found.
    non_karaoke = [c for c in claims if "karaoke" not in c.description.lower()]
    if non_karaoke:
        return non_karaoke[0]
    return claims[0]


# ---------------------------------------------------------------------------
#  Strategy ABC
# ---------------------------------------------------------------------------


class Strategy(ABC):
    name: str = "base"

    @abstractmethod
    def choose_action(
        self, gs: GameState, player_id: UUID, valid_actions: list[Action]
    ) -> Action: ...

    def choose_free_action(
        self, gs: GameState, player_id: UUID, free_actions: list[Action]
    ) -> Action | None:
        # Claiming is a free action: take any affordable card — free points
        # are always better than nothing.
        claim = _free_claim_action(free_actions)
        if claim is not None:
            return claim
        return None

    def choose_take_assignments(
        self, gs: GameState, player_id: UUID, count: int
    ) -> list[dict]:
        """Return display-only assignments. Remaining items come from bag.

        Should return between 0 and min(count, len(display)) assignments.
        All must have source="display".
        """
        ps = gs.player_states[player_id]
        cups = CupTracker(ps)
        return _smart_take_assignments(gs, ps, count, cups)

    def choose_pending_assignments(
        self, gs: GameState, player_id: UUID, drawn: list[Ingredient]
    ) -> list[dict]:
        """Assign bag-drawn ingredients after seeing what was drawn.

        `drawn` contains the actual Ingredient objects drawn from the bag.
        Must return len(drawn) assignments, each with source="pending".
        """
        ps = gs.player_states[player_id]
        cups = CupTracker(ps)
        return _smart_pending_assignments(ps, drawn, cups)


# ---------------------------------------------------------------------------
#  Strategy implementations
# ---------------------------------------------------------------------------


class RandomStrategy(Strategy):
    """Picks uniformly at random. Uses smart assignments to stay alive."""

    name = "Random"

    def choose_action(
        self, gs: GameState, player_id: UUID, valid_actions: list[Action]
    ) -> Action:
        return random.choice(valid_actions)

    def choose_free_action(
        self, gs: GameState, player_id: UUID, free_actions: list[Action]
    ) -> Action | None:
        if free_actions and random.random() < 0.3:
            return random.choice(free_actions)
        return None


class KaraokeRusher(Strategy):
    """Rushes karaoke cards for the 3-karaoke win.

    A song needs drunk 3+ and 2 of its spirit in the bladder, so it drinks
    the songs' spirits (which also gets it drunk enough) up to drunk 4,
    then sings. Otherwise plays safe with spirits→cups.
    """

    name = "KaraokeRusher"

    def _target_spirits(self, gs: GameState) -> list[str]:
        targets = []
        for row in gs.card_rows:
            for card in row.cards:
                if card.card_type == "karaoke" and card.spirit_type:
                    targets.append(card.spirit_type)
        return targets

    def choose_action(
        self, gs: GameState, player_id: UUID, valid_actions: list[Action]
    ) -> Action:
        ps = gs.player_states[player_id]

        # Claim karaoke card (the goal)
        karaoke = _card_claims_by_type(valid_actions, "karaoke")
        if karaoke:
            return karaoke[0]

        # Singing means living at drunk 3+: step back from the edge first
        if ps.drunk_level >= 4 or _is_in_danger(ps):
            wee = _find_action(valid_actions, "go_for_a_wee")
            if wee:
                return wee

        # Safe specials take — bank them on the mat for future cocktails
        take = _safe_specials_take(gs, ps, valid_actions)
        if take:
            return take

        # Sell any cup with points (free up cup space + score)
        sell = _best_sell(valid_actions, min_pts=1)
        if sell:
            return sell

        # Wee if needed
        if _should_wee(ps):
            wee = _find_action(valid_actions, "go_for_a_wee")
            if wee:
                return wee

        # Claim store card matching a target spirit
        targets = self._target_spirits(gs)
        store_claims = _card_claims_by_type(valid_actions, "store")
        for sc in store_claims:
            card_id = sc.params["card_id"]
            for row in gs.card_rows:
                for card in row.cards:
                    if card.id == card_id and card.spirit_type in targets:
                        return sc

        # Claim refresher (survival)
        refreshers = _card_claims_by_type(valid_actions, "refresher")
        if refreshers:
            return refreshers[0]

        # Take ingredients
        take = _find_action(valid_actions, "take_ingredients")
        if take:
            return take

        # Wee
        wee = _find_action(valid_actions, "go_for_a_wee")
        if wee:
            return wee

        return valid_actions[0]

    def choose_free_action(
        self, gs: GameState, player_id: UUID, free_actions: list[Action]
    ) -> Action | None:
        # A free karaoke claim is the dream — prefer it over any other claim
        # type or stored-spirit move.
        claim = _free_claim_action(free_actions, prefer_card_types=["karaoke"])
        if claim is not None:
            return claim
        use = _find_action(free_actions, "use_stored_spirit")
        if use:
            return use
        return None

    def choose_take_assignments(
        self, gs: GameState, player_id: UUID, count: int
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        cups = CupTracker(ps)

        # Drink a song's spirit while it still needs one and drunk stays ≤ 4:
        # the drinking is what gets it to drunk 3 to sing.
        ing = self._song_to_drink(gs, ps)
        if ing is not None:
            return _smart_take_assignments(
                gs,
                ps,
                count,
                cups,
                drunk_cap=4,
                drink_first=self._song_spirits_needed(gs, ps),
            )

        return _smart_take_assignments(gs, ps, count, cups)

    def _song_spirits_needed(self, gs: GameState, ps: PlayerState) -> set[Ingredient]:
        """Song spirits still short of the 2 a song needs."""
        needed = set()
        for t in self._target_spirits(gs):
            ing = _SPIRIT_MAP.get(t)
            if ing is not None and sum(1 for i in ps.bladder if i == ing) < 2:
                needed.add(ing)
        return needed

    def _song_to_drink(self, gs: GameState, ps: PlayerState) -> Ingredient | None:
        """The karaoke spirit worth drinking now, if any: the song closest to
        its 2 spirits, while drunk is below 4."""
        if ps.drunk_level >= 4:
            return None
        best, best_have = None, -1
        for t in self._target_spirits(gs):
            ing = _SPIRIT_MAP.get(t)
            if ing is None:
                continue
            have = sum(1 for i in ps.bladder if i == ing)
            if have < 2 and have > best_have:
                best, best_have = ing, have
        return best

    def choose_pending_assignments(
        self, gs: GameState, player_id: UUID, drawn: list[Ingredient]
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        cups = CupTracker(ps)

        # Drink drawn song spirits it still needs (up to drunk 4); the rest
        # are handled as usual.
        if self._song_to_drink(gs, ps) is not None:
            needed = self._song_spirits_needed(gs, ps)
            already = sum(1 for i in gs.drunk_ingredients_this_turn if i in _SPIRITS)
            budget = max(0, 4 - ps.drunk_level - already)
            song, rest = [], []
            for ing in drawn:
                if ing in needed and len(song) < budget:
                    song.append(ing)
                    needed.discard(ing)  # one of each per batch is plenty
                else:
                    rest.append(ing)
            if song:
                rest_asg = _smart_pending_assignments(
                    ps, rest, cups, spirits_already_drunk=already + len(song)
                )
                drink = [{"source": "pending", "disposition": "drink"}] * len(song)
                return _in_drawn_order(drawn, song + rest, drink + rest_asg)

        return _smart_pending_assignments(ps, drawn, cups)


class CocktailHunter(Strategy):
    """Chases 10–15 pt cocktails.

    Takes specials off the specials display into a glass (an empty one
    will do) and then fills that glass with what the recipe still needs;
    sells ordinary drinks from the other glass meanwhile.
    """

    name = "CocktailHunter"

    def choose_action(
        self, gs: GameState, player_id: UUID, valid_actions: list[Action]
    ) -> Action:
        ps = gs.player_states[player_id]

        # A finished cocktail sells first
        sell = _best_sell(valid_actions, min_pts=10)
        if sell:
            return sell

        # If a special would start or advance a cocktail AND taking is safe
        # (won't push drunk above 3), take — cocktails are worth 10–15 pts.
        take = _safe_specials_take(gs, ps, valid_actions, eager=True)
        if take:
            return take

        # Otherwise, sell any cup with points (highest value first)
        sell = _best_sell(valid_actions, min_pts=1)
        if sell:
            return sell

        # Wee if needed
        if _should_wee(ps):
            wee = _find_action(valid_actions, "go_for_a_wee")
            if wee:
                return wee

        # Claim refresher (survival + points)
        refreshers = _card_claims_by_type(valid_actions, "refresher")
        if refreshers:
            return refreshers[0]

        # Danger: emergency wee
        if _is_in_danger(ps):
            wee = _find_action(valid_actions, "go_for_a_wee")
            if wee:
                return wee

        # Take ingredients
        take = _find_action(valid_actions, "take_ingredients")
        if take:
            return take

        wee = _find_action(valid_actions, "go_for_a_wee")
        if wee:
            return wee

        return valid_actions[0]

    def choose_free_action(
        self, gs: GameState, player_id: UUID, free_actions: list[Action]
    ) -> Action | None:
        claim = _free_claim_action(free_actions)
        if claim is not None:
            return claim
        return None

    def choose_take_assignments(
        self, gs: GameState, player_id: UUID, count: int
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        cups = CupTracker(ps)
        return _smart_take_assignments(
            gs,
            ps,
            count,
            cups,
            mixer_to_cup_if_paired=True,
            prioritize_specials=True,
            special_mode="eager",
        )


class SafeSeller(Strategy):
    """Conservative: sell quickly, stay sober, wee when needed.

    Spirits → cups with valid mixers → sell immediately.
    Drinks only mixers for sobering. Grabs SPECIAL tokens eagerly because
    they roll to the mat without filling the bladder or raising drunk.
    """

    name = "SafeSeller"

    def choose_action(
        self, gs: GameState, player_id: UUID, valid_actions: list[Action]
    ) -> Action:
        ps = gs.player_states[player_id]

        # Safe specials take — banking specials avoids drinking and unlocks
        # future cocktails.
        take = _safe_specials_take(gs, ps, valid_actions)
        if take:
            return take

        # Sell any cup with points FIRST (before weeing)
        sell = _best_sell(valid_actions, min_pts=1)
        if sell:
            return sell

        # Wee if needed
        if _should_wee(ps):
            wee = _find_action(valid_actions, "go_for_a_wee")
            if wee:
                return wee

        # Claim refresher (survival)
        refreshers = _card_claims_by_type(valid_actions, "refresher")
        if refreshers:
            return refreshers[0]

        # Claim store cards
        stores = _card_claims_by_type(valid_actions, "store")
        if stores:
            return stores[0]

        # Take ingredients
        take = _find_action(valid_actions, "take_ingredients")
        if take:
            return take

        # Wee if anything in bladder
        wee = _find_action(valid_actions, "go_for_a_wee")
        if wee:
            return wee

        return valid_actions[0]

    def choose_take_assignments(
        self, gs: GameState, player_id: UUID, count: int
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        cups = CupTracker(ps)
        return _smart_take_assignments(gs, ps, count, cups, prioritize_specials=True)


class AggressiveDrinker(Strategy):
    """Gets drunk to refresh rows, claims refreshers for hot mixers.

    Backs off when in danger zone. Hot mixers (from refresher cards)
    always subtract from drunk even with spirits present.
    """

    name = "AggressiveDrinker"

    def choose_action(
        self, gs: GameState, player_id: UUID, valid_actions: list[Action]
    ) -> Action:
        ps = gs.player_states[player_id]

        # Safe specials take — free pickups for the mat
        take = _safe_specials_take(gs, ps, valid_actions)
        if take:
            return take

        # Sell any cup with points
        sell = _best_sell(valid_actions, min_pts=1)
        if sell:
            return sell

        # Survival: wee if near burst
        if _should_wee(ps):
            wee = _find_action(valid_actions, "go_for_a_wee")
            if wee:
                return wee

        # Claim refresher cards (core strategy — hot mixers!)
        refreshers = _card_claims_by_type(valid_actions, "refresher")
        if refreshers:
            return refreshers[0]

        # Drink cups to get drunker (but NOT if we'd die)
        if ps.drunk_level < 4:
            drinks = _find_actions(valid_actions, "drink_cup")
            if drinks:
                return drinks[0]

        # Refresh card rows when drunk enough
        refreshes = _find_actions(valid_actions, "refresh_card_row")
        if refreshes:
            return random.choice(refreshes)

        # Claim karaoke if possible
        karaoke = _card_claims_by_type(valid_actions, "karaoke")
        if karaoke:
            return karaoke[0]

        # Take ingredients
        take = _find_action(valid_actions, "take_ingredients")
        if take:
            return take

        wee = _find_action(valid_actions, "go_for_a_wee")
        if wee:
            return wee

        return valid_actions[0]

    def choose_free_action(
        self, gs: GameState, player_id: UUID, free_actions: list[Action]
    ) -> Action | None:
        ps = gs.player_states[player_id]
        # Refresher claims fit this strategy best (hot mixers ↔ refresh rows);
        # otherwise any free claim is welcome.
        claim = _free_claim_action(free_actions, prefer_card_types=["refresher"])
        if claim is not None:
            return claim
        if ps.drunk_level < 4:
            use = _find_action(free_actions, "use_stored_spirit")
            if use:
                return use
        return None

    def choose_take_assignments(
        self, gs: GameState, player_id: UUID, count: int
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        cups = CupTracker(ps)
        if _is_in_danger(ps):
            return _smart_take_assignments(
                gs,
                ps,
                count,
                cups,
                mixer_to_cup_if_paired=False,
            )
        return _smart_take_assignments(gs, ps, count, cups)


class SpecialistBuilder(Strategy):
    """Claims specialist cards then sells boosted drinks.

    Specialist gives +2pts per matching spirit type on non-cocktail sells.
    """

    name = "SpecialistBuilder"

    def _held_specialist_types(self, ps: PlayerState) -> set[str]:
        return {
            cd.get("spirit_type")
            for cd in ps.cards
            if cd.get("card_type") == "specialist" and cd.get("spirit_type")
        }

    def _target_specialist_types(self, gs: GameState) -> list[str]:
        targets = []
        for row in gs.card_rows:
            for card in row.cards:
                if card.card_type == "specialist" and card.spirit_type:
                    targets.append(card.spirit_type)
        return targets

    def _best_spirit_type(self, gs: GameState, ps: PlayerState) -> str | None:
        held = self._held_specialist_types(ps)
        if held:
            return next(iter(held))
        available = self._target_specialist_types(gs)
        if available:
            best, best_count = available[0], 0
            for st in available:
                ing = _SPIRIT_MAP.get(st)
                if ing:
                    c = sum(1 for i in ps.bladder if i == ing)
                    if c > best_count:
                        best, best_count = st, c
            return best
        best, best_count = None, 0
        for name, ing in _SPIRIT_MAP.items():
            c = sum(1 for i in ps.bladder if i == ing)
            if c > best_count:
                best, best_count = name, c
        return best

    def choose_action(
        self, gs: GameState, player_id: UUID, valid_actions: list[Action]
    ) -> Action:
        ps = gs.player_states[player_id]
        focus = self._best_spirit_type(gs, ps)

        # Safe specials take — bank specials for future cocktails before
        # cashing in non-cocktail sells.
        take = _safe_specials_take(gs, ps, valid_actions)
        if take:
            return take

        # Sell cups (specialist bonus makes even small drinks worthwhile)
        sell = _best_sell(valid_actions, min_pts=1)
        if sell:
            return sell

        # Wee if needed
        if _should_wee(ps):
            wee = _find_action(valid_actions, "go_for_a_wee")
            if wee:
                return wee

        # Claim specialist card
        specialists = _card_claims_by_type(valid_actions, "specialist")
        if specialists:
            for sc in specialists:
                if focus and focus in sc.description:
                    return sc
            return specialists[0]

        # Claim store card for focus spirit
        stores = _card_claims_by_type(valid_actions, "store")
        for sc in stores:
            card_id = sc.params["card_id"]
            for row in gs.card_rows:
                for card in row.cards:
                    if card.id == card_id and card.spirit_type == focus:
                        return sc

        # Claim cup doubler
        doublers = _card_claims_by_type(valid_actions, "cup doubler")
        if doublers:
            return doublers[0]

        # Claim refresher (survival)
        refreshers = _card_claims_by_type(valid_actions, "refresher")
        if refreshers:
            return refreshers[0]

        # Take ingredients
        take = _find_action(valid_actions, "take_ingredients")
        if take:
            return take

        wee = _find_action(valid_actions, "go_for_a_wee")
        if wee:
            return wee

        return valid_actions[0]

    def choose_free_action(
        self, gs: GameState, player_id: UUID, free_actions: list[Action]
    ) -> Action | None:
        ps = gs.player_states[player_id]
        # Specialist claim free is amazing — it is the entire strategy in
        # one free action.
        claim = _free_claim_action(
            free_actions, prefer_card_types=["specialist", "store"]
        )
        if claim is not None:
            return claim
        held = self._held_specialist_types(ps)
        use_actions = _find_actions(free_actions, "use_stored_spirit")
        for ua in use_actions:
            idx = ua.params["store_card_index"]
            card_dict = ps.cards[idx]
            spirit = card_dict.get("spirit_type", "")
            if spirit in held:
                return ua
        return None

    def choose_take_assignments(
        self, gs: GameState, player_id: UUID, count: int
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        cups = CupTracker(ps)
        held = self._held_specialist_types(ps)
        focus = self._best_spirit_type(gs, ps)
        focus_ing = _SPIRIT_MAP.get(focus) if focus else None

        # One special pays for a specialist card: drink it off the tray
        unlock = _specialist_unlock(gs, ps)
        if unlock is not None:
            return _smart_take_assignments(
                gs,
                ps,
                count,
                cups,
                prefer_spirit=focus_ing,
                prioritize_specials=True,
                prefix=[
                    {
                        "ingredient": unlock.name,
                        "source": "specials",
                        "disposition": "drink",
                    }
                ],
            )

        if held and focus_ing:
            return _smart_take_assignments(
                gs,
                ps,
                count,
                cups,
                prefer_spirit=focus_ing,
                mixer_to_cup_if_paired=True,
                prioritize_specials=True,
            )
        else:
            # Need spirits in bladder for specialist claim (2 required).
            # Only drink spirits when safe (drunk ≤ 1) and have 1 already.
            if focus_ing and ps.drunk_level <= 1:
                have = sum(1 for i in ps.bladder if i == focus_ing)
                if have == 1:
                    return _smart_take_assignments(
                        gs,
                        ps,
                        count,
                        cups,
                        prefer_spirit=focus_ing,
                        spirit_to_cup=False,
                        mixer_to_cup_if_paired=False,
                        prioritize_specials=True,
                        drunk_aware=False,
                    )

            # Default: safe play with preferred spirit → cups
            return _smart_take_assignments(
                gs,
                ps,
                count,
                cups,
                prefer_spirit=focus_ing,
                prioritize_specials=True,
            )

    def choose_pending_assignments(
        self, gs: GameState, player_id: UUID, drawn: list[Ingredient]
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        cups = CupTracker(ps)
        held = self._held_specialist_types(ps)
        focus = self._best_spirit_type(gs, ps)
        focus_ing = _SPIRIT_MAP.get(focus) if focus else None

        # If no specialist yet, safe, and close to claiming: drink spirits
        if not held and focus_ing and ps.drunk_level <= 1:
            have = sum(1 for i in ps.bladder if i == focus_ing)
            if have == 1:
                return _smart_pending_assignments(
                    ps, drawn, cups, spirit_to_cup=False, drunk_aware=False
                )

        return _smart_pending_assignments(ps, drawn, cups)


class Mastermind(Strategy):
    """Weighted-evaluation strategy with bag probability analysis.

    Scores every valid action on a common scale considering:
    - Immediate point value and sell bonuses
    - Card synergies (specialist, doubler, store, karaoke)
    - Bag composition (probability of drawing useful vs harmful ingredients)
    - Survival costs (drunk risk, bladder pressure)
    - Opponent threat level (scoring pressure, elimination likelihood)

    Key advantages over rule-based strategies:
    1. Naturally adapts sell timing to risk — holds for 3-pt sells when safe,
       dumps at 1 pt when drunk is high.
    2. Claims specialist/doubler for 6-8 pt sells, prioritised by synergy value.
    3. Skips negative-value display items; draws from bag when expected value is
       higher (avoids forced spirit drinking).
    4. Pre-wee claim bonus: claims cards before weeing flushes bladder spirits.
    5. Spirit accumulation emerges from display item scoring — no brittle mode
       switching.
    """

    name = "Mastermind"

    # ------------------------------------------------------------------
    #  Focus spirit selection
    # ------------------------------------------------------------------

    def _focus_spirit(self, gs: GameState, ps: PlayerState) -> str:
        """Pick the best spirit type to build around."""
        for c in ps.cards:
            if c.get("card_type") == "specialist" and c.get("spirit_type"):
                return c["spirit_type"]

        best, best_score = "VODKA", -1
        for name, ing in _SPIRIT_MAP.items():
            score = len(VALID_PAIRINGS.get(ing, set())) * 10
            for cup in ps.cups:
                score += sum(12 for i in cup.ingredients if i == ing)
            score += sum(5 for i in ps.bladder if i == ing)
            score += sum(3 for i in gs.open_display if i == ing)
            for row in gs.card_rows:
                for card in row.cards:
                    if card.card_type == "specialist" and card.spirit_type == name:
                        score += 20
                    if card.card_type == "store" and card.spirit_type == name:
                        score += 5
            # Orders on the table that want this spirit
            for order in _order_cards(gs):
                if order.drink == "simple" and order.spirit_type == name:
                    score += 4 + order.bonus
                elif order.drink == "slammer" and name == "TEQUILA":
                    score += 4 + order.bonus
            if score > best_score:
                best, best_score = name, score
        return best

    # ------------------------------------------------------------------
    #  State queries
    # ------------------------------------------------------------------

    def _has_specialist(self, ps: PlayerState, focus: str) -> bool:
        return any(
            c.get("card_type") == "specialist" and c.get("spirit_type") == focus
            for c in ps.cards
        )

    def _has_doubler(self, ps: PlayerState) -> bool:
        return any(cup.has_cup_doubler for cup in ps.cups)

    def _max_opp_pts(self, gs: GameState, pid) -> int:
        return max(
            (
                p.points
                for k, p in gs.player_states.items()
                if k != pid and not p.is_eliminated
            ),
            default=0,
        )

    def _opp_might_die(self, gs: GameState, pid) -> bool:
        return any(
            p.drunk_level >= 4
            for k, p in gs.player_states.items()
            if k != pid and not p.is_eliminated
        )

    # ------------------------------------------------------------------
    #  Bag probability helpers
    # ------------------------------------------------------------------

    def _bag_spirit_frac(self, gs: GameState) -> float:
        drawable = drawable_in_bag(gs)
        if not drawable:
            return 0.0
        return sum(1 for i in gs.bag_contents if i in _SPIRITS) / drawable

    # ------------------------------------------------------------------
    #  Spirit accumulation value (for card claims via bladder)
    # ------------------------------------------------------------------

    def _spirit_accum_value(
        self, gs: GameState, ps: PlayerState, spirit_ing: Ingredient, focus: str
    ) -> float:
        """Value of having one more of this spirit in bladder for claims."""
        name = spirit_ing.name
        current = sum(1 for i in ps.bladder if i == spirit_ing)
        after = current + 1
        value = 0.0
        for row in gs.card_rows:
            for card in row.cards:
                if card.card_type == "specialist" and card.spirit_type == name:
                    if current < 2 <= after and not self._has_specialist(ps, focus):
                        value += 30
                if card.card_type == "cup_doubler":
                    if current < 3 <= after and not self._has_doubler(ps):
                        value += 35
                if card.card_type == "karaoke" and card.spirit_type == name:
                    # A song: 2 of its spirit, and drunk 3+ (this drink helps)
                    if current < 2 <= after and ps.drunk_level + 1 >= 3:
                        kc = ps.karaoke_cards_claimed
                        value += 100 if kc >= 2 else (25 if kc >= 1 else 10)
                if card.card_type == "store" and card.spirit_type == name:
                    if current < 1 <= after:
                        value += 8
        # Discount by drunk risk: drinking a spirit is far worse when already drunk
        drunk_discount = max(0.1, 1.0 - ps.drunk_level * 0.3)
        return value * drunk_discount

    # ------------------------------------------------------------------
    #  Urgency from opponent state
    # ------------------------------------------------------------------

    def _urgency(self, gs: GameState, pid) -> float:
        """0.0 = relaxed, 1.0 = desperate."""
        max_pts = self._max_opp_pts(gs, pid)
        u = 0.0
        if max_pts >= 35:
            u = 0.8
        elif max_pts >= 28:
            u = 0.5
        elif max_pts >= 20:
            u = 0.2
        opp_karaoke = max(
            (
                p.karaoke_cards_claimed
                for k, p in gs.player_states.items()
                if k != pid and not p.is_eliminated
            ),
            default=0,
        )
        if opp_karaoke >= 2:
            u = max(u, 0.7)
        if self._opp_might_die(gs, pid):
            u = max(0.0, u - 0.2)
        return u

    # ------------------------------------------------------------------
    #  Action scoring (common scale 0-200)
    # ------------------------------------------------------------------

    def _score_sell(
        self, gs: GameState, ps: PlayerState, action: Action, focus: str, pid
    ) -> float:
        pts = action.params.get("points", 0)
        drunk = ps.drunk_level
        score = pts * 10.0

        # Penalize low-value sells — hold cups for higher value
        # Kyle sells for 5.2 avg, bots sell for 2.3 avg (44% are 1-pt dumps)
        if pts <= 1:
            score -= 15.0  # Strong penalty for 1-pt sells
        elif pts <= 2:
            score -= 5.0

        # Bonus for high-value sells (cocktails, doubled cups)
        if pts >= 6:
            score += 15.0
        elif pts >= 4:
            score += 8.0

        # Serving an order: take the bonus before a rival does
        if action.params.get("order"):
            score += 12.0

        # Urgency: score faster when opponent is ahead
        score += self._urgency(gs, pid) * 10

        # Relative score gap: sell faster when falling behind
        score_gap = self._max_opp_pts(gs, pid) - ps.points
        if score_gap > 5:
            score += min(score_gap, 10)

        # Drunk pressure: sell faster to avoid taking when drunk
        # (reduced from before — bots were panic-selling too much)
        if drunk >= 5:
            score += 20
        elif drunk >= 4:
            score += 10
        elif drunk >= 3:
            score += 5

        # Need cup space: small bonus when both cups occupied
        if not ps.cups[0].is_empty and not ps.cups[1].is_empty:
            score += 5

        # Dead-end cup: no matching spirits left in bag/display → sell now
        ci = action.params.get("cup_index")
        if ci is not None and pts <= 1:
            from app.actions import _SPIRITS as _SP

            cup_spirit = next(
                (ing for ing in ps.cups[ci].ingredients if ing in _SP), None
            )
            if cup_spirit:
                remaining = gs.bag_contents.count(cup_spirit) + gs.open_display.count(
                    cup_spirit
                )
                if remaining == 0:
                    score += 20  # No matching spirits exist — sell immediately

        return score

    def _score_take(
        self, gs: GameState, ps: PlayerState, focus_ing: Ingredient | None, pid
    ) -> float:
        cups = CupTracker(ps)
        drunk = ps.drunk_level

        # Count spirit slots available across both cups
        spirit_slots = 0
        for i in (0, 1):
            if cups.can_add(i) and cups.spirit_counts[i] < 2:
                spirit_slots += 2 - cups.spirit_counts[i]

        # Taking is how you build cups and score points — higher baseline.
        # Kyle takes 42.7% of the time + draws from bag 16.5%.
        score = 25.0  # Baseline — taking is the default productive action
        score += min(spirit_slots, 3) * 2.0  # Bonus for cup headroom

        # Risk penalty when cups can't absorb spirits
        if spirit_slots == 0 and drunk >= 4:
            score -= 25.0  # Danger zone: very likely to die from forced spirit drink
        elif spirit_slots == 0 and drunk >= 3:
            score -= 12.0
        elif spirit_slots == 0:
            score -= 3.0 + drunk * 2.0
        elif drunk >= 4:
            score -= 5.0

        # Display quality bonus/penalty (rough estimate)
        mat_specials = len(ps.special_ingredients)
        special_bonus = 2.0 + min(mat_specials, 3) * 1.0
        for ing in gs.open_display:
            if ing in _SPIRITS:
                if cups.best_cup_for_spirit(ing) is not None:
                    score += 2.0  # Can cup it
                else:
                    score -= 1.0 + drunk * 0.5  # Forced to drink
            elif ing in _MIXERS:
                score += 0.5
            else:
                # SPECIAL → mat: cost-free pickup that enables 10–15 pt cocktails
                score += special_bonus
        # Specials on show that would move a glass toward a cocktail
        showing = Counter(gs.specials_display)
        for ing in showing:
            others = showing.copy()
            others[ing] -= 1
            if cups.best_cup_for_special(ing, available=others) is not None:
                score += 3.0

        # Bag risk when spirit slots are exhausted
        if spirit_slots == 0:
            bag_draws = max(0, ps.take_count - len(gs.open_display))
            score -= bag_draws * self._bag_spirit_frac(gs) * (2.0 + drunk * 1.5)

        # Bladder overflow risk: hard penalty only when truly at risk
        bladder_room = ps.bladder_capacity - len(ps.bladder)
        cup_room = sum(MAX_CUP_INGREDIENTS - cups.fill[i] for i in (0, 1))
        est_drunk = max(0, ps.take_count - cup_room)
        if est_drunk > bladder_room:
            score -= (est_drunk - bladder_room) * 10  # Wet risk — keep this hard

        return score

    def _score_claim(
        self, gs: GameState, ps: PlayerState, action: Action, focus: str, pid
    ) -> float:
        desc = action.description.lower()
        params = action.params
        has_spec = self._has_specialist(ps, focus)
        has_dbl = self._has_doubler(ps)
        num_cards = len(ps.cards)

        # Cards are the engine — kyle claims 3.2/game, bots claim 0.5/game.
        # Every card claimed compounds value for the rest of the game.
        # Base bonus scales with how few cards we have (early claims most impactful).
        card_hunger = max(0, 3 - num_cards) * 8.0

        score = 0.0
        if "cup doubler" in desc:
            score = 90.0 + card_hunger
            if has_spec:
                score += 25  # Specialist + doubler combo → 8-pt sells
            ci = params.get("cup_index", 0)
            focus_ing = _SPIRIT_MAP.get(focus)
            if focus_ing and any(i == focus_ing for i in ps.cups[ci].ingredients):
                score += 10  # Place on focus cup
        elif "specialist" in desc:
            score = 80.0 + card_hunger
            if has_dbl:
                score += 20
            if focus.lower() in desc:
                score += 15  # Matches focus spirit
        elif "karaoke" in desc:
            kc = ps.karaoke_cards_claimed
            if kc >= 2:
                return 200.0  # Instant win — always take this
            score = (70.0 + self._urgency(gs, pid) * 25) if kc == 1 else 40.0
            score += card_hunger
        elif "store" in desc:
            card_id = params.get("card_id")
            is_focus = any(
                card.spirit_type == focus
                for row in gs.card_rows
                for card in row.cards
                if card.id == card_id
            )
            # Store cards enable spirit accumulation — the key to high-value sells
            score = 65.0 + card_hunger if is_focus else 45.0 + card_hunger
            if ps.drunk_level >= 4:
                score -= 10  # Don't claim in danger zone
        elif "refresher" in desc:
            score = 50.0 + card_hunger
            if ps.drunk_level >= 2:
                score += 10  # More valuable when drunk
        else:
            score = 30.0 + card_hunger

        # Pre-wee bonus: claim before weeing flushes bladder spirits
        overflow = len(ps.bladder) + ps.take_count - ps.bladder_capacity
        if overflow > 0:
            score += min(overflow * 5, 20)

        return score

    def _score_wee(self, ps: PlayerState) -> float:
        overflow = len(ps.bladder) + ps.take_count - ps.bladder_capacity

        # Kyle wees rarely (2.6%) but survives. Key: wee when next take overflows.
        if overflow >= 3:
            score = 80.0  # Emergency
        elif overflow >= 2:
            score = 55.0  # Very likely to overflow
        elif overflow >= 1:
            score = 35.0  # At risk
        elif overflow == 0:
            score = 15.0  # Borderline
        else:
            score = -5.0  # Don't waste a turn

        # Conserve last toilet token
        if ps.toilet_tokens <= 1 and overflow < 2:
            score -= 15

        return score

    def _score_drink_cup(self, ps: PlayerState, action: Action) -> float:
        """Score drinking a cup.

        Two scenarios where this is valuable:
        1. Mixer-only cup at high drunk → sobers us (delta < 0)
        2. Stuck cup (unsellable) at high drunk → controlled delta is safer
           than a random take, AND fills bladder so we can wee next turn
        """
        ci = action.params.get("cup_index", 0)
        cup = ps.cups[ci]
        cup_spirits = sum(1 for i in cup.ingredients if i in _SPIRITS)
        cup_size = len(cup.ingredients)

        # Check bladder can handle the extra items
        if len(ps.bladder) + cup_size > ps.bladder_capacity:
            return -50.0  # Would cause wet elimination!

        hot = _hot_mixer_types(ps)
        cup_hot = sum(1 for i in cup.ingredients if i in _MIXERS and i.name in hot)

        if cup_spirits > 0:
            delta = cup_spirits - cup_hot
        else:
            cup_plain = sum(
                1 for i in cup.ingredients if i in _MIXERS and i.name not in hot
            )
            delta = -(cup_plain + cup_hot)

        # Mixer-only cup: great for sobering
        if cup_spirits == 0 and ps.drunk_level >= 2 and delta < 0:
            score = abs(delta) * (3.0 + ps.drunk_level * 2.0) + cup_size * 1.5
            if ps.drunk_level < 2:
                score -= 10.0
            return score

        # Stuck cup (has spirit, unsellable or low-value) at high drunk:
        # known delta is safer than random take, and fills bladder for wee
        if ps.drunk_level >= 3 and delta <= 1:
            score = 5.0 - delta * 3.0  # delta=0→5, delta=1→2, delta=-1→8
            if not ps.bladder:
                score += 5.0  # Fills empty bladder → enables wee next turn
            return score

        return -20.0

    # ------------------------------------------------------------------
    #  Main action selection — pick highest-scoring action
    # ------------------------------------------------------------------

    def choose_action(
        self, gs: GameState, player_id, valid_actions: list[Action]
    ) -> Action:
        ps = gs.player_states[player_id]
        focus = self._focus_spirit(gs, ps)
        focus_ing = _SPIRIT_MAP.get(focus)

        # Safe specials take — pre-empt weighted scoring when SPECIAL tokens
        # are on the display and the take stays under the drunk cap.
        take = _safe_specials_take(gs, ps, valid_actions)
        if take:
            return take

        best_score, best_action = float("-inf"), valid_actions[0]
        for action in valid_actions:
            t = action.action_type
            if t == "sell_cup":
                s = self._score_sell(gs, ps, action, focus, player_id)
            elif t == "take_ingredients":
                s = self._score_take(gs, ps, focus_ing, player_id)
            elif t == "claim_card":
                s = self._score_claim(gs, ps, action, focus, player_id)
            elif t == "go_for_a_wee":
                s = self._score_wee(ps)
            elif t == "drink_cup":
                s = self._score_drink_cup(ps, action)
            elif t == "refresh_card_row":
                s = 2.0  # Very low priority
            else:
                s = 0.0
            if s > best_score:
                best_score, best_action = s, action

        return best_action

    # ------------------------------------------------------------------
    #  Free actions — scored use_stored_spirit selection
    # ------------------------------------------------------------------

    def choose_free_action(
        self, gs: GameState, player_id, free_actions: list[Action]
    ) -> Action | None:
        ps = gs.player_states[player_id]
        focus = self._focus_spirit(gs, ps)
        cups = CupTracker(ps)
        # Claiming is a free action: take any free claim — bonus points are
        # always above the use_stored_spirit / drink_stored_spirit ceiling
        # (which top out around ~10-65 internal score). Prefer cards that
        # synergise with focus.
        claim = _free_claim_action(
            free_actions, prefer_card_types=["specialist", "cup doubler", "karaoke"]
        )
        if claim is not None:
            return claim
        # Wipe the orders when a rival is one ingredient from serving one
        clear = _clear_orders_action(free_actions)
        if clear is not None and _worth_clearing_orders(gs, ps):
            return clear
        best_score, best_action = -1.0, None

        for fa in free_actions:
            if fa.action_type == "use_stored_spirit":
                ci = fa.params["cup_index"]
                idx = fa.params["store_card_index"]
                card = ps.cards[idx]
                spirit_ing = _SPIRIT_MAP.get(card.get("spirit_type", ""))
                if spirit_ing and cups._can_add_spirit(ci, spirit_ing):
                    score = 10.0
                    # 2nd spirit → enables 3-pt double-spirit sell
                    if (
                        cups.spirit_counts[ci] == 1
                        and cups.spirit_type[ci] == spirit_ing
                    ):
                        score += 5
                    # Cup already has a mixer → closer to sellable
                    if cups.mixer_count[ci] > 0:
                        score += 3
                    if score > best_score:
                        best_score, best_action = score, fa

            elif fa.action_type == "drink_stored_spirit":
                # Drink stored spirits to unlock high-value card claims.
                # Only worth it if: (a) enables a claim threshold, (b) drunk
                # stays manageable, (c) claim value exceeds drunk cost.
                count = fa.params["count"]
                if ps.drunk_level + count > 3:
                    continue  # Too risky
                idx = fa.params["store_card_index"]
                card = ps.cards[idx]
                spirit_name = card.get("spirit_type", "")
                spirit_ing = _SPIRIT_MAP.get(spirit_name)
                if not spirit_ing:
                    continue
                cur = sum(1 for i in ps.bladder if i == spirit_ing)
                after = cur + count
                claim_val = self._claim_unlock_value(
                    gs, ps, spirit_name, cur, after, focus
                )
                if claim_val > 0:
                    drunk_cost = count * (5 + ps.drunk_level * 3)
                    score = claim_val - drunk_cost
                    if score > best_score:
                        best_score, best_action = score, fa

        return best_action

    def _claim_unlock_value(
        self,
        gs: GameState,
        ps: PlayerState,
        spirit_name: str,
        before: int,
        after: int,
        focus: str,
    ) -> float:
        """Value of a card claim that drinking stored spirits would unlock."""
        value = 0.0
        for row in gs.card_rows:
            for card in row.cards:
                if card.card_type == "specialist" and card.spirit_type == spirit_name:
                    if before < 2 <= after and not self._has_specialist(ps, focus):
                        v = 55.0 if spirit_name == focus else 40.0
                        value = max(value, v)
                if card.card_type == "cup_doubler":
                    if before < 3 <= after and not self._has_doubler(ps):
                        value = max(value, 65.0)
                if card.card_type == "karaoke" and card.spirit_type == spirit_name:
                    if before < 2 <= after and ps.drunk_level + (after - before) >= 3:
                        kc = ps.karaoke_cards_claimed
                        v = 200.0 if kc >= 2 else (50.0 if kc >= 1 else 25.0)
                        value = max(value, v)
        return value

    # ------------------------------------------------------------------
    #  Take assignments — weighted display selection vs bag EV
    # ------------------------------------------------------------------

    def choose_take_assignments(
        self, gs: GameState, player_id, count: int
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        focus = self._focus_spirit(gs, ps)
        focus_ing = _SPIRIT_MAP.get(focus)
        cups = CupTracker(ps)
        hot = _hot_mixer_types(ps)
        threats = _opponent_threats(gs, ps)
        bag_ev = self._bag_draw_ev(gs, ps, cups, focus_ing)
        # Prefer display certainty over bag variance: accept display items
        # slightly below average bag EV (known > random)
        # Prefer display certainty more as drunk rises — bag variance is deadlier
        display_premium = 1.0 + max(0, ps.drunk_level - 1) * 1.25

        # Both displays: spirits and mixers, and the specials set aside
        items = [(ing, "display") for ing in gs.open_display] + [
            (ing, "specials") for ing in gs.specials_display
        ]
        assignments: list[dict] = []
        used: set[int] = set()
        # What each glass still needs for the order it's best placed to serve
        order_want = {ci: needs for ci, (_o, needs) in order_plans(gs, ps).items()}

        for _ in range(count):
            # Greedily pick the best remaining item (re-evaluated after each
            # pick so cup state stays accurate).
            best_val, best_idx = bag_ev - display_premium, -1
            best_disp, best_ci = "drink", None
            specials_left = Counter(
                ing
                for idx, (ing, src) in enumerate(items)
                if src == "specials" and idx not in used
            )
            for idx, (ing, _src) in enumerate(items):
                if idx in used:
                    continue
                val, disp, ci = self._eval_display_item(
                    gs,
                    ps,
                    ing,
                    cups,
                    focus_ing,
                    focus,
                    hot,
                    threats,
                    order_want,
                    specials_left,
                )
                if val > best_val:
                    best_val, best_idx, best_disp, best_ci = val, idx, disp, ci

            if best_idx < 0:
                break  # All remaining items are worse than bag draws

            ing, src = items[best_idx]
            used.add(best_idx)
            entry: dict = {
                "ingredient": ing.name,
                "source": src,
                "disposition": best_disp,
            }
            if best_disp == "cup" and best_ci is not None:
                entry["cup_index"] = best_ci
                if ing in _SPIRITS:
                    cups.add_spirit(best_ci, ing)
                elif is_special(ing):
                    cups.add_special(best_ci, ing)
                else:
                    cups.add_mixer(best_ci, ing)
                want = order_want.get(best_ci)
                if want and want.get(ing, 0) > 0:
                    want[ing] -= 1
            assignments.append(entry)

        return assignments

    def _eval_display_item(
        self,
        gs,
        ps,
        ing,
        cups,
        focus_ing,
        focus,
        hot,
        threats=None,
        order_want=None,
        specials_left=None,
    ):
        """Score a single display ingredient.

        Returns (value, disposition, cup_index).

        `threats` (dict[Ingredient, float]) adds a denial bonus for items
        opponents need. The bonus is suppressed when the only disposition
        would be a dangerous drink (e.g. drinking a spirit while drunk_level
        is high), so blocking never causes self-elimination.

        `order_want` ({cup: Counter}) adds a bonus for an ingredient a glass
        needs to serve an order; `specials_left` is what's still on the
        specials display, for judging whether a special's cocktail can be
        finished.
        """
        threat = (threats or {}).get(ing, 0.0)

        def for_order(ci) -> float:
            want = (order_want or {}).get(ci)
            return 4.0 if want and want.get(ing, 0) > 0 else 0.0

        if is_special(ing):
            others = Counter(specials_left or {})
            others[ing] -= 1
            ci = cups.best_cup_for_special(ing, available=others)
            if ci is None:
                # An order-planned cocktail glass may take it too
                ci = next(
                    (
                        c
                        for c in (0, 1)
                        if for_order(c) and cups.can_add_special(c, ing)
                    ),
                    None,
                )
            if ci is not None:
                return (9.0 + for_order(ci) + threat, "cup", ci)
            boozy = ing in BOOZY_SPECIALS
            # Drunk, one special pays for a specialist card
            if ing == _specialist_unlock(gs, ps):
                return (
                    12.0 - (3.0 + ps.drunk_level * 2.0 if boozy else 0),
                    "drink",
                    None,
                )
            # Lemon and sugar sober like a mixer, and deny whoever needs them;
            # the boozy ones cost a drunk level like a spirit.
            if boozy:
                return (-(3.0 + ps.drunk_level * 2.0) + threat, "drink", None)
            if threat > 0:
                return (1.5 + threat * 2.0, "drink", None)
            return (-2.0, "drink", None)

        if ing in _SPIRITS:
            ci = cups.best_cup_for_spirit(ing)
            if ci is not None:
                base = 8.0 if ing == focus_ing else 5.0
                return (base + threat * 1.5 + for_order(ci), "cup", ci)
            # Can't cup → must drink — weigh accumulation value against drunk cost.
            # Only allow a denial bonus when drinking is safe.
            penalty = 3.0 + ps.drunk_level * 2.0
            accum = self._spirit_accum_value(gs, ps, ing, focus)
            denial_bonus = threat * 0.5 if ps.drunk_level <= 1 else 0.0
            if accum > penalty and ps.drunk_level <= 1:
                return (accum - penalty + denial_bonus, "drink", None)
            return (-penalty + denial_bonus, "drink", None)

        if ing in _MIXERS:
            ci = cups.best_cup_for_mixer(ing)
            if ci is not None and cups.spirit_type[ci] is not None:
                return (6.0 + threat * 1.5 + for_order(ci), "cup", ci)
            base = 3.0 if ing.name in hot else 1.5
            return (base + threat * 0.8, "drink", None)

        # SPECIAL token: rolls onto the mat without raising drunk or filling
        # bladder, and unlocks 10–15 pt cocktail recipes. Each special already
        # on the mat signals committed cocktail intent — the next one is
        # increasingly valuable.
        mat_specials = len(ps.special_ingredients)
        base = 4.0 + min(mat_specials, 3) * 1.0
        return (base + threat * 0.5, "drink", None)

    def _bag_draw_ev(self, gs, ps, cups, focus_ing):
        """Expected value of a single random bag draw given current cup state."""
        # A draw never hands you a special: they go to the specials display
        drawable = [i for i in gs.bag_contents if not is_special(i)]
        if not drawable:
            return -5.0
        total = len(drawable)
        ev = 0.0
        for ing in set(drawable):
            frac = drawable.count(ing) / total
            if ing in _SPIRITS:
                ci = cups.best_cup_for_spirit(ing)
                ev += frac * (5.0 if ci is not None else -(2.0 + ps.drunk_level * 1.5))
            elif ing in _MIXERS:
                ci = cups.best_cup_for_mixer(ing)
                ev += frac * (
                    4.0
                    if (ci is not None and cups.spirit_type[ci] is not None)
                    else 1.5
                )
            else:
                ev += frac * 0.5
        return ev

    # ------------------------------------------------------------------
    #  Pending assignments (bag draws — standard optimal)
    # ------------------------------------------------------------------

    def choose_pending_assignments(
        self, gs: GameState, player_id, drawn: list[Ingredient]
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        focus = self._focus_spirit(gs, ps)
        focus_ing = _SPIRIT_MAP.get(focus)
        cups = CupTracker(ps)
        hot = _hot_mixer_types(ps)

        assignments: list[dict] = []
        spirits = [i for i in drawn if i in _SPIRITS]
        mixers = [i for i in drawn if i in _MIXERS]
        others = [i for i in drawn if i not in _SPIRITS and i not in _MIXERS]

        # Cup spirits (focus first), drink what can't be cupped
        spirits.sort(key=lambda s: 0 if s == focus_ing else 1)
        spirits_drunk_this_batch = 0
        for spirit in spirits:
            ci = cups.best_cup_for_spirit(spirit)
            if ci is not None:
                cups.add_spirit(ci, spirit)
                assignments.append(
                    {"source": "pending", "disposition": "cup", "cup_index": ci}
                )
            else:
                spirits_drunk_this_batch += 1
                assignments.append({"source": "pending", "disposition": "drink"})

        # Check total spirits drunk this turn (display + this batch)
        prev_spirits_drunk = sum(
            1 for i in gs.drunk_ingredients_this_turn if i in _SPIRITS
        )
        total_spirits_drunk = prev_spirits_drunk + spirits_drunk_this_batch

        # Cup mixers that pair with cup spirits, drink the rest.
        # Two sobering optimisations:
        #   1. Hot mixers always subtract from drunk delta (even with spirits).
        #      At drunk ≥ 3, drinking them is better than cupping.
        #   2. Plain mixers sober only when no spirits are drunk this turn.
        #      At drunk ≥ 2, drink redundant ones (cup already sellable).
        for mixer in mixers:
            ci = cups.best_cup_for_mixer(mixer)
            if ci is not None and cups.spirit_type[ci] is not None:
                already_sellable = (
                    cups.spirit_counts[ci] >= 1 and cups.mixer_count[ci] >= 1
                )
                # Hot mixers: drink at high drunk for guaranteed -1 to delta
                if mixer.name in hot and ps.drunk_level >= 3:
                    assignments.append({"source": "pending", "disposition": "drink"})
                # Plain mixers: drink when no spirits drunk & cup already sellable
                elif (
                    mixer.name not in hot
                    and total_spirits_drunk == 0
                    and ps.drunk_level >= 2
                    and already_sellable
                ):
                    assignments.append({"source": "pending", "disposition": "drink"})
                else:
                    cups.add_mixer(ci, mixer)
                    assignments.append(
                        {"source": "pending", "disposition": "cup", "cup_index": ci}
                    )
            else:
                assignments.append({"source": "pending", "disposition": "drink"})

        for _ in others:
            assignments.append({"source": "pending", "disposition": "drink"})

        return _in_drawn_order(drawn, spirits + mixers + others, assignments)


class OrderChaser(Strategy):
    """Fills the drink orders on the table.

    Each glass works toward the order it's best placed to serve (see
    order_plans): the order's spirit and mixer, a slammer's tequila, or a
    cocktail's recipe, specials included. Serves an order as soon as a glass
    matches one, and clears the orders (a free action at drunk 3+) when a
    rival is one ingredient from serving an order it can't beat them to.
    """

    name = "OrderChaser"

    def choose_action(
        self, gs: GameState, player_id: UUID, valid_actions: list[Action]
    ) -> Action:
        ps = gs.player_states[player_id]

        # Serve an order — the bonus is the point of the whole strategy
        serving = [
            a
            for a in valid_actions
            if a.action_type == "sell_cup" and a.params.get("order")
        ]
        if serving:
            return max(serving, key=lambda a: a.params.get("points", 0))

        # A finished cocktail is worth more than waiting for an order
        sell = _best_sell(valid_actions, min_pts=10)
        if sell:
            return sell

        if _should_wee(ps) or _is_in_danger(ps):
            wee = _find_action(valid_actions, "go_for_a_wee")
            if wee:
                return wee

        # Sell a glass that isn't close to an order: it frees the glass up
        plans = order_plans(gs, ps)

        def close(ci) -> bool:
            return ci in plans and sum(plans[ci][1].values()) <= 1

        idle = [
            a
            for a in valid_actions
            if a.action_type == "sell_cup"
            and not a.params.get("additional_cups")
            and not close(a.params.get("cup_index"))
            and (
                a.params.get("cup_index") not in plans or a.params.get("points", 0) >= 3
            )
            and a.params.get("points", 0) >= 1
        ]
        if idle:
            return max(idle, key=lambda a: a.params.get("points", 0))

        take = _find_action(valid_actions, "take_ingredients")
        if take and _safe_to_take(gs, ps):
            return take

        # Nothing safe to take: bank whatever sells, then wee
        sell = _best_sell(valid_actions, min_pts=1)
        if sell:
            return sell
        wee = _find_action(valid_actions, "go_for_a_wee")
        if wee:
            return wee
        if take:
            return take
        return valid_actions[0]

    def choose_free_action(
        self, gs: GameState, player_id: UUID, free_actions: list[Action]
    ) -> Action | None:
        claim = _free_claim_action(free_actions)
        if claim is not None:
            return claim
        clear = _clear_orders_action(free_actions)
        if clear is not None and _worth_clearing_orders(
            gs, gs.player_states[player_id]
        ):
            return clear
        return None

    def _cups_with_plans(self, ps: PlayerState, plans: dict) -> CupTracker:
        cups = CupTracker(ps)
        for ci, (order, _needs) in plans.items():
            if order.drink == "cocktail":
                recipe = RECIPE_BY_NAME.get(order.cocktail or "")
                if recipe is not None:
                    cups.aim_at(ci, recipe)
            else:
                cups.plain[ci] = True
        return cups

    def choose_take_assignments(
        self, gs: GameState, player_id: UUID, count: int
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        plans = order_plans(gs, ps)
        cups = self._cups_with_plans(ps, plans)
        display = list(gs.open_display)
        specials = list(gs.specials_display)
        chosen: list[dict] = []

        # Take what each planned glass needs, spirits first
        for ci, (order, needs) in plans.items():
            wanted = sorted(needs.elements(), key=lambda i: (i not in _SPIRITS, i.name))
            # A simple order pays more as a double: take a second spirit too
            if order.drink == "simple" and ps.cups[ci].base_count + len(wanted) < 4:
                spirit = _SPIRIT_MAP.get((order.spirit_type or "").upper())
                if (
                    spirit is not None
                    and cups.spirits[ci][spirit] + wanted.count(spirit) < 2
                ):
                    wanted.append(spirit)
            for ing in wanted:
                if len(chosen) >= count:
                    break
                pool = specials if is_special(ing) else display
                if ing not in pool:
                    continue
                if is_special(ing):
                    if not cups.can_add_special(ci, ing):
                        continue
                    cups.add_special(ci, ing)
                elif ing in _SPIRITS:
                    if not cups._can_add_spirit(ci, ing):
                        continue
                    cups.add_spirit(ci, ing)
                else:
                    if not cups._can_add_mixer(ci, ing):
                        continue
                    cups.add_mixer(ci, ing)
                pool.remove(ing)
                chosen.append(
                    {
                        "ingredient": ing.name,
                        "source": "specials" if is_special(ing) else "display",
                        "disposition": "cup",
                        "cup_index": ci,
                    }
                )

        return _smart_take_assignments(gs, ps, count, cups, prefix=chosen)

    def choose_pending_assignments(
        self, gs: GameState, player_id: UUID, drawn: list[Ingredient]
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        cups = self._cups_with_plans(ps, order_plans(gs, ps))
        return _smart_pending_assignments(ps, drawn, cups)


# Registry for CLI lookup
STRATEGY_CLASSES: dict[str, type[Strategy]] = {
    "random": RandomStrategy,
    "karaoke": KaraokeRusher,
    "cocktail": CocktailHunter,
    "safe": SafeSeller,
    "aggressive": AggressiveDrinker,
    "specialist": SpecialistBuilder,
    "mastermind": Mastermind,
    "orders": OrderChaser,
}


# NOTE: the ml-backed strategies (mcts, lookahead) are NOT registered here.
# Importing ml from this module would create a circular import (ml.* imports
# playtesting.strategy), and the old try/except hook silently swallowed failures
# — which is exactly how the production bots degraded to random when ml/ was
# missing from the image. Instead, those modules self-register when imported
# (see ml/__init__.py), and the app imports ml at startup so a missing ml fails
# loudly. Selectable bots are derived from STRATEGY_CLASSES, so a strategy that
# fails to load is never offered.
