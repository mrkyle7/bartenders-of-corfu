"""Depth-limited lookahead strategy backed by the static evaluator.

This is the "real shallow search + state evaluator" bot. Instead of scoring the
immediate action (Mastermind) or averaging full noisy rollouts (the flat MCTS),
it:

1. Simulates each candidate main action,
2. plays opponents (modelled as Mastermind) until control returns,
3. and scores the resulting position with ``ml.evaluator.evaluate``.

Because the game has hidden/stochastic information (bag draws, opponent draws),
each candidate is sampled a few times and averaged. ``drink_cup`` / risky takes
that can self-eliminate naturally score badly because eliminated leaf states are
clamped to a large negative value — no hand-written suicide filter required.

Micro-decisions (take assignments, free actions) reuse Mastermind: the search
only governs *which main action* to take, which is where the strategic depth
lives. Opponents are modelled with Mastermind via the shared RolloutExecutor.
"""

from uuid import UUID

from app.GameState import GameState
from app.Ingredient import Ingredient
from app.actions import _advance_turn, _deep_copy_state

from playtesting.strategy import Mastermind, Strategy
from playtesting.valid_actions import Action, get_valid_actions

from ml.cocktail import (
    cocktail_display_assignments,
    cocktail_pending_assignments,
    plan_cocktail,
)
from ml.evaluator import DEFAULT_WEIGHTS, EvalWeights, evaluate
from ml.mcts import RolloutExecutor


class LookaheadStrategy(Strategy):
    """Shallow expectimax over main actions using the static evaluator.

    Args:
        depth: number of *own* future decision points to search. depth=1 means
            "apply my action, let opponents respond, then evaluate". depth=2
            adds one more of my turns (pick my best follow-up before evaluating).
        samples: simulations per candidate to average over hidden/stochastic
            outcomes (bag/opponent draws). Higher = less noise, more compute.
        max_opponent_turns: safety cap when advancing opponents back to us.
    """

    name = "Lookahead"

    def __init__(
        self,
        depth: int = 1,
        samples: int = 3,
        max_opponent_turns: int = 12,
        weights: EvalWeights = DEFAULT_WEIGHTS,
    ):
        self.depth = depth
        self.samples = samples
        self.max_opponent_turns = max_opponent_turns
        self.weights = weights
        self._executor = RolloutExecutor()
        self._fallback = Mastermind()

    # -- main action: the searched decision ---------------------------------

    def choose_action(
        self, gs: GameState, player_id: UUID, valid_actions: list[Action]
    ) -> Action:
        if not valid_actions:
            return self._fallback.choose_action(gs, player_id, valid_actions)
        if len(valid_actions) == 1:
            return valid_actions[0]

        best_action = valid_actions[0]
        best_value = float("-inf")
        for action in valid_actions:
            value = self._action_value(gs, player_id, action, self.depth)
            if value > best_value:
                best_value, best_action = value, action
        return best_action

    def _action_value(
        self, gs: GameState, player_id: UUID, action: Action, depth: int
    ) -> float:
        """Average value of taking ``action`` now, searched to ``depth``."""
        total = 0.0
        for _ in range(self.samples):
            sim = _deep_copy_state(gs)
            try:
                # Simulate the action with *our own* disposition (self), not
                # Mastermind's: when cocktail building is on, that's what makes the
                # search see a build-take's real drunk/bladder cost, so the safety
                # penalty discourages reckless builds. For v1 (cocktail off) self
                # delegates to Mastermind, so behaviour is unchanged.
                sim = self._executor._exec(sim, player_id, action, self)
            except Exception:
                total += evaluate(sim, player_id, self.weights)
                continue
            sim = self._advance_to_me(sim, player_id)
            total += self._evaluate_node(sim, player_id, depth)
        return total / self.samples

    def _evaluate_node(self, gs: GameState, player_id: UUID, depth: int) -> float:
        """Value of a state where it is (about to be) our turn again."""
        if gs.winner is not None:
            return evaluate(gs, player_id, self.weights)
        ps = gs.player_states.get(player_id)
        if ps is None or ps.is_eliminated:
            return evaluate(gs, player_id, self.weights)
        if depth <= 0 or gs.player_turn != player_id:
            return evaluate(gs, player_id, self.weights)

        # Our turn: clear free actions with Mastermind, then search our best
        # follow-up main action one level shallower.
        gs = self._do_my_free_actions(gs, player_id)
        if gs.winner is not None:
            return evaluate(gs, player_id, self.weights)

        all_acts = get_valid_actions(gs, player_id)
        main_acts = [a for a in all_acts if not a.is_free]
        if not main_acts:
            return evaluate(gs, player_id, self.weights)

        return max(self._action_value(gs, player_id, a, depth - 1) for a in main_acts)

    # -- simulation helpers --------------------------------------------------

    def _advance_to_me(self, gs: GameState, player_id: UUID) -> GameState:
        """Run opponent turns (Mastermind) until it's our turn or game ends."""
        for _ in range(self.max_opponent_turns):
            if gs.winner is not None or gs.player_turn == player_id:
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
            gs = self._executor._execute_turn(gs, current)
        return gs

    def _do_my_free_actions(self, gs: GameState, player_id: UUID) -> GameState:
        from app.game import GameException

        for _ in range(10):
            all_acts = get_valid_actions(gs, player_id)
            free_acts = [a for a in all_acts if a.is_free]
            if not free_acts:
                break
            chosen = self._fallback.choose_free_action(gs, player_id, free_acts)
            if chosen is None:
                break
            try:
                gs = self._executor._exec(gs, player_id, chosen, self._fallback)
            except (GameException, Exception):
                break
            if gs.winner is not None:
                break
        return gs

    # -- micro-decisions: delegate to Mastermind, except cocktail building --

    def choose_free_action(
        self, gs: GameState, player_id: UUID, free_actions: list[Action]
    ) -> Action | None:
        return self._fallback.choose_free_action(gs, player_id, free_actions)

    def choose_take_assignments(
        self, gs: GameState, player_id: UUID, count: int
    ) -> list[dict]:
        # When cocktail knowledge is on, build a held-specials recipe straight
        # from the display before falling back to Mastermind's generic disposition
        # (which caps cups at 2 spirits and can't assemble a cocktail).
        if self.weights.cocktail_progress:
            ps = gs.player_states[player_id]
            plan = plan_cocktail(ps)
            if plan is not None:
                asn = cocktail_display_assignments(gs.open_display, count, plan)
                if asn:
                    return asn
        return self._fallback.choose_take_assignments(gs, player_id, count)

    def choose_pending_assignments(
        self, gs: GameState, player_id: UUID, drawn: list[Ingredient]
    ) -> list[dict]:
        if self.weights.cocktail_progress:
            ps = gs.player_states[player_id]
            plan = plan_cocktail(ps)  # re-plan from live state (display picks applied)
            if plan is not None:
                return cocktail_pending_assignments(ps, drawn, plan)
        return self._fallback.choose_pending_assignments(gs, player_id, drawn)


# Self-register so the strategy is discoverable regardless of whether this
# module or playtesting.strategy is imported first (the lazy hook in
# playtesting.strategy can lose the race under a circular import).
from playtesting.strategy import STRATEGY_CLASSES  # noqa: E402

STRATEGY_CLASSES.setdefault("lookahead", LookaheadStrategy)
