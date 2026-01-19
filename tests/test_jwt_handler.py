from datetime import datetime, timedelta, timezone
import unittest
import sys
import os
from uuid import uuid4

import jwt

from app.user import User
from app.JWTHandler import JWTHandler
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


# Add the app directory to the path so we can import the modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestJWTHandler(unittest.TestCase):

    def setUp(self):
        """Set up a fresh JWTHandler before each test."""
        self.jwt_handler = JWTHandler()

    def test_jwt_sign_and_verify(self):
        """Test signing and verifying a JWT token."""
        user = User("testuser", "test@abc.com", "Password123")
        token = self.jwt_handler.sign(user)

        # Decode the token to verify its contents
        decoded_payload = self.jwt_handler.verify(token)

        self.assertEqual(decoded_payload.username, user.username)
        self.assertEqual(decoded_payload.id, user.id)

    def test_jwt_fails_with_wrong_key(self):
        """Test signing and verifying a JWT token is fail with a different key."""
        user = User("testuser", "test@abc.com", "Password123")
        
        private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user.username,
            "id": str(user.id),
            "iat": now,
            "exp": now + timedelta(hours=1),
            "kid": str(uuid4()),
        }
        
        token = jwt.encode(payload, private_key, "RS256")

        decoded_payload = self.jwt_handler.verify(token)
        self.assertIsNone(decoded_payload)

    def test_jwt_is_ok_with_new_handler(self):
        """Test signing and verifying a JWT token with a new handler."""
        user = User("testuser", "test@abc.com", "Password123")
        token = self.jwt_handler.sign(user)

        diff_handler = JWTHandler()

        decoded_payload = diff_handler.verify(token)
        self.assertEqual(decoded_payload.username, user.username)
        self.assertEqual(decoded_payload.id, user.id)
