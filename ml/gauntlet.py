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

    if name == "lookahead" and param_str.strip():
        # `lookahead:v1` / `lookahead:latest` — a frozen weight snapshot, so a
        # candidate can be gauntletted against previous versions of itself.
        from ml.lookahead import LookaheadStrategy
        from ml.versions import get_version

        version = param_str.strip()
        weights = get_version(version)

        def factory() -> Strategy:
            return LookaheadStrategy(weights=weights)

        return factory, f"lookahead:{version}"

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


def wilson_bounds(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """(lower, upper) bounds of the Wilson score interval for a win proportion.

    Returns (0.0, 1.0) for n == 0. With z=1.96 this is a ~95% interval. The lower
    bound is the conservative "is it really better?" estimate; the upper bound
    powers the no-regression check ("are we confident it got worse?").
    """
    if n == 0:
        return 0.0, 1.0
    phat = wins / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom)


def wilson_lower_bound(wins: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson score interval (see ``wilson_bounds``)."""
    return wilson_bounds(wins, n, z)[0]


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


def classify(res: GauntletResult, gate: float, kind: str) -> tuple[bool, str]:
    """Decide PASS/FAIL for one matchup and a human-readable verdict.

    ``kind`` is "beat" (the candidate must out-win the champion — used for
    Mastermind and any explicit champion) or "noregress" (the champion is a
    previous version of the candidate; we only FAIL if the candidate is
    *confidently worse*, and flag genuine progress separately).
    """
    lower, upper = wilson_bounds(res.candidate_wins, res.decisive)
    if kind == "noregress":
        if upper < 0.5:
            return False, "FAIL — regressed (confidently worse than this version)"
        if lower > 0.5:
            return True, "PASS — progress (confidently beats this version)"
        return True, "PASS — no regression (statistically even)"
    passed = lower > gate
    verdict = "PASS — beats champion" if passed else "FAIL — does not beat champion"
    return passed, verdict


def print_report(
    res: GauntletResult,
    candidate_label: str,
    champion_label: str,
    modes: list[str],
    gate: float,
    kind: str = "beat",
) -> bool:
    """Print one matchup's report and return True if the candidate PASSES."""
    lower, upper = wilson_bounds(res.candidate_wins, res.decisive)
    passed, verdict = classify(res, gate, kind)

    print()
    print("=" * 64)
    print("GAUNTLET REPORT")
    print("=" * 64)
    print(f"  Candidate : {candidate_label}")
    print(f"  Champion  : {champion_label}  [{kind}]")
    print(f"  Modes     : {', '.join(modes) if modes else 'none'}")
    print(f"  Games     : {res.games} (errors: {res.errors}, draws: {res.draws})")
    print()
    print(
        f"  Head-to-head (decisive games: {res.decisive}):\n"
        f"    candidate wins : {res.candidate_wins}\n"
        f"    champion wins  : {res.champion_wins}"
    )
    print(f"  Candidate win share : {res.candidate_win_share * 100:.1f}%")
    print(
        f"  Wilson 95% interval : [{lower * 100:.1f}%, {upper * 100:.1f}%]"
        f"  (gate: >{gate * 100:.0f}%)"
    )
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
    print(f"  RESULT: {verdict}")
    print("=" * 64)
    return passed


def _regression_champions(candidate_label: str) -> list[tuple[str, str]]:
    """Champions for --regression: Mastermind (beat) + every frozen version
    (noregress), minus the candidate's own version (a v-vs-itself mirror).
    """
    from ml.versions import LOOKAHEAD_VERSIONS

    champions: list[tuple[str, str]] = [("mastermind", "beat")]
    own = (
        candidate_label.split(":", 1)[1]
        if candidate_label.startswith("lookahead:")
        else None
    )
    for v in LOOKAHEAD_VERSIONS:
        if v != own:
            champions.append((f"lookahead:{v}", "noregress"))
    return champions


def main():
    parser = argparse.ArgumentParser(
        description="Win-rate gauntlet: gate a candidate bot vs champions."
    )
    parser.add_argument(
        "--candidate", default="mastermind", help="Candidate strategy spec"
    )
    parser.add_argument(
        "--champion", default="mastermind", help="Champion (baseline) strategy spec"
    )
    parser.add_argument(
        "--champions",
        default=None,
        help="Comma-separated champion specs to run the candidate against "
        "(each a 'beat' target). Overrides --champion.",
    )
    parser.add_argument(
        "--regression",
        action="store_true",
        help="Play the candidate against Mastermind (must beat) AND every frozen "
        "lookahead version in ml/versions.py (must not regress). Shows progress "
        "and guards against regression in one run.",
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
        help="Min Wilson lower-bound win share to beat a 'beat' champion (0.5)",
    )

    args = parser.parse_args()

    if args.players < 2:
        parser.error("--players must be >= 2")

    try:
        candidate, candidate_label = _parse_strategy_spec(args.candidate)
        modes = _resolve_modes(args.modes)
        if args.regression:
            champion_specs = _regression_champions(candidate_label)
        elif args.champions:
            champion_specs = [
                (s.strip(), "beat") for s in args.champions.split(",") if s.strip()
            ]
        else:
            champion_specs = [(args.champion, "beat")]
        # Resolve all champion factories up front so a bad spec fails fast.
        champions = [
            (*_parse_strategy_spec(spec), kind) for spec, kind in champion_specs
        ]
    except ValueError as e:
        parser.error(str(e))

    print("Win-rate gauntlet")
    print(f"  candidate = {candidate_label}")
    print(f"  champions = {', '.join(f'{lbl} [{k}]' for _, lbl, k in champions)}")
    print(f"  games={args.games} players={args.players} modes={modes or 'none'}")

    all_passed = True
    summary: list[tuple[str, str, float, bool]] = []
    start = time.time()
    for champion, champion_label, kind in champions:
        res = run_gauntlet(
            candidate,
            champion,
            games=args.games,
            num_players=args.players,
            base_seed=args.seed,
            game_modes=modes,
        )
        passed = print_report(
            res, candidate_label, champion_label, modes, args.gate, kind
        )
        all_passed = all_passed and passed
        summary.append((champion_label, kind, res.candidate_win_share, passed))
    elapsed = time.time() - start

    if len(summary) > 1:
        print()
        print("=" * 64)
        print(f"SUMMARY — candidate {candidate_label}")
        print("=" * 64)
        for label, kind, share, passed in summary:
            mark = "PASS" if passed else "FAIL"
            print(f"  vs {label:<18} [{kind:<9}] {share * 100:5.1f}%  {mark}")
        print("=" * 64)
        print(f"  OVERALL: {'PASS' if all_passed else 'FAIL'}")
    print(f"  Time: {elapsed:.1f}s")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
