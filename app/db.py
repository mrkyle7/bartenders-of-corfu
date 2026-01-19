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
            .limit(100)
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


db = Db()