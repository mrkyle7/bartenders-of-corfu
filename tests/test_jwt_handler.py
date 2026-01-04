import unittest
import sys
import os

from app.user import User

# Add the app directory to the path so we can import the modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

class TestJWTHandler(unittest.TestCase):

    def setUp(self):
        """Set up a fresh JWTHandler before each test."""
        from app.JWTHandler import JWTHandler
        self.jwt_handler = JWTHandler()

    def test_jwt_sign_and_verify(self):
        """Test signing and verifying a JWT token."""
        user = User("testuser", "test@abc.com", "Password123")
        token = self.jwt_handler.sign(user)

        # Decode the token to verify its contents
        decoded_payload = self.jwt_handler.verify(token)

        self.assertEqual(decoded_payload.username, user.username)
        self.assertEqual(decoded_payload.id, user.id)
