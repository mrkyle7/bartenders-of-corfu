#!/usr/bin/env python3

import sys
import os
import unittest
import time

# Add the app directory to the path so we can import the modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from fastapi.testclient import TestClient
from app.api import app


class TestAPI(unittest.TestCase):
    def setUp(self):
        """Set up test client."""
        self.client = TestClient(app)
        self.test_user = None
        self.test_game = None
        self.jwt_token = None

    def test_health_endpoint(self):
        """Test the health check endpoint."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"isAvailable": True})

    def test_root_endpoint(self):
        """Test the root endpoint returns HTML."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertIn("Bartenders of Corfu", response.text)

    def test_login_page_endpoint(self):
        """Test the login page endpoint."""
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))

    def test_game_page_endpoint(self):
        """Test the game page endpoint."""
        response = self.client.get("/game")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))

    def test_list_games_no_auth_required(self):
        """Test listing games doesn't require authentication."""
        response = self.client.get("/v1/games")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("games", data)
        self.assertIn("page", data)
        self.assertIn("page_size", data)
        self.assertIn("total", data)

    def test_list_games_pagination_fields(self):
        """Pagination metadata is returned correctly."""
        response = self.client.get("/v1/games?page=1&page_size=5")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 5)
        self.assertIsInstance(data["total"], int)
        self.assertLessEqual(len(data["games"]), 5)

    def test_list_games_invalid_page_size(self):
        """page_size > 100 is rejected."""
        response = self.client.get("/v1/games?page_size=101")
        self.assertEqual(response.status_code, 422)

    def test_list_games_invalid_status(self):
        """An unrecognised status value returns 400."""
        response = self.client.get("/v1/games?status=BOGUS")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_list_games_valid_status_filter(self):
        """status=NEW filter is accepted and returns only NEW games."""
        response = self.client.get("/v1/games?status=NEW")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        for game in data["games"]:
            self.assertEqual(game["status"], "NEW")

    def test_list_games_status_case_insensitive(self):
        """status filter accepts lowercase."""
        response = self.client.get("/v1/games?status=new")
        self.assertEqual(response.status_code, 200)

    def test_list_games_invalid_player_id(self):
        """A non-UUID player_id returns 400."""
        response = self.client.get("/v1/games?player_id=not-a-uuid")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_list_games_player_id_filter(self):
        """player_id filter returns only games containing that player."""
        timestamp = int(time.time() * 1000000)
        user_data = {
            "username": f"filteruser{timestamp}",
            "email": f"filteruser{timestamp}@example.com",
            "password": "password123",
        }
        reg = self.client.post("/register", json=user_data)
        self.assertEqual(reg.status_code, 201)
        token = reg.cookies.get("userjwt")
        user_id = reg.json()["id"]

        # Create a game as this user
        game_resp = self.client.post("/v1/games", cookies={"userjwt": token})
        self.assertEqual(game_resp.status_code, 200)

        # Filter by player_id — game must appear
        response = self.client.get(f"/v1/games?player_id={user_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        player_ids_in_results = [pid for g in data["games"] for pid in g["players"]]
        self.assertIn(user_id, player_ids_in_results)

    def test_create_game_requires_auth(self):
        """Test creating a game requires authentication."""
        response = self.client.post("/v1/games")
        self.assertEqual(response.status_code, 401)

    def test_create_game_success(self):
        """Test successfully creating a game with real user."""
        # First create a real user
        timestamp = int(time.time() * 1000000)  # Microsecond precision
        user_data = {
            "username": f"testuser{timestamp}",
            "email": f"test{timestamp}@example.com",
            "password": "password123",
        }
        response = self.client.post("/register", json=user_data)
        self.assertEqual(response.status_code, 201)

        # Get the JWT token from the response
        jwt_token = response.cookies.get("userjwt")
        self.assertIsNotNone(jwt_token)

        # Now create a game with the authenticated user
        response = self.client.post("/v1/games", cookies={"userjwt": jwt_token})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("id", data)

        # Store for cleanup
        self.test_game = data["id"]
        self.test_user = user_data["username"]
        self.jwt_token = jwt_token

    def test_join_game_success(self):
        """Test successfully joining a game with real user."""
        # First create a real user
        timestamp = int(time.time() * 1000000)  # Microsecond precision
        user_data = {
            "username": f"testuser{timestamp}",
            "email": f"test{timestamp}@example.com",
            "password": "password123",
        }
        response = self.client.post("/register", json=user_data)
        host_id = response.json().get("id")
        self.assertEqual(response.status_code, 201)

        # Get the JWT token from the response
        jwt_token = response.cookies.get("userjwt")
        self.assertIsNotNone(jwt_token)

        # Now create a game with the authenticated user
        response = self.client.post("/v1/games", cookies={"userjwt": jwt_token})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("id", data)
        game_id = data.get("id")

        # now create a user to join the game

        timestamp = int(time.time() * 1000000)  # Microsecond precision
        user_data = {
            "username": f"testuser{timestamp}",
            "email": f"test{timestamp}@example.com",
            "password": "password123",
        }
        response = self.client.post("/register", json=user_data)
        joinee_id = response.json().get("id")
        self.assertEqual(response.status_code, 201)

        # Get the JWT token from the response
        jwt_token = response.cookies.get("userjwt")
        self.assertIsNotNone(jwt_token)

        # try and join the game!

        print(f"joining game {game_id}")

        response = self.client.post(
            f"/v1/games/{game_id}/join", cookies={"userjwt": jwt_token}
        )
        self.assertEqual(response.status_code, 200)

        # now check the players are in the game

        response = self.client.get(
            f"/v1/games/{game_id}", cookies={"userjwt": jwt_token}
        )
        self.assertEqual(response.status_code, 200)
        self.assertListEqual(
            sorted([host_id, joinee_id]), sorted(response.json().get("players"))
        )

        # Store for cleanup
        self.test_game = game_id
        self.test_user = user_data["username"]
        self.jwt_token = jwt_token

    def test_join_game_requires_auth(self):
        """Test joining a game requires authentication."""
        response = self.client.post("/v1/games/123/join")
        self.assertEqual(response.status_code, 401)

    def test_join_nonexistent_game(self):
        """Test joining a nonexistent game returns 404."""
        # Create a test user first with more unique identifiers
        timestamp = int(time.time() * 1000000)  # Microsecond precision
        user_data = {
            "username": f"testuser{timestamp}",
            "email": f"test{timestamp}@example.com",
            "password": "password123",
        }
        response = self.client.post("/register", json=user_data)
        self.assertEqual(response.status_code, 201)
        jwt_token = response.cookies.get("userjwt")

        response = self.client.post(
            "/v1/games/nonexistent-id/join", cookies={"userjwt": jwt_token}
        )
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertEqual(data["error"], "Game not found")

    def test_get_game_requires_auth(self):
        """Test getting a specific game requires authentication."""
        response = self.client.get("/v1/games/123")
        self.assertEqual(response.status_code, 401)

    def test_create_user_success(self):
        """Test successfully creating a user."""
        timestamp = int(time.time() * 1000000)  # Microsecond precision
        user_data = {
            "username": f"testuser{timestamp}",
            "email": f"test{timestamp}@example.com",
            "password": "password123",
        }

        response = self.client.post("/v1/users", json=user_data)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["username"], user_data["username"])

    def test_create_user_invalid_data(self):
        """Test creating a user with invalid data."""
        user_data = {
            "username": "",  # Invalid empty username
            "email": "invalid-email",
            "password": "short",
        }

        response = self.client.post("/v1/users", json=user_data)
        self.assertEqual(response.status_code, 400)

    def test_register_success(self):
        """Test successful user registration."""
        timestamp = int(time.time() * 1000000)  # Microsecond precision
        user_data = {
            "username": f"testuser{timestamp}",
            "email": f"test{timestamp}@example.com",
            "password": "password123",
        }

        response = self.client.post("/register", json=user_data)
        self.assertEqual(response.status_code, 201)
        self.assertIn("userjwt", response.cookies)
        self.assertEqual(response.headers.get("Location"), "/")

    def test_login_success(self):
        """Test successful login."""
        # First register a user
        timestamp = int(time.time() * 1000000)  # Microsecond precision
        user_data = {
            "username": f"testuser{timestamp}",
            "email": f"test{timestamp}@example.com",
            "password": "password123",
        }
        self.client.post("/register", json=user_data)

        # Now try to login
        login_data = {"username": user_data["username"], "password": "password123"}

        response = self.client.post("/login", json=login_data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("userjwt", response.cookies)
        self.assertEqual(response.headers.get("Location"), "/")

    def test_login_invalid_credentials(self):
        """Test login with invalid credentials."""
        login_data = {"username": "nonexistent", "password": "wrongpassword"}

        response = self.client.post("/login", json=login_data)
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertEqual(data["error"], "Invalid credentials")

    def test_logout(self):
        """Test logout endpoint."""
        response = self.client.post("/logout")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["message"], "Logged out")

    def test_user_details_invalid_token(self):
        """Test user details with invalid token."""
        response = self.client.get("/userDetails", cookies={"userjwt": "invalid-token"})
        self.assertEqual(response.status_code, 401)

    def test_list_users(self):
        """Test listing users requires auth and returns a list."""
        # Unauthenticated
        response = self.client.get("/v1/users")
        self.assertEqual(response.status_code, 401)

        # Authenticated
        timestamp = int(time.time() * 1000000)
        user_data = {
            "username": f"listuser{timestamp}",
            "email": f"listuser{timestamp}@example.com",
            "password": "password123",
        }
        reg = self.client.post("/register", json=user_data)
        token = reg.cookies.get("userjwt")
        response = self.client.get("/v1/users", cookies={"userjwt": token})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("users", data)
        self.assertIsInstance(data["users"], list)


if __name__ == "__main__":
    unittest.main()
