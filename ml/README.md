# Bots, evaluation, and how to make them stronger

This document is the entry point for anyone (human or agent) picking up the bot
work later. It explains how the bots are wired, how we decide one is better than
another, the current state of play, and the concrete next steps.

## The one rule

**A bot/strategy/weight change ships only if it beats the current champion
head-to-head in the gauntlet.** Not "the average sell value went up", not "it
claims more cards" — *win rate*. The previous tuning round optimised proxy stats
and regressed real games; the gauntlet exists so that can't happen again.

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
`random`, `lookahead`) or `mcts` / `mcts:sims=200,time=1.0`.

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
  clamped to large ±values. All weights live at the top of `evaluator.py`.
- `LookaheadStrategy` does a shallow expectimax over **main actions only**:
  apply the action, play opponents (modelled as Mastermind) to the next
  decision, score the leaf with the evaluator; sample a few times to average
  bag/opponent randomness. Self-eliminating lines score very negative
  automatically — no hand-written suicide filter. Micro-decisions (takes, free
  actions) delegate to Mastermind. `depth=1, samples=3` by default.

## Current results (seat-balanced, 2-player)

| Matchup | Modes | Win rate | Wilson 95% low | Self-elim | Speed |
|---|---|---|---|---|---|
| lookahead vs mastermind | all | **90.5%** (181/200) | 85.6% | 9.5% | 0.68 s/game |
| lookahead vs mastermind | none | **82.5%** (99/120) | 74.7% | 16.7% | 10.1 s/game |
| mcts(100) vs mastermind | all | 75.0% (45/60) | 62.8% | 25% | **52.9 s/game** |

Takeaways: lookahead is **stronger and ~78× faster** than the shipped MCTS. The
dominant failure mode of the old bots was **self-elimination** (~50% in a
mastermind mirror); the evaluator's safety terms cut lookahead's to ~10%.

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
2. **`depth=2` + a weight pass.** Bump search depth and tune the `evaluator.py`
   weight block; gauntlet each change. Watch per-move latency (depth grows cost
   ~quadratically but is far under MCTS).
3. **`ml/fit_evaluator.py`** — replay history, fit evaluator weights, auto-run
   the gauntlet to accept/reject. Versioned, gated, offline.
4. **Better opponent model.** The search assumes opponents play Mastermind;
   model them as lookahead (self-play) once #1 lands.
5. **4-player evaluation.** All current numbers are 2-player; add a 4-player
   gauntlet mode and confirm the win-rate holds.
6. **Rework `train_from_history`.** Its action-type-frequency prior is nearly
   useless and only fed the (now-frozen) MCTS policy. Replace with #3 or remove.
