"""GameRunner: manages turn flow, free actions, and game-end detection."""

import random as _random
from dataclasses import dataclass, field
from uuid import UUID

from app import actions
from app.GameState import GameState
from app.game import GameException

from playtesting.display import format_action, format_game_state
from playtesting.strategy import Strategy
from playtesting.valid_actions import Action, get_valid_actions

MAX_TURNS = 500
MAX_FREE_ACTIONS_PER_TURN = 20
MAX_RETRIES = 3


@dataclass
class PlayerResult:
    player_id: UUID
    strategy_name: str
    points: int = 0
    status: str = "active"
    karaoke_cards: int = 0
    elimination_turn: int | None = None


@dataclass
class GameResult:
    winner: UUID | None = None
    winner_strategy: str = ""
    reason: str = ""  # "points", "karaoke", "last_standing", "stalemate"
    turn_count: int = 0
    player_results: dict[UUID, PlayerResult] = field(default_factory=dict)


class GameRunner:
    def __init__(self, strategies: dict[UUID, Strategy], seed: int | None = None):
        self.strategies = strategies
        self.seed = seed

    def run(self, verbose: bool = False) -> GameResult:
        if self.seed is not None:
            _random.seed(self.seed)

        player_ids = list(self.strategies.keys())
        gs = GameState.start_game(player_ids)

        if verbose:
            strategy_names = {pid: self.strategies[pid].name for pid in player_ids}
            print("=== Game Start ===")
            print(format_game_state(gs, strategy_names))
            print()

        while gs.winner is None and gs.turn_number < MAX_TURNS:
            current_player = gs.player_turn
            if current_player is None:
                break

            ps = gs.player_states.get(current_player)
            if ps is None or ps.is_eliminated:
                break

            strategy = self.strategies[current_player]

            # Free actions phase
            gs = self._do_free_actions(gs, current_player, strategy, verbose)
            if gs.winner is not None:
                break

            # Main action phase
            gs = self._do_main_action(gs, current_player, strategy, verbose)

            if verbose and gs.turn_number % 10 == 0:
                strategy_names = {pid: self.strategies[pid].name for pid in player_ids}
                print(format_game_state(gs, strategy_names))
                print()

        return self._build_result(gs)

    def _do_free_actions(
        self,
        gs: GameState,
        player_id: UUID,
        strategy: Strategy,
        verbose: bool,
    ) -> GameState:
        for _ in range(MAX_FREE_ACTIONS_PER_TURN):
            all_actions = get_valid_actions(gs, player_id)
            free_actions = [a for a in all_actions if a.is_free]
            if not free_actions:
                break

            chosen = strategy.choose_free_action(gs, player_id, free_actions)
            if chosen is None:
                break

            if verbose:
                print(
                    f"  [free] {self.strategies[player_id].name}: {format_action(chosen)}"
                )

            try:
                gs = self._execute_action(gs, player_id, chosen, strategy)
            except GameException as e:
                if verbose:
                    print(f"  [free] FAILED: {e}")
                break

            if gs.winner is not None:
                break

        return gs

    def _do_main_action(
        self,
        gs: GameState,
        player_id: UUID,
        strategy: Strategy,
        verbose: bool,
    ) -> GameState:
        for attempt in range(MAX_RETRIES):
            all_actions = get_valid_actions(gs, player_id)
            turn_actions = [a for a in all_actions if not a.is_free]

            if not turn_actions:
                if verbose:
                    print(
                        f"  {self.strategies[player_id].name}: NO VALID ACTIONS - skipping turn"
                    )
                from app.actions import _advance_turn, _deep_copy_state

                gs = _deep_copy_state(gs)
                gs.turn_number += 1
                _advance_turn(gs)
                return gs

            chosen = strategy.choose_action(gs, player_id, turn_actions)

            if verbose:
                print(
                    f"  T{gs.turn_number} {self.strategies[player_id].name}: {format_action(chosen)}"
                )

            try:
                gs = self._execute_action(gs, player_id, chosen, strategy)
                return gs
            except GameException as e:
                if verbose:
                    print(f"  RETRY ({attempt + 1}/{MAX_RETRIES}): {e}")
                continue

        # All retries exhausted — force-advance the turn to prevent infinite loop
        if verbose:
            print(
                f"  {self.strategies[player_id].name}: all retries exhausted, skipping turn"
            )
        from app.actions import _advance_turn, _deep_copy_state

        gs = _deep_copy_state(gs)
        gs.turn_number += 1
        _advance_turn(gs)
        return gs

    def _execute_action(
        self,
        gs: GameState,
        player_id: UUID,
        action: Action,
        strategy: Strategy,
    ) -> GameState:
        t = action.action_type
        p = action.params

        if t == "take_ingredients":
            return self._execute_take(gs, player_id, strategy)
        elif t == "sell_cup":
            gs, _ = actions.sell_cup(
                gs, player_id, p["cup_index"], p.get("declared_specials", [])
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
        else:
            raise GameException(f"Unknown action type: {t}", status_code=500)

        return gs

    def _execute_take(
        self,
        gs: GameState,
        player_id: UUID,
        strategy: Strategy,
    ) -> GameState:
        """Handle take_ingredients with two-phase bag draws.

        Flow:
        1. Strategy picks display items (known ingredients)
        2. Send display picks to take_ingredients (partial batch)
        3. For remaining count, draw from bag (reveals ingredients)
        4. Strategy assigns bag draws after seeing what was drawn
        5. Send pending assignments to complete the turn
        """
        ps = gs.player_states[player_id]
        take_count = ps.take_count
        remaining = take_count - gs.ingredients_taken_this_turn

        # Phase 1: display picks (strategy knows what's available)
        display_assignments = strategy.choose_take_assignments(gs, player_id, remaining)

        if display_assignments:
            gs, payload = actions.take_ingredients(gs, player_id, display_assignments)
            if payload.get("turn_complete", False):
                return gs

        # Phase 2: draw remaining from bag, let strategy see + assign
        batch_limit = 10
        while batch_limit > 0:
            batch_limit -= 1
            ps = gs.player_states[player_id]
            remaining = ps.take_count - gs.ingredients_taken_this_turn
            if remaining <= 0:
                break

            # Draw from bag — reveals ingredients
            bag_count = min(remaining, len(gs.bag_contents))
            if bag_count <= 0:
                break
            gs, draw_payload = actions.draw_from_bag(gs, player_id, bag_count)

            # Strategy sees drawn items and decides dispositions
            drawn = gs.bag_draw_pending[:]
            pending_assignments = strategy.choose_pending_assignments(
                gs, player_id, drawn
            )

            gs, payload = actions.take_ingredients(gs, player_id, pending_assignments)
            if payload.get("turn_complete", False):
                return gs

        return gs

    def _build_result(self, gs: GameState) -> GameResult:
        result = GameResult(turn_count=gs.turn_number)

        for pid, ps in gs.player_states.items():
            strategy_name = self.strategies[pid].name
            pr = PlayerResult(
                player_id=pid,
                strategy_name=strategy_name,
                points=ps.points,
                status=ps.status,
                karaoke_cards=ps.karaoke_cards_claimed,
                elimination_turn=None,  # Would need tracking during game
            )
            result.player_results[pid] = pr

        if gs.winner is not None:
            result.winner = gs.winner
            result.winner_strategy = self.strategies[gs.winner].name
            ws = gs.player_states[gs.winner]
            if ws.points >= 40:
                result.reason = "points"
            elif ws.karaoke_cards_claimed >= 3:
                result.reason = "karaoke"
            else:
                result.reason = "last_standing"
        else:
            result.reason = "stalemate"

        return result
