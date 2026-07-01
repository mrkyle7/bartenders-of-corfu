"""Self-play data generation for on-policy evaluator weight fitting.

Human-history fitting was *off-policy*: the value/outcome relationship in human
games doesn't match the consequences of the bot's own actions, so the fit learned
correlations that collapse when used for control (see ml/fit_evaluator.py). Self-
play fixes that — the value function is learned on the bot's **own** state
distribution, so ``V(s)`` reflects what actually follows from the bot's play, and
``argmax`` over it is a genuine policy-improvement step (approximate policy
iteration when iterated).

This records ``evaluator.player_features`` at sampled decision points of lookahead
self-play games, labelled by who eventually won. ml/fit_evaluator.py consumes it
via ``--source selfplay``.
"""

from uuid import uuid4

import numpy as np

from app.GameState import GameState
from app.Ingredient import Ingredient

from ml.evaluator import DEFAULT_WEIGHTS, FEATURE_NAMES, EvalWeights, player_features
from ml.lookahead import LookaheadStrategy
from playtesting.runner import GameRunner
from playtesting.strategy import Strategy
from playtesting.valid_actions import Action


class _Recorder(Strategy):
    """Wraps a strategy, snapshotting every player's features on each decision."""

    def __init__(self, inner: Strategy, sink: list):
        self._inner = inner
        self._sink = sink
        self.name = inner.name

    def choose_action(
        self, gs: GameState, player_id, valid_actions: list[Action]
    ) -> Action:
        self._sink.append(
            {
                str(pid): player_features(gs, ps)
                for pid, ps in gs.player_states.items()
                if not ps.is_eliminated
            }
        )
        return self._inner.choose_action(gs, player_id, valid_actions)

    def choose_free_action(self, gs, player_id, free_actions):
        return self._inner.choose_free_action(gs, player_id, free_actions)

    def choose_take_assignments(self, gs, player_id, count):
        return self._inner.choose_take_assignments(gs, player_id, count)

    def choose_pending_assignments(self, gs, player_id, drawn: list[Ingredient]):
        return self._inner.choose_pending_assignments(gs, player_id, drawn)


def generate_dataset(
    n_games: int,
    weights: EvalWeights = DEFAULT_WEIGHTS,
    *,
    modes: list[str] | None = None,
    players: int = 2,
    base_seed: int = 5000,
    samples_per_game: int = 12,
    verbose: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Play ``n_games`` lookahead self-play games; return (features, win-labels).

    All seats use ``weights`` (on-policy). Snapshots are sampled evenly across each
    game so early and late positions both appear; each active player at a snapshot
    is one labelled row (1 if it went on to win the game).
    """
    modes = modes or []
    rows: list[list[float]] = []
    labels: list[float] = []
    for i in range(n_games):
        sink: list[dict] = []
        pids = [uuid4() for _ in range(players)]
        strategies = {
            pid: _Recorder(LookaheadStrategy(weights=weights), sink) for pid in pids
        }
        result = GameRunner(strategies, seed=base_seed + i, game_modes=modes).run()
        if result.winner is None or not sink:
            continue
        winner = str(result.winner)

        k = min(samples_per_game, len(sink))
        idxs = sorted(set(np.linspace(0, len(sink) - 1, k).astype(int)))
        for idx in idxs:
            for pid_str, feats in sink[idx].items():
                rows.append([feats[name] for name in FEATURE_NAMES])
                labels.append(1.0 if pid_str == winner else 0.0)
        if verbose and (i + 1) % 20 == 0:
            print(f"  self-play {i + 1}/{n_games} games, {len(rows)} samples")

    return np.array(rows, dtype=float), np.array(labels, dtype=float)
