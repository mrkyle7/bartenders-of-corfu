from uuid import UUID
from app.user import User

class UserManagerUserExistsException(Exception):
    pass

class UserManager:
    __users = set() # type: set[User]

    def authenticate_user(self, username: str, password: str) -> User | None:
        """Authenticate a user by their username and password. Returns the User if successful, else None."""
        for user in self.__users:
            if user.name == username and user.verify_secret(password, user._password_hash):
                return user
        return None
    
    def get_user_by_username(self, username: str) -> User | None:
        for user in self.__users:
            if user.name == username:
                return user
        return None

    def new_user(self, name, email, password) -> User:
        if any([user.verify_secret(email, user._email_hash) for user in self.__users]):
            print(f"User with email {email} already exists.")
            raise UserManagerUserExistsException("A user already exists with that email")

        if any([user.name == name for user in self.__users]):
            print(f"User with name {name} already exists.")
            raise UserManagerUserExistsException("A user already exists with that name")
        
        new_user = User(name, email, password)
        self.__users.add(new_user)
        return new_user

    def list_users(self) -> tuple[User, ...]:
        """Returns a tuple of all users"""
        return tuple(self.__users)
    
    def delete_user(self, user_id: UUID) -> None:
        """Deletes a user by their ID"""
        self.__users = {user for user in self.__users if user.id != user_id}