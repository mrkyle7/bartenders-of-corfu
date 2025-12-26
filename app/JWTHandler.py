import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets

class JWTHandler:
    def __init__(self, secret_key: Optional[str] = None, algorithm: str = "HS256", expiration_hours: int = 24):
        self.secret_key = secret_key or secrets.token_urlsafe(32)
        self.algorithm = algorithm
        self.expiration_hours = expiration_hours

    def sign(self, username: str) -> str:
        """Sign a JWT token with username as subject. Returns the JWT string."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": username,
            "iat": now,
            "exp": now + timedelta(hours=self.expiration_hours),
        }
        # PyJWT v2 returns a string
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token

    def verify(self, token: str) -> Optional[str]:
        """Verify a JWT token and return the username (sub), or None if invalid/expired."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload.get("sub")
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
