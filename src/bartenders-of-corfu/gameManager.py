from uuid import UUID
from game import Game


class GameManager:
    __games = [] # type: list[Game]

    def new_game(self) -> UUID:
        game = Game()
        self.__games.append(game)
        return game.id
    
    def list_games(self) -> tuple[Game, ...]:
        """Returns a tuple of all games"""
        return tuple(self.__games)