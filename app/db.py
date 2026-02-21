import os
import logging
from datetime import datetime, timezone
from uuid import UUID
from supabase import create_client, Client
from app.game import Game, Status
from app.GameState import GameState
from app.Ingredient import Ingredient
from app.PlayerState import PlayerState
from app.user import User
from app.utils import bytesToHexString, hexStringToBytes


class Db:
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    supabase: Client = create_client(url, key)

    _USER_COLUMNS = (
        "id",
        "username",
        "email",
        "password",
        "status",
        "is_admin",
        "created_at",
        "password_changed_at",
        "deactivated_at",
        "deactivated_by",
        "deleted_at",
        "logged_out_at",
    )

    @staticmethod
    def _row_to_user(row: dict) -> User:
        password_bytes = hexStringToBytes(row.get("password")) or None
        return User.from_dict(
            {
                "id": row.get("id"),
                "username": row.get("username"),
                "email": row.get("email"),
                "password_hash": password_bytes,
                "status": row.get("status", "active"),
                "is_admin": row.get("is_admin", False),
                "created_at": row.get("created_at"),
                "password_changed_at": row.get("password_changed_at"),
                "deactivated_at": row.get("deactivated_at"),
                "deactivated_by": row.get("deactivated_by"),
                "deleted_at": row.get("deleted_at"),
                "logged_out_at": row.get("logged_out_at"),
            }
        )

    def add_user(self, user: User) -> bool:
        password_value = bytesToHexString(user._password_hash)
        response = (
            self.supabase.table("users")
            .insert(
                {
                    "id": str(user.id),
                    "username": user.username,
                    "email": user.email,
                    "password": password_value,
                    "status": user.status,
                    "is_admin": user.is_admin,
                }
            )
            .execute()
        )
        return len(response.data) == 1

    def get_user_by_username(self, username: str) -> User | None:
        response = (
            self.supabase.table("users")
            .select(*self._USER_COLUMNS)
            .eq("username", username)
            .execute()
        )
        logging.debug(f"user_by_username response from db {response}")
        if len(response.data) == 1:
            return self._row_to_user(response.data[0])
        return None

    def get_user_by_id(self, id: UUID) -> User | None:
        response = (
            self.supabase.table("users")
            .select(*self._USER_COLUMNS)
            .eq("id", str(id))
            .execute()
        )
        if len(response.data) == 1:
            return self._row_to_user(response.data[0])
        return None

    def get_users_by_ids(self, ids: set[UUID]) -> list[User]:
        response = (
            self.supabase.table("users")
            .select(*self._USER_COLUMNS)
            .in_("id", [str(i) for i in ids])
            .execute()
        )
        return [self._row_to_user(row) for row in response.data]

    def get_users(self) -> list[User]:
        response = (
            self.supabase.table("users")
            .select(*self._USER_COLUMNS)
            .neq("status", "deleted")
            .limit(1000)
            .execute()
        )
        return [self._row_to_user(row) for row in response.data]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def delete_user(self, user_id: UUID) -> bool:
        response = (
            self.supabase.table("users")
            .update(
                {
                    "status": "deleted",
                    "username": None,
                    "email": None,
                    "password": None,
                    "deleted_at": self._now(),
                }
            )
            .eq("id", str(user_id))
            .execute()
        )
        return len(response.data) == 1

    def deactivate_user(self, target_id: UUID, admin_id: UUID) -> bool:
        response = (
            self.supabase.table("users")
            .update(
                {
                    "status": "deactivated",
                    "deactivated_at": self._now(),
                    "deactivated_by": str(admin_id),
                }
            )
            .eq("id", str(target_id))
            .execute()
        )
        return len(response.data) == 1

    def reactivate_user(self, target_id: UUID) -> bool:
        response = (
            self.supabase.table("users")
            .update(
                {
                    "status": "active",
                    "deactivated_at": None,
                    "deactivated_by": None,
                }
            )
            .eq("id", str(target_id))
            .execute()
        )
        return len(response.data) == 1

    def logout_user(self, user_id: UUID) -> bool:
        response = (
            self.supabase.table("users")
            .update({"logged_out_at": self._now()})
            .eq("id", str(user_id))
            .execute()
        )
        return len(response.data) == 1

    def update_password(self, user_id: UUID, new_hash: bytes) -> bool:
        response = (
            self.supabase.table("users")
            .update(
                {
                    "password": bytesToHexString(new_hash),
                    "password_changed_at": "now()",
                }
            )
            .eq("id", str(user_id))
            .execute()
        )
        return len(response.data) == 1

    def get_public_key(self, kid: str) -> bytes | None:
        response = (
            self.supabase.table("public_keys")
            .select("public_key")
            .eq("kid", str(kid))
            .eq("valid", True)
            .execute()
        )
        if len(response.data) == 1:
            return hexStringToBytes(response.data[0].get("public_key"))
        else:
            return None

    def add_public_key(self, kid: UUID, public_key: bytes) -> bool:
        response = (
            self.supabase.table("public_keys")
            .insert({"kid": str(kid), "public_key": bytesToHexString(public_key)})
            .execute()
        )
        return len(response.data) == 1

    def create_game(self, game: Game):
        """Create a game in the database"""
        (
            self.supabase.table("games")
            .insert(
                {
                    "id": str(game.id),
                    "host": str(game.host),
                    "players": [str(id) for id in game.players],
                    "status": game.status.name,
                    "latest_state": game.game_state.to_dict(),
                }
            )
            .execute()
        )

    @staticmethod
    def game_response_to_game(game_data) -> Game:

        state_data = game_data["latest_state"]
        player_states = {}
        if "player_states" in game_data["latest_state"]:
            for player, ps_data in state_data["player_states"].items():
                player_states[UUID(player)] = PlayerState(
                    player_id=UUID(ps_data["player_id"]),
                    points=ps_data["points"],
                    drunk_level=ps_data["drunk_level"],
                    cup1=[Ingredient[ingredient] for ingredient in ps_data["cup1"]],
                    cup2=[Ingredient[ingredient] for ingredient in ps_data["cup2"]],
                )

        game_state = GameState(
            winner=UUID(state_data["winner"]) if state_data.get("winner") else None,
            bag_contents=[
                Ingredient[ingredient] for ingredient in state_data["bag_contents"]
            ],
            player_states=player_states,
            player_turn=UUID(state_data["player_turn"])
            if state_data.get("player_turn")
            else None,
        )

        return Game(
            id=UUID(game_data["id"]),
            host=UUID(game_data["host"]),
            players=set(UUID(p) for p in game_data["players"]),
            status=Status[game_data["status"]],
            game_state=game_state,
            created=game_data["created_at"],
        )

    def get_game(self, game_id: UUID) -> Game | None:
        """Get a single game by ID"""
        response = (
            self.supabase.table("games")
            .select("id", "host", "players", "status", "latest_state", "created_at")
            .eq("id", str(game_id))
            .execute()
        )

        if len(response.data) == 1:
            game_data = response.data[0]
            return Db.game_response_to_game(game_data)

        return None

    def get_games(self) -> list[Game]:
        """Get all games"""
        response = (
            self.supabase.table("games")
            .select("id", "host", "players", "status", "latest_state", "created_at")
            .limit(100)
            .execute()
        )

        games = []
        for game_data in response.data:
            games.append(Db.game_response_to_game(game_data))

        return games

    def add_player_to_game(self, game_id: UUID, player_id: UUID) -> bool:
        """Add a player to an existing game"""
        response = self.supabase.rpc(
            "add_player_to_game", {"game_id": str(game_id), "player_id": str(player_id)}
        ).execute()
        return response.data


db = Db()
