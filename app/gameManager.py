import logging
from uuid import UUID
from app.db import db
from app.game import Game, GameException, Status
from app.GameState import GameState


class GameManager:
    def new_game(self, host_id: UUID) -> UUID:
        """Create a new game for the host user and return the game ID"""
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
        """Returns a game by its ID or None if not found"""
        return db.get_game(id)

    def list_games(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        player_id: UUID | None = None,
    ) -> tuple[list[Game], int]:
        """Returns (games, total_count) with optional pagination and filters."""
        return db.get_games(
            page=page, page_size=page_size, status=status, player_id=player_id
        )
