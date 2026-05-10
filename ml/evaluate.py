"""Evaluate MCTS bot against other strategies via tournament.

Usage:
    uv run python -m ml.evaluate [options]

Examples:
    # Quick test: 20 games, MCTS vs Mastermind
    uv run python -m ml.evaluate --games 20 --sims 50

    # Full evaluation: 100 games, more simulations
    uv run python -m ml.evaluate --games 100 --sims 200

    # Time-limited MCTS (1 second per move)
    uv run python -m ml.evaluate --games 50 --time-limit 1.0

    # Test against all strategies
    uv run python -m ml.evaluate --games 50 --opponents all
"""

import argparse
import sys
import time
from uuid import uuid4

from playtesting.runner import GameRunner
from playtesting.strategy import STRATEGY_CLASSES, Mastermind
from playtesting.tournament import Tournament

from ml.mcts import MCTSStrategy


def run_tournament(
    num_games: int,
    num_simulations: int,
    time_limit: float | None,
    opponents: str,
    num_players: int,
    seed: int | None,
    verbose: bool,
):
    """Run MCTS vs opponents tournament."""

    # Create MCTS class with configured params
    class ConfiguredMCTS(MCTSStrategy):
        name = f"MCTS({num_simulations})"

        def __init__(self):
            super().__init__(
                num_simulations=num_simulations,
                time_limit=time_limit,
            )

    if opponents == "mastermind":
        strategy_classes = [ConfiguredMCTS, Mastermind]
    elif opponents == "all":
        strategy_classes = [ConfiguredMCTS] + list(STRATEGY_CLASSES.values())
    else:
        opp_cls = STRATEGY_CLASSES.get(opponents)
        if opp_cls is None:
            print(f"Unknown opponent: {opponents}")
            print(f"Available: {', '.join(STRATEGY_CLASSES.keys())}")
            sys.exit(1)
        strategy_classes = [ConfiguredMCTS, opp_cls]

    print("MCTS Bot Evaluation")
    print(f"  Simulations per move: {num_simulations}")
    if time_limit:
        print(f"  Time limit per move: {time_limit}s")
    print(f"  Games: {num_games}")
    print(f"  Players per game: {num_players}")
    print(f"  Opponents: {opponents}")
    print()

    tourney = Tournament(
        strategy_classes,
        num_games=num_games,
        base_seed=seed,
        num_players=num_players,
        verbose=verbose,
    )

    start = time.time()
    stats = tourney.run()
    elapsed = time.time() - start

    tourney.print_report(stats)
    print(f"\nTotal time: {elapsed:.1f}s ({elapsed / num_games:.2f}s/game)")


def run_single_game(num_simulations: int, time_limit: float | None, seed: int | None):
    """Run a single verbose game for debugging."""
    mcts = MCTSStrategy(num_simulations=num_simulations, time_limit=time_limit)
    mastermind = Mastermind()

    player_ids = [uuid4() for _ in range(4)]
    strategies = {
        player_ids[0]: mcts,
        player_ids[1]: mastermind,
        player_ids[2]: mastermind,
        player_ids[3]: mastermind,
    }

    runner = GameRunner(strategies, seed=seed)
    print("=== MCTS vs 3x Mastermind ===")
    print(f"  MCTS simulations: {num_simulations}")
    print()

    start = time.time()
    result = runner.run(verbose=True)
    elapsed = time.time() - start

    print()
    print(f"Winner: {result.winner_strategy} ({result.reason})")
    print(f"Turns: {result.turn_count}")
    print(f"Time: {elapsed:.1f}s")
    for pid, pr in result.player_results.items():
        print(f"  {pr.strategy_name}: {pr.points}pts, status={pr.status}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate MCTS bot")
    parser.add_argument("--games", type=int, default=50, help="Number of games")
    parser.add_argument(
        "--sims", type=int, default=100, help="MCTS simulations per move"
    )
    parser.add_argument(
        "--time-limit", type=float, default=None, help="Time limit per move (seconds)"
    )
    parser.add_argument(
        "--opponents",
        type=str,
        default="mastermind",
        help="Opponent strategy (mastermind/all/name)",
    )
    parser.add_argument("--players", type=int, default=4, help="Players per game")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--verbose", action="store_true", help="Print each action")
    parser.add_argument("--single", action="store_true", help="Run single verbose game")

    args = parser.parse_args()

    if args.single:
        run_single_game(args.sims, args.time_limit, args.seed)
    else:
        run_tournament(
            num_games=args.games,
            num_simulations=args.sims,
            time_limit=args.time_limit,
            opponents=args.opponents,
            num_players=args.players,
            seed=args.seed,
            verbose=args.verbose,
        )


if __name__ == "__main__":
    main()
