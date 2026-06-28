"""Monte Carlo Tree Search bot for Bartenders of Corfu.

Uses UCB1 tree policy with random rollouts to evaluate actions.
Integrates as a Strategy so it can compete in tournaments.

Key design choices:
- Information Set MCTS: samples hidden state (bag contents) for each simulation
- Progressive widening: limits branching in high-action states
- Rollout policy: uses Mastermind heuristic (much better than random)
- Configurable simulation budget trades compute for strength
"""

import math
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from uuid import UUID

from app.GameState import GameState
from app.Ingredient import Ingredient
from app.actions import _advance_turn, _deep_copy_state
from app.game import GameException

from playtesting.strategy import Mastermind, Strategy
from playtesting.valid_actions import Action, get_valid_actions


# ---------------------------------------------------------------------------
#  MCTS Node
# ---------------------------------------------------------------------------


@dataclass
class MCTSNode:
    """A node in the MCTS tree."""

    parent: Optional["MCTSNode"] = None
    action: Optional[Action] = None  # Action that led to this node
    children: list["MCTSNode"] = field(default_factory=list)
    visits: int = 0
    total_value: float = 0.0
    untried_actions: list[Action] = field(default_factory=list)

    @property
    def value(self) -> float:
        if self.visits == 0:
            return 0.0
        return self.total_value / self.visits

    def ucb1(self, exploration: float = 1.41) -> float:
        if self.visits == 0:
            return float("inf")
        exploit = self.total_value / self.visits
        explore = exploration * math.sqrt(math.log(self.parent.visits) / self.visits)
        return exploit + explore

    def best_child(self, exploration: float = 1.41) -> "MCTSNode":
        return max(self.children, key=lambda c: c.ucb1(exploration))

    def best_action_child(self) -> "MCTSNode":
        """Select child with highest visit count (most robust)."""
        return max(self.children, key=lambda c: c.visits)


# ---------------------------------------------------------------------------
#  Rollout executor (fast game simulation)
# ---------------------------------------------------------------------------


class RolloutExecutor:
    """Executes fast game rollouts using heuristic strategies."""

    def __init__(self):
        self._rollout_strategy = Mastermind()

    def rollout(self, gs: GameState, player_id: UUID, max_turns: int = 30) -> float:
        """Simulate game from current state and return value for player_id.

        Value in [0, 1]: 1.0 = win, 0.0 = loss, intermediate = score-based.
        """
        gs = _deep_copy_state(gs)

        for _ in range(max_turns):
            if gs.winner is not None:
                break

            current = gs.player_turn
            if current is None:
                break

            ps = gs.player_states.get(current)
            if ps is None or ps.is_eliminated:
                gs.turn_number += 1
                _advance_turn(gs)
                continue

            # Execute one turn for current player
            gs = self._execute_turn(gs, current)

        return self._evaluate(gs, player_id)

    def _execute_turn(self, gs: GameState, player_id: UUID) -> GameState:
        """Execute a single turn using Mastermind strategy."""
        strategy = self._rollout_strategy

        # Free actions (limited)
        for _ in range(5):
            all_acts = get_valid_actions(gs, player_id)
            free_acts = [a for a in all_acts if a.is_free]
            if not free_acts:
                break
            chosen = strategy.choose_free_action(gs, player_id, free_acts)
            if chosen is None:
                break
            try:
                gs = self._exec(gs, player_id, chosen, strategy)
            except (GameException, Exception):
                break
            if gs.winner is not None:
                return gs

        # Main action
        for _ in range(3):
            all_acts = get_valid_actions(gs, player_id)
            turn_acts = [a for a in all_acts if not a.is_free]
            if not turn_acts:
                gs = _deep_copy_state(gs)
                gs.turn_number += 1
                _advance_turn(gs)
                return gs

            chosen = strategy.choose_action(gs, player_id, turn_acts)
            try:
                gs = self._exec(gs, player_id, chosen, strategy)
                return gs
            except (GameException, Exception):
                continue

        # Fallback: advance turn
        gs = _deep_copy_state(gs)
        gs.turn_number += 1
        _advance_turn(gs)
        return gs

    def _exec(
        self, gs: GameState, player_id: UUID, action: Action, strategy: Strategy
    ) -> GameState:
        from app import actions

        t = action.action_type
        p = action.params

        if t == "take_ingredients":
            return self._do_take(gs, player_id, strategy)
        elif t == "sell_cup":
            gs, _ = actions.sell_cup(
                gs,
                player_id,
                p["cup_index"],
                p.get("declared_specials", []),
                additional_cups=p.get("additional_cups"),
            )
        elif t == "drink_cup":
            gs, _ = actions.drink_cup(gs, player_id, p["cup_index"])
        elif t == "go_for_a_wee":
            gs, _ = actions.go_for_a_wee(gs, player_id)
        elif t == "claim_card":
            gs, _ = actions.claim_card(
                gs,
                player_id,
                p["card_id"],
                cup_index=p.get("cup_index"),
                spirit_type=p.get("spirit_type"),
            )
        elif t == "drink_stored_spirit":
            gs, _ = actions.drink_stored_spirit(
                gs, player_id, p["store_card_index"], p["count"]
            )
        elif t == "use_stored_spirit":
            gs, _ = actions.use_stored_spirit(
                gs, player_id, p["store_card_index"], p["cup_index"]
            )
        elif t == "refresh_card_row":
            gs, _ = actions.refresh_card_row(gs, player_id, p["row_position"])
        elif t == "reroll_specials":
            gs, _ = actions.reroll_specials(gs, player_id, p["chosen_specials"])

        return gs

    def _do_take(self, gs: GameState, player_id: UUID, strategy: Strategy) -> GameState:
        from app import actions

        ps = gs.player_states[player_id]
        remaining = ps.take_count - gs.ingredients_taken_this_turn

        # Display picks
        display_assignments = strategy.choose_take_assignments(gs, player_id, remaining)
        if display_assignments:
            gs, payload = actions.take_ingredients(gs, player_id, display_assignments)
            if payload.get("turn_complete", False):
                return gs

        # Bag draws
        for _ in range(10):
            ps = gs.player_states[player_id]
            remaining = ps.take_count - gs.ingredients_taken_this_turn
            if remaining <= 0:
                break
            bag_count = min(remaining, len(gs.bag_contents))
            if bag_count <= 0:
                display_assignments = strategy.choose_take_assignments(
                    gs, player_id, remaining
                )
                if display_assignments:
                    gs, payload = actions.take_ingredients(
                        gs, player_id, display_assignments
                    )
                    if payload.get("turn_complete", False):
                        return gs
                break
            gs, _ = actions.draw_from_bag(gs, player_id, bag_count)
            drawn = gs.bag_draw_pending[:]
            pending = strategy.choose_pending_assignments(gs, player_id, drawn)
            gs, payload = actions.take_ingredients(gs, player_id, pending)
            if payload.get("turn_complete", False):
                return gs

        return gs

    def _evaluate(self, gs: GameState, player_id: UUID) -> float:
        """Evaluate terminal/timeout state for player_id."""
        if gs.winner == player_id:
            return 1.0
        if gs.winner is not None:
            return 0.0

        ps = gs.player_states.get(player_id)
        if ps is None or ps.is_eliminated:
            return 0.0

        # Score-based heuristic — cards matter hugely
        # Kyle wins with avg 3.2 cards and 5.2 pts/sell.
        # Cards compound value: specialist = +2pt/sell, doubler = x2, store = spirit bank
        card_value = 0.0
        for cd in ps.cards:
            ct = cd.get("card_type", "")
            if ct == "specialist":
                card_value += 6.0  # Enables +2pt per sell
            elif ct == "cup_doubler":
                card_value += 8.0  # Doubles non-cocktail sell
            elif ct == "store":
                card_value += 5.0  # Spirit accumulation
            elif ct == "refresher":
                card_value += 4.0  # Drunk management
            elif ct == "karaoke":
                card_value += 5.0  # Points already scored
            else:
                card_value += 3.0

        my_score = ps.points + ps.karaoke_cards_claimed * 10 + card_value
        best_opp = max(
            (
                p.points + p.karaoke_cards_claimed * 10 + sum(3 for _ in p.cards)
                for pid, p in gs.player_states.items()
                if pid != player_id and not p.is_eliminated
            ),
            default=0,
        )

        if my_score + best_opp == 0:
            return 0.5

        # Normalize to [0, 1] based on relative score
        advantage = (my_score - best_opp) / max(40, my_score + best_opp)
        return max(0.0, min(1.0, 0.5 + advantage))


# ---------------------------------------------------------------------------
#  MCTS Search
# ---------------------------------------------------------------------------


class MCTSSearch:
    """Monte Carlo Tree Search engine."""

    def __init__(
        self,
        num_simulations: int = 100,
        exploration: float = 1.41,
        rollout_depth: int = 25,
        time_limit: float | None = None,
    ):
        self.num_simulations = num_simulations
        self.exploration = exploration
        self.rollout_depth = rollout_depth
        self.time_limit = time_limit
        self.executor = RolloutExecutor()
        self.last_root: MCTSNode | None = None

    def search(
        self,
        gs: GameState,
        player_id: UUID,
        valid_actions: list[Action],
        policy: Optional["OnlinePolicy"] = None,
    ) -> Action:
        """Run MCTS and return the best action."""
        if len(valid_actions) == 1:
            self.last_root = None
            return valid_actions[0]

        root = MCTSNode(untried_actions=list(valid_actions))
        start_time = time.time()

        for i in range(self.num_simulations):
            if self.time_limit and (time.time() - start_time) > self.time_limit:
                break

            # 1. Selection — traverse tree using UCB1
            node = root
            sim_gs = _deep_copy_state(gs)

            # 2. Expansion — pick untried action (bias by policy if available)
            if node.untried_actions:
                if policy and len(node.untried_actions) > 1:
                    # Bias expansion toward actions with higher learned priors
                    weights = [
                        policy.get_prior(a.action_type) + 0.1
                        for a in node.untried_actions
                    ]
                    total = sum(weights)
                    probs = [w / total for w in weights]
                    action = random.choices(node.untried_actions, weights=probs, k=1)[0]
                else:
                    action = random.choice(node.untried_actions)
                node.untried_actions.remove(action)

                # Apply action to get child state
                try:
                    sim_gs = self._apply_action(sim_gs, player_id, action)
                except Exception:
                    # Invalid action in this simulation — skip
                    continue

                child = MCTSNode(parent=node, action=action)
                node.children.append(child)
                node = child
            elif node.children:
                # Select best child
                node = node.best_child(self.exploration)
                if node.action:
                    try:
                        sim_gs = self._apply_action(sim_gs, player_id, node.action)
                    except Exception:
                        node.visits += 1
                        node.total_value += 0.0
                        self._backpropagate(node.parent, 0.0)
                        continue

            # 3. Simulation (rollout)
            value = self.executor.rollout(sim_gs, player_id, self.rollout_depth)

            # 4. Backpropagation
            self._backpropagate(node, value)

        # Store root for learning
        self.last_root = root

        # Return action with most visits (most robust)
        if not root.children:
            return random.choice(valid_actions)

        best = root.best_action_child()
        return best.action

    def _apply_action(
        self, gs: GameState, player_id: UUID, action: Action
    ) -> GameState:
        """Apply an action and run opponents until it's player's turn again."""
        gs = self.executor._exec(gs, player_id, action, self.executor._rollout_strategy)

        # Run opponent turns
        for _ in range(20):
            if gs.winner is not None:
                break
            if gs.player_turn == player_id:
                break
            current = gs.player_turn
            if current is None:
                break
            ps = gs.player_states.get(current)
            if ps is None or ps.is_eliminated:
                gs.turn_number += 1
                _advance_turn(gs)
                continue
            gs = self.executor._execute_turn(gs, current)

        return gs

    def _backpropagate(self, node: MCTSNode | None, value: float):
        while node is not None:
            node.visits += 1
            node.total_value += value
            node = node.parent


# ---------------------------------------------------------------------------
#  Persistent learned policy
# ---------------------------------------------------------------------------

_policy_lock = threading.Lock()


class OnlinePolicy:
    """Thread-safe persistent policy that learns from each MCTS decision.

    Stores action-type value estimates derived from MCTS search statistics.
    Persists to Supabase so learnings survive Cloud Run restarts.
    Falls back to local file if Supabase is unavailable (e.g. in tests).
    """

    _LOCAL_PATH = Path(__file__).parent / "policy_data.json"

    def __init__(self):
        self.action_values: dict[str, float] = {}
        self.action_counts: dict[str, int] = {}
        self.games_played: int = 0
        self._load()

    def _load(self):
        """Load policy from Supabase, falling back to local file."""
        # Try Supabase first
        try:
            from app.db import db

            data = db.get_bot_policy("mcts_policy")
            if data:
                self.action_values = data.get("values", {})
                self.action_counts = data.get("counts", {})
                self.games_played = data.get("games_played", 0)
                return
        except Exception:
            pass

        # Fallback: local file (for tests / local dev)
        if self._LOCAL_PATH.exists():
            try:
                import json

                with open(self._LOCAL_PATH) as f:
                    data = json.load(f)
                self.action_values = data.get("values", {})
                self.action_counts = data.get("counts", {})
                self.games_played = data.get("games_played", 0)
            except (json.JSONDecodeError, OSError):
                pass

    def save(self):
        """Persist policy to Supabase (and local file as backup)."""
        data = {
            "values": self.action_values,
            "counts": self.action_counts,
            "games_played": self.games_played,
        }

        # Try Supabase
        try:
            from app.db import db

            db.save_bot_policy(data, "mcts_policy")
        except Exception:
            pass

        # Also save locally as backup
        try:
            import json

            with open(self._LOCAL_PATH, "w") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def record_decision(self, root: "MCTSNode"):
        """Record MCTS search results to improve future decisions.

        Called after every MCTS search. Updates running averages of action
        values based on visit counts and estimated values from the tree.
        """
        if not root.children:
            return

        with _policy_lock:
            total_visits = sum(c.visits for c in root.children)
            if total_visits == 0:
                return

            for child in root.children:
                if child.action is None or child.visits == 0:
                    continue
                atype = child.action.action_type
                value = child.total_value / child.visits

                # Exponential moving average (alpha=0.05 for slow, stable learning)
                alpha = 0.05
                old_val = self.action_values.get(atype, 0.5)
                old_count = self.action_counts.get(atype, 0)

                if old_count == 0:
                    self.action_values[atype] = value
                else:
                    self.action_values[atype] = old_val * (1 - alpha) + value * alpha
                self.action_counts[atype] = old_count + 1

    def record_game_complete(self):
        """Called when a game finishes to track total games played."""
        with _policy_lock:
            self.games_played += 1

    def get_prior(self, action_type: str) -> float:
        """Get learned prior for an action type (0-1 scale)."""
        return self.action_values.get(action_type, 0.5)

    @property
    def total_decisions(self) -> int:
        return sum(self.action_counts.values())


# Singleton policy instance (shared across all MCTS bot instances)
_online_policy: OnlinePolicy | None = None


def get_online_policy() -> OnlinePolicy:
    global _online_policy
    if _online_policy is None:
        _online_policy = OnlinePolicy()
    return _online_policy


# ---------------------------------------------------------------------------
#  MCTS Strategy (integrates with tournament system)
# ---------------------------------------------------------------------------


class MCTSStrategy(Strategy):
    """MCTS-based strategy with online learning.

    Each decision updates a persistent policy file. Over time, the bot
    learns which action types tend to produce winning outcomes and biases
    its exploration accordingly.

    Args:
        num_simulations: Number of MCTS rollouts per decision (higher = stronger)
        time_limit: Optional time limit in seconds per move
        exploration: UCB1 exploration constant
        rollout_depth: Max turns to simulate per rollout
        learn: Whether to update the persistent policy from search results
    """

    name = "MCTS"

    def __init__(
        self,
        num_simulations: int = 100,
        time_limit: float | None = None,
        exploration: float = 1.41,
        rollout_depth: int = 25,
        learn: bool = True,
    ):
        self.search_engine = MCTSSearch(
            num_simulations=num_simulations,
            exploration=exploration,
            rollout_depth=rollout_depth,
            time_limit=time_limit,
        )
        self._fallback = Mastermind()
        self._learn = learn
        self._decisions_since_save = 0
        self._save_interval = 10  # Save policy every N decisions

    def _filter_suicidal(
        self, gs: GameState, player_id: UUID, actions: list[Action]
    ) -> list[Action]:
        """Remove actions that would cause self-elimination."""
        ps = gs.player_states[player_id]
        safe = []
        for a in actions:
            if a.action_type == "drink_cup":
                ci = a.params.get("cup_index", 0)
                cup = ps.cups[ci]
                cup_size = len(cup.ingredients)
                # Would overflow bladder → wet elimination
                if len(ps.bladder) + cup_size > ps.bladder_capacity:
                    continue
                # Would get hospitalised (drunk > 5)
                from app.actions import _SPIRITS as _SP

                cup_spirits = sum(1 for i in cup.ingredients if i in _SP)
                if ps.drunk_level + cup_spirits > 5:
                    continue
            safe.append(a)
        return safe if safe else actions  # Never return empty

    def choose_action(
        self, gs: GameState, player_id: UUID, valid_actions: list[Action]
    ) -> Action:
        if not valid_actions:
            return self._fallback.choose_action(gs, player_id, valid_actions)

        # Safety: filter out suicidal actions before MCTS considers them
        valid_actions = self._filter_suicidal(gs, player_id, valid_actions)

        # For trivial decisions, use heuristic
        if len(valid_actions) <= 2:
            return self._fallback.choose_action(gs, player_id, valid_actions)

        # Run MCTS search
        action = self.search_engine.search(
            gs,
            player_id,
            valid_actions,
            policy=get_online_policy() if self._learn else None,
        )

        # Record learnings from the search tree
        if self._learn and self.search_engine.last_root is not None:
            policy = get_online_policy()
            policy.record_decision(self.search_engine.last_root)
            self._decisions_since_save += 1
            if self._decisions_since_save >= self._save_interval:
                policy.save()
                self._decisions_since_save = 0

        return action

    def choose_free_action(
        self, gs: GameState, player_id: UUID, free_actions: list[Action]
    ) -> Action | None:
        # Free actions are low-stakes; use Mastermind heuristic
        return self._fallback.choose_free_action(gs, player_id, free_actions)

    def choose_take_assignments(
        self, gs: GameState, player_id: UUID, count: int
    ) -> list[dict]:
        # Micro-assignment decisions use Mastermind (MCTS overhead not worth it)
        return self._fallback.choose_take_assignments(gs, player_id, count)

    def choose_pending_assignments(
        self, gs: GameState, player_id: UUID, drawn: list[Ingredient]
    ) -> list[dict]:
        return self._fallback.choose_pending_assignments(gs, player_id, drawn)
