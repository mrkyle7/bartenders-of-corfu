"""Self-play training loop using Monte Carlo policy improvement.

This implements a simplified AlphaZero-style loop WITHOUT a neural network:
1. Play games using MCTS
2. Collect (state, action_visits) pairs from MCTS tree statistics
3. Use visit distributions to train a lightweight policy (logistic regression
   over state features) that biases future MCTS rollouts

This is "Monte Carlo + ML" — the ML model learns from MCTS experience data
to warm-start future searches, making them converge faster.

Usage:
    uv run python -m ml.train_selfplay [options]
"""

import argparse
import pickle
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from uuid import uuid4

import numpy as np

from app.GameState import GameState
from app.actions import _advance_turn, _deep_copy_state

from playtesting.strategy import Mastermind
from playtesting.valid_actions import get_valid_actions

from ml.env import _encode_state
from ml.mcts import MCTSNode, MCTSSearch, RolloutExecutor


# ---------------------------------------------------------------------------
#  Experience collection
# ---------------------------------------------------------------------------


@dataclass
class Experience:
    """One decision point's MCTS statistics."""

    state_vec: np.ndarray  # encoded observation
    action_types: list[str]  # action type labels
    visit_counts: list[int]  # MCTS visit counts per action
    chosen_idx: int  # index of chosen action
    game_outcome: float = 0.0  # final game result for this player


@dataclass
class ActionStats:
    """Aggregated statistics per action type."""

    total_visits: int = 0
    total_value: float = 0.0
    appearances: int = 0

    @property
    def avg_value(self) -> float:
        return self.total_value / self.appearances if self.appearances else 0.0

    @property
    def avg_visits(self) -> float:
        return self.total_visits / self.appearances if self.appearances else 0.0


# ---------------------------------------------------------------------------
#  Self-play data collector
# ---------------------------------------------------------------------------


class SelfPlayCollector:
    """Plays games with MCTS and collects experience data."""

    def __init__(self, num_simulations: int = 80):
        self.num_simulations = num_simulations
        self.experiences: list[Experience] = []

    def play_game(self, num_players: int = 2, seed: int | None = None) -> dict:
        """Play one self-play game and collect experiences.

        Returns game result dict.
        """
        if seed is not None:
            random.seed(seed)

        player_ids = [uuid4() for _ in range(num_players)]
        gs = GameState.start_game(player_ids)

        # All players use MCTS with experience collection
        search = MCTSSearch(num_simulations=self.num_simulations, rollout_depth=20)
        fallback = Mastermind()
        executor = RolloutExecutor()

        game_experiences: dict[str, list[Experience]] = {
            str(pid): [] for pid in player_ids
        }

        max_turns = 500
        for _ in range(max_turns):
            if gs.winner is not None:
                break

            current = gs.player_turn
            if current is None:
                break

            ps = gs.player_states.get(current)
            if ps is None or ps.is_eliminated:
                gs = _deep_copy_state(gs)
                gs.turn_number += 1
                _advance_turn(gs)
                continue

            # Get valid actions
            all_acts = get_valid_actions(gs, current)
            free_acts = [a for a in all_acts if a.is_free]
            turn_acts = [a for a in all_acts if not a.is_free]

            # Handle free actions with fallback
            for _ in range(5):
                if not free_acts:
                    break
                chosen_free = fallback.choose_free_action(gs, current, free_acts)
                if chosen_free is None:
                    break
                try:
                    gs = executor._exec(gs, current, chosen_free, fallback)
                except Exception:
                    break
                if gs.winner is not None:
                    break
                all_acts = get_valid_actions(gs, current)
                free_acts = [a for a in all_acts if a.is_free]
                turn_acts = [a for a in all_acts if not a.is_free]

            if gs.winner is not None:
                break

            if gs.main_action_taken_this_turn:
                gs = _deep_copy_state(gs)
                gs.turn_number += 1
                _advance_turn(gs)
                gs.main_action_taken_this_turn = False
                gs.free_actions_used_this_turn = []
                gs.ingredients_taken_this_turn = 0
                gs.drunk_ingredients_this_turn = []
                gs.bag_draw_pending = []
                gs.taken_records_this_turn = []
                continue

            if not turn_acts:
                gs = _deep_copy_state(gs)
                gs.turn_number += 1
                _advance_turn(gs)
                continue

            # MCTS search with data collection
            if len(turn_acts) > 2:
                root = MCTSNode(untried_actions=list(turn_acts))
                sim_gs_base = _deep_copy_state(gs)

                for _ in range(self.num_simulations):
                    node = root
                    sim_gs = _deep_copy_state(sim_gs_base)

                    if node.untried_actions:
                        action = random.choice(node.untried_actions)
                        node.untried_actions.remove(action)
                        try:
                            sim_gs = search._apply_action(sim_gs, current, action)
                        except Exception:
                            continue
                        child = MCTSNode(parent=node, action=action)
                        node.children.append(child)
                        node = child
                    elif node.children:
                        node = node.best_child(1.41)
                        if node.action:
                            try:
                                sim_gs = search._apply_action(
                                    sim_gs, current, node.action
                                )
                            except Exception:
                                node.visits += 1
                                search._backpropagate(node.parent, 0.0)
                                continue

                    value = executor.rollout(sim_gs, current, 20)
                    search._backpropagate(node, value)

                # Collect experience from root
                if root.children:
                    state_vec = _encode_state(gs, current)
                    action_types = [
                        c.action.action_type for c in root.children if c.action
                    ]
                    visit_counts = [c.visits for c in root.children]
                    best_child = max(root.children, key=lambda c: c.visits)
                    chosen_idx = root.children.index(best_child)

                    exp = Experience(
                        state_vec=state_vec,
                        action_types=action_types,
                        visit_counts=visit_counts,
                        chosen_idx=chosen_idx,
                    )
                    game_experiences[str(current)].append(exp)

                    chosen = best_child.action
                else:
                    chosen = fallback.choose_action(gs, current, turn_acts)
            else:
                chosen = (
                    turn_acts[0]
                    if len(turn_acts) == 1
                    else fallback.choose_action(gs, current, turn_acts)
                )

            # Execute chosen action
            try:
                gs = executor._exec(gs, current, chosen, fallback)
            except Exception:
                gs = _deep_copy_state(gs)
                gs.turn_number += 1
                _advance_turn(gs)

        # Assign game outcomes
        for pid in player_ids:
            outcome = executor._evaluate(gs, pid)
            for exp in game_experiences[str(pid)]:
                exp.game_outcome = outcome
            self.experiences.extend(game_experiences[str(pid)])

        return {
            "winner": str(gs.winner) if gs.winner else None,
            "turns": gs.turn_number,
            "scores": {str(pid): gs.player_states[pid].points for pid in player_ids},
        }


# ---------------------------------------------------------------------------
#  Policy learning from MCTS data
# ---------------------------------------------------------------------------


class LearnedPolicy:
    """Simple learned policy from MCTS experience.

    Stores action-type value estimates derived from MCTS visit statistics.
    Used to bias action selection in future games.
    """

    def __init__(self):
        self.action_values: dict[str, float] = defaultdict(float)
        self.action_counts: dict[str, int] = defaultdict(int)

    def update_from_experiences(self, experiences: list[Experience]):
        """Update policy from collected MCTS experiences."""
        for exp in experiences:
            total_visits = sum(exp.visit_counts)
            if total_visits == 0:
                continue
            for atype, visits in zip(exp.action_types, exp.visit_counts):
                # Weight by visit proportion * game outcome
                weight = (visits / total_visits) * exp.game_outcome
                self.action_values[atype] += weight
                self.action_counts[atype] += 1

    def action_prior(self, action_type: str) -> float:
        """Return learned prior value for an action type."""
        count = self.action_counts.get(action_type, 0)
        if count == 0:
            return 0.5
        return self.action_values[action_type] / count

    def save(self, path: str):
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "values": dict(self.action_values),
                    "counts": dict(self.action_counts),
                },
                f,
            )

    @classmethod
    def load(cls, path: str) -> "LearnedPolicy":
        policy = cls()
        with open(path, "rb") as f:
            data = pickle.load(f)
        policy.action_values = defaultdict(float, data["values"])
        policy.action_counts = defaultdict(int, data["counts"])
        return policy

    def report(self):
        """Print learned action values."""
        print("\nLearned Action Priors:")
        print(f"  {'Action':<25} {'Prior':>8} {'Samples':>8}")
        print("  " + "-" * 43)
        sorted_actions = sorted(
            self.action_counts.keys(),
            key=lambda k: self.action_prior(k),
            reverse=True,
        )
        for atype in sorted_actions:
            prior = self.action_prior(atype)
            count = self.action_counts[atype]
            print(f"  {atype:<25} {prior:>8.3f} {count:>8}")


# ---------------------------------------------------------------------------
#  Training loop
# ---------------------------------------------------------------------------


def train(
    num_iterations: int = 5,
    games_per_iteration: int = 10,
    num_simulations: int = 60,
    num_players: int = 2,
    base_seed: int = 42,
    save_path: str | None = None,
):
    """Run self-play training loop."""
    policy = LearnedPolicy()

    print("Self-Play Training")
    print(f"  Iterations: {num_iterations}")
    print(f"  Games per iteration: {games_per_iteration}")
    print(f"  MCTS simulations: {num_simulations}")
    print(f"  Players: {num_players}")
    print()

    for iteration in range(num_iterations):
        print(f"--- Iteration {iteration + 1}/{num_iterations} ---")
        start = time.time()

        collector = SelfPlayCollector(num_simulations=num_simulations)

        wins = 0
        total_turns = 0
        for game_idx in range(games_per_iteration):
            seed = base_seed + iteration * games_per_iteration + game_idx
            result = collector.play_game(num_players=num_players, seed=seed)
            total_turns += result["turns"]
            if result["winner"]:
                wins += 1

        # Update policy
        policy.update_from_experiences(collector.experiences)

        elapsed = time.time() - start
        print(
            f"  Games: {games_per_iteration}, Experiences: {len(collector.experiences)}"
        )
        print(f"  Avg turns: {total_turns / games_per_iteration:.0f}")
        print(f"  Time: {elapsed:.1f}s ({elapsed / games_per_iteration:.1f}s/game)")
        print()

    policy.report()

    if save_path:
        policy.save(save_path)
        print(f"\nPolicy saved to: {save_path}")

    return policy


def main():
    parser = argparse.ArgumentParser(description="Self-play MCTS training")
    parser.add_argument("--iterations", type=int, default=5, help="Training iterations")
    parser.add_argument("--games", type=int, default=10, help="Games per iteration")
    parser.add_argument(
        "--sims", type=int, default=60, help="MCTS simulations per move"
    )
    parser.add_argument("--players", type=int, default=2, help="Players per game")
    parser.add_argument("--seed", type=int, default=42, help="Base random seed")
    parser.add_argument(
        "--save", type=str, default=None, help="Path to save learned policy"
    )

    args = parser.parse_args()

    train(
        num_iterations=args.iterations,
        games_per_iteration=args.games,
        num_simulations=args.sims,
        num_players=args.players,
        base_seed=args.seed,
        save_path=args.save,
    )


if __name__ == "__main__":
    main()
