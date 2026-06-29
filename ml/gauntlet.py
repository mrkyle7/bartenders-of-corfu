"""Win-rate gauntlet: gate a candidate bot against the current champion.

The only metric that should ever gate a strategy/policy change is **head-to-head
win rate vs the current champion**, measured over many seeded games. This module
is that yardstick. Use it before touching strategy weights, training the policy,
or shipping a new bot.

Why this exists
---------------
The previous tuning loop optimised *proxy* stats (avg sell value, cards/game)
rather than wins, and the online policy mutated itself live in production. This
harness replaces "the stats look better" with "it actually beats the champion,
with a confidence interval".

Key design choices
-------------------
- **Seat-balanced pairing.** First-player advantage is real. Games are played in
  pairs that share a seed (identical deal) with the candidate and champion
  swapping seats, so seat/deal luck cancels out.
- **Role attribution, not class name.** Candidate and champion may be the same
  strategy class (e.g. Mastermind vs a tweaked Mastermind). Wins are attributed
  by seat role, never by ``strategy.name``.
- **Wilson lower bound.** The PASS/FAIL gate uses the lower bound of a Wilson
  score interval on the candidate's win share among decisive games, so we don't
  ship on a lucky streak.

Usage
-----
    # Candidate Mastermind vs champion Mastermind, all optional rules on:
    uv run python -m ml.gauntlet --candidate mastermind --champion mastermind \
        --games 200 --modes all

    # MCTS candidate (150 sims) vs Mastermind champion:
    uv run python -m ml.gauntlet --candidate mcts:sims=150 --champion mastermind \
        --games 100

Strategy specs are names from ``STRATEGY_CLASSES`` (mastermind, cocktail,
safeseller, specialist, aggressive, karaoke, random) or ``mcts`` with optional
``key=value`` params, e.g. ``mcts:sims=200,time=1.0``.
"""

import argparse
import math
import sys
import time
from dataclasses import dataclass, field
from typing import Callable
from uuid import UUID, uuid4

from app.game_modes import VALID_GAME_MODES, normalise_modes

import ml  # noqa: F401  — registers ml-backed strategies (mcts, lookahead)
from playtesting.runner import GameRunner
from playtesting.strategy import STRATEGY_CLASSES, Strategy

# Factory builds a fresh Strategy instance per game (strategies hold per-game
# state, so they must not be shared across games).
StrategyFactory = Callable[[], Strategy]

CANDIDATE = "candidate"
CHAMPION = "champion"


def _parse_strategy_spec(spec: str) -> tuple[StrategyFactory, str]:
    """Resolve a spec string to a (factory, label) pair.

    Examples:
        "mastermind"            -> Mastermind
        "mcts"                  -> MCTSStrategy()
        "mcts:sims=200,time=1.0"-> MCTSStrategy(num_simulations=200, time_limit=1.0)
    """
    name, _, param_str = spec.partition(":")
    name = name.strip().lower()

    if name == "mcts":
        from ml.mcts import MCTSStrategy

        params = _parse_params(param_str)
        sims = int(params.get("sims", 100))
        time_limit = float(params["time"]) if "time" in params else None

        def factory() -> Strategy:
            # learn=False: the gauntlet must never mutate the shared policy.
            return MCTSStrategy(
                num_simulations=sims, time_limit=time_limit, learn=False
            )

        label = f"mcts(sims={sims}{f',t={time_limit}' if time_limit else ''})"
        return factory, label

    cls = STRATEGY_CLASSES.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown strategy '{name}'. "
            f"Available: {', '.join(sorted(STRATEGY_CLASSES))}, mcts"
        )
    return (lambda: cls()), name


def _parse_params(param_str: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for part in param_str.split(","):
        part = part.strip()
        if not part:
            continue
        key, _, value = part.partition("=")
        params[key.strip()] = value.strip()
    return params


def _resolve_modes(modes_arg: str | None) -> list[str]:
    """Resolve the --modes argument to a normalised list of mode strings."""
    if not modes_arg or modes_arg.lower() == "none":
        return []
    if modes_arg.lower() == "all":
        return normalise_modes(sorted(VALID_GAME_MODES))
    requested = [m.strip() for m in modes_arg.split(",") if m.strip()]
    return normalise_modes(requested)


def wilson_lower_bound(wins: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson score interval for a win proportion.

    Returns 0.0 for n == 0. With z=1.96 this is a ~95% one-sided-ish bound used
    as a conservative estimate of true win rate.
    """
    if n == 0:
        return 0.0
    phat = wins / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


@dataclass
class GauntletResult:
    games: int = 0
    candidate_wins: int = 0
    champion_wins: int = 0
    draws: int = 0  # stalemate / no winner
    candidate_first_games: int = 0
    candidate_first_wins: int = 0
    eliminations: dict[str, int] = field(
        default_factory=lambda: {CANDIDATE: 0, CHAMPION: 0}
    )
    points: dict[str, list[int]] = field(
        default_factory=lambda: {CANDIDATE: [], CHAMPION: []}
    )
    errors: int = 0

    @property
    def decisive(self) -> int:
        return self.candidate_wins + self.champion_wins

    @property
    def candidate_win_share(self) -> float:
        return self.candidate_wins / self.decisive if self.decisive else 0.0

    def avg_points(self, role: str) -> float:
        pts = self.points[role]
        return sum(pts) / len(pts) if pts else 0.0

    def elim_rate(self, role: str) -> float:
        return self.eliminations[role] / self.games if self.games else 0.0


def run_gauntlet(
    candidate: StrategyFactory,
    champion: StrategyFactory,
    *,
    games: int = 200,
    num_players: int = 2,
    base_seed: int = 1000,
    game_modes: list[str] | None = None,
    progress_every: int = 50,
) -> GauntletResult:
    """Play ``games`` seat-balanced head-to-head games and tally outcomes.

    The candidate occupies one seat; remaining seats are filled by the champion.
    Games are run in seed-paired couples that swap the candidate's seat so that
    deal and first-player advantage cancel out.
    """
    game_modes = game_modes or []
    res = GauntletResult()

    for i in range(games):
        # Pair games on a shared seed; flip the candidate's seat between them.
        seed = base_seed + (i // 2)
        candidate_first = i % 2 == 0

        player_ids = [uuid4() for _ in range(num_players)]
        # Candidate sits in seat 0 on even games, seat 1 on odd games (so it
        # alternates first/second player). All other seats are the champion.
        cand_seat = 0 if candidate_first else min(1, num_players - 1)

        strategies: dict[UUID, Strategy] = {}
        roles: dict[UUID, str] = {}
        for seat, pid in enumerate(player_ids):
            if seat == cand_seat:
                strategies[pid] = candidate()
                roles[pid] = CANDIDATE
            else:
                strategies[pid] = champion()
                roles[pid] = CHAMPION

        runner = GameRunner(strategies, seed=seed, game_modes=game_modes)
        try:
            result = runner.run()
        except Exception:
            res.errors += 1
            continue

        res.games += 1
        if candidate_first:
            res.candidate_first_games += 1

        # Points + eliminations by role.
        for pid, pr in result.player_results.items():
            role = roles[pid]
            res.points[role].append(pr.points)
            if pr.status in ("hospitalised", "wet"):
                res.eliminations[role] += 1

        if result.winner is None:
            res.draws += 1
        elif roles.get(result.winner) == CANDIDATE:
            res.candidate_wins += 1
            if candidate_first:
                res.candidate_first_wins += 1
        else:
            res.champion_wins += 1

        if progress_every and res.games % progress_every == 0:
            print(
                f"  {res.games}/{games}: "
                f"candidate {res.candidate_wins} - {res.champion_wins} champion "
                f"({res.draws} draws)"
            )

    return res


def print_report(
    res: GauntletResult,
    candidate_label: str,
    champion_label: str,
    modes: list[str],
    gate: float,
) -> bool:
    """Print the gauntlet report and return True if the candidate PASSES."""
    lower = wilson_lower_bound(res.candidate_wins, res.decisive)
    passed = lower > gate

    print()
    print("=" * 64)
    print("GAUNTLET REPORT")
    print("=" * 64)
    print(f"  Candidate : {candidate_label}")
    print(f"  Champion  : {champion_label}")
    print(f"  Modes     : {', '.join(modes) if modes else 'none'}")
    print(f"  Games     : {res.games} (errors: {res.errors}, draws: {res.draws})")
    print()
    print(
        f"  Head-to-head (decisive games: {res.decisive}):\n"
        f"    candidate wins : {res.candidate_wins}\n"
        f"    champion wins  : {res.champion_wins}"
    )
    print(f"  Candidate win share : {res.candidate_win_share * 100:.1f}%")
    print(f"  Wilson 95% lower    : {lower * 100:.1f}%  (gate: >{gate * 100:.0f}%)")
    print()
    if res.candidate_first_games:
        cf_rate = res.candidate_first_wins / res.candidate_first_games
        cs_games = res.games - res.candidate_first_games
        cs_wins = res.candidate_wins - res.candidate_first_wins
        cs_rate = cs_wins / cs_games if cs_games else 0.0
        print("  Seat balance (sanity — should be similar):")
        print(
            f"    candidate going first : {cf_rate * 100:.1f}% win ({res.candidate_first_games} g)"
        )
        print(f"    candidate going second: {cs_rate * 100:.1f}% win ({cs_games} g)")
        print()
    print(f"  {'role':<12}{'avg pts':>10}{'elim rate':>12}")
    print("  " + "-" * 32)
    for role, label in ((CANDIDATE, "candidate"), (CHAMPION, "champion")):
        print(
            f"  {label:<12}{res.avg_points(role):>10.1f}"
            f"{res.elim_rate(role) * 100:>11.1f}%"
        )
    print()
    print(
        f"  RESULT: {'PASS — candidate beats champion' if passed else 'FAIL — does not beat champion'}"
    )
    print("=" * 64)
    return passed


def main():
    parser = argparse.ArgumentParser(
        description="Win-rate gauntlet: gate a candidate bot vs the champion."
    )
    parser.add_argument(
        "--candidate", default="mastermind", help="Candidate strategy spec"
    )
    parser.add_argument(
        "--champion", default="mastermind", help="Champion (baseline) strategy spec"
    )
    parser.add_argument("--games", type=int, default=200, help="Number of games")
    parser.add_argument("--players", type=int, default=2, help="Players per game (>=2)")
    parser.add_argument("--seed", type=int, default=1000, help="Base seed")
    parser.add_argument(
        "--modes",
        default="none",
        help="Optional rules: 'all', 'none', or comma-separated mode names",
    )
    parser.add_argument(
        "--gate",
        type=float,
        default=0.5,
        help="Min Wilson lower-bound win share to PASS (default 0.5)",
    )

    args = parser.parse_args()

    if args.players < 2:
        parser.error("--players must be >= 2")

    try:
        candidate, candidate_label = _parse_strategy_spec(args.candidate)
        champion, champion_label = _parse_strategy_spec(args.champion)
        modes = _resolve_modes(args.modes)
    except ValueError as e:
        parser.error(str(e))

    print("Win-rate gauntlet")
    print(f"  candidate={candidate_label} vs champion={champion_label}")
    print(f"  games={args.games} players={args.players} modes={modes or 'none'}")
    print()

    start = time.time()
    res = run_gauntlet(
        candidate,
        champion,
        games=args.games,
        num_players=args.players,
        base_seed=args.seed,
        game_modes=modes,
    )
    elapsed = time.time() - start

    passed = print_report(res, candidate_label, champion_label, modes, args.gate)
    print(f"  Time: {elapsed:.1f}s ({elapsed / max(1, res.games):.2f}s/game)")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
