import logging
from uuid import UUID
from app.db import db
from app.game import Game
from app.user import User


class GameManager:

    def new_game(self, host: User) -> UUID:
        """Create a new game for the host user and return the game ID""" 
        game = Game.new_game(host.id)
        try:
            db.create_game(game)
            return game.id
        except Exception as e:
            logging.exception("DB error when creating game")
            raise e
        
    def add_player(self, player_id: UUID, game_id: UUID):
        db.add_player_to_game(game_id, player_id)

    def get_game_by_id(self, id: UUID) -> Game | None:
        """Returns a game by its ID or None if not found"""
        return db.get_game(id)

    def list_games(self) -> list[Game]:
        """Returns a tuple of all games"""
        return db.get_games()
