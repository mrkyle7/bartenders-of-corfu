from uuid import UUID, uuid4
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from app.db import db

from app.user import User, TokenUser


class JWTHandler:
    
    
    def __init__(self, private_key: Optional[str] = None, algorithm: str = "RS256", expiration_hours: int = 24 * 7):
        self.public_keys = {}
        if private_key:
            self.private_key = serialization.load_pem_private_key(
                private_key.encode(),
                password=None,
                backend=default_backend()
            )
        else:
            # Generate new RSA key pair
            self.private_key: rsa.RSAPrivateKey = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )

        self.public_key: rsa.RSAPublicKey = self.private_key.public_key()
        self.algorithm = algorithm
        self.expiration_hours = expiration_hours
        self.kid: UUID = uuid4()
        db.add_public_key(self.kid, self.public_key.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        self.public_keys[str(self.kid)] = self.public_key

    def sign(self, user: User) -> str:
        """Sign a JWT token with a User. Returns the JWT string."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user.username,
            "id": str(user.id),
            "iat": now,
            "exp": now + timedelta(hours=self.expiration_hours),
            "kid": str(self.kid),
        }
        # PyJWT v2 returns a string
        token = jwt.encode(payload, self.private_key, algorithm=self.algorithm)
        return token

    def verify(self, token: str) -> Optional[TokenUser]:
        """Verify a JWT token and return the username (sub), or None if invalid/expired."""
        try:
            details = jwt.decode(token, options={"verify_signature": False})
            kid = details.get("kid")
            public_key=self.public_keys.get(kid)
            if public_key is None:
                public_key = db.get_public_key(UUID(kid))
                if public_key is None:
                    raise jwt.InvalidTokenError
            self.public_keys[kid] = public_key
            payload = jwt.decode(token, public_key,
                                 algorithms=[self.algorithm])
            return TokenUser(payload.get("sub"), payload.get("id"))
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    def get_public_key_pem(self) -> str:
        """Extract and return the public key in PEM format."""
        public_pem = self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return public_pem.decode()
