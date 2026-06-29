"""Static state evaluator for Bartenders of Corfu.

The previous bots scored only *immediate* actions (Mastermind) or averaged
noisy full-game rollouts (the flat MCTS). Neither could "see" multi-turn plans
like drinking the right spirits to unlock a high-value card, or building a cup
toward a cocktail. This module gives a shallow search a *potential* estimate of
a position so those plans show up as higher-valued leaf states.

``evaluate(gs, player_id)`` returns a scalar where higher is better for
``player_id``. It is the player's potential minus the strongest opponent's
potential, with hard overrides for terminal/elimination states. The scale is
roughly "points-equivalent": a cocktail (10 pts) and a near-fatal drunk level
are deliberately the same order of magnitude so the search trades them off.

All weights live at the top of the file so tuning happens in one place, gated
by ml/gauntlet.py (win rate), never by eyeballing proxy stats.
"""

from collections import Counter
from uuid import UUID

from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import PlayerState
from app.actions import SCORE_TO_WIN
from app.cocktails import _MIXERS, _RECIPES, _SPIRITS, drink_points

# --- Terminal overrides ---------------------------------------------------
WIN_VALUE = 1000.0
LOSS_VALUE = -1000.0

# --- Potential weights (points-equivalent) --------------------------------
POINTS_W = 1.0  # one realized point == one unit
KARAOKE_CARD_W = 6.0  # each karaoke card already gives +5 pts; ongoing rarity value
NEAR_KARAOKE_WIN = 25.0  # holding 2 karaoke cards: one claim from instant win

# Cup potential: the realizable sale value of what's currently in each cup.
CUP_SELL_W = 0.7
# Progress toward a high-value (cocktail / doubled) sale that isn't complete yet.
CUP_PROGRESS_W = 1.0

SPECIAL_MAT_W = 1.2  # option value of an unused special on the mat (caps out)

# Ongoing engine value of held cards (their claim points are already counted).
SPECIALIST_W = 4.0  # +2 per matching non-cocktail sell, repeatedly
DOUBLER_W = 5.0  # doubles a non-cocktail cup, repeatedly
STORE_W = 2.5  # spirit bank: flexibility + protects spirits from a wee
REFRESHER_W = 1.5

# Acquisition pull: how badly the search should *want* to set up a not-yet-held
# engine card. This is deliberately larger than the static held-card weight
# above, because a doubler/specialist compounds over every future sale — a held
# doubler turned ~3-pt cups into 6-8 pt cups for the rest of a real game, which
# bots kept losing for lack of. The static *_W is the residual value once held;
# these drive the bot to drink the spirits needed to claim one in the first
# place (the lever it was missing: doublers sat unclaimed in the row all game).
DOUBLER_ACQUIRE_W = 11.0
SPECIALIST_ACQUIRE_W = 7.0
KARAOKE_ACQUIRE_W = 8.0

# Card-threshold proximity: a nudge toward unlocking a claimable card soon.
# Still safety-gated (see SAFE_DRUNK_CAP) so the bot won't chase a card straight
# off the elimination cliff — but no longer so timid that it never builds the
# engine that actually wins games.
THRESHOLD_W = 1.0
# Reach of the proximity lure: a card up to this many matching ingredients away
# still registers. A from-scratch cup-doubler needs 3 spirits, so a reach of 2
# (the old value) made doublers invisible until you already had one in hand.
THRESHOLD_REACH = 3
# Don't let the lure push us toward a drunk level above this by drinking spirits.
# Kept at 3: weeing only sobers one level *and* permanently shrinks bladder
# capacity, so a drunk-3 doubler chase is slow and costly to unwind. The bot
# should prefer engine cards it can reach without crossing into the danger zone,
# not drink blindly toward one (which just trades reliable cup points for
# self-elimination risk — the gauntlet punishes the latter hard).
SAFE_DRUNK_CAP = 3

# --- Safety (convex penalties near the elimination cliffs) ----------------
# drunk_level 0..5; a spirit drink at 5 is fatal, and take_count = drunk + 3, so
# high drunk also forces large, dangerous takes. Penalties ramp up well before
# the cliff so the search manages drunk/bladder proactively, like a human does.
_DRUNK_PENALTY = [0.0, 0.5, 2.5, 7.0, 16.0, 32.0]
# Bladder penalty keyed by remaining room (capacity - len(bladder)).
_BLADDER_PENALTY_BY_ROOM = {0: 28.0, 1: 12.0, 2: 5.0, 3: 2.0}


_SPIRIT_NAME_TO_ING = {i.name: i for i in _SPIRITS}


def _bladder_spirit_counts(ps: PlayerState) -> Counter:
    return Counter(i for i in ps.bladder if i in _SPIRITS)


def _bladder_mixer_counts(ps: PlayerState) -> Counter:
    return Counter(i for i in ps.bladder if i in _MIXERS)


def _best_cup_sale(ps: PlayerState, cup) -> int:
    """Best points obtainable by selling this cup right now.

    Considers cocktails (if the mat holds the required specials), the cup
    doubler, and the specialist bonus. Returns 0 if nothing is sellable.
    """
    ingredients = cup.ingredients
    if not ingredients:
        return 0

    best = 0

    # Non-cocktail sale (no declared specials). drink_points already applies the
    # 2-spirit cap; we apply doubler + specialist the same way sell_cup does.
    base = drink_points(ingredients, [])
    if base is not None:
        pts = base
        if cup.has_cup_doubler:
            pts *= 2
        specialist_types = {
            cd.get("spirit_type")
            for cd in ps.cards
            if cd.get("card_type") == "specialist" and cd.get("spirit_type")
        }
        cup_spirit_types = {i.name for i in ingredients if i in _SPIRITS}
        pts += len(specialist_types & cup_spirit_types) * 2
        best = max(best, pts)

    # Cocktail sales: match the cup against each recipe and check the mat has the
    # specials. Cocktails ignore doubler/specialist.
    cup_spirits = Counter(i for i in ingredients if i in _SPIRITS)
    cup_mixers = Counter(i for i in ingredients if i in _MIXERS)
    mat = Counter(ps.special_ingredients)
    for r_spirits, r_mixers, r_specials, pts, _name in _RECIPES:
        if cup_spirits != r_spirits or cup_mixers != r_mixers:
            continue
        if all(mat.get(st.value, 0) >= n for st, n in r_specials.items()):
            best = max(best, pts)

    return best


def _cup_progress(ps: PlayerState, cup) -> float:
    """Heuristic value for a partially-built, not-yet-sellable cup.

    Rewards cups heading somewhere valuable so the search keeps building them
    instead of dumping 1-pt drinks: a started cup with room, especially with a
    doubler attached or specials banked that fit a cocktail.
    """
    ings = cup.ingredients
    if not ings or cup.is_full:
        return 0.0

    spirits = [i for i in ings if i in _SPIRITS]
    if not spirits:
        return 0.0  # mixer-only partial cup has little standalone potential

    score = 0.0
    spirit_types = {i for i in spirits}

    # A doubler cup is worth building toward a double-spirit drink (3 -> 6 pts).
    if cup.has_cup_doubler:
        score += 2.0

    # Single spirit type with room to become a double (3-pt) drink.
    if len(spirit_types) == 1 and len(spirits) == 1 and not cup.is_full:
        score += 1.0

    # Specials banked that could turn this into a cocktail: small nudge per
    # special on the mat while the cup still has a spirit.
    score += 0.5 * min(len(ps.special_ingredients), 2)
    return score


def _threshold_proximity(gs: GameState, ps: PlayerState) -> float:
    """Lure toward a claimable card the player is close to affording.

    Card costs are *threshold checks on bladder contents* (not consumed), so
    being one matching spirit/mixer away from a valuable card is worth setting
    up. Returns the value of the single best reachable card, discounted by how
    many more matching ingredients are needed.
    """
    spirit_counts = _bladder_spirit_counts(ps)
    mixer_counts = _bladder_mixer_counts(ps)

    best = 0.0
    for row in gs.card_rows:
        for card in row.cards:
            ct = card.card_type
            if ct == "karaoke":
                need, have, worth, spirit_cost = (
                    3,
                    _have_spirit(spirit_counts, card.spirit_type),
                    KARAOKE_ACQUIRE_W,
                    True,
                )
            elif ct == "specialist":
                need, have, worth, spirit_cost = (
                    2,
                    _have_spirit(spirit_counts, card.spirit_type),
                    SPECIALIST_ACQUIRE_W,
                    True,
                )
            elif ct == "cup_doubler":
                # Needs 3 of *some* spirit in bladder; use the player's richest.
                need, have, worth, spirit_cost = (
                    3,
                    max(spirit_counts.values(), default=0),
                    DOUBLER_ACQUIRE_W,
                    True,
                )
            elif ct == "store":
                need, have, worth, spirit_cost = (
                    1,
                    _have_spirit(spirit_counts, card.spirit_type),
                    STORE_W,
                    True,
                )
            elif ct == "refresher":
                # Mixers sober the player, so this is always safe to chase.
                need, have, worth, spirit_cost = (
                    2,
                    mixer_counts.get(_mixer_ing(card.mixer_type), 0),
                    REFRESHER_W,
                    False,
                )
            else:
                continue

            missing = need - have
            if missing <= 0:
                continue  # already claimable — the search sees the claim directly
            if missing > THRESHOLD_REACH:
                continue  # too far to count as "proximity"
            # Don't lure into drinking spirits past a safe drunk level: claiming
            # this needs `missing` more spirits, each adding a drunk level.
            if spirit_cost and ps.drunk_level + missing > SAFE_DRUNK_CAP:
                continue
            # Closer (and higher-worth) reachable cards score more. The discount
            # is gentle (0.6 per missing step) on purpose: with the old 1/(1+m)
            # falloff a 3-away doubler scored too little to overcome the drunk
            # cost of drinking toward it, so the search never started climbing.
            best = max(best, worth / (1.0 + 0.6 * missing))
    return best


def _have_spirit(spirit_counts: Counter, spirit_type: str | None) -> int:
    if not spirit_type:
        return 0
    ing = _SPIRIT_NAME_TO_ING.get(spirit_type)
    return spirit_counts.get(ing, 0) if ing else 0


def _mixer_ing(mixer_type: str | None) -> Ingredient | None:
    if not mixer_type:
        return None
    try:
        return Ingredient[mixer_type]
    except KeyError:
        return None


def _safety_penalty(ps: PlayerState) -> float:
    drunk = max(0, min(ps.drunk_level, 5))
    penalty = _DRUNK_PENALTY[drunk]
    room = ps.bladder_capacity - len(ps.bladder)
    penalty += _BLADDER_PENALTY_BY_ROOM.get(room, 0.0)
    return penalty


def _card_engine_value(ps: PlayerState) -> float:
    value = 0.0
    for cd in ps.cards:
        ct = cd.get("card_type")
        if ct == "specialist":
            value += SPECIALIST_W
        elif ct == "cup_doubler":
            value += DOUBLER_W
        elif ct == "store":
            value += STORE_W
            # Stored spirits are bankable future cup fillers / claim fodder.
            value += 0.5 * len(cd.get("stored_spirits", []))
        elif ct == "refresher":
            value += REFRESHER_W
    return value


def player_potential(gs: GameState, ps: PlayerState, *, full: bool) -> float:
    """Estimate a player's total position value (points-equivalent).

    ``full`` enables the more expensive terms (cup progress, threshold
    proximity); opponents are valued with the cheaper core terms only.
    """
    value = ps.points * POINTS_W
    value += ps.karaoke_cards_claimed * KARAOKE_CARD_W
    if ps.karaoke_cards_claimed >= 2:
        value += NEAR_KARAOKE_WIN

    for cup in ps.cups:
        value += _best_cup_sale(ps, cup) * CUP_SELL_W

    value += min(len(ps.special_ingredients), 4) * SPECIAL_MAT_W
    value += _card_engine_value(ps)
    value -= _safety_penalty(ps)

    if full:
        for cup in ps.cups:
            value += _cup_progress(ps, cup) * CUP_PROGRESS_W
        value += _threshold_proximity(gs, ps) * THRESHOLD_W

    return value


def evaluate(gs: GameState, player_id: UUID) -> float:
    """Scalar value of ``gs`` for ``player_id`` — higher is better.

    Terminal/elimination states are clamped to large +/- values; otherwise the
    score is this player's potential minus the strongest live opponent's.
    """
    if gs.winner is not None:
        return WIN_VALUE if gs.winner == player_id else LOSS_VALUE

    me = gs.player_states.get(player_id)
    if me is None or me.is_eliminated:
        return LOSS_VALUE

    my_value = player_potential(gs, me, full=True)

    best_opp = None
    for pid, opp in gs.player_states.items():
        if pid == player_id or opp.is_eliminated:
            continue
        ov = player_potential(gs, opp, full=False)
        if best_opp is None or ov > best_opp:
            best_opp = ov

    if best_opp is None:
        # All opponents eliminated and the game hasn't ended yet — winning.
        return WIN_VALUE / 2

    # A win is worth more the closer we are to the score cap; keep the leading
    # term as the head-to-head potential gap.
    lead = my_value - best_opp
    progress = me.points / SCORE_TO_WIN
    return lead + progress * 5.0
