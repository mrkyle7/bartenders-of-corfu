import re
from datetime import datetime
from uuid import UUID, uuid4
from typing import Optional
import bcrypt


class UserValidationError(Exception):
    """Raised when user input validation fails."""

    pass


class TokenUser:
    def __init__(self, username: str, id: str, iat: Optional[datetime] = None):
        self.username = username
        self.id = UUID(id)
        self.iat = iat  # UTC datetime when the token was issued

    def to_dict(self) -> dict:
        return {"username": self.username, "id": str(self.id)}


class User:
    def __init__(self, username: str, email: str, password: str):
        self.id: UUID = uuid4()
        self.status: str = "active"
        self.is_admin: bool = False
        self.username: Optional[str] = self._validate_name(username)
        self.email: Optional[str] = self._validate_email(email)
        self._password_hash: Optional[bytes] = self._hash_password(password)
        self.created_at: Optional[str] = None
        self.password_changed_at: Optional[str] = None
        self.deactivated_at: Optional[str] = None
        self.deactivated_by: Optional[UUID] = None
        self.deleted_at: Optional[str] = None
        self.logged_out_at: Optional[str] = None

    def _validate_name(self, name: str) -> str:
        if not isinstance(name, str):
            raise UserValidationError("Name must be a string")

        name = name.strip()

        if not name:
            raise UserValidationError("Name cannot be empty")

        if len(name) < 3:
            raise UserValidationError("Name must be at least 3 characters long")

        if len(name) > 50:
            raise UserValidationError("Name cannot exceed 50 characters")

        if not re.match(r"^[a-zA-Z0-9\s\-_]+$", name):
            raise UserValidationError(
                "Name can only contain letters, numbers, spaces, hyphens, and underscores"
            )

        return name

    def _validate_email(self, email: str) -> str:
        if not isinstance(email, str):
            raise UserValidationError("Email must be a string")

        email = email.strip()

        if not email:
            raise UserValidationError("Email cannot be empty")

        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(email_regex, email):
            raise UserValidationError("Invalid email format")

        return email

    def _validate_password(self, password: str) -> str:
        if not isinstance(password, str):
            raise UserValidationError("Password must be a string")

        if len(password) < 8:
            raise UserValidationError("Password must be at least 8 characters long")

        if len(password) > 128:
            raise UserValidationError("Password cannot exceed 128 characters")

        if not re.search(r"[a-zA-Z]", password):
            raise UserValidationError("Password must contain at least one letter")

        if not re.search(r"\d", password):
            raise UserValidationError("Password must contain at least one number")

        return password

    def _hash_password(self, password: str) -> bytes:
        validated_password = self._validate_password(password)
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(validated_password.encode("utf-8"), salt)

    def verify_secret(self, secret: str, hash: Optional[bytes]) -> bool:
        if not isinstance(secret, str):
            return False
        if not hash:
            return False
        try:
            return bcrypt.checkpw(secret.encode("utf-8"), hash)
        except (ValueError, TypeError):
            return False

    def change_password(self, old_password: str, new_password: str) -> bool:
        if not self.verify_secret(old_password, self._password_hash):
            raise UserValidationError("Incorrect password")

        self._password_hash = self._hash_password(new_password)
        return True

    def __repr__(self) -> str:
        return f"User(id={self.id}, name='{self.username}', status='{self.status}')"

    def __eq__(self, other) -> bool:
        if not isinstance(other, User):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def to_dict(self, include_sensitive: bool = False) -> dict:
        result: dict = {
            "id": str(self.id),
            "username": self.username,
            "status": self.status,
        }

        if include_sensitive:
            result["email"] = self.email
            result["is_admin"] = self.is_admin
            result["created_at"] = self.created_at
            result["deactivated_at"] = self.deactivated_at
            result["deactivated_by"] = (
                str(self.deactivated_by) if self.deactivated_by else None
            )

        return result

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        user = cls.__new__(cls)
        user.id = UUID(data["id"])
        user.status = data.get("status", "active")
        user.is_admin = data.get("is_admin", False)
        user.username = data.get("username")
        user.email = data.get("email")
        user.created_at = data.get("created_at")
        user.password_changed_at = data.get("password_changed_at")
        user.deactivated_at = data.get("deactivated_at")
        user.deactivated_by = (
            UUID(data["deactivated_by"]) if data.get("deactivated_by") else None
        )
        user.deleted_at = data.get("deleted_at")
        user.logged_out_at = data.get("logged_out_at")

        password_hash = data.get("password_hash")
        if password_hash:
            if isinstance(password_hash, bytes):
                user._password_hash = password_hash
            else:
                user._password_hash = password_hash.encode("utf-8")
        else:
            user._password_hash = None

        return user
