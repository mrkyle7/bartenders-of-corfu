"""CLI entry point for the Bartenders of Corfu play-test harness.

Usage:
    uv run python -m playtesting [options]

Examples:
    # Single verbose game, deterministic
    uv run python -m playtesting --single --seed 42 --strategies karaoke,safe

    # 500-game tournament, all strategies
    uv run python -m playtesting --games 500 --seed 1000

    # Quick 2-player matchup
    uv run python -m playtesting --games 100 --strategies random,cocktail --players 2
"""

import argparse
import sys
from uuid import uuid4

from playtesting.display import format_result
from playtesting.runner import GameRunner
from playtesting.strategy import STRATEGY_CLASSES
from playtesting.tournament import Tournament


def main():
    parser = argparse.ArgumentParser(
        description="Bartenders of Corfu play-test harness"
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument(
        "--games", type=int, default=100, help="Games per tournament (default: 100)"
    )
    parser.add_argument(
        "--players", type=int, default=4, help="Players per game (default: 4)"
    )
    parser.add_argument(
        "--strategies",
        type=str,
        default=",".join(STRATEGY_CLASSES.keys()),
        help=f"Comma-separated strategies: {','.join(STRATEGY_CLASSES.keys())}",
    )
    parser.add_argument("--verbose", action="store_true", help="Print each action")
    parser.add_argument(
        "--single", action="store_true", help="Run a single game (verbose)"
    )

    args = parser.parse_args()

    strategy_names = [s.strip() for s in args.strategies.split(",")]
    for name in strategy_names:
        if name not in STRATEGY_CLASSES:
            print(f"Unknown strategy: {name}")
            print(f"Available: {', '.join(STRATEGY_CLASSES.keys())}")
            sys.exit(1)

    strategy_classes = [STRATEGY_CLASSES[n] for n in strategy_names]

    if args.single:
        _run_single(strategy_classes, args)
    else:
        _run_tournament(strategy_classes, args)


def _run_single(strategy_classes: list, args):
    num_players = min(args.players, len(strategy_classes))
    player_ids = [uuid4() for _ in range(num_players)]
    strategies = {}
    for i, pid in enumerate(player_ids):
        cls = strategy_classes[i % len(strategy_classes)]
        strategies[pid] = cls()

    runner = GameRunner(strategies, seed=args.seed)
    result = runner.run(verbose=True)

    print()
    print(format_result(result))


def _run_tournament(strategy_classes: list, args):
    print(
        f"Tournament: {args.games} games, {args.players} players/game, "
        f"strategies: {','.join(s.name for s in (cls() for cls in strategy_classes))}"
    )
    if args.seed is not None:
        print(f"Base seed: {args.seed}")

    tourney = Tournament(
        strategy_classes,
        num_games=args.games,
        base_seed=args.seed,
        num_players=args.players,
        verbose=args.verbose,
    )
    stats = tourney.run()
    tourney.print_report(stats)


if __name__ == "__main__":
    main()
