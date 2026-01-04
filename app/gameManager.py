from uuid import UUID
from app.game import Game
from app.user import User


class GameManager:
    __games = [] # type: list[Game]

    def new_game(self, user: User) -> UUID:
        game = Game(user)
        self.__games.append(game)
        return game.id

    def get_game_by_id(self, game_id: str) -> Game | None:
        """Returns a game by its ID or None if not found"""
        for game in self.__games:
            if str(game.id) == game_id:
                return game
        return None

    def list_games(self) -> tuple[Game, ...]:
        """Returns a tuple of all games"""
        return tuple(self.__games)
