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
  - No mixed spirit types

So CupTracker must be strict: never mix spirit types, never put invalid
mixers, max 2 spirits per cup.
"""

import random
from abc import ABC, abstractmethod
from collections import Counter
from uuid import UUID

from app.GameState import GameState
from app.Ingredient import Ingredient, SpecialType
from app.PlayerState import MAX_CUP_INGREDIENTS, PlayerState
from app.actions import _MIXERS, _SPIRITS
from app.cocktails import VALID_PAIRINGS, _RECIPES

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
#  Shared helpers
# ---------------------------------------------------------------------------


class CupTracker:
    """Tracks cup contents during assignment building within a single batch.

    Enforces sellability rules:
    - Max 2 spirits per cup, all same type
    - Only valid mixer pairings for the cup's spirit type
    """

    def __init__(self, ps: PlayerState):
        self.fill = [len(ps.cups[0].ingredients), len(ps.cups[1].ingredients)]
        self.spirit_counts: list[int] = [0, 0]
        self.spirit_type: list[Ingredient | None] = [None, None]
        self.mixer_count: list[int] = [0, 0]

        for ci in (0, 1):
            for ing in ps.cups[ci].ingredients:
                if ing in _SPIRITS:
                    self.spirit_counts[ci] += 1
                    if self.spirit_type[ci] is None:
                        self.spirit_type[ci] = ing
                    elif self.spirit_type[ci] != ing:
                        # Mixed spirits — cup is already ruined
                        self.spirit_type[ci] = ing  # just track latest
                elif ing in _MIXERS:
                    self.mixer_count[ci] += 1

    def can_add(self, cup_idx: int) -> bool:
        return self.fill[cup_idx] < MAX_CUP_INGREDIENTS

    def _can_add_spirit(self, cup_idx: int, spirit: Ingredient) -> bool:
        """Can this spirit be added without ruining the cup's sellability?"""
        if not self.can_add(cup_idx):
            return False
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
        st = self.spirit_type[cup_idx]
        if st is None:
            return True  # empty cup, mixer can go in (spirit comes later)
        valid = VALID_PAIRINGS.get(st, set())
        return mixer in valid

    def add_spirit(self, cup_idx: int, spirit: Ingredient):
        self.fill[cup_idx] += 1
        self.spirit_counts[cup_idx] += 1
        self.spirit_type[cup_idx] = spirit

    def add_mixer(self, cup_idx: int, mixer: Ingredient):
        self.fill[cup_idx] += 1
        self.mixer_count[cup_idx] += 1

    def any_open(self) -> int | None:
        for i in (0, 1):
            if self.can_add(i):
                return i
        return None

    def best_cup_for_spirit(self, spirit: Ingredient) -> int | None:
        """Find the best cup for this spirit, respecting sellability rules."""
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
                    opp_special_counter.get(sp, 0) >= n
                    for sp, n in r_specials.items()
                ):
                    for ing, n in r_spirits.items():
                        bump(ing, 0.7 * n)
                    for ing, n in r_mixers.items():
                        bump(ing, 0.4 * n)

        # 3. Karaoke progress — opponent close to claiming
        for spirit_name in karaoke_spirits:
            spirit = _SPIRIT_MAP.get(spirit_name)
            if spirit is None:
                continue
            in_bladder = sum(1 for i in opp.bladder if i == spirit)
            if 1 <= in_bladder <= 2:
                # Closer to 3 → stronger threat
                bump(spirit, 0.4 * in_bladder)

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
) -> list[dict]:
    """Shared smart assignment builder — returns display-only assignments.

    Picks from the open display up to `count` items. Remaining items
    will come from the bag via draw_from_bag + choose_pending_assignments.

    Core rules:
    1. Spirits → cups (respecting sellability: same type, max 2)
    2. Paired mixers → cups (only valid pairings)
    3. Other mixers → drink (sobering effect when no spirits drunk)
    4. Stops when display is exhausted (remaining come from bag)

    Within each priority class, ingredients opponents need are picked
    first as a denial play (see `_opponent_threats`).
    """
    assignments: list[dict] = []
    display_available = list(gs.open_display)
    hot = _hot_mixer_types(ps)
    threats = _opponent_threats(gs, ps)

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

    for _ in range(count):
        placed = False

        # Pass 1: preferred spirit → cup
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

        # Pass 4: drink mixers from display (sobering)
        if not placed:
            for ing in list(display_available):
                if ing in _MIXERS:
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

        # Pass 5: drink spirits from display (when spirit_to_cup=False,
        # or when no cup has room for this spirit type)
        if not placed:
            for ing in list(display_available):
                if ing in _SPIRITS:
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
) -> list[dict]:
    """Assign bag-drawn ingredients after seeing what was drawn.

    Since we know what each ingredient is, we can make optimal decisions:
    - Spirits → cup (if valid slot exists) to avoid raising drunk level
    - Mixers → drink (sobering effect when no spirits drunk in batch)
    - If no cup room for a spirit, drink it (unavoidable)
    """
    assignments: list[dict] = []

    # Separate spirits and mixers for batch-aware assignment
    spirits = [i for i in drawn if i in _SPIRITS]
    mixers = [i for i in drawn if i in _MIXERS]
    others = [i for i in drawn if i not in _SPIRITS and i not in _MIXERS]

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
        # Can't cup it (or don't want to) — drink it
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

    return assignments


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

    Needs spirits in bladder for threshold checks, so drinks spirits
    when close to claiming. Otherwise plays safe with spirits→cups.
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
        use = _find_action(free_actions, "use_stored_spirit")
        if use:
            return use
        return None

    def choose_take_assignments(
        self, gs: GameState, player_id: UUID, count: int
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        cups = CupTracker(ps)
        targets = self._target_spirits(gs)

        # Only drink spirits when safe (drunk ≤ 1) and close to claiming
        # (have 1-2 already, need 1-2 more). Otherwise play safe.
        if ps.drunk_level <= 1:
            for t in targets:
                ing = _SPIRIT_MAP.get(t)
                if ing:
                    have = sum(1 for i in ps.bladder if i == ing)
                    if 1 <= have < 3:
                        return _smart_take_assignments(
                            gs,
                            ps,
                            count,
                            cups,
                            prefer_spirit=ing,
                            spirit_to_cup=False,
                            mixer_to_cup_if_paired=False,
                        )

        return _smart_take_assignments(gs, ps, count, cups)

    def choose_pending_assignments(
        self, gs: GameState, player_id: UUID, drawn: list[Ingredient]
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        cups = CupTracker(ps)
        targets = self._target_spirits(gs)

        # If safe and close to karaoke claim, drink drawn spirits to bladder
        if ps.drunk_level <= 1:
            for t in targets:
                ing = _SPIRIT_MAP.get(t)
                if ing:
                    have = sum(1 for i in ps.bladder if i == ing)
                    if 1 <= have < 3:
                        return _smart_pending_assignments(
                            ps, drawn, cups, spirit_to_cup=False
                        )

        return _smart_pending_assignments(ps, drawn, cups)


class CocktailHunter(Strategy):
    """Builds spirits + valid mixers in cups for sellable drinks.

    Prioritises selling any sellable cup to stay alive and score.
    """

    name = "CocktailHunter"

    def choose_action(
        self, gs: GameState, player_id: UUID, valid_actions: list[Action]
    ) -> Action:
        ps = gs.player_states[player_id]

        # Sell any cup with points (keeps cups clear for new drinks)
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

    def choose_take_assignments(
        self, gs: GameState, player_id: UUID, count: int
    ) -> list[dict]:
        ps = gs.player_states[player_id]
        cups = CupTracker(ps)
        return _smart_take_assignments(gs, ps, count, cups, mixer_to_cup_if_paired=True)


class SafeSeller(Strategy):
    """Conservative: sell quickly, stay sober, wee when needed.

    Spirits → cups with valid mixers → sell immediately.
    Drinks only mixers for sobering.
    """

    name = "SafeSeller"

    def choose_action(
        self, gs: GameState, player_id: UUID, valid_actions: list[Action]
    ) -> Action:
        ps = gs.player_states[player_id]

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

        if held and focus_ing:
            return _smart_take_assignments(
                gs,
                ps,
                count,
                cups,
                prefer_spirit=focus_ing,
                mixer_to_cup_if_paired=True,
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
                    )

            # Default: safe play with preferred spirit → cups
            return _smart_take_assignments(gs, ps, count, cups, prefer_spirit=focus_ing)

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
                return _smart_pending_assignments(ps, drawn, cups, spirit_to_cup=False)

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
            (p.points for k, p in gs.player_states.items()
             if k != pid and not p.is_eliminated),
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
        if not gs.bag_contents:
            return 0.0
        return sum(1 for i in gs.bag_contents if i in _SPIRITS) / len(gs.bag_contents)

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
                    if current < 3 <= after:
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
            (p.karaoke_cards_claimed for k, p in gs.player_states.items()
             if k != pid and not p.is_eliminated),
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

        # Urgency: score faster when opponent is ahead
        score += self._urgency(gs, pid) * 15

        # Relative score gap: sell faster when falling behind
        score_gap = self._max_opp_pts(gs, pid) - ps.points
        if score_gap > 5:
            score += min(score_gap, 15)

        # Drunk pressure: sell faster to avoid taking when drunk
        if drunk >= 4:
            score += 30
        elif drunk >= 3:
            score += 15
        elif drunk >= 2:
            score += 8

        # Need cup space: bonus when both cups occupied
        if not ps.cups[0].is_empty and not ps.cups[1].is_empty:
            score += 10

        # Bladder pressure: selling frees cups, reducing future forced drinking
        bladder_fill = len(ps.bladder) / ps.bladder_capacity if ps.bladder_capacity else 1
        if bladder_fill >= 0.75:
            score += 5

        # Dead-end cup: no matching spirits left in bag/display → sell now
        ci = action.params.get("cup_index")
        if ci is not None and pts <= 1:
            from app.actions import _SPIRITS as _SP
            cup_spirit = next(
                (ing for ing in ps.cups[ci].ingredients if ing in _SP), None
            )
            if cup_spirit:
                remaining = gs.bag_contents.count(cup_spirit) + gs.open_display.count(cup_spirit)
                if remaining == 0:
                    score += 12  # No matching spirits exist — sell immediately

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

        score = 15.0  # Baseline — taking is the default action
        score += min(spirit_slots, 3) * 2.0  # Bonus for cup headroom

        # Risk penalty when cups can't absorb spirits
        if spirit_slots == 0:
            score -= 3.0 + drunk * 3.0
        elif drunk >= 3:
            score -= 3.0

        # Display quality bonus/penalty (rough estimate)
        for ing in gs.open_display:
            if ing in _SPIRITS:
                if cups.best_cup_for_spirit(ing) is not None:
                    score += 1.5  # Can cup it
                else:
                    score -= 1.0 + drunk * 0.5  # Forced to drink
            elif ing in _MIXERS:
                score += 0.5

        # Bag risk when spirit slots are exhausted
        if spirit_slots == 0:
            bag_draws = max(0, ps.take_count - len(gs.open_display))
            score -= bag_draws * self._bag_spirit_frac(gs) * (2.0 + drunk * 1.5)

        # Bladder overflow risk: taking adds items to bladder via drinking
        bladder_room = ps.bladder_capacity - len(ps.bladder)
        cup_room = sum(MAX_CUP_INGREDIENTS - cups.fill[i] for i in (0, 1))
        est_drunk = max(0, ps.take_count - cup_room)
        if est_drunk > bladder_room:
            score -= (est_drunk - bladder_room) * 8  # Wet risk

        return score

    def _score_claim(
        self, gs: GameState, ps: PlayerState, action: Action, focus: str, pid
    ) -> float:
        desc = action.description.lower()
        params = action.params
        has_spec = self._has_specialist(ps, focus)
        has_dbl = self._has_doubler(ps)

        score = 0.0
        if "cup doubler" in desc:
            score = 65.0
            if has_spec:
                score += 20  # Specialist + doubler combo → 8-pt sells
            ci = params.get("cup_index", 0)
            focus_ing = _SPIRIT_MAP.get(focus)
            if focus_ing and any(i == focus_ing for i in ps.cups[ci].ingredients):
                score += 10  # Place on focus cup
        elif "specialist" in desc:
            score = 55.0
            if has_dbl:
                score += 15
            if focus.lower() in desc:
                score += 15  # Matches focus spirit
        elif "karaoke" in desc:
            kc = ps.karaoke_cards_claimed
            if kc >= 2:
                return 200.0  # Instant win — always take this
            score = 50.0 + self._urgency(gs, pid) * 20 if kc == 1 else 25.0
        elif "store" in desc:
            card_id = params.get("card_id")
            is_focus = any(
                card.spirit_type == focus
                for row in gs.card_rows
                for card in row.cards
                if card.id == card_id
            )
            score = 40.0 if is_focus else (18.0 if ps.drunk_level < 3 else 8.0)
        elif "refresher" in desc:
            score = 22.0
            if ps.drunk_level >= 2:
                score += 8
        else:
            score = 10.0

        # Pre-wee bonus: claim before weeing flushes bladder spirits
        overflow = len(ps.bladder) + ps.take_count - ps.bladder_capacity
        if overflow > 0:
            score += min(overflow * 5, 20)

        return score

    def _score_wee(self, ps: PlayerState) -> float:
        overflow = len(ps.bladder) + ps.take_count - ps.bladder_capacity
        bladder_fill = len(ps.bladder) / ps.bladder_capacity if ps.bladder_capacity else 1

        if overflow >= 3:
            score = 80.0
        elif overflow >= 1:
            score = 55.0
        elif overflow == 0:
            score = 38.0
        elif overflow == -1:
            score = 22.0
        elif bladder_fill >= 0.75:
            score = 12.0  # Proactive wee
        else:
            score = 3.0

        # Conserve last toilet token — only wee in true emergencies
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
                    if cups.spirit_counts[ci] == 1 and cups.spirit_type[ci] == spirit_ing:
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
        self, gs: GameState, ps: PlayerState,
        spirit_name: str, before: int, after: int, focus: str,
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
                    if before < 3 <= after:
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

        display = list(gs.open_display)
        assignments: list[dict] = []
        used: set[int] = set()

        for _ in range(count):
            # Greedily pick the best remaining display item (re-evaluated
            # after each pick so cup state stays accurate).
            best_val, best_idx = bag_ev - display_premium, -1
            best_disp, best_ci = "drink", None
            for idx, ing in enumerate(display):
                if idx in used:
                    continue
                val, disp, ci = self._eval_display_item(
                    gs, ps, ing, cups, focus_ing, focus, hot, threats,
                )
                if val > best_val:
                    best_val, best_idx, best_disp, best_ci = val, idx, disp, ci

            if best_idx < 0:
                break  # All remaining display items are worse than bag draws

            ing = display[best_idx]
            used.add(best_idx)
            entry: dict = {
                "ingredient": ing.name,
                "source": "display",
                "disposition": best_disp,
            }
            if best_disp == "cup" and best_ci is not None:
                entry["cup_index"] = best_ci
                if ing in _SPIRITS:
                    cups.add_spirit(best_ci, ing)
                else:
                    cups.add_mixer(best_ci, ing)
            assignments.append(entry)

        return assignments

    def _eval_display_item(
        self, gs, ps, ing, cups, focus_ing, focus, hot, threats=None,
    ):
        """Score a single display ingredient.

        Returns (value, disposition, cup_index).

        `threats` (dict[Ingredient, float]) adds a denial bonus for items
        opponents need. The bonus is suppressed when the only disposition
        would be a dangerous drink (e.g. drinking a spirit while drunk_level
        is high), so blocking never causes self-elimination.
        """
        threat = (threats or {}).get(ing, 0.0)

        if ing in _SPIRITS:
            ci = cups.best_cup_for_spirit(ing)
            if ci is not None:
                base = 8.0 if ing == focus_ing else 5.0
                return (base + threat * 1.5, "cup", ci)
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
                return (6.0 + threat * 1.5, "cup", ci)
            base = 3.0 if ing.name in hot else 1.5
            return (base + threat * 0.8, "drink", None)

        # SPECIAL token
        return (0.5 + threat * 0.5, "drink", None)

    def _bag_draw_ev(self, gs, ps, cups, focus_ing):
        """Expected value of a single random bag draw given current cup state."""
        if not gs.bag_contents:
            return -5.0
        total = len(gs.bag_contents)
        ev = 0.0
        for ing in set(gs.bag_contents):
            frac = gs.bag_contents.count(ing) / total
            if ing in _SPIRITS:
                ci = cups.best_cup_for_spirit(ing)
                ev += frac * (5.0 if ci is not None else -(2.0 + ps.drunk_level * 1.5))
            elif ing in _MIXERS:
                ci = cups.best_cup_for_mixer(ing)
                ev += frac * (4.0 if (ci is not None and cups.spirit_type[ci] is not None) else 1.5)
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
        spirits.sort(key=lambda s: (0 if s == focus_ing else 1))
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

        return assignments


# Registry for CLI lookup
STRATEGY_CLASSES: dict[str, type[Strategy]] = {
    "random": RandomStrategy,
    "karaoke": KaraokeRusher,
    "cocktail": CocktailHunter,
    "safe": SafeSeller,
    "aggressive": AggressiveDrinker,
    "specialist": SpecialistBuilder,
    "mastermind": Mastermind,
}
