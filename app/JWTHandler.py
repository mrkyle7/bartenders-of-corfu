import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets

from app.user import User, UserShort

class JWTHandler:
    def __init__(self, secret_key: Optional[str] = None, algorithm: str = "HS256", expiration_hours: int = 24 * 7):
        self.secret_key = secret_key or secrets.token_urlsafe(32)
        self.algorithm = algorithm
        self.expiration_hours = expiration_hours

    def sign(self, user: User) -> str:
        """Sign a JWT token with a User. Returns the JWT string."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user.username,
            "id": str(user.id),
            "iat": now,
            "exp": now + timedelta(hours=self.expiration_hours),
        }
        # PyJWT v2 returns a string
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token

    def verify(self, token: str) -> Optional[UserShort]:
        """Verify a JWT token and return the username (sub), or None if invalid/expired."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return UserShort(payload.get("sub"), payload.get("id"))
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
