import re
from uuid import UUID, uuid4
import bcrypt


class UserValidationError(Exception):
    """Raised when user input validation fails."""
    pass


class User:
    """
    Represents a user in the Bartenders of Corfu application.
    
    This class handles user creation with secure password hashing,
    input validation, and provides methods for password verification.
    
    Attributes:
        id (UUID): Unique identifier for the user
        name (str): User's display name
        _email_hash (bytes): Securely hashed email - used for linking other authentication methods without storing plaintext email
        _password_hash (bytes): Securely hashed password
    """

    def __init__(self, name: str, email: str, password: str):
        """
        Initialize a new User instance.
        
        Args:
            name (str): The user's name (3-50 characters, alphanumeric and spaces)
            email (str): The user's email
            password (str): The user's password (minimum 8 characters)
            
        Raises:
            UserValidationError: If name or password validation fails
        """
        self.id: UUID = uuid4()
        self.name: str = self._validate_name(name)
        self._email_hash: bytes = self._hash_email(email)
        self._password_hash: bytes = self._hash_password(password)
    
    def _validate_name(self, name: str) -> str:
        """
        Validate the user's name.
        
        Args:
            name (str): The name to validate
            
        Returns:
            str: The validated name (stripped of leading/trailing whitespace)
            
        Raises:
            UserValidationError: If name validation fails
        """
        if not isinstance(name, str):
            raise UserValidationError("Name must be a string")
        
        name = name.strip()
        
        if not name:
            raise UserValidationError("Name cannot be empty")
        
        if len(name) < 3:
            raise UserValidationError("Name must be at least 3 characters long")
        
        if len(name) > 50:
            raise UserValidationError("Name cannot exceed 50 characters")
        
        # Allow alphanumeric characters, spaces, hyphens, and underscores
        if not re.match(r'^[a-zA-Z0-9\s\-_]+$', name):
            raise UserValidationError(
                "Name can only contain letters, numbers, spaces, hyphens, and underscores"
            )
        
        return name
    
    def _validate_email(self, email: str) -> str:
        """
        Validate the user's email address.

        Args:
            email (str): The email address to validate

        Returns:
            str: The validated email address

        Raises:
            UserValidationError: If email validation fails
        """
        if not isinstance(email, str):
            raise UserValidationError("Email must be a string")

        email = email.strip()

        if not email:
            raise UserValidationError("Email cannot be empty")

        # Basic email format validation
        email_regex = r'^[\w\.-]+@[\w\.-]+\.\w+$'
        if not re.match(email_regex, email):
            raise UserValidationError("Invalid email format")

        return email

    def _validate_password(self, password: str) -> str:
        """
        Validate the user's password.
        
        Args:
            password (str): The password to validate
            
        Returns:
            str: The validated password
            
        Raises:
            UserValidationError: If password validation fails
        """
        if not isinstance(password, str):
            raise UserValidationError("Password must be a string")
        
        if len(password) < 8:
            raise UserValidationError("Password must be at least 8 characters long")
        
        if len(password) > 128:
            raise UserValidationError("Password cannot exceed 128 characters")
        
        # Check for at least one letter and one number
        if not re.search(r'[a-zA-Z]', password):
            raise UserValidationError("Password must contain at least one letter")
        
        if not re.search(r'\d', password):
            raise UserValidationError("Password must contain at least one number")
        
        return password
    
    def _hash_password(self, password: str) -> bytes:
        """
        Hash a password using bcrypt.
        
        Args:
            password (str): The plain text password to hash
            
        Returns:
            bytes: The hashed password
            
        Raises:
            UserValidationError: If password validation fails
        """
        validated_password = self._validate_password(password)
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(validated_password.encode('utf-8'), salt)
    
    
    def _hash_email(self, email: str) -> bytes:
        """
        Hash an email using bcrypt.
        
        Args:
            email (str): The plain text email to hash
            
        Returns:
            bytes: The hashed email
            
        Raises:
            UserValidationError: If email validation fails
        """
        validated_email = self._validate_email(email)
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(validated_email.encode('utf-8'), salt)
    
    def verify_secret(self, secret: str, hash: bytes) -> bool:
        """
        Verify a secret string (password or email) against the stored hash.
        
        Args:
            secret (str): The plaintext secret to verify
            
        Returns:
            bool: True if secret matches, False otherwise
        """
        if not isinstance(secret, str):
            return False
        
        try:
            return bcrypt.checkpw(secret.encode('utf-8'), hash)
        except (ValueError, TypeError):
            return False
    
    def change_password(self, old_password: str, new_password: str) -> bool:
        """
        Change the user's password.
        
        Args:
            old_password (str): The current password
            new_password (str): The new password
            
        Returns:
            bool: True if password was changed successfully, False if old password is incorrect
            
        Raises:
            UserValidationError: If new password validation fails
        """
        if not self.verify_secret(old_password, self._password_hash):
            raise UserValidationError("Incorrect password")
        
        self._password_hash = self._hash_password(new_password)
        return True
    
    def __repr__(self) -> str:
        """
        Return a string representation of the User.
        
        Note: Password hash is intentionally excluded for security.
        
        Returns:
            str: String representation of the user
        """
        return f"User(id={self.id}, name='{self.name}')"
    
    def __eq__(self, other) -> bool:
        """
        Check equality with another User instance.
        
        Args:
            other: The object to compare with
            
        Returns:
            bool: True if users have the same name and email
        """
        if not isinstance(other, User):
            return False
        return self.id == other.id
    
    def __hash__(self) -> int:
        """
        Return hash of the user based on ID.
        
        Returns:
            int: Hash value
        """
        return hash(self.id)
    
    def to_dict(self, include_sensitive: bool = False) -> dict:
        """
        Convert user to dictionary representation.
        
        Args:
            include_sensitive (bool): Whether to include sensitive data (password hash)
            
        Returns:
            dict: Dictionary representation of the user
        """
        result = {
            'id': str(self.id),
            'name': self.name
        }
        
        if include_sensitive:
            result['password_hash'] = self._password_hash.decode('utf-8')
            result['email_hash'] = self._email_hash.decode('utf-8')
        
        return result
    
    @classmethod
    def from_dict(cls, data: dict) -> 'User':
        """
        Create a User instance from dictionary data.
        
        This method is useful for deserializing user data from storage.
        Note: This bypasses normal validation and should only be used
        with trusted data from storage.
        
        Args:
            data (dict): Dictionary containing user data
            
        Returns:
            User: New User instance
            
        Raises:
            KeyError: If required keys are missing
            ValueError: If data format is invalid
        """
        user = cls.__new__(cls)  # Create instance without calling __init__
        user.id = UUID(data['id'])
        user.name = data['name']
        
        if 'password_hash' in data:
            user._password_hash = data['password_hash'].encode('utf-8')
        else:
            raise KeyError("password_hash is required for user deserialization")
        
        if 'email_hash' in data:
            user._email_hash = data['email_hash'].encode('utf-8')
        else:
            raise KeyError("email_hash is required for user deserialization")
        
        return user
