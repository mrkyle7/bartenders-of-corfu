import os
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4
from supabase import create_client, Client
from app.game import Game, Status
from app.GameState import GameState
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
        "theme",
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
                "theme": row.get("theme", "taverna"),
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
            .order("created_at", desc=True)
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

    def update_email(self, user_id: UUID, new_email: str) -> bool:
        response = (
            self.supabase.table("users")
            .update({"email": new_email})
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

    def update_theme(self, user_id: UUID, theme: str) -> bool:
        response = (
            self.supabase.table("users")
            .update({"theme": theme})
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
        game_state = GameState.from_dict(game_data["latest_state"])
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

    def get_games(
        self,
        page: int = 1,
        page_size: int = 20,
        status: list[str] | str | None = None,
        player_id: UUID | None = None,
    ) -> tuple[list[Game], int]:
        """Get paginated games with optional filters. Returns (games, total_count)."""
        offset = (page - 1) * page_size
        query = (
            self.supabase.table("games")
            .select(
                "id, host, players, status, latest_state, created_at",
                count="exact",
            )
            .order("created_at", desc=True)
        )
        if status:
            if isinstance(status, list):
                query = query.in_("status", status)
            else:
                query = query.eq("status", status)
        if player_id:
            query = query.contains("players", [str(player_id)])
        response = query.range(offset, offset + page_size - 1).execute()
        games = [Db.game_response_to_game(g) for g in response.data]
        total = response.count or 0
        return games, total

    def start_game(self, game_id: UUID, game_state: GameState) -> str:
        """Start a game: atomically set status=STARTED, save initial_state and latest_state.
        Returns 'ok' | 'not_found' | 'not_new'"""
        state_dict = game_state.to_dict()
        response = (
            self.supabase.table("games")
            .update(
                {
                    "status": "STARTED",
                    "latest_state": state_dict,
                    "initial_state": state_dict,
                }
            )
            .eq("id", str(game_id))
            .eq("status", "NEW")
            .execute()
        )
        if len(response.data) == 1:
            return "ok"
        check = (
            self.supabase.table("games").select("id").eq("id", str(game_id)).execute()
        )
        if not check.data:
            return "not_found"
        return "not_new"

    def update_game_state(self, game_id: UUID, game_state: GameState) -> bool:
        """Overwrite latest_state after a game action. Also sets status=ENDED if there is a winner."""
        update_data: dict = {"latest_state": game_state.to_dict()}
        if game_state.winner is not None:
            update_data["status"] = "ENDED"
        response = (
            self.supabase.table("games")
            .update(update_data)
            .eq("id", str(game_id))
            .execute()
        )
        return len(response.data) == 1

    def end_game(self, game_id: UUID, game_state: GameState) -> bool:
        """End a game (cancel or quit): save state and set status=ENDED."""
        response = (
            self.supabase.table("games")
            .update({"latest_state": game_state.to_dict(), "status": "ENDED"})
            .eq("id", str(game_id))
            .execute()
        )
        return len(response.data) == 1

    def get_next_move_number(self, game_id: UUID, turn_number: int) -> int:
        """Return the next move_number for (game_id, turn_number), starting at 1."""
        resp = (
            self.supabase.table("game_moves")
            .select("move_number")
            .eq("game_id", str(game_id))
            .eq("turn_number", turn_number)
            .order("move_number", desc=True)
            .limit(1)
            .execute()
        )
        return (resp.data[0]["move_number"] + 1) if resp.data else 1

    def add_game_move(
        self,
        game_id: UUID,
        turn_number: int,
        move_number: int,
        player_id: UUID,
        action_type: str,
        action_payload: dict,
        state_before: dict,
    ) -> bool:
        """Append a MoveRecord to game_moves."""
        action = {"type": action_type, **action_payload}
        response = (
            self.supabase.table("game_moves")
            .insert(
                {
                    "id": str(uuid4()),
                    "game_id": str(game_id),
                    "turn_number": turn_number,
                    "move_number": move_number,
                    "player_id": str(player_id),
                    "action": action,
                    "state_before": state_before,
                }
            )
            .execute()
        )
        return len(response.data) == 1

    def get_game_moves(self, game_id: UUID) -> list[dict]:
        """Return all MoveRecords for a game, ordered by (turn_number, move_number) ascending."""
        response = (
            self.supabase.table("game_moves")
            .select("id, turn_number, move_number, player_id, action, created_at")
            .eq("game_id", str(game_id))
            .order("turn_number", desc=False)
            .order("move_number", desc=False)
            .execute()
        )
        return response.data or []

    def get_state_at_turn(self, game_id: UUID, turn_number: int) -> dict | None:
        """Return the reconstructed game state immediately after turn_number completed.

        turn_number=0  → initial state (before any moves)
        turn_number=N  → state_before from the first move of internal turn_number N
                         (each move stores the pre-action turn_number, so move N's
                         state_before is the state after the previous turn completed)
        """
        if turn_number == 0:
            # Return the initial state snapshot
            resp = (
                self.supabase.table("games")
                .select("initial_state")
                .eq("id", str(game_id))
                .execute()
            )
            if not resp.data:
                return None
            return resp.data[0].get("initial_state")

        # State after the N-th completed turn = state_before of the first move
        # that uses internal turn_number N (the next turn's opening state).
        next_move = (
            self.supabase.table("game_moves")
            .select("state_before")
            .eq("game_id", str(game_id))
            .eq("turn_number", turn_number)
            .order("move_number", desc=False)
            .limit(1)
            .execute()
        )
        if next_move.data:
            return next_move.data[0]["state_before"]

        # N is the last turn — only valid if N ≤ current turn_number
        resp = (
            self.supabase.table("games")
            .select("latest_state")
            .eq("id", str(game_id))
            .execute()
        )
        if not resp.data:
            return None
        latest = resp.data[0].get("latest_state")
        if latest is None:
            return None
        if turn_number > latest.get("turn_number", 0):
            return None
        return latest

    # ─── Undo requests ────────────────────────────────────────────────────────

    def get_pending_undo(self, game_id: UUID) -> dict | None:
        """Return the pending UndoRequest for a game, or None."""
        resp = (
            self.supabase.table("undo_requests")
            .select("*")
            .eq("game_id", str(game_id))
            .eq("status", "pending")
            .execute()
        )
        return resp.data[0] if resp.data else None

    def create_undo_request(
        self,
        game_id: UUID,
        target_turn_number: int,
        proposed_by: UUID,
    ) -> dict:
        """Create a new pending UndoRequest. Proposer implicitly votes agree."""
        record = {
            "id": str(uuid4()),
            "game_id": str(game_id),
            "target_turn_number": target_turn_number,
            "proposed_by": str(proposed_by),
            "votes": {str(proposed_by): "agree"},
            "status": "pending",
        }
        self.supabase.table("undo_requests").insert(record).execute()
        return record

    def vote_on_undo(self, request_id: str, player_id: UUID, vote: str) -> dict | None:
        """Record a player's vote on an undo request. Returns updated request or None."""
        # Fetch current request
        resp = (
            self.supabase.table("undo_requests")
            .select("*")
            .eq("id", request_id)
            .eq("status", "pending")
            .execute()
        )
        if not resp.data:
            return None
        request = resp.data[0]
        votes: dict = dict(request.get("votes") or {})
        votes[str(player_id)] = vote

        new_status = "pending"
        if vote == "disagree":
            new_status = "rejected"

        updated = (
            self.supabase.table("undo_requests")
            .update({"votes": votes, "status": new_status})
            .eq("id", request_id)
            .execute()
        )
        return updated.data[0] if updated.data else None

    def approve_undo(self, request_id: str, votes: dict) -> bool:
        """Mark an undo request as approved."""
        resp = (
            self.supabase.table("undo_requests")
            .update({"votes": votes, "status": "approved"})
            .eq("id", request_id)
            .execute()
        )
        return len(resp.data) == 1

    def get_state_before_turn(self, game_id: UUID, turn_number: int) -> dict | None:
        """Return the state_before from the first move of the given turn_number."""
        resp = (
            self.supabase.table("game_moves")
            .select("state_before")
            .eq("game_id", str(game_id))
            .eq("turn_number", turn_number)
            .order("move_number", desc=False)
            .limit(1)
            .execute()
        )
        return resp.data[0]["state_before"] if resp.data else None

    def get_max_turn_number(self, game_id: UUID) -> int:
        """Return the highest turn_number recorded in game_moves for this game, or 0."""
        resp = (
            self.supabase.table("game_moves")
            .select("turn_number")
            .eq("game_id", str(game_id))
            .order("turn_number", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0]["turn_number"] if resp.data else 0

    def add_player_to_game(self, game_id: UUID, player_id: UUID) -> str:
        """Add a player to an existing game. Returns a text code: 'ok' | 'not_found' | 'not_new' | 'duplicate' | 'full'"""
        response = self.supabase.rpc(
            "add_player_to_game", {"game_id": str(game_id), "player_id": str(player_id)}
        ).execute()
        return response.data

    def remove_player_from_game(
        self, game_id: UUID, requester_id: UUID, player_id: UUID
    ) -> str:
        """Remove a player from an existing game. Returns a text code: 'ok' | 'not_found' | 'not_host' | 'not_in_game' | 'is_host'"""
        response = self.supabase.rpc(
            "remove_player_from_game",
            {
                "game_id": str(game_id),
                "requester_id": str(requester_id),
                "player_id": str(player_id),
            },
        ).execute()
        return response.data


db = Db()
