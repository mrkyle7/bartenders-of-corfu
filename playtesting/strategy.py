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
from uuid import UUID

from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import MAX_CUP_INGREDIENTS, PlayerState
from app.actions import _MIXERS, _SPIRITS
from app.cocktails import VALID_PAIRINGS

from playtesting.valid_actions import Action

_SPIRIT_MAP: dict[str, Ingredient] = {
    "WHISKEY": Ingredient.WHISKEY,
    "GIN": Ingredient.GIN,
    "RUM": Ingredient.RUM,
    "TEQUILA": Ingredient.TEQUILA,
    "VODKA": Ingredient.VODKA,
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
    """
    assignments: list[dict] = []
    display_available = list(gs.open_display)
    hot = _hot_mixer_types(ps)

    # Pre-sort display: spirits we can cup first, then paired mixers,
    # then hot mixers (great to drink), then plain mixers, then specials
    def _display_priority(ing: Ingredient) -> int:
        if prefer_spirit and ing == prefer_spirit:
            return 0
        if ing in _SPIRITS:
            return 1
        if ing in _MIXERS and ing.name in hot:
            return 2
        if ing in _MIXERS:
            return 3
        return 4

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


# Registry for CLI lookup
STRATEGY_CLASSES: dict[str, type[Strategy]] = {
    "random": RandomStrategy,
    "karaoke": KaraokeRusher,
    "cocktail": CocktailHunter,
    "safe": SafeSeller,
    "aggressive": AggressiveDrinker,
    "specialist": SpecialistBuilder,
}
