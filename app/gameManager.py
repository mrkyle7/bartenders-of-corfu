import logging
from uuid import UUID

from app import actions
from app.db import db
from app.game import Game, GameException, Status
from app.GameState import GameState


class GameManager:
    def new_game(self, host_id: UUID) -> UUID:
        """Create a new game for the host user and return the game ID."""
        game = Game.new_game(host_id)
        try:
            db.create_game(game)
            return game.id
        except Exception as e:
            logging.exception("DB error when creating game")
            raise e

    def add_player(self, player_id: UUID, game_id: UUID):
        result = db.add_player_to_game(game_id, player_id)
        match result:
            case "not_found":
                raise GameException("Game not found", status_code=404)
            case "not_new":
                raise GameException("Game is not open for joining", status_code=409)
            case "duplicate":
                raise GameException("Player is already in this game", status_code=409)
            case "full":
                raise GameException("Game is full", status_code=409)
            case "ok":
                return
            case _:
                raise GameException("Failed to join game", status_code=500)

    def remove_player(self, requester_id: UUID, game_id: UUID, target_id: UUID):
        game = db.get_game(game_id)
        if game is None:
            raise GameException("Game not found", status_code=404)
        if game.status != Status.NEW:
            raise GameException(
                "Cannot remove players from a game that has already started",
                status_code=409,
            )
        result = db.remove_player_from_game(game_id, requester_id, target_id)
        match result:
            case "not_found":
                raise GameException("Game not found", status_code=404)
            case "not_host":
                raise GameException("Only the host can remove players", status_code=403)
            case "not_in_game":
                raise GameException("Player is not in this game", status_code=404)
            case "is_host":
                raise GameException("Host cannot remove themselves", status_code=400)
            case "ok":
                return
            case _:
                raise GameException("Failed to remove player", status_code=500)

    def start_game(self, requester_id: UUID, game_id: UUID):
        """Start a game. Validates host, minimum players, and NEW status."""
        game = db.get_game(game_id)
        if game is None:
            raise GameException("Game not found", status_code=404)
        if game.host != requester_id:
            raise GameException("Only the host can start the game", status_code=403)
        if game.status != Status.NEW:
            raise GameException("Game has already been started", status_code=409)
        if len(game.players) < 2:
            raise GameException(
                "At least 2 players are required to start the game", status_code=409
            )
        new_state = GameState.start_game(list(game.players))
        result = db.start_game(game_id, new_state)
        match result:
            case "not_found":
                raise GameException("Game not found", status_code=404)
            case "not_new":
                raise GameException("Game has already been started", status_code=409)
            case "ok":
                return
            case _:
                raise GameException("Failed to start game", status_code=500)

    def get_game_by_id(self, id: UUID) -> Game | None:
        """Returns a game by its ID or None if not found."""
        return db.get_game(id)

    def list_games(
        self,
        page: int = 1,
        page_size: int = 20,
        status: list[str] | str | None = None,
        player_id: UUID | None = None,
    ) -> tuple[list[Game], int]:
        """Returns (games, total_count) with optional pagination and filters."""
        return db.get_games(
            page=page, page_size=page_size, status=status, player_id=player_id
        )

    # ─── Game actions ─────────────────────────────────────────────────────────

    def _require_started(self, game: Game):
        if game.status != Status.STARTED:
            raise GameException("Game is not in progress", status_code=409)

    def _apply_action(
        self,
        game: Game,
        player_id: UUID,
        action_type: str,
        new_state: GameState,
        payload: dict,
    ) -> GameState:
        """Persist the move record and updated game state.

        Uses the pre-action turn_number so all moves within a logical turn share
        the same turn_number. move_number is the next sequence within that turn.
        """
        state_before = game.game_state.to_dict()
        turn_number = game.game_state.turn_number  # pre-action, shared across the turn
        move_number = db.get_next_move_number(game.id, turn_number)
        db.add_game_move(
            game.id,
            turn_number,
            move_number,
            player_id,
            action_type,
            payload,
            state_before,
        )
        db.update_game_state(game.id, new_state)
        return new_state

    def draw_from_bag(
        self, game: Game, player_id: UUID, count: int
    ) -> tuple[GameState, dict]:
        self._require_started(game)
        new_state, payload = actions.draw_from_bag(game.game_state, player_id, count)
        self._apply_action(game, player_id, "draw_from_bag", new_state, payload)
        return new_state, payload

    def take_ingredients(
        self, game: Game, player_id: UUID, assignments: list[dict]
    ) -> tuple[GameState, dict]:
        self._require_started(game)
        new_state, payload = actions.take_ingredients(
            game.game_state, player_id, assignments
        )
        self._apply_action(game, player_id, "take_ingredients", new_state, payload)
        return new_state, payload

    def sell_cup(
        self, game: Game, player_id: UUID, cup_index: int, declared_specials: list[str]
    ) -> tuple[GameState, dict]:
        self._require_started(game)
        new_state, payload = actions.sell_cup(
            game.game_state, player_id, cup_index, declared_specials
        )
        self._apply_action(game, player_id, "sell_cup", new_state, payload)
        return new_state, payload

    def drink_cup(
        self, game: Game, player_id: UUID, cup_index: int
    ) -> tuple[GameState, dict]:
        self._require_started(game)
        new_state, payload = actions.drink_cup(game.game_state, player_id, cup_index)
        self._apply_action(game, player_id, "drink_cup", new_state, payload)
        return new_state, payload

    def go_for_a_wee(self, game: Game, player_id: UUID) -> tuple[GameState, dict]:
        self._require_started(game)
        new_state, payload = actions.go_for_a_wee(game.game_state, player_id)
        self._apply_action(game, player_id, "go_for_a_wee", new_state, payload)
        return new_state, payload

    def claim_card(
        self,
        game: Game,
        player_id: UUID,
        card_id: str,
        cup_index: int | None = None,
        spirit_type: str | None = None,
    ) -> tuple[GameState, dict]:
        self._require_started(game)
        new_state, payload = actions.claim_card(
            game.game_state,
            player_id,
            card_id,
            cup_index=cup_index,
            spirit_type=spirit_type,
        )
        self._apply_action(game, player_id, "claim_card", new_state, payload)
        return new_state, payload

    def drink_stored_spirit(
        self, game: Game, player_id: UUID, store_card_index: int, count: int
    ) -> tuple[GameState, dict]:
        self._require_started(game)
        new_state, payload = actions.drink_stored_spirit(
            game.game_state, player_id, store_card_index, count
        )
        self._apply_action(game, player_id, "drink_stored_spirit", new_state, payload)
        return new_state, payload

    def use_stored_spirit(
        self, game: Game, player_id: UUID, store_card_index: int, cup_index: int
    ) -> tuple[GameState, dict]:
        self._require_started(game)
        new_state, payload = actions.use_stored_spirit(
            game.game_state, player_id, store_card_index, cup_index
        )
        self._apply_action(game, player_id, "use_stored_spirit", new_state, payload)
        return new_state, payload

    def refresh_card_row(
        self, game: Game, player_id: UUID, row_position: int
    ) -> tuple[GameState, dict]:
        self._require_started(game)
        new_state, payload = actions.refresh_card_row(
            game.game_state, player_id, row_position
        )
        self._apply_action(game, player_id, "refresh_card_row", new_state, payload)
        return new_state, payload

    def quit_game(self, game: Game, player_id: UUID) -> tuple[GameState, dict]:
        """A player voluntarily quits the game."""
        self._require_started(game)
        if player_id not in game.players:
            raise GameException("Not a member of this game", status_code=403)
        new_state, payload = actions.quit_game(game.game_state, player_id)
        self._apply_action(game, player_id, "quit_game", new_state, payload)
        # If no winner was set (game continues), update_game_state handles it.
        # If last-player-standing triggered, update_game_state sets ENDED via winner.
        # Either way, _apply_action already persisted.
        return new_state, payload

    def cancel_game(self, game: Game, requester_id: UUID) -> tuple[GameState, dict]:
        """The host cancels the game. No winner is declared."""
        self._require_started(game)
        if game.host != requester_id:
            raise GameException("Only the host can cancel the game", status_code=403)
        new_state, payload = actions.cancel_game(game.game_state)
        self._apply_action(game, requester_id, "cancel_game", new_state, payload)
        # Force ENDED status since there's no winner to trigger it automatically
        db.end_game(game.id, new_state)
        return new_state, payload

    # ─── History & replay ─────────────────────────────────────────────────────

    def get_history(self, game_id: UUID) -> list[dict]:
        return db.get_game_moves(game_id)

    def get_state_at_turn(self, game_id: UUID, turn_number: int) -> dict | None:
        return db.get_state_at_turn(game_id, turn_number)

    # ─── Undo ─────────────────────────────────────────────────────────────────

    def get_pending_undo(self, game_id: UUID) -> dict | None:
        return db.get_pending_undo(game_id)

    def propose_undo(self, game: Game, player_id: UUID) -> dict:
        self._require_started(game)
        if player_id not in game.players:
            raise GameException("Not a member of this game", status_code=403)

        ps = game.game_state.player_states.get(player_id)
        if ps and ps.is_eliminated:
            raise GameException(
                "Eliminated players cannot propose undo", status_code=409
            )

        if db.get_pending_undo(game.id):
            raise GameException(
                "An undo proposal is already pending for this game", status_code=409
            )

        moves = db.get_game_moves(game.id)
        if not moves:
            raise GameException("No moves to undo", status_code=409)

        last_turn = moves[-1]["turn_number"]
        return db.create_undo_request(game.id, last_turn, player_id)

    def vote_undo(
        self, game: Game, player_id: UUID, request_id: str, vote: str
    ) -> dict:
        self._require_started(game)
        pending = db.get_pending_undo(game.id)
        if pending is None or pending["id"] != request_id:
            raise GameException(
                "Undo request not found or no longer pending", status_code=404
            )

        existing_votes: dict = pending.get("votes") or {}
        if str(player_id) in existing_votes:
            raise GameException(
                "You have already voted on this undo request", status_code=409
            )

        updated = db.vote_on_undo(request_id, player_id, vote)
        if updated is None:
            raise GameException("Failed to record vote", status_code=500)

        # Check if all active players have now voted agree
        if updated["status"] == "pending":
            votes: dict = updated.get("votes") or {}
            active_players = [
                pid
                for pid, ps in game.game_state.player_states.items()
                if not ps.is_eliminated
            ]
            if all(votes.get(str(pid)) == "agree" for pid in active_players):
                # Execute the undo
                db.approve_undo(request_id, votes)
                self._execute_undo(
                    game,
                    pending["target_turn_number"],
                    UUID(pending["proposed_by"]),
                )
                return {"status": "approved", "message": "Undo applied"}

        return {"status": updated["status"], "votes": updated.get("votes")}

    def _execute_undo(self, game: Game, target_turn_number: int, proposed_by: UUID):
        """Restore game state to just before the target turn.

        Restores from the state_before of the first move of the target turn —
        which is always a clean turn-start state (batch fields reset by _advance_turn).
        Records an "undo" move, then sets turn_number to max_recorded + 1 so no
        future move collides with existing records for the undone turn.
        """
        state_dict = db.get_state_before_turn(game.id, target_turn_number)
        if state_dict is None:
            raise GameException(
                "Cannot restore state: snapshot not found", status_code=500
            )
        # Record the undo as its own move before restoring
        current_max = db.get_max_turn_number(game.id)
        undo_turn_number = current_max + 1
        db.add_game_move(
            game.id,
            undo_turn_number,
            1,
            proposed_by,
            "undo",
            {"target_turn_number": target_turn_number},
            state_dict,
        )
        restored_state = GameState.from_dict(state_dict)
        restored_state.turn_number = undo_turn_number + 1
        db.update_game_state(game.id, restored_state)
