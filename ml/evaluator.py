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

All tunable weights live in the ``EvalWeights`` dataclass below. Bundling them
(instead of module globals) lets *multiple* weight sets coexist in one process,
so the gauntlet can pit a candidate against frozen previous versions of this very
bot as well as Mastermind (see ``ml/versions.py`` and ``ml/gauntlet.py``).
Tuning is gated by win rate, never by eyeballing proxy stats.
"""

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import PlayerState
from app.actions import SCORE_TO_WIN
from app.cocktails import _MIXERS, _RECIPES, _SPIRITS, drink_points

from ml.cocktail import best_cocktail

# --- Terminal overrides ---------------------------------------------------
# Not version-tuned: a win is a win regardless of which weight set is playing.
WIN_VALUE = 1000.0
LOSS_VALUE = -1000.0


@dataclass(frozen=True)
class EvalWeights:
    """A single bot "personality": every weight the evaluator trades off.

    One frozen instance == one tunable version of the lookahead bot. Defaults
    are the current champion weights; ``ml/versions.py`` pins named snapshots so
    future tuning can be gauntletted against them for progress / no-regression.
    """

    # Potential weights (points-equivalent).
    points: float = 1.0  # one realized point == one unit
    karaoke_card: float = 6.0  # each karaoke card gives +5 pts; ongoing rarity value
    near_karaoke_win: float = 25.0  # holding 2 karaoke cards: one claim from a win

    # Cup potential: realizable sale value of what's in each cup, plus progress
    # toward a high-value (cocktail / doubled) sale that isn't complete yet.
    cup_sell: float = 0.7
    cup_progress: float = 1.0
    # Cocktail knowledge: reward a cup that is a few ingredients from completing a
    # reachable cocktail recipe (10-15 pts, exempt from the 2-spirit cap). Kept at
    # 0.0 — the experiment is documented in _cocktail_progress; enabling it (any
    # weight 0.3-1.0) regressed the gauntlet because the search holds cups it can't
    # finish (disposition is delegated to Mastermind, which doesn't aim at
    # recipes). The term stays available for the disposition-aware follow-up.
    cocktail_progress: float = 0.0

    special_mat: float = 1.2  # option value of an unused special on the mat (caps)

    # Ongoing engine value of *held* cards (their claim points already counted).
    specialist: float = 4.0  # +2 per matching non-cocktail sell, repeatedly
    doubler: float = 5.0  # doubles a non-cocktail cup, repeatedly
    store: float = 2.5  # spirit bank: flexibility + protects spirits from a wee
    refresher: float = 1.5

    # Acquisition pull: how badly the search should *want* to set up a not-yet-
    # held engine card. Deliberately larger than the held-card weight above,
    # because a doubler/specialist compounds over every future sale — the lever
    # the bot was missing when it walked past unclaimed doublers all game.
    doubler_acquire: float = 11.0
    specialist_acquire: float = 7.0
    karaoke_acquire: float = 8.0

    # Card-threshold proximity. ``reach`` is how many matching ingredients away
    # a card can be and still register (a from-scratch doubler needs 3 spirits,
    # so reach 2 made doublers invisible). ``discount`` falls off per missing
    # step; gentle (0.6) so a 3-away doubler still outweighs the drunk cost of
    # drinking toward it. ``safe_drunk_cap`` stops the lure pushing past a safe
    # drunk level — weeing only sobers one level and shrinks bladder capacity,
    # so a reckless doubler chase trades reliable points for self-elimination.
    threshold: float = 1.0
    threshold_reach: int = 3
    threshold_discount: float = 0.6
    safe_drunk_cap: int = 3

    # Safety: convex penalties near the elimination cliffs. drunk_level 0..5; a
    # spirit drink at 5 is fatal and take_count = drunk + 3, so high drunk also
    # forces large dangerous takes. Penalties ramp well before the cliff so the
    # search manages drunk/bladder proactively. ``bladder_penalty_by_room`` is
    # indexed by remaining room (capacity - len(bladder)); rooms beyond it = 0.
    drunk_penalty: tuple[float, ...] = (0.0, 0.5, 2.5, 7.0, 16.0, 32.0)
    bladder_penalty_by_room: tuple[float, ...] = (28.0, 12.0, 5.0, 2.0)


# The live champion weights. ``ml/versions.py`` imports this as the latest entry
# in its registry; production and the bare ``lookahead`` strategy use it.
# NOTE: cocktail_progress stays 0.0 here — enabling it regressed the gauntlet
# (see _cocktail_progress). The capability is kept, off, for future work.
DEFAULT_WEIGHTS = EvalWeights()


_SPIRIT_NAME_TO_ING = {i.name: i for i in _SPIRITS}


def _bladder_spirit_counts(ps: PlayerState) -> Counter:
    return Counter(i for i in ps.bladder if i in _SPIRITS)


def _bladder_mixer_counts(ps: PlayerState) -> Counter:
    return Counter(i for i in ps.bladder if i in _MIXERS)


def _best_cup_sale(ps: PlayerState, cup) -> int:
    """Best points obtainable by selling this cup right now.

    Considers cocktails (if the mat holds the required specials), the cup
    doubler, and the specialist bonus. Returns 0 if nothing is sellable. This is
    raw game scoring — no evaluator weights involved.
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


def _cocktail_progress(gs: GameState, ps: PlayerState) -> float:
    """Expected value of this player's best cocktail opportunity.

    Delegates to ``ml.cocktail.best_cocktail``: P(complete) * (cocktail points - a
    normal sale), shared with the bot's disposition so search and play agree. It's
    a value, not a rule — the search weighs it against safety, the cup's lost sale
    value when stranded, and the opponent gap, so *when* to chase a cocktail (and
    which) falls out of the evaluation rather than hand-written conditions.
    """
    return best_cocktail(gs, ps)[1]


def _threshold_proximity(
    gs: GameState, ps: PlayerState, w: EvalWeights = DEFAULT_WEIGHTS
) -> float:
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
                    w.karaoke_acquire,
                    True,
                )
            elif ct == "specialist":
                need, have, worth, spirit_cost = (
                    2,
                    _have_spirit(spirit_counts, card.spirit_type),
                    w.specialist_acquire,
                    True,
                )
            elif ct == "cup_doubler":
                # Needs 3 of *some* spirit in bladder; use the player's richest.
                need, have, worth, spirit_cost = (
                    3,
                    max(spirit_counts.values(), default=0),
                    w.doubler_acquire,
                    True,
                )
            elif ct == "store":
                need, have, worth, spirit_cost = (
                    1,
                    _have_spirit(spirit_counts, card.spirit_type),
                    w.store,
                    True,
                )
            elif ct == "refresher":
                # Mixers sober the player, so this is always safe to chase.
                need, have, worth, spirit_cost = (
                    2,
                    mixer_counts.get(_mixer_ing(card.mixer_type), 0),
                    w.refresher,
                    False,
                )
            else:
                continue

            missing = need - have
            if missing <= 0:
                continue  # already claimable — the search sees the claim directly
            if missing > w.threshold_reach:
                continue  # too far to count as "proximity"
            # Don't lure into drinking spirits past a safe drunk level: claiming
            # this needs `missing` more spirits, each adding a drunk level.
            if spirit_cost and ps.drunk_level + missing > w.safe_drunk_cap:
                continue
            # Closer (and higher-worth) reachable cards score more. The discount
            # is gentle on purpose: with a steep 1/(1+m) falloff a 3-away doubler
            # scored too little to overcome the drunk cost of drinking toward it,
            # so the search never started climbing.
            best = max(best, worth / (1.0 + w.threshold_discount * missing))
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


def _safety_penalty(ps: PlayerState, w: EvalWeights = DEFAULT_WEIGHTS) -> float:
    drunk = max(0, min(ps.drunk_level, 5))
    penalty = w.drunk_penalty[drunk]
    room = ps.bladder_capacity - len(ps.bladder)
    if 0 <= room < len(w.bladder_penalty_by_room):
        penalty += w.bladder_penalty_by_room[room]
    return penalty


def _card_engine_value(ps: PlayerState, w: EvalWeights = DEFAULT_WEIGHTS) -> float:
    value = 0.0
    for cd in ps.cards:
        ct = cd.get("card_type")
        if ct == "specialist":
            value += w.specialist
        elif ct == "cup_doubler":
            value += w.doubler
        elif ct == "store":
            value += w.store
            # Stored spirits are bankable future cup fillers / claim fodder.
            value += 0.5 * len(cd.get("stored_spirits", []))
        elif ct == "refresher":
            value += w.refresher
    return value


def player_potential(
    gs: GameState,
    ps: PlayerState,
    w: EvalWeights = DEFAULT_WEIGHTS,
    *,
    full: bool,
) -> float:
    """Estimate a player's total position value (points-equivalent).

    ``full`` enables the more expensive terms (cup progress, threshold
    proximity); opponents are valued with the cheaper core terms only.
    """
    value = ps.points * w.points
    value += ps.karaoke_cards_claimed * w.karaoke_card
    if ps.karaoke_cards_claimed >= 2:
        value += w.near_karaoke_win

    for cup in ps.cups:
        value += _best_cup_sale(ps, cup) * w.cup_sell

    value += min(len(ps.special_ingredients), 4) * w.special_mat
    value += _card_engine_value(ps, w)
    value -= _safety_penalty(ps, w)

    if full:
        for cup in ps.cups:
            value += _cup_progress(ps, cup) * w.cup_progress
        if w.cocktail_progress:
            value += _cocktail_progress(gs, ps) * w.cocktail_progress
        value += _threshold_proximity(gs, ps, w) * w.threshold

    return value


def evaluate(gs: GameState, player_id: UUID, w: EvalWeights = DEFAULT_WEIGHTS) -> float:
    """Scalar value of ``gs`` for ``player_id`` — higher is better.

    Terminal/elimination states are clamped to large +/- values; otherwise the
    score is this player's potential minus the strongest live opponent's.
    """
    if gs.winner is not None:
        return WIN_VALUE if gs.winner == player_id else LOSS_VALUE

    me = gs.player_states.get(player_id)
    if me is None or me.is_eliminated:
        return LOSS_VALUE

    my_value = player_potential(gs, me, w, full=True)

    best_opp = None
    for pid, opp in gs.player_states.items():
        if pid == player_id or opp.is_eliminated:
            continue
        ov = player_potential(gs, opp, w, full=False)
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
