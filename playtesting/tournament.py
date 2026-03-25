"""Tournament runner: plays N games per matchup and reports stats."""

from collections import defaultdict
from dataclasses import dataclass, field
from uuid import uuid4

from playtesting.runner import GameResult, GameRunner
from playtesting.strategy import Strategy


@dataclass
class TournamentStats:
    games_played: int = 0
    wins: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    win_reasons: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    total_scores: dict[str, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    turn_counts: list[int] = field(default_factory=list)
    eliminations: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    elimination_types: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    stalemates: int = 0
    errors: int = 0


class Tournament:
    def __init__(
        self,
        strategy_classes: list[type[Strategy]],
        num_games: int = 100,
        base_seed: int | None = None,
        num_players: int = 4,
        verbose: bool = False,
    ):
        self.strategy_classes = strategy_classes
        self.num_games = num_games
        self.base_seed = base_seed
        self.num_players = num_players
        self.verbose = verbose

    def run(self) -> TournamentStats:
        stats = TournamentStats()

        for i in range(self.num_games):
            seed = self.base_seed + i if self.base_seed is not None else None

            # Assign strategies round-robin to players
            player_ids = [uuid4() for _ in range(self.num_players)]
            strategies: dict = {}
            for j, pid in enumerate(player_ids):
                cls = self.strategy_classes[j % len(self.strategy_classes)]
                strategies[pid] = cls()

            runner = GameRunner(strategies, seed=seed)

            try:
                result = runner.run(verbose=self.verbose)
                self._record_result(stats, result)
            except Exception as e:
                stats.errors += 1
                if self.verbose:
                    print(f"  Game {i} ERROR: {e}")

            if not self.verbose and (i + 1) % 50 == 0:
                print(f"  {i + 1}/{self.num_games} games completed...")

        return stats

    def _record_result(self, stats: TournamentStats, result: GameResult):
        stats.games_played += 1
        stats.turn_counts.append(result.turn_count)

        if result.reason == "stalemate":
            stats.stalemates += 1

        if result.winner:
            stats.wins[result.winner_strategy] += 1
            stats.win_reasons[result.winner_strategy][result.reason] += 1

        for pid, pr in result.player_results.items():
            stats.total_scores[pr.strategy_name].append(pr.points)
            if pr.status in ("hospitalised", "wet"):
                stats.eliminations[pr.strategy_name] += 1
                stats.elimination_types[pr.strategy_name][pr.status] += 1

    def print_report(self, stats: TournamentStats):
        print()
        print("=" * 60)
        print(f"TOURNAMENT REPORT ({stats.games_played} games)")
        print("=" * 60)

        if stats.errors:
            print(f"  Errors: {stats.errors}")
        if stats.stalemates:
            print(f"  Stalemates: {stats.stalemates}")

        avg_turns = (
            sum(stats.turn_counts) / len(stats.turn_counts) if stats.turn_counts else 0
        )
        print(f"  Avg game length: {avg_turns:.1f} turns")
        print()

        # Collect all strategy names
        all_strategies = set()
        for name in stats.wins:
            all_strategies.add(name)
        for name in stats.total_scores:
            all_strategies.add(name)
        all_strategies = sorted(all_strategies)

        # Header
        print(
            f"{'Strategy':<20} {'Wins':>5} {'Win%':>6} {'Avg Pts':>8} "
            f"{'Elim':>5} {'Elim%':>6} {'Hosp':>5} {'Wet':>5}"
        )
        print("-" * 76)

        for name in all_strategies:
            wins = stats.wins.get(name, 0)
            scores = stats.total_scores.get(name, [])
            appearances = len(scores)
            win_pct = (wins / appearances * 100) if appearances else 0
            avg_score = sum(scores) / len(scores) if scores else 0
            elims = stats.eliminations.get(name, 0)
            elim_pct = (elims / appearances * 100) if appearances else 0
            hosp = stats.elimination_types.get(name, {}).get("hospitalised", 0)
            wet = stats.elimination_types.get(name, {}).get("wet", 0)

            print(
                f"{name:<20} {wins:>5} {win_pct:>5.1f}% {avg_score:>8.1f} "
                f"{elims:>5} {elim_pct:>5.1f}% {hosp:>5} {wet:>5}"
            )

        # Win reasons breakdown
        print()
        print("Win reasons:")
        for name in all_strategies:
            reasons = stats.win_reasons.get(name, {})
            if reasons:
                reason_str = ", ".join(f"{r}: {c}" for r, c in sorted(reasons.items()))
                print(f"  {name}: {reason_str}")

        print()
