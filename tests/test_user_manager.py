import unittest
import sys
import os
import time

# Add the app directory to the path so we can import the modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


from app.UserManager import UserManager, UserManagerUserExistsException


class TestUserManager(unittest.TestCase):
    def setUp(self):
        """Set up a fresh UserManager before each test."""
        self.user_manager = UserManager()

    def test_new_user_creation(self):
        """Test basic user creation."""

        user = f"test_user{time.time_ns()}"
        email = f"john{time.time_ns()}@gmail.com"
        self.user_manager.new_user(user, email, "password123")

        users = self.user_manager.list_users()
        self.assertTrue(any(u.username == user for u in users))

    def test_duplicate_user_error(self):
        """Test user manager duplicate user error handling."""

        user = f"test_user{time.time_ns()}"
        email = f"john{time.time_ns()}@gmail.com"
        self.user_manager.new_user(user, email, "password123")

        with self.assertRaises(UserManagerUserExistsException):
            self.user_manager.new_user(user, "different_email@gmail.com", "password123")

        with self.assertRaises(UserManagerUserExistsException):
            self.user_manager.new_user("test_user2", email, "password123")


if __name__ == "__main__":
    unittest.main()
