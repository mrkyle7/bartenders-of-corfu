#!/usr/bin/env python3

import sys
import os
import unittest

# Add the src directory to the path so we can import the user module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'bartenders-of-corfu'))

from app.user import User, UserValidationError

class TestUser(unittest.TestCase):

    def test_user_creation(self):
        """Test basic user creation."""

        user = User("TestUser123", "abc@abc.com", "password123")

        self.assertEqual(user.name, "TestUser123")
        self.assertTrue(user.verify_secret("abc@abc.com", user._email_hash))
        self.assertTrue(user.verify_secret("password123", user._password_hash))
        self.assertTrue(hasattr(user, 'id'))


    def test_password_validation(self):

        # Test password too short

        with self.assertRaises(UserValidationError):        
            User("TestUser", "abc@abc.com", "short")

        # Test password without letter
        with self.assertRaises(UserValidationError):
            User("TestUser", "abc@abc.com", "12345678")

        # Test password without number
        with self.assertRaises(UserValidationError):
            User("TestUser", "abc@abc.com", "password")

    def test_name_validation(self):
        """Test name validation rules."""

        # Test empty name
        with self.assertRaises(UserValidationError):
            User("", "abc@abc.com", "password123")
    
        # Test name too short
        with self.assertRaises(UserValidationError):
            User("ab", "abc@abc.com", "password123")
        
        # Test name with invalid characters
        with self.assertRaises(UserValidationError):
            User("Test@User!", "abc@abc.com", "password123")

    def test_email_verification(self):
        """Test email verification functionality."""

        # Test valid email
        user = User("TestUser", "abc@abc.com", "mypassword123")
        self.assertTrue(user.verify_secret("abc@abc.com", user._email_hash), "Should verify valid email")

        # Test invalid email formats
        invalid_emails = ["plainaddress", "@missingusername.com", "username@.com"]
        for email in invalid_emails:
            with self.assertRaises(UserValidationError):
                User("TestUser", email, "mypassword123")

    def test_password_verification(self):
        """Test password verification functionality."""

        user = User("TestUser", "abc@abc.com", "mypassword123")

        # Test correct password
        self.assertTrue(user.verify_secret("mypassword123", user._password_hash), "Should verify correct password")    
        
        # Test incorrect password
        self.assertFalse(user.verify_secret("wrongpassword", user._password_hash), "Should reject incorrect password")
    
        # Test invalid input types
        self.assertFalse(user.verify_secret(123, user._password_hash), "Should reject non-string input")


    def test_password_change(self):
        """Test password change functionality."""

        user = User("TestUser", "abc@abc.com", "oldpassword123")

        # Test successful password change
        self.assertTrue(user.change_password("oldpassword123", "newpassword456"), "Password change should succeed with correct old password")
        
        # Verify old password no longer works
        self.assertFalse(user.verify_secret("oldpassword123", user._password_hash), "Old password should not work")

        # Verify new password works
        self.assertTrue(user.verify_secret("newpassword456", user._password_hash), "New password should work")

        # Test failed password change with wrong old password
        with self.assertRaises(UserValidationError):
            user.change_password("wrongpassword", "anotherpassword789")


    def test_user_equality(self):
        """Test user equality and hashing."""

        user1 = User("User1", "abc@abc.com", "password123")
        user2 = User("User2", "abc@abc.com", "password456")
        user3 = user1  # Same instance
        
        
        # Test equality
        self.assertEqual(user1, user3, "Same user instance should be equal")
        self.assertNotEqual(user1, user2, "Different users should not be equal")
        
        # Test hashing (for use in sets/dicts)
        user_set = {user1, user2, user3}
        self.assertEqual(len(user_set), 2, "Set should contain only unique users")

    def test_serialization(self):
        """Test user serialization and deserialization."""
        
        original_user = User("TestUser", "abc@abc.com", "password123")
        
        # Test to_dict
        user_dict = original_user.to_dict()
        expected_keys = {'id', 'name'}
        self.assertEqual(set(user_dict.keys()), expected_keys, f"Expected keys {expected_keys}, got {set(user_dict.keys())}")
        
        # Test to_dict with sensitive data
        sensitive_dict = original_user.to_dict(include_sensitive=True)
        expected_sensitive_keys = {'id', 'name', 'password_hash', 'email_hash'}
        self.assertEqual(set(sensitive_dict.keys()), expected_sensitive_keys, f"Expected keys {expected_sensitive_keys}, got {set(sensitive_dict.keys())}")
        
        # Test from_dict
        restored_user = User.from_dict(sensitive_dict)
        self.assertEqual(restored_user.id, original_user.id, "Restored user should have same ID")
        self.assertEqual(restored_user.name, original_user.name, "Restored user should have same name")
        self.assertTrue(restored_user.verify_secret("password123", restored_user._password_hash), "Restored user should verify original password")
