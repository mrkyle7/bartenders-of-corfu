from uuid import UUID
from app.user import User
from app.db import db


class UserManagerUserExistsException(Exception):
    pass


class UserManager:
    def authenticate_user(self, username: str, password: str) -> User | None:
        """Authenticate a user by their username and password. Returns the User if successful, else None."""
        user = self.get_user_by_username(username)
        if user and user.verify_secret(password, user._password_hash):
            return user
        return None

    def get_user_by_username(self, username: str) -> User | None:
        user: User = db.get_user_by_username(username)
        return user

    def get_user(self, id: UUID) -> User | None:
        user: User = db.get_user_by_id(id)
        return user

    def new_user(self, name, email, password) -> User:
        new_user: User = User(name, email, password)
        try:
            db.add_user(new_user)
        except Exception as e:
            if "duplicate key" in str(e):
                raise UserManagerUserExistsException(
                    "User already exists by name or email"
                )
            else:
                raise e
        return new_user

    def list_users(self) -> list[User]:
        """Returns a list of all users"""
        return db.get_users()
