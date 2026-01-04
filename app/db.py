import os
import logging
from uuid import UUID
from supabase import create_client, Client
from app.user import User
from app.utils import bytesToHexString, hexStringToBytes

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
                {"id": str(user.id), "username": user.username, "email": user.email, "password": password_value}
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

        return [ User.from_dict(
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
            .limit(100)
            .execute()
        )
        return [ User.from_dict(
                {
                    "id": user.get('id'),
                    "username": user.get('username'),
                    "email": user.get('email'),
                    "password_hash": hexStringToBytes(user.get('password'))
                }
                ) for user in response.data ]
        

db = Db()