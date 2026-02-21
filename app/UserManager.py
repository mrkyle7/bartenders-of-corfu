from uuid import UUID
from app.user import User, UserValidationError
from app.db import db


class UserManagerUserExistsException(Exception):
    pass


class UserManagerPermissionError(Exception):
    pass


class UserManager:
    def authenticate_user(self, username: str, password: str) -> User | None:
        """Authenticate a user. Returns User only if credentials are valid and account is active."""
        user = self.get_user_by_username(username)
        if user and user.status == "active" and user.verify_secret(password, user._password_hash):
            return user
        return None

    def get_user_by_username(self, username: str) -> User | None:
        return db.get_user_by_username(username)

    def get_user(self, id: UUID) -> User | None:
        return db.get_user_by_id(id)

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
        """Returns all non-deleted users."""
        return db.get_users()

    def logout_user(self, user_id: UUID) -> None:
        """Record the logout time so the issued token is server-side invalidated."""
        db.logout_user(user_id)

    def change_password(self, user_id: UUID, old_password: str, new_password: str) -> None:
        """Change a user's password. Raises UserValidationError if old password is wrong."""
        user = db.get_user_by_id(user_id)
        if not user or user.status != "active":
            raise UserValidationError("User not found or account is not active")
        user.change_password(old_password, new_password)
        db.update_password(user_id, user._password_hash)

    def delete_user(self, user_id: UUID) -> None:
        """Delete own account: nulls PII, preserves ID for game history."""
        user = db.get_user_by_id(user_id)
        if not user or user.status != "active":
            raise UserValidationError("User not found or account is not active")
        db.delete_user(user_id)

    def deactivate_user(self, admin_id: UUID, target_id: UUID) -> None:
        """Admin deactivates an active account."""
        admin = db.get_user_by_id(admin_id)
        if not admin or not admin.is_admin:
            raise UserManagerPermissionError("Admin access required")
        target = db.get_user_by_id(target_id)
        if not target or target.status != "active":
            raise UserValidationError("Target user not found or is not active")
        db.deactivate_user(target_id, admin_id)

    def reactivate_user(self, admin_id: UUID, target_id: UUID) -> None:
        """Admin reactivates a deactivated account."""
        admin = db.get_user_by_id(admin_id)
        if not admin or not admin.is_admin:
            raise UserManagerPermissionError("Admin access required")
        target = db.get_user_by_id(target_id)
        if not target or target.status != "deactivated":
            raise UserValidationError("Target user not found or is not deactivated")
        db.reactivate_user(target_id)
