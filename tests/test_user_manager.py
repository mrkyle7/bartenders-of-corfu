import unittest
import sys
import os

# Add the app directory to the path so we can import the modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.UserManager import UserManager, UserManagerUserExistsException


class TestUserManager(unittest.TestCase):

    def setUp(self):
        """Set up a fresh UserManager before each test."""
        self.user_manager = UserManager()
        # Clear existing users
        for user in self.user_manager.list_users():
            self.user_manager.delete_user(user.id)

    def test_new_user_creation(self):
        """Test basic user creation."""

        for user in self.user_manager.list_users():
            self.user_manager.delete_user(user.id)

        self.user_manager.new_user("test_user", "john@gmail.com", "password123")

        users = self.user_manager.list_users()
        self.assertTrue(any(u.name == "test_user" for u in users))

    def test_duplicate_user_error(self):
        """Test user manager duplicate user error handling."""

        self.user_manager.new_user("test_user", "john@gmail.com", "password123")
       
        with self.assertRaises(UserManagerUserExistsException):
            self.user_manager.new_user("test_user", "different_email@gmail.com", "password123")

        with self.assertRaises(UserManagerUserExistsException):
            self.user_manager.new_user("test_user2", "john@gmail.com", "password123")


if __name__ == "__main__":
    unittest.main()
