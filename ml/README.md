# Bots, evaluation, and how to make them stronger

This document is the entry point for anyone (human or agent) picking up the bot
work later. It explains how the bots are wired, how we decide one is better than
another, the current state of play, and the concrete next steps.

## The one rule

**A bot/strategy/weight change ships only if it beats the current champion
head-to-head in the gauntlet** — and, for the lookahead bot, only if it also
doesn't regress against the previous frozen version of itself (see Versioned
gauntlet). Not "the average sell value went up", not "it claims more cards" —
*win rate*. The previous tuning round optimised proxy stats and regressed real
games; the gauntlet exists so that can't happen again.

```bash
# Candidate vs champion, all optional rules on, 200 seeded games:
uv run python -m ml.gauntlet --candidate lookahead --champion mastermind \
    --games 200 --modes all
```

`ml/gauntlet.py` plays seat-balanced pairs (same deal, swapped seats, so
first-player luck cancels), attributes wins by seat role (not class name, so a
tweaked Mastermind can fight stock Mastermind), and PASS/FAILs on the **Wilson
95% lower bound** of the candidate's win share (default gate > 50%). Exit code is
0 on PASS, 1 on FAIL — usable in CI.

Strategy specs: any name in `STRATEGY_CLASSES`
(`mastermind`, `cocktail`, `safe`, `specialist`, `aggressive`, `karaoke`,
`random`, `lookahead`) or `mcts` / `mcts:sims=200,time=1.0`. A **frozen previous
version** of the lookahead bot is `lookahead:v0`, `lookahead:v1`, …, or
`lookahead:latest` (see Versioned gauntlet).

### Versioned gauntlet (progress + no regression)

Mastermind is a *timid* opponent: it can't reward the engine play that beats a
human in a long game (a real production loss the Mastermind-only gauntlet would
never have flagged). So each tuned bot is **frozen as a numbered version** in
`ml/versions.py`, and new tuning must beat **both** Mastermind *and* the version
it replaces:

```bash
# Current DEFAULT_WEIGHTS vs Mastermind (must beat) + every frozen version
# (must not regress), all in one run:
uv run python -m ml.gauntlet --candidate lookahead --regression --games 200 --modes all
```

- Each version is an immutable `EvalWeights` snapshot. The newest is `latest`.
- vs Mastermind (a **beat** target): PASS needs Wilson-lower > gate.
- vs a previous version (a **noregress** target): FAIL only if the candidate is
  *confidently worse* (Wilson-upper < 50%); flagged **progress** when
  confidently better (Wilson-lower > 50%), else "no regression (even)".
- **Workflow to ship a new version:** tune `evaluator.py`'s `DEFAULT_WEIGHTS`,
  pass `--regression`, then append the new explicit weights to
  `LOOKAHEAD_VERSIONS` (never edit an existing entry). It becomes the new
  `latest` that the *next* round must beat.
- **Caveat — version-vs-version is slow.** Two lookahead bots each run the
  depth-limited search, so a `lookahead:vX` matchup is ~7× slower than vs
  Mastermind (~5 s/game). Use fewer games for version matchups and read the
  Wilson *interval* — a wide one over few decisive games means "inconclusive",
  not "even". (Earlier these matchups also showed ~30% bogus "draws"; that was a
  runner bug — turns force-advanced past the last-round check — now fixed, so
  games resolve by points as they should.)

## The strategies

| Strategy | What it is |
|---|---|
| `mastermind` | Hand-tuned **greedy 1-ply** scorer. The long-standing baseline/champion. |
| `mcts` | "MCTS" that is really a **flat 1-deep bandit** over the root actions whose rollouts use Mastermind, so it inherits Mastermind's blind spots. Slow. |
| `lookahead` | **State evaluator + depth-limited search** (this round's work). Current strongest. |

### Lookahead (`ml/lookahead.py` + `ml/evaluator.py`)

- `evaluator.evaluate(gs, player_id)` returns a **potential** score (points-
  equivalent scale): realized points, karaoke progress (+ near-instant-win),
  cup sale value (cocktail/doubler/specialist aware), cocktail-in-progress, card
  engine value, and a **safety-gated** card-threshold-proximity lure, minus
  **convex drunk/bladder safety penalties**. Terminal/elimination states are
  clamped to large ±values. All tunable weights live in the `EvalWeights`
  dataclass in `evaluator.py`; `evaluate(gs, pid, weights)` and
  `LookaheadStrategy(weights=…)` take a weight set, so frozen versions coexist.
- `LookaheadStrategy` does a shallow expectimax over **main actions only**:
  apply the action, play opponents (modelled as Mastermind) to the next
  decision, score the leaf with the evaluator; sample a few times to average
  bag/opponent randomness. Self-eliminating lines score very negative
  automatically — no hand-written suicide filter. Micro-decisions (takes, free
  actions) delegate to Mastermind. `depth=1, samples=3` by default.

## Current results (seat-balanced, 2-player)

| Matchup | Modes | Win rate | Wilson 95% low | Self-elim | Speed |
|---|---|---|---|---|---|
| lookahead vs mastermind | all | **90.5–91.0%** (seeds 1000/2000) | 85.6–86.2% | 8.5% | 0.7 s/game |
| mcts(100) vs mastermind | all | 75.0% (45/60) | 62.8% | 25% | **52.9 s/game** |

### Engine-acquisition tuning round (this round)

A real production loss (`lookahead` lost a 2-player game to a human 28–40) showed
the bot **never built the scoring engine**: two cup-doublers sat unclaimed in the
row the entire game while it sold un-multiplied ~3-pt cups and rerolled specials
17 times to no effect. The doubler-proximity lure was invisible (a from-scratch
doubler needs 3 spirits, but the lure's reach was 2 and the worth too small to
overcome the drunk cost of drinking toward it). Fix: a dedicated **acquisition
pull** for doubler/specialist/karaoke cards (`*_ACQUIRE_W`), a longer
`THRESHOLD_REACH=3`, a gentler distance discount, and a **reroll gate** that
stops churning specials once two are banked. The safety penalties / `SAFE_DRUNK_CAP`
were left untouched — softening them made the bot drink recklessly and *regressed*
the gauntlet (more self-elimination). Same 200 seeds, all modes:

| Weights (`v0`→`v1`) | Win share | Wilson 95% low | Candidate avg pts | Candidate self-elim |
|---|---|---|---|---|
| pre-tuning (`v0`) | 86.0% | 81.0% | 29.7 | 13.5% |
| **tuned (`v1`, current)** | **88.5–91.0%** | **83.3–86.2%** | 30.6 | **8.5–11.5%** |

**`v1` is a specialisation toward the production (modes-on) regime, not a strict
upgrade** — and the versioned gauntlet is what made that legible:

- vs Mastermind, **all modes**: clear progress (above) — the bot now claims the
  doublers it used to walk past, in the exact regime the production loss happened.
- vs Mastermind, **no modes**: **regressed** 80.8% → 75.8% (when `claim_card` is a
  main action the engine chase costs tempo).
- **`v1` vs `v0` head-to-head** (all modes, 120 games, after the runner-draw
  fix): **51.7%**, CI [42.8%, 60.4%] — a slight edge that isn't yet significant,
  but `v1` self-eliminates less (8.3% vs 13.3%). A modest real upgrade, not the
  sidegrade the buggy runner first suggested (~46% with 32% bogus draws).

So `v1` ships as `latest` because it targets the regime that actually broke in
production, but the next round (`v2`) must pull *significantly* ahead of `v1`
*head-to-head* without giving back the no-modes ground. lookahead remains **~78×
faster** than the shipped MCTS.

### Cocktail knowledge (`lookahead:cocktail`) — a long-game specialist, off by default

Cocktails are the big scores (10–15 pts, exempt from the 2-spirit cap that caps
every other drink at 3), and the bot ignored them. The full feature is now built:

- **Evaluator** (`_cocktail_progress` + `cocktail_progress` weight): values a cup
  a few ingredients from a *completable* cocktail (recipe sub-multiset + specials
  on the mat).
- **Decision is value/probability-driven, not rule-driven** (`ml/cocktail.py`
  `best_cocktail`): for every recipe whose specials are banked and every cup
  that's a sub-multiset of it, **EV = P(complete) × (points − a normal sale)**,
  where `P(complete)` is a cheap proxy on how comfortably the missing ingredients
  are obtainable from display+bag. The evaluator's cocktail term *is* that EV, so
  the search trades it off against everything else — "only when behind" (points
  are worth more head-to-head when behind), "don't strand a cup" (a stranded cup
  loses its `_best_cup_sale` value), and "play safe" (the safety penalty) all
  **emerge from the evaluation**, not from `if` statements. The knobs (`_HEADROOM`,
  display weight, the EV build threshold) are tunable weights.
- **Disposition**: when the best EV clears the build bar, it builds that cup from
  the display, stacking the 3rd/4th spirit (the 2-spirit cap is a *sale* rule,
  not a take rule) and spoiling off-plan spirits rather than drinking into the
  cliff. `LookaheadStrategy` simulates its *own* disposition so the safety penalty
  sees a build-take's real cost.

Honest gauntlet result (120-game, all modes): it builds real cocktails but
**still trails** — ~76% vs Mastermind (`v1` ~90%) and ~46% vs `v1` head-to-head,
and a weight sweep (0.3 / 0.5 / 1.0) only makes it worse. The ceiling is
structural, not a tuning miss:

- The **forced ~5-item take economy** makes a multi-take build (e.g. a 3-gin
  Martini) inefficient — most of each take is off-plan.
- The cocktails that *don't* need building — **Margarita** (2 tequila),
  **Manhattan** (2 whiskey), **Cosmopolitan** (vodka+cranberry) — are **free
  declare-at-sale upgrades `v1` already takes** (the sale enumerates special
  combos and the search picks the 10-pt cocktail). So the build code only adds
  the *costly* cocktails, which short games don't repay.

So cocktail building is a **long-game / vs-human** play, kept **off by default**
(`cocktail_progress` 0.0; `DEFAULT_WEIGHTS == v1`) and selectable as
`lookahead:cocktail` (`ALT_BUILDS` in `ml/versions.py`). Promote it by flipping
`cocktail_progress` into `DEFAULT_WEIGHTS` if the long game is what you care about.

## Important gotchas

- **`ml/` must be in the Docker image.** `playtesting.strategy` registers `mcts`
  and `lookahead` via lazy imports of `ml.*`. If `ml/` isn't shipped, those
  imports ModuleNotFound-fail, the strategies never register, and
  `bot_player._get_strategy` silently falls back to **`random`**. This was the
  case before this round — the production "mcts" bot was almost certainly
  playing random moves. `COPY ml ./ml` now fixes it. The runtime-imported
  modules (`ml.mcts`, `ml.evaluator`, `ml.lookahead`) pull only
  `app`/`playtesting` + stdlib, so no numpy/gymnasium is needed at runtime.
- **The online policy is frozen.** `MCTSStrategy.learn` defaults to `False`:
  production play must never mutate the shared `OnlinePolicy` (it did, on every
  move, via EMA — a likely cause of the "disaster" game). Policy/weight changes
  are made offline and gated by the gauntlet.

## Does the bot learn? Can it train on human history?

The lookahead bot **does not learn during play** — every move is computed fresh
from the board; nothing persists between games. It does not *need* training to
work, but it *can* be made stronger by changing its weights/depth offline and
gating on the gauntlet.

It **can** be tuned from human game history — as offline weight-fitting, not
live learning:

1. Replay ended games (public endpoints `/v1/games?status=ENDED` + `/history`)
   and fit the evaluator weights so `evaluate(state, winner)` ranks the eventual
   winner above losers (logistic regression on "did this side win?").
2. Optionally build an opening book to bias *search ordering* (not override it).
3. Ship only if the fitted weights beat the champion in the gauntlet.

Do **not** resurrect per-move live mutation in production.

## Next steps (in priority order)

1. **Promote lookahead to the production default / retire MCTS.** It is faster
   and stronger. Decide whether `mcts` stays selectable at all. Consider making
   bot games default the optional rules on (host still controls them today).
2. **`depth=2` *needs* a weight pass — it regresses on its own.** Depth is now
   selectable in the gauntlet (`lookahead:depth=2`, `lookahead:cocktail,depth=2`).
   Note the naming: the default `depth=1` already searches *two* of the bot's
   turns (action → opponents → follow-up → opponents → evaluate), so `depth=2` is
   a three-turn search. Measured (120/60g, all modes): `depth=2` with v1 weights
   is **~74% vs Mastermind** (down from ~90%) and **~50% vs v1** head-to-head —
   i.e. no better head-to-head, worse vs Mastermind, and ~10× slower. The
   evaluator is tuned for the 2-ply horizon, so a 3rd ply amplifies the
   "holding/potential looks good → defer the sale" bias and adds sampling noise.
   To make depth pay off, re-tune the `evaluator.py` weight block *for that depth*
   (less `cup_sell`/potential, more realized points, more `samples`) and gauntlet
   each change — but the flat head-to-head suggests the 3rd ply has marginal value
   in a game this tactical, so weigh the effort.
3. **`ml/fit_evaluator.py`** — replay history, fit evaluator weights, auto-run
   the gauntlet to accept/reject. Versioned, gated, offline.
4. **Better opponent model.** The search assumes opponents play Mastermind;
   model them as lookahead (self-play) once #1 lands.
5. **4-player evaluation.** All current numbers are 2-player; add a 4-player
   gauntlet mode and confirm the win-rate holds.
6. **Rework `train_from_history`.** Its action-type-frequency prior is nearly
   useless and only fed the (now-frozen) MCTS policy. Replace with #3 or remove.
