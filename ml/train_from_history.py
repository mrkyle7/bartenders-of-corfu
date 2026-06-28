"""Train MCTS bot from real game history fetched from the production API.

Fetches completed games from cheetahmoongames.com, extracts winning players'
action choices at each turn, and updates the OnlinePolicy action-type priors.

The idea: human winners consistently chose certain action types in certain
situations. By weighting action-type priors toward what winners actually did,
the MCTS bot explores winning strategies first.

Usage:
    uv run python -m ml.train_from_history --url https://cheetahmoongames.com
    uv run python -m ml.train_from_history --url https://cheetahmoongames.com --max-games 50
"""

import argparse
import json
import urllib.request
from collections import defaultdict


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_ended_games(base_url: str, max_games: int = 100) -> list[dict]:
    """Fetch ended games from the public list endpoint."""
    games = []
    page = 1
    page_size = 100
    while len(games) < max_games:
        url = f"{base_url}/v1/games?status=ENDED&page={page}&page_size={page_size}"
        data = fetch_json(url)
        batch = data.get("games", [])
        if not batch:
            break
        games.extend(batch)
        if len(batch) < page_size or len(games) >= data.get("total", 0):
            break
        page += 1
    return games[:max_games]


def fetch_game_history(base_url: str, game_id: str) -> list[dict]:
    """Fetch move history for a single game."""
    url = f"{base_url}/v1/games/{game_id}/history"
    data = fetch_json(url)
    return data.get("moves", [])


def extract_training_data(
    games: list[dict], base_url: str, verbose: bool = False
) -> dict:
    """Extract action-type statistics from winning players' moves.

    Returns dict with:
        - winner_action_counts: {action_type: count} from winners
        - loser_action_counts: {action_type: count} from losers
        - winner_action_values: {action_type: total_value} weighted by outcome
        - games_processed: int
    """
    winner_counts: dict[str, int] = defaultdict(int)
    loser_counts: dict[str, int] = defaultdict(int)
    action_values: dict[str, float] = defaultdict(float)
    action_samples: dict[str, int] = defaultdict(int)
    games_processed = 0
    games_skipped = 0

    for game in games:
        game_id = game["id"]
        state = game.get("game_state") or game.get("latest_state") or {}
        winner_id = state.get("winner") if state else None

        if not winner_id:
            games_skipped += 1
            continue

        # Fetch move history
        try:
            moves = fetch_game_history(base_url, game_id)
        except Exception as e:
            if verbose:
                print(f"  Skipping game {game_id[:8]}: {e}")
            games_skipped += 1
            continue

        if not moves:
            games_skipped += 1
            continue

        # Extract action types per player
        player_actions: dict[str, list[str]] = defaultdict(list)
        for move in moves:
            player_id = move.get("player_id")
            action = move.get("action", {})
            action_type = action.get("type")
            if player_id and action_type:
                player_actions[player_id].append(action_type)

        if not player_actions:
            games_skipped += 1
            continue

        # Winner's actions get positive weight, losers get negative
        for player_id, actions in player_actions.items():
            is_winner = player_id == winner_id
            for atype in actions:
                if is_winner:
                    winner_counts[atype] += 1
                    action_values[atype] += 1.0
                else:
                    loser_counts[atype] += 1
                    action_values[atype] -= 0.3  # smaller penalty for losing
                action_samples[atype] += 1

        games_processed += 1
        if verbose and games_processed % 10 == 0:
            print(f"  Processed {games_processed} games...")

    return {
        "winner_action_counts": dict(winner_counts),
        "loser_action_counts": dict(loser_counts),
        "action_values": dict(action_values),
        "action_samples": dict(action_samples),
        "games_processed": games_processed,
        "games_skipped": games_skipped,
    }


def update_policy(training_data: dict, alpha: float = 0.1) -> dict:
    """Update the OnlinePolicy with training data from real games.

    Uses exponential moving average to blend real-game insights with
    existing self-play learnings.

    Returns the updated policy data dict.
    """
    from ml.mcts import get_online_policy

    policy = get_online_policy()

    action_values = training_data["action_values"]
    action_samples = training_data["action_samples"]

    for atype, total_val in action_values.items():
        samples = action_samples[atype]
        if samples == 0:
            continue

        # Normalize to [0, 1] range
        # raw value: winners add +1, losers add -0.3 per action
        # so max possible avg ~= 1.0 (all winner), min ~= -0.3 (all loser)
        raw_avg = total_val / samples
        normalized = max(0.0, min(1.0, (raw_avg + 0.3) / 1.3))

        old_val = policy.action_values.get(atype, 0.5)
        old_count = policy.action_counts.get(atype, 0)

        if old_count == 0:
            # No prior data — use real game data directly
            policy.action_values[atype] = normalized
        else:
            # Blend with existing policy using EMA
            policy.action_values[atype] = old_val * (1 - alpha) + normalized * alpha

        policy.action_counts[atype] = old_count + samples

    policy.games_played += training_data["games_processed"]
    policy.save()

    return {
        "values": policy.action_values,
        "counts": policy.action_counts,
        "games_played": policy.games_played,
    }


def report(training_data: dict, policy_data: dict):
    """Print a summary of what was learned."""
    print("\n--- Training Summary ---")
    print(
        f"Games processed: {training_data['games_processed']} "
        f"(skipped: {training_data['games_skipped']})"
    )

    print("\nAction frequency (winner vs loser):")
    print(f"  {'Action':<25} {'Winner':>8} {'Loser':>8} {'Win%':>8}")
    print("  " + "-" * 51)

    all_types = sorted(
        set(training_data["winner_action_counts"])
        | set(training_data["loser_action_counts"])
    )
    for atype in all_types:
        w = training_data["winner_action_counts"].get(atype, 0)
        lost = training_data["loser_action_counts"].get(atype, 0)
        total = w + lost
        pct = f"{w / total * 100:.0f}%" if total > 0 else "n/a"
        print(f"  {atype:<25} {w:>8} {lost:>8} {pct:>8}")

    print("\nUpdated policy priors:")
    print(f"  {'Action':<25} {'Prior':>8} {'Samples':>8}")
    print("  " + "-" * 43)
    values = policy_data["values"]
    counts = policy_data["counts"]
    for atype in sorted(values, key=lambda k: values[k], reverse=True):
        print(f"  {atype:<25} {values[atype]:>8.3f} {counts[atype]:>8}")

    print(f"\nTotal games in policy: {policy_data['games_played']}")


def main():
    parser = argparse.ArgumentParser(
        description="Train MCTS bot from production game history"
    )
    parser.add_argument(
        "--url",
        type=str,
        default="https://cheetahmoongames.com",
        help="Base URL of the Bartenders API",
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=100,
        help="Maximum number of ended games to fetch",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.1,
        help="EMA blending factor (higher = more weight to new data)",
    )
    parser.add_argument("--verbose", action="store_true", help="Print progress details")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and analyze data without updating policy",
    )

    args = parser.parse_args()

    print(f"Fetching ended games from {args.url}...")
    games = fetch_ended_games(args.url, max_games=args.max_games)
    print(f"Found {len(games)} ended games")

    if not games:
        print("No games to train from.")
        return

    print("Extracting training data from move histories...")
    training_data = extract_training_data(games, args.url, verbose=args.verbose)

    if training_data["games_processed"] == 0:
        print("No valid games with history found.")
        return

    if args.dry_run:
        print("\n[DRY RUN] Showing analysis without updating policy")
        # Show raw stats without policy update
        report(training_data, {"values": {}, "counts": {}, "games_played": 0})
        return

    print("Updating MCTS policy...")
    policy_data = update_policy(training_data, alpha=args.alpha)
    report(training_data, policy_data)


if __name__ == "__main__":
    main()
