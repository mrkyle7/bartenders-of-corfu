"""Gymnasium environment for Bartenders of Corfu.

Wraps the game engine as a single-agent environment. The agent controls one
player; opponents use a configurable Strategy (default: Mastermind).

Observation: flattened numeric vector of all visible game state.
Action: discrete index into the list of valid actions at each step.
"""

import random as _random
from uuid import UUID, uuid4

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import (
    INITIAL_BLADDER_CAPACITY,
    INITIAL_TOILET_TOKENS,
    MAX_CUP_INGREDIENTS,
)
from app.actions import MAX_DRUNK_LEVEL, SCORE_TO_WIN

from playtesting.strategy import Mastermind, Strategy
from playtesting.valid_actions import Action, get_valid_actions

# Indices for encoding ingredients
_INGREDIENT_INDEX: dict[Ingredient, int] = {
    Ingredient.WHISKEY: 0,
    Ingredient.GIN: 1,
    Ingredient.RUM: 2,
    Ingredient.TEQUILA: 3,
    Ingredient.VODKA: 4,
    Ingredient.COLA: 5,
    Ingredient.SODA: 6,
    Ingredient.TONIC: 7,
    Ingredient.CRANBERRY: 8,
    Ingredient.SPECIAL: 9,
}
NUM_INGREDIENTS = 10

# Maximum actions we'll expose (padded with no-ops if fewer are valid)
MAX_ACTIONS = 64


def _encode_state(gs: GameState, player_id: UUID) -> np.ndarray:
    """Encode visible game state as a flat float32 vector.

    Layout (total ~180 floats):
    - Player state: points, drunk, bladder counts, cup contents, cards, etc.
    - Opponent summaries: points, drunk, status for each opponent
    - Board: open display counts, bag size, card rows summary
    """
    ps = gs.player_states[player_id]
    obs = []

    # --- Player scalars (normalized) ---
    obs.append(ps.points / SCORE_TO_WIN)
    obs.append(ps.drunk_level / (MAX_DRUNK_LEVEL + 1))
    obs.append(len(ps.bladder) / INITIAL_BLADDER_CAPACITY)
    obs.append(ps.bladder_capacity / INITIAL_BLADDER_CAPACITY)
    obs.append(ps.toilet_tokens / INITIAL_TOILET_TOKENS)
    obs.append(ps.karaoke_cards_claimed / 3.0)
    obs.append(1.0 if ps.status == "active" else 0.0)
    obs.append(ps.take_count / 10.0)

    # --- Bladder composition (count of each ingredient type) ---
    bladder_counts = [0] * NUM_INGREDIENTS
    for ing in ps.bladder:
        idx = _INGREDIENT_INDEX.get(ing)
        if idx is not None:
            bladder_counts[idx] += 1
    obs.extend([c / INITIAL_BLADDER_CAPACITY for c in bladder_counts])

    # --- Cup contents (2 cups × ingredient counts) ---
    for cup in ps.cups:
        cup_counts = [0] * NUM_INGREDIENTS
        for ing in cup.ingredients:
            idx = _INGREDIENT_INDEX.get(ing)
            if idx is not None:
                cup_counts[idx] += 1
        obs.extend([c / MAX_CUP_INGREDIENTS for c in cup_counts])
        obs.append(1.0 if cup.has_cup_doubler else 0.0)

    # --- Special ingredients on mat ---
    special_types = ["bitters", "cointreau", "lemon", "sugar", "vermouth"]
    special_counts = [0] * 5
    for s in ps.special_ingredients:
        for i, st in enumerate(special_types):
            if s == st:
                special_counts[i] += 1
                break
    obs.extend([c / 3.0 for c in special_counts])

    # --- Cards held (count by type) ---
    card_type_counts = {
        "karaoke": 0,
        "store": 0,
        "refresher": 0,
        "cup_doubler": 0,
        "specialist": 0,
        "free_action": 0,
    }
    for cd in ps.cards:
        ct = cd.get("card_type", "")
        if ct in card_type_counts:
            card_type_counts[ct] += 1
    obs.extend([card_type_counts[k] / 3.0 for k in card_type_counts])

    # --- Opponents (up to 3, padded) ---
    opponents = [p for pid, p in gs.player_states.items() if pid != player_id]
    for i in range(3):
        if i < len(opponents):
            opp = opponents[i]
            obs.append(opp.points / SCORE_TO_WIN)
            obs.append(opp.drunk_level / (MAX_DRUNK_LEVEL + 1))
            obs.append(len(opp.bladder) / INITIAL_BLADDER_CAPACITY)
            obs.append(opp.karaoke_cards_claimed / 3.0)
            obs.append(0.0 if opp.status == "active" else 1.0)
        else:
            obs.extend([0.0] * 5)

    # --- Board: open display composition ---
    display_counts = [0] * NUM_INGREDIENTS
    for ing in gs.open_display:
        idx = _INGREDIENT_INDEX.get(ing)
        if idx is not None:
            display_counts[idx] += 1
    obs.extend([c / 5.0 for c in display_counts])

    # --- Bag size (normalized by initial) ---
    obs.append(len(gs.bag_contents) / 100.0)

    # --- Card rows summary (3 rows × cards present, karaoke count) ---
    for row_idx in range(3):
        if row_idx < len(gs.card_rows):
            row = gs.card_rows[row_idx]
            obs.append(len(row.cards) / 3.0)
            karaoke_in_row = sum(1 for c in row.cards if c.card_type == "karaoke")
            obs.append(karaoke_in_row / 3.0)
        else:
            obs.extend([0.0, 0.0])

    # --- Turn progress ---
    obs.append(gs.ingredients_taken_this_turn / 10.0)
    obs.append(1.0 if gs.main_action_taken_this_turn else 0.0)
    obs.append(gs.turn_number / 500.0)

    return np.array(obs, dtype=np.float32)


# Observation size is fixed
_DUMMY_OBS_SIZE = len(
    _encode_state.__code__.co_varnames
)  # placeholder; computed at init


class BartendersEnv(gym.Env):
    """Single-agent Gymnasium env for Bartenders of Corfu.

    The agent picks from valid actions each step. Invalid action indices
    map to a random valid action (masked).

    Args:
        opponent_strategy: Strategy class for opponent bots (default Mastermind)
        num_players: Total players including the agent (2-4)
        seed: Random seed for reproducibility
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        opponent_strategy: type[Strategy] | None = None,
        num_players: int = 4,
        seed: int | None = None,
        render_mode: str | None = None,
    ):
        super().__init__()
        self.opponent_strategy_cls = opponent_strategy or Mastermind
        self.num_players = num_players
        self._seed = seed
        self.render_mode = render_mode

        # Compute observation size from a dummy state
        self._obs_size = self._compute_obs_size()

        self.observation_space = spaces.Dict(
            {
                "obs": spaces.Box(
                    low=0.0, high=10.0, shape=(self._obs_size,), dtype=np.float32
                ),
                "action_mask": spaces.MultiBinary(MAX_ACTIONS),
            }
        )
        self.action_space = spaces.Discrete(MAX_ACTIONS)

        self.gs: GameState | None = None
        self.agent_id: UUID | None = None
        self.opponent_ids: list[UUID] = []
        self.opponent_strategies: dict[UUID, Strategy] = {}
        self._valid_actions: list[Action] = []
        self._prev_points: int = 0

    def _compute_obs_size(self) -> int:
        """Run encode on a dummy game to get vector size."""
        player_ids = [uuid4() for _ in range(self.num_players)]
        gs = GameState.start_game(player_ids)
        obs = _encode_state(gs, player_ids[0])
        return len(obs)

    def reset(
        self, *, seed: int | None = None, options: dict | None = None
    ) -> tuple[dict, dict]:
        if seed is not None:
            self._seed = seed
        if self._seed is not None:
            _random.seed(self._seed)
            np.random.seed(self._seed)

        # Create players
        player_ids = [uuid4() for _ in range(self.num_players)]
        self.agent_id = player_ids[0]
        self.opponent_ids = player_ids[1:]

        # Start game
        self.gs = GameState.start_game(player_ids)

        # Set up opponent strategies
        self.opponent_strategies = {
            pid: self.opponent_strategy_cls() for pid in self.opponent_ids
        }

        # If it's not the agent's turn, run opponents first
        self._run_opponents()

        self._prev_points = 0
        self._valid_actions = get_valid_actions(self.gs, self.agent_id)

        return self._get_obs(), {}

    def step(self, action: int) -> tuple[dict, float, bool, bool, dict]:
        """Execute one action for the agent.

        Returns (obs, reward, terminated, truncated, info)
        """
        if self.gs is None or self.gs.winner is not None:
            return self._get_obs(), 0.0, True, False, {}

        # Map action index to valid action
        if not self._valid_actions:
            # No valid actions — shouldn't happen, but handle gracefully
            return self._get_obs(), 0.0, False, True, {"error": "no_valid_actions"}

        action_idx = action % len(self._valid_actions)
        chosen = self._valid_actions[action_idx]

        # Execute the action
        try:
            self.gs = self._execute_agent_action(chosen)
        except Exception as e:
            # Action failed — small penalty, pick random valid action
            if self._valid_actions:
                fallback = _random.choice(self._valid_actions)
                try:
                    self.gs = self._execute_agent_action(fallback)
                except Exception:
                    pass
            return self._get_obs(), -1.0, False, False, {"error": str(e)}

        # Check termination
        terminated = self.gs.winner is not None
        if terminated:
            # Big reward for winning, penalty for losing
            if self.gs.winner == self.agent_id:
                reward = 100.0
            else:
                reward = -50.0
            return self._get_obs(), reward, True, False, {"winner": str(self.gs.winner)}

        # Check if agent is eliminated
        ps = self.gs.player_states.get(self.agent_id)
        if ps and ps.is_eliminated:
            return self._get_obs(), -80.0, True, False, {"eliminated": ps.status}

        # Run opponents' turns
        self._run_opponents()

        # Check post-opponent termination
        if self.gs.winner is not None:
            if self.gs.winner == self.agent_id:
                reward = 100.0
            else:
                reward = -50.0
            return self._get_obs(), reward, True, False, {}

        # Reward = points gained this step
        ps = self.gs.player_states[self.agent_id]
        reward = float(ps.points - self._prev_points) * 2.0
        self._prev_points = ps.points

        # Small survival bonus
        reward += 0.1

        # Truncation check (game too long)
        truncated = self.gs.turn_number >= 500

        self._valid_actions = get_valid_actions(self.gs, self.agent_id)

        return self._get_obs(), reward, False, truncated, {}

    def _get_obs(self) -> dict:
        if self.gs is None:
            obs = np.zeros(self._obs_size, dtype=np.float32)
            mask = np.zeros(MAX_ACTIONS, dtype=np.int8)
        else:
            obs = _encode_state(self.gs, self.agent_id)
            mask = np.zeros(MAX_ACTIONS, dtype=np.int8)
            for i in range(min(len(self._valid_actions), MAX_ACTIONS)):
                mask[i] = 1
            if mask.sum() == 0:
                mask[0] = 1  # fallback
        return {"obs": obs, "action_mask": mask}

    def _execute_agent_action(self, action: Action) -> GameState:
        """Execute an action using the game runner's logic."""
        from app import actions

        t = action.action_type
        p = action.params
        gs = self.gs
        pid = self.agent_id

        if t == "take_ingredients":
            return self._execute_take(gs, pid)
        elif t == "sell_cup":
            gs, _ = actions.sell_cup(
                gs,
                pid,
                p["cup_index"],
                p.get("declared_specials", []),
                additional_cups=p.get("additional_cups"),
            )
        elif t == "drink_cup":
            gs, _ = actions.drink_cup(gs, pid, p["cup_index"])
        elif t == "go_for_a_wee":
            gs, _ = actions.go_for_a_wee(gs, pid)
        elif t == "claim_card":
            gs, _ = actions.claim_card(
                gs,
                pid,
                p["card_id"],
                cup_index=p.get("cup_index"),
                spirit_type=p.get("spirit_type"),
            )
        elif t == "drink_stored_spirit":
            gs, _ = actions.drink_stored_spirit(
                gs, pid, p["store_card_index"], p["count"]
            )
        elif t == "use_stored_spirit":
            gs, _ = actions.use_stored_spirit(
                gs, pid, p["store_card_index"], p["cup_index"]
            )
        elif t == "refresh_card_row":
            gs, _ = actions.refresh_card_row(gs, pid, p["row_position"])
        elif t == "reroll_specials":
            gs, _ = actions.reroll_specials(gs, pid, p["chosen_specials"])
        else:
            raise ValueError(f"Unknown action: {t}")

        return gs

    def _execute_take(self, gs: GameState, player_id: UUID) -> GameState:
        """Execute take_ingredients using a simple heuristic for assignments.

        For the agent, we use the Mastermind's assignment logic since the
        MCTS/RL bot only decides WHEN to take, not the micro-assignments.
        """
        from app import actions

        strategy = Mastermind()
        ps = gs.player_states[player_id]
        remaining = ps.take_count - gs.ingredients_taken_this_turn

        # Phase 1: display picks
        display_assignments = strategy.choose_take_assignments(gs, player_id, remaining)
        if display_assignments:
            gs, payload = actions.take_ingredients(gs, player_id, display_assignments)
            if payload.get("turn_complete", False):
                return gs

        # Phase 2: bag draws
        for _ in range(10):
            ps = gs.player_states[player_id]
            remaining = ps.take_count - gs.ingredients_taken_this_turn
            if remaining <= 0:
                break

            bag_count = min(remaining, len(gs.bag_contents))
            if bag_count <= 0:
                # Try display again
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

    def _run_opponents(self):
        """Run opponent turns until it's the agent's turn again."""
        from app.actions import _advance_turn, _deep_copy_state

        max_opp_turns = 50  # safety limit
        for _ in range(max_opp_turns):
            if self.gs.winner is not None:
                return
            if self.gs.player_turn == self.agent_id:
                return

            current = self.gs.player_turn
            if current is None:
                return

            ps = self.gs.player_states.get(current)
            if ps is None or ps.is_eliminated:
                # Skip eliminated player
                self.gs = _deep_copy_state(self.gs)
                self.gs.turn_number += 1
                _advance_turn(self.gs)
                continue

            strategy = self.opponent_strategies.get(current)
            if strategy is None:
                return

            # Execute opponent turn using runner logic
            try:
                self.gs = self._execute_opponent_turn(current, strategy)
            except Exception:
                # Force advance on error
                self.gs = _deep_copy_state(self.gs)
                self.gs.turn_number += 1
                _advance_turn(self.gs)

    def _execute_opponent_turn(self, player_id: UUID, strategy: Strategy) -> GameState:
        """Execute a full opponent turn (free actions + main)."""
        from app.actions import _advance_turn, _deep_copy_state
        from app.game import GameException

        gs = self.gs

        # Free actions
        for _ in range(20):
            all_acts = get_valid_actions(gs, player_id)
            free_acts = [a for a in all_acts if a.is_free]
            if not free_acts:
                break
            chosen = strategy.choose_free_action(gs, player_id, free_acts)
            if chosen is None:
                break
            try:
                gs = self._execute_action_for(gs, player_id, chosen, strategy)
            except GameException:
                break
            if gs.winner is not None:
                return gs

        # Check if main already taken
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
                gs = self._execute_action_for(gs, player_id, chosen, strategy)
                return gs
            except GameException:
                continue

        # Exhausted retries
        gs = _deep_copy_state(gs)
        gs.turn_number += 1
        _advance_turn(gs)
        return gs

    def _execute_action_for(
        self, gs: GameState, player_id: UUID, action: Action, strategy: Strategy
    ) -> GameState:
        """Execute action for any player (opponent or agent)."""
        from app import actions

        t = action.action_type
        p = action.params

        if t == "take_ingredients":
            return self._execute_take(gs, player_id)
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

    def render(self):
        if self.render_mode == "human" and self.gs is not None:
            from playtesting.display import format_game_state

            names = {self.agent_id: "AGENT"}
            for i, oid in enumerate(self.opponent_ids):
                names[oid] = f"OPP_{i}"
            print(format_game_state(self.gs, names))

    def action_meanings(self) -> list[str]:
        """Return human-readable descriptions of current valid actions."""
        return [a.description for a in self._valid_actions]
