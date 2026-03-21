"""
Integration tests for the game-manager spec using FastAPI TestClient.
"""

import threading
import time
import unittest

from fastapi.testclient import TestClient
from app.api import app


def _unique(prefix: str) -> str:
    return f"{prefix}_{time.time_ns()}"


class GameManagerTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def _register(self, username: str, email: str, password: str = "Password1"):
        return self.client.post(
            "/register",
            json={"username": username, "email": email, "password": password},
        )

    def _token(self, response) -> str:
        return response.cookies.get("userjwt")

    def _auth(self, token: str) -> dict:
        return {"userjwt": token}

    def _new_game(self, token: str) -> str:
        resp = self.client.post("/v1/games", cookies=self._auth(token))
        self.assertEqual(resp.status_code, 200)
        return resp.json()["id"]

    def _join_game(self, token: str, game_id: str):
        return self.client.post(f"/v1/games/{game_id}/join", cookies=self._auth(token))

    def _remove_player(self, token: str, game_id: str, player_id: str):
        return self.client.delete(
            f"/v1/games/{game_id}/players/{player_id}", cookies=self._auth(token)
        )

    def _start_game(self, token: str, game_id: str):
        return self.client.post(f"/v1/games/{game_id}/start", cookies=self._auth(token))


class TestJoinGame(GameManagerTestCase):
    def test_join_game_success(self):
        host = _unique("host")
        host_reg = self._register(host, f"{host}@example.com")
        host_token = self._token(host_reg)
        game_id = self._new_game(host_token)

        player = _unique("player")
        player_reg = self._register(player, f"{player}@example.com")
        player_token = self._token(player_reg)

        resp = self._join_game(player_token, game_id)
        self.assertEqual(resp.status_code, 200)

    def test_join_game_duplicate_rejected(self):
        host = _unique("host")
        host_reg = self._register(host, f"{host}@example.com")
        host_token = self._token(host_reg)
        game_id = self._new_game(host_token)

        player = _unique("player")
        player_reg = self._register(player, f"{player}@example.com")
        player_token = self._token(player_reg)

        self._join_game(player_token, game_id)
        resp = self._join_game(player_token, game_id)
        self.assertEqual(resp.status_code, 409)

    def test_join_game_full_rejected(self):
        host = _unique("host")
        host_reg = self._register(host, f"{host}@example.com")
        host_token = self._token(host_reg)
        game_id = self._new_game(host_token)

        # Add 3 more players to fill the 4-player cap (host is player 1)
        for i in range(3):
            name = _unique(f"p{i}")
            reg = self._register(name, f"{name}@example.com")
            resp = self._join_game(self._token(reg), game_id)
            self.assertEqual(
                resp.status_code, 200, f"Player {i} should join successfully"
            )

        # 5th player (would be player 5) should be rejected
        name = _unique("overflow")
        reg = self._register(name, f"{name}@example.com")
        resp = self._join_game(self._token(reg), game_id)
        self.assertEqual(resp.status_code, 409)


class TestRemovePlayer(GameManagerTestCase):
    def _setup_game_with_player(self):
        """Create a game and add one additional player. Returns (host_token, host_id, game_id, player_token, player_id)."""
        host = _unique("host")
        host_reg = self._register(host, f"{host}@example.com")
        host_token = self._token(host_reg)
        host_id = host_reg.json()["id"]
        game_id = self._new_game(host_token)

        player = _unique("player")
        player_reg = self._register(player, f"{player}@example.com")
        player_token = self._token(player_reg)
        player_id = player_reg.json()["id"]
        self._join_game(player_token, game_id)

        return host_token, host_id, game_id, player_token, player_id

    def test_host_can_remove_player(self):
        host_token, _, game_id, _, player_id = self._setup_game_with_player()
        resp = self._remove_player(host_token, game_id, player_id)
        self.assertEqual(resp.status_code, 200)

    def test_non_host_cannot_remove_player(self):
        host_token, host_id, game_id, player_token, player_id = (
            self._setup_game_with_player()
        )
        # player tries to remove host
        resp = self._remove_player(player_token, game_id, host_id)
        self.assertEqual(resp.status_code, 403)

    def test_host_cannot_remove_themselves(self):
        host_token, host_id, game_id, _, _ = self._setup_game_with_player()
        resp = self._remove_player(host_token, game_id, host_id)
        self.assertEqual(resp.status_code, 400)

    def test_remove_player_not_in_game(self):
        host_token, _, game_id, _, _ = self._setup_game_with_player()
        from uuid import uuid4

        resp = self._remove_player(host_token, game_id, str(uuid4()))
        self.assertEqual(resp.status_code, 404)

    def test_remove_nonexistent_game(self):
        host = _unique("host")
        host_reg = self._register(host, f"{host}@example.com")
        host_token = self._token(host_reg)
        from uuid import uuid4

        resp = self._remove_player(host_token, str(uuid4()), str(uuid4()))
        self.assertEqual(resp.status_code, 404)

    def test_remove_player_requires_auth(self):
        from uuid import uuid4

        resp = self.client.delete(f"/v1/games/{uuid4()}/players/{uuid4()}")
        self.assertEqual(resp.status_code, 401)

    def test_cannot_remove_player_from_started_game(self):
        host_token, _, game_id, _, player_id = self._setup_game_with_player()
        self._start_game(host_token, game_id)
        resp = self._remove_player(host_token, game_id, player_id)
        self.assertEqual(resp.status_code, 409)
        self.assertIn("started", resp.json()["error"])


class TestConcurrentPlayerOps(GameManagerTestCase):
    def test_concurrent_join_only_one_succeeds(self):
        """Two threads race to join a game with one slot left; exactly one gets 200 and one gets 409."""
        host = _unique("host")
        host_reg = self._register(host, f"{host}@example.com")
        host_token = self._token(host_reg)
        game_id = self._new_game(host_token)

        # Fill 3 of 4 slots (host + 2 more players)
        for i in range(2):
            name = _unique(f"filler{i}")
            reg = self._register(name, f"{name}@example.com")
            resp = self._join_game(self._token(reg), game_id)
            self.assertEqual(resp.status_code, 200)

        # Register two racers
        racer_a = _unique("racer_a")
        racer_a_token = self._token(self._register(racer_a, f"{racer_a}@example.com"))
        racer_b = _unique("racer_b")
        racer_b_token = self._token(self._register(racer_b, f"{racer_b}@example.com"))

        barrier = threading.Barrier(2)
        results = []

        def join(token):
            barrier.wait()
            resp = self._join_game(token, game_id)
            results.append(resp.status_code)

        t1 = threading.Thread(target=join, args=(racer_a_token,))
        t2 = threading.Thread(target=join, args=(racer_b_token,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(sorted(results), [200, 409])

    def test_concurrent_remove_both_succeed(self):
        """Two threads race to remove different players; both removals must take effect."""
        host = _unique("host")
        host_reg = self._register(host, f"{host}@example.com")
        host_token = self._token(host_reg)
        game_id = self._new_game(host_token)

        # Add 3 more players so we have host + p1 + p2 + p3 (4 total)
        player_ids = []
        player_tokens = []
        for i in range(3):
            name = _unique(f"p{i}")
            reg = self._register(name, f"{name}@example.com")
            player_ids.append(reg.json()["id"])
            player_tokens.append(self._token(reg))
            resp = self._join_game(player_tokens[-1], game_id)
            self.assertEqual(resp.status_code, 200)

        barrier = threading.Barrier(2)
        results = []

        def remove(pid):
            barrier.wait()
            resp = self._remove_player(host_token, game_id, pid)
            results.append(resp.status_code)

        # Remove two different players concurrently
        t1 = threading.Thread(target=remove, args=(player_ids[0],))
        t2 = threading.Thread(target=remove, args=(player_ids[1],))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(sorted(results), [200, 200])

        # Verify both removals actually took effect — game should have exactly 2 players
        resp = self.client.get(f"/v1/games/{game_id}", cookies=self._auth(host_token))
        self.assertEqual(resp.status_code, 200)
        remaining = resp.json()["players"]
        self.assertEqual(
            len(remaining),
            2,
            f"Expected 2 players remaining, got {len(remaining)}: {remaining}",
        )


class TestStartGame(GameManagerTestCase):
    def _setup_game_with_two_players(self):
        """Create a game and add a second player. Returns (host_token, host_id, game_id, player_token, player_id)."""
        host = _unique("host")
        host_reg = self._register(host, f"{host}@example.com")
        host_token = self._token(host_reg)
        host_id = host_reg.json()["id"]
        game_id = self._new_game(host_token)

        player = _unique("player")
        player_reg = self._register(player, f"{player}@example.com")
        player_token = self._token(player_reg)
        player_id = player_reg.json()["id"]
        self._join_game(player_token, game_id)

        return host_token, host_id, game_id, player_token, player_id

    def test_host_can_start_game_with_two_players(self):
        host_token, _, game_id, _, _ = self._setup_game_with_two_players()
        resp = self._start_game(host_token, game_id)
        self.assertEqual(resp.status_code, 200)

    def test_start_game_updates_status_to_started(self):
        host_token, _, game_id, _, _ = self._setup_game_with_two_players()
        self._start_game(host_token, game_id)
        game_resp = self.client.get(
            f"/v1/games/{game_id}", cookies=self._auth(host_token)
        )
        self.assertEqual(game_resp.json()["status"], "STARTED")

    def test_start_game_initialises_game_state(self):
        """Started game should have bag, open_display (5 items), and player states."""
        host_token, host_id, game_id, _, player_id = self._setup_game_with_two_players()
        self._start_game(host_token, game_id)
        game_resp = self.client.get(
            f"/v1/games/{game_id}", cookies=self._auth(host_token)
        )
        state = game_resp.json()["game_state"]
        self.assertEqual(len(state["open_display"]), 5)
        self.assertEqual(len(state["bag_contents"]), 44)  # 49 - 5 open
        self.assertIn(host_id, state["player_states"])
        self.assertIn(player_id, state["player_states"])
        self.assertIsNotNone(state["player_turn"])

    def test_start_game_player_state_has_correct_initial_values(self):
        host_token, host_id, game_id, _, _ = self._setup_game_with_two_players()
        self._start_game(host_token, game_id)
        game_resp = self.client.get(
            f"/v1/games/{game_id}", cookies=self._auth(host_token)
        )
        ps = game_resp.json()["game_state"]["player_states"][host_id]
        self.assertEqual(ps["points"], 0)
        self.assertEqual(ps["drunk_level"], 0)
        self.assertEqual(ps["bladder_capacity"], 8)
        self.assertEqual(ps["toilet_tokens"], 4)
        self.assertEqual(ps["bladder"], [])
        self.assertEqual(ps["special_ingredients"], [])
        self.assertEqual(ps["karaoke_cards_claimed"], 0)
        self.assertEqual(ps["status"], "active")

    def test_non_host_cannot_start_game(self):
        _, _, game_id, player_token, _ = self._setup_game_with_two_players()
        resp = self._start_game(player_token, game_id)
        self.assertEqual(resp.status_code, 403)

    def test_cannot_start_game_with_only_one_player(self):
        host = _unique("solo")
        host_reg = self._register(host, f"{host}@example.com")
        host_token = self._token(host_reg)
        game_id = self._new_game(host_token)
        resp = self._start_game(host_token, game_id)
        self.assertEqual(resp.status_code, 409)
        self.assertIn("2 players", resp.json()["error"])

    def test_cannot_start_already_started_game(self):
        host_token, _, game_id, _, _ = self._setup_game_with_two_players()
        self._start_game(host_token, game_id)
        resp = self._start_game(host_token, game_id)
        self.assertEqual(resp.status_code, 409)

    def test_start_game_requires_auth(self):
        from uuid import uuid4

        resp = self.client.post(f"/v1/games/{uuid4()}/start")
        self.assertEqual(resp.status_code, 401)

    def test_start_nonexistent_game(self):
        host = _unique("host")
        host_reg = self._register(host, f"{host}@example.com")
        host_token = self._token(host_reg)
        from uuid import uuid4

        resp = self._start_game(host_token, str(uuid4()))
        self.assertEqual(resp.status_code, 404)

    def test_cannot_join_started_game(self):
        host_token, _, game_id, _, _ = self._setup_game_with_two_players()
        self._start_game(host_token, game_id)
        newcomer = _unique("newcomer")
        newcomer_reg = self._register(newcomer, f"{newcomer}@example.com")
        resp = self._join_game(self._token(newcomer_reg), game_id)
        self.assertEqual(resp.status_code, 409)


if __name__ == "__main__":
    unittest.main()
