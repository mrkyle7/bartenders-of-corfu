import os
import logging
from uuid import UUID
from supabase import create_client, Client
from app.Game import Game, Status
from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import PlayerState
from app.user import User
from app.utils import bytesToHexString, hexStringToBytes
import json


class Db:
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    supabase: Client = create_client(url, key)

    def add_user(self, user: User) -> bool:
        # Convert bytes/bytearray password to Postgres bytea hex literal (e.g. "\\xDEADBEEF")
        password_value = (
            bytesToHexString(user._password_hash)
        )
        response = (
            self.supabase.table('users')
            .insert(
                {"id": str(user.id), "username": user.username,
                 "email": user.email, "password": password_value}
            )
            .execute()
        )
        return len(response.data) == 1

    def get_user_by_username(self, username: str) -> User | None:
        response = (
            self.supabase.table('users')
            .select('id', 'username', 'email', 'password')
            .eq('username', username)
            .execute()
        )
        logging.debug(f"user_by_username response from db {response}")
        if len(response.data) == 1:
            logging.info(f"Got user {response.data[0].get('username')}")
            return User.from_dict(
                {
                    "id": response.data[0].get('id'),
                    "username": response.data[0].get('username'),
                    "email": response.data[0].get('email'),
                    "password_hash": hexStringToBytes(response.data[0].get('password'))
                }
            )
        else:
            return None

    def get_user_by_id(self, id: UUID) -> User | None:
        response = (
            self.supabase.table('users')
            .select('id', 'username', 'email', 'password')
            .eq('id', str(id))
            .execute()
        )
        if len(response.data) == 1:
            logging.info(f"Got user {response.data[0].get('username')}")
            return User.from_dict(
                {
                    "id": response.data[0].get('id'),
                    "username": response.data[0].get('username'),
                    "email": response.data[0].get('email'),
                    "password_hash": hexStringToBytes(response.data[0].get('password'))
                }
            )
        else:
            return None

    def get_users_by_ids(self, ids: set[UUID]) -> list[User]:
        response = (
            self.supabase.table('users')
            .select('id', 'username', 'email', 'password')
            .in_('id', ids)
            .execute()
        )

        return [User.from_dict(
            {
                "id": user.get('id'),
                "username": user.get('username'),
                "email": user.get('email'),
                "password_hash": hexStringToBytes(user.get('password'))
            }
        ) for user in response.data
        ]

    def get_users(self) -> list[User]:
        response = (
            self.supabase.table('users')
            .select('id', 'username', 'email', 'password')
            .limit(1000)
            .execute()
        )
        return [User.from_dict(
            {
                "id": user.get('id'),
                "username": user.get('username'),
                "email": user.get('email'),
                "password_hash": hexStringToBytes(user.get('password'))
            }
        ) for user in response.data]

    def get_public_key(self, kid: str) -> bytes | None:
        response = (
            self.supabase.table('public_keys')
            .select('public_key')
            .eq('kid', str(kid))
            .eq('valid', True)
            .execute()
        )
        if len(response.data) == 1:
            return hexStringToBytes(response.data[0].get('public_key'))
        else:
            return None

    def add_public_key(self, kid: UUID, public_key: bytes) -> bool:
        response = (
            self.supabase.table('public_keys')
            .insert(
                {"kid": str(kid),
                 "public_key": bytesToHexString(public_key)}
            )
            .execute()
        )
        return len(response.data) == 1

    def create_game(self, game: Game):
        """Create a game in the database"""
        (
            self.supabase.table('games')
            .insert(
                {
                    "id": str(game.id),
                    "host": str(game.host),
                    "players": [str(id) for id in game.players],
                    "status": game.status.name,
                    "latest_state": game.game_state.to_dict()
                }
            )
            .execute()
        )

    @staticmethod
    def game_response_to_game(game_data) -> Game:
     
        state_data = game_data['latest_state']
        player_states = {}
        if 'player_states' in game_data['latest_state']:
            for player, ps_data in state_data['player_states'].items():
                player_states[UUID(player)] = PlayerState(
                    player_id=UUID(ps_data['player_id']),
                    points=ps_data['points'],
                    drunk_level=ps_data['drunk_level'],
                    cup1=[Ingredient[ingredient]
                          for ingredient in ps_data['cup1']],
                    cup2=[Ingredient[ingredient]
                          for ingredient in ps_data['cup2']],
                )

        game_state = GameState(
            winner=UUID(state_data['winner']) if state_data.get(
                'winner') else None,
            bag_contents=[Ingredient[ingredient]
                          for ingredient in state_data['bag_contents']],
            player_states=player_states,
            player_turn=UUID(state_data['player_turn']) if state_data.get(
                'player_turn') else None
        )

        return Game(
            id=UUID(game_data['id']),
            host=UUID(game_data['host']),
            players=set(UUID(p) for p in game_data['players']),
            status=Status[game_data['status']],
            game_state=game_state,
            created=game_data['created_at']
        )

    def get_game(self, game_id: UUID) -> Game | None:
        """Get a single game by ID"""
        response = (
            self.supabase.table('games')
            .select('id', 'host', 'players', 'status', 'latest_state', 'created_at')
            .eq('id', str(game_id))
            .execute()
        )

        if len(response.data) == 1:
            game_data = response.data[0]
            return Db.game_response_to_game(game_data)

        return None

    def get_games(self) -> list[Game]:
        """Get all games"""
        response = (
            self.supabase.table('games')
            .select('id', 'host', 'players', 'status', 'latest_state', 'created_at')
            .limit(100)
            .execute()
        )

        games = []
        for game_data in response.data:
            games.append(Db.game_response_to_game(game_data))

        return games

    def add_player_to_game(self, game_id: UUID, player_id: UUID) -> bool:
        """Add a player to an existing game"""
        response = (
            self.supabase.rpc('add_player_to_game', {
                              "game_id": str(game_id), "player_id": str(player_id)})
            .execute()
        )
        return response.data


db = Db()
