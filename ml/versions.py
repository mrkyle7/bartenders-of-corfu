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
LATEST_VERSION = next(reversed(LOOKAHEAD_VERSIONS))


def get_version(version: str) -> EvalWeights:
    """Resolve a version id (e.g. ``"v1"``, or ``"latest"``) to its weights."""
    key = LATEST_VERSION if version.lower() == "latest" else version
    try:
        return LOOKAHEAD_VERSIONS[key]
    except KeyError:
        raise ValueError(
            f"Unknown lookahead version {version!r}. "
            f"Known: {', '.join(LOOKAHEAD_VERSIONS)}, latest"
        ) from None
