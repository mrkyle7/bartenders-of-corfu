"""Versioned snapshots of the lookahead bot's evaluator weights.

Each entry is a *frozen* ``EvalWeights``: an immutable record of a bot version
that once passed the gauntlet. Future tuning is gauntletted against the latest
registered version (not just Mastermind), so every change has to **show progress
and prove no regression** against the bot it replaces — the blind spot the
Mastermind-only gauntlet had (it can't reward the engine play that beats a human
in a long game).

Adding a version
----------------
1. Tune ``ml/evaluator.py``'s ``DEFAULT_WEIGHTS`` until
   ``python -m ml.gauntlet --regression`` shows the new weights beat **both**
   Mastermind and the current ``LATEST`` version below.
2. Append a new entry here with explicit numbers (copy ``DEFAULT_WEIGHTS``'
   fields). **Never edit an existing entry** — versions are immutable history.
   The newest entry is automatically ``LATEST``.

The keys (``v0``, ``v1`` …) are stable ids usable in gauntlet specs, e.g.
``lookahead:v1``. Values must be explicit and must NOT reference
``DEFAULT_WEIGHTS``, so they stay frozen as the live defaults move on.
"""

from ml.evaluator import EvalWeights

LOOKAHEAD_VERSIONS: dict[str, EvalWeights] = {
    # v0 — the lookahead that first shipped this module, *before* the
    # engine-acquisition tuning. It valued cards in the proximity lure at their
    # bare held-card weight, reached only 2 ingredients, and discounted distance
    # steeply — so a from-scratch cup-doubler (needs 3 spirits) was invisible and
    # the bot walked past unclaimed doublers all game, losing to a human 28-40.
    # Kept so we can demonstrate the progress the next version made.
    "v0": EvalWeights(
        doubler_acquire=5.0,  # was DOUBLER_W, reused directly in the lure
        specialist_acquire=4.0,  # was SPECIALIST_W
        karaoke_acquire=8.0,  # was a hardcoded 8.0
        threshold_reach=2,
        threshold_discount=1.0,
    ),
    # v1 — engine-acquisition tuning (2026-06). Dedicated acquire pull for
    # doubler/specialist/karaoke cards, reach 3, gentle 0.6 distance discount.
    # Safety penalties deliberately unchanged (softening them regressed the
    # gauntlet via self-elimination). This is the live DEFAULT_WEIGHTS; pinned
    # explicitly here so it stays frozen as defaults move.
    #
    # Honest scorecard (the versioned gauntlet's first real finding): v1 is a
    # *specialisation toward the production, modes-on regime*, not a strict
    # upgrade over v0.
    #   - vs Mastermind, all modes: 86.0% -> 88.5% win, self-elim 13.5% -> 11.5%
    #     (clear progress in the regime where the production loss happened).
    #   - vs Mastermind, NO modes: 80.8% -> 75.8% (regressed — when claim is a
    #     main action the engine chase costs tempo).
    #   - v1 vs v0 head-to-head, all modes (120 games, post runner-draw fix):
    #     51.7%, CI [42.8%, 60.4%] — a slight edge that isn't yet significant,
    #     but v1 self-eliminates less (8.3% vs 13.3%). So a modest real upgrade,
    #     not the sidegrade the buggy runner first suggested (~46% w/ 32% draws).
    # The bar for v2 is to pull *significantly* ahead of v1 head-to-head without
    # giving back the no-modes ground.
    "v1": EvalWeights(
        doubler_acquire=11.0,
        specialist_acquire=7.0,
        karaoke_acquire=8.0,
        threshold_reach=3,
        threshold_discount=0.6,
    ),
}

# The newest registered version (last inserted). New tuning is gated against it.
# Deliberately the last entry of the *progression* dict above — experimental
# alternates (below) are not part of the line and never become `latest`.
LATEST_VERSION = next(reversed(LOOKAHEAD_VERSIONS))

# Experimental / alternate builds — selectable (e.g. `lookahead:cocktail`) and
# gauntlet-comparable, but NOT in the progression and NOT the default, because
# they don't beat `latest` across the board. Kept here so the work is first-class
# and runnable instead of buried behind a hand-edited weight.
ALT_BUILDS: dict[str, EvalWeights] = {
    # cocktail — engine-acquisition (v1) PLUS recipe-directed cocktail building,
    # driven by *value and probability*, not hand-written rules (see ml/cocktail.py
    # best_cocktail: EV = P(complete) * (points - a normal sale); the search weighs
    # it via cocktail_progress, so "only when behind", "don't strand a cup" and
    # "play safe" emerge from the evaluation rather than if-statements). It builds
    # real cocktails but still trails on the gauntlet — ~76% vs Mastermind (v1
    # ~90%) and ~46% vs v1 head-to-head; a weight sweep (0.3/0.5/1.0) only ever
    # makes it worse, so the ceiling is structural: the forced ~5-item take economy
    # makes multi-take builds inefficient, and the cocktails that DON'T need
    # building (Margarita/Manhattan/Cosmopolitan) are free declare-at-sale upgrades
    # v1 already takes. Off by default; flip cocktail_progress into DEFAULT_WEIGHTS
    # to promote it.
    "cocktail": EvalWeights(
        doubler_acquire=11.0,
        specialist_acquire=7.0,
        karaoke_acquire=8.0,
        threshold_reach=3,
        threshold_discount=0.6,
        cocktail_progress=0.5,
    ),
}


def get_version(version: str) -> EvalWeights:
    """Resolve a version id (``"v1"``, ``"latest"``, or an alt build) to weights."""
    key = LATEST_VERSION if version.lower() == "latest" else version
    if key in LOOKAHEAD_VERSIONS:
        return LOOKAHEAD_VERSIONS[key]
    if key in ALT_BUILDS:
        return ALT_BUILDS[key]
    raise ValueError(
        f"Unknown lookahead version {version!r}. Known: "
        f"{', '.join((*LOOKAHEAD_VERSIONS, *ALT_BUILDS))}, latest"
    )
