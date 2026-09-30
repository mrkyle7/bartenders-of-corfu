"""Supabase-dependent API tests for push notification endpoints."""

import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from app.api import app


def _register(client: TestClient) -> tuple[str, str]:
    """Register a throwaway user and return (user_id, jwt_token)."""
    ts = int(time.time() * 1_000_000)
    resp = client.post(
        "/register",
        json={
            "username": f"pushtest{ts}",
            "email": f"pushtest{ts}@example.com",
            "password": "password123",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], resp.cookies["userjwt"]


_FAKE_SUB = {
    "endpoint": "https://push.example.com/sub/fake-endpoint-{ts}",
    "keys": {
        "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtBBMWVNuT2985JHbek",
        "auth": "tBHItJI5svbpez7KI4CCXg",
    },
}


class TestVapidPublicKeyEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_returns_503_when_not_configured(self):
        with patch("app.push._VAPID_PUBLIC_KEY", ""):
            resp = self.client.get("/vapid-public-key")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("error", resp.json())

    def test_returns_public_key_when_configured(self):
        with patch("app.push._VAPID_PUBLIC_KEY", "FAKE_PUBLIC_KEY_VALUE"):
            resp = self.client.get("/vapid-public-key")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("public_key", data)
        self.assertEqual(data["public_key"], "FAKE_PUBLIC_KEY_VALUE")


class TestSavePushSubscription(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user_id, self.token = _register(self.client)

    def _sub(self) -> dict:
        ts = int(time.time() * 1_000_000)
        return {
            "endpoint": f"https://push.example.com/sub/{ts}",
            "keys": {
                "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtBBMWVNuT2985JHbek",
                "auth": "tBHItJI5svbpez7KI4CCXg",
            },
        }

    def test_requires_auth(self):
        resp = self.client.post(
            "/v1/push-subscriptions", json=self._sub(), cookies={"userjwt": "invalid"}
        )
        self.assertEqual(resp.status_code, 401)

    def test_saves_subscription(self):
        resp = self.client.post(
            "/v1/push-subscriptions",
            json=self._sub(),
            cookies={"userjwt": self.token},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json(), {"ok": True})

    def test_idempotent_on_same_endpoint(self):
        sub = self._sub()
        r1 = self.client.post(
            "/v1/push-subscriptions", json=sub, cookies={"userjwt": self.token}
        )
        r2 = self.client.post(
            "/v1/push-subscriptions", json=sub, cookies={"userjwt": self.token}
        )
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)

    def test_rejects_missing_keys_field(self):
        resp = self.client.post(
            "/v1/push-subscriptions",
            json={"endpoint": "https://example.com/push/x"},
            cookies={"userjwt": self.token},
        )
        self.assertEqual(resp.status_code, 422)


class TestDeletePushSubscription(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user_id, self.token = _register(self.client)

    def _endpoint(self) -> str:
        return f"https://push.example.com/sub/{int(time.time() * 1_000_000)}"

    def test_requires_auth(self):
        resp = self.client.request(
            "DELETE",
            "/v1/push-subscriptions",
            json={"endpoint": "https://push.example.com/sub/x"},
            cookies={"userjwt": "invalid"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_deletes_existing_subscription(self):
        endpoint = self._endpoint()
        self.client.post(
            "/v1/push-subscriptions",
            json={
                "endpoint": endpoint,
                "keys": {"p256dh": "FAKEP256DH", "auth": "FAKEAUTH"},
            },
            cookies={"userjwt": self.token},
        )
        resp = self.client.request(
            "DELETE",
            "/v1/push-subscriptions",
            json={"endpoint": endpoint},
            cookies={"userjwt": self.token},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})

    def test_no_endpoint_returns_400(self):
        resp = self.client.request(
            "DELETE",
            "/v1/push-subscriptions",
            json={},
            cookies={"userjwt": self.token},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_delete_nonexistent_subscription_still_200(self):
        resp = self.client.request(
            "DELETE",
            "/v1/push-subscriptions",
            json={"endpoint": "https://push.example.com/sub/does-not-exist"},
            cookies={"userjwt": self.token},
        )
        self.assertEqual(resp.status_code, 200)

    def test_only_the_owner_can_remove_a_device(self):
        from app.db import db

        endpoint = self._endpoint()
        self.client.post(
            "/v1/push-subscriptions",
            json={"endpoint": endpoint, "keys": {"p256dh": "P", "auth": "A"}},
            cookies={"userjwt": self.token},
        )
        _, other_token = _register(self.client)
        resp = self.client.request(
            "DELETE",
            "/v1/push-subscriptions",
            json={"endpoint": endpoint},
            cookies={"userjwt": other_token},
        )
        self.assertEqual(resp.status_code, 200)
        endpoints = [s["endpoint"] for s in db.get_push_subscriptions(self.user_id)]
        self.assertIn(endpoint, endpoints)


class TestSaveRejectsUnsafeEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user_id, self.token = _register(self.client)

    def test_rejects_endpoints_on_the_servers_network(self):
        for endpoint in (
            "http://push.example.com/x",
            "https://127.0.0.1/x",
            "https://metadata.google.internal/computeMetadata/v1/",
        ):
            resp = self.client.post(
                "/v1/push-subscriptions",
                json={"endpoint": endpoint, "keys": {"p256dh": "P", "auth": "A"}},
                cookies={"userjwt": self.token},
            )
            self.assertEqual(resp.status_code, 400, endpoint)


class TestAway(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_requires_auth(self):
        resp = self.client.post("/v1/games/abc/away", cookies={"userjwt": "invalid"})
        self.assertEqual(resp.status_code, 401)

    def test_viewing_a_game_counts_as_watching_until_away(self):
        from app import presence

        user_id, token = _register(self.client)
        game_id = self.client.post("/v1/games", cookies={"userjwt": token}).json()["id"]
        self.client.get(f"/v1/games/{game_id}", cookies={"userjwt": token})
        self.assertTrue(presence.is_watching(game_id, user_id))
        resp = self.client.post(f"/v1/games/{game_id}/away", cookies={"userjwt": token})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(presence.is_watching(game_id, user_id))


class TestNotifyAfterAction(unittest.TestCase):
    """_notify_after_action with the game, users and push mocked."""

    def setUp(self):
        from uuid import uuid4
        from app import presence

        presence.clear()
        self.game_id = uuid4()
        self.a, self.b, self.bot = uuid4(), uuid4(), uuid4()
        self.sent = []

    def _game(self, turn, winner=None):
        game = MagicMock()
        game.id = self.game_id
        game.host = self.a
        game.players = [self.a, self.bot, self.b]
        game.game_state.player_turn = turn
        game.game_state.winner = winner
        return game

    def _user(self, uid, name, is_bot=False):
        u = MagicMock()
        u.id, u.username, u.is_bot = uid, name, is_bot
        return u

    def _run(self, game, old_turn, cancelled=False):
        import app.api as api

        users = {
            self.a: self._user(self.a, "ann"),
            self.b: self._user(self.b, "bob"),
            self.bot: self._user(self.bot, "bot", True),
        }
        subs = {
            uid: [
                {
                    "endpoint": f"https://push.example.com/{uid}",
                    "p256dh": "p",
                    "auth": "a",
                }
            ]
            for uid in users
        }

        def send(subscription_info, title, body, url, tag=None):
            self.sent.append((subscription_info["endpoint"], body, url, tag))
            return True

        with (
            patch.object(api.gameManager, "get_game_by_id", return_value=game),
            patch.object(
                api.userManager, "get_user", side_effect=lambda uid: users.get(uid)
            ),
            patch.object(
                api.userManager, "get_users_by_ids", return_value=list(users.values())
            ),
            patch.object(
                api.db, "get_push_subscriptions", side_effect=lambda uid: subs[uid]
            ),
            patch.object(api.push, "send_push", side_effect=send),
        ):
            api._notify_after_action(
                self.game_id, old_turn, game if cancelled else None
            )

    def test_tells_the_next_human_after_the_bots_have_moved(self):
        # Ann's move passed the turn to the bot, which moved on to Bob
        self._run(self._game(turn=self.b), old_turn=self.a)
        self.assertEqual(
            self.sent,
            [
                (
                    f"https://push.example.com/{self.b}",
                    "It's your turn in ann's game!",
                    f"/game?id={self.game_id}",
                    f"game-{self.game_id}",
                )
            ],
        )

    def test_says_nothing_when_the_turn_is_unchanged(self):
        self._run(self._game(turn=self.a), old_turn=self.a)
        self.assertEqual(self.sent, [])

    def test_says_nothing_to_a_player_watching_the_game(self):
        from app import presence

        presence.mark_watching(self.game_id, self.b)
        self._run(self._game(turn=self.b), old_turn=self.a)
        self.assertEqual(self.sent, [])

    def test_game_over_goes_to_every_human_not_watching(self):
        from app import presence

        presence.mark_watching(self.game_id, self.a)
        self._run(self._game(turn=self.a, winner=self.b), old_turn=self.a)
        self.assertEqual(
            [(e, b) for e, b, _, _ in self.sent],
            [(f"https://push.example.com/{self.b}", "bob won ann's game!")],
        )

    def test_cancelled_game(self):
        self._run(self._game(turn=self.a), old_turn=None, cancelled=True)
        self.assertEqual(
            sorted(e for e, *_ in self.sent),
            sorted(f"https://push.example.com/{u}" for u in (self.a, self.b)),
        )
        self.assertTrue(
            all(b == "ann's game was cancelled." for _, b, _, _ in self.sent)
        )

    def test_failures_never_reach_the_player(self):
        import app.api as api

        with patch.object(
            api.gameManager, "get_game_by_id", side_effect=RuntimeError("db down")
        ):
            api._notify_after_action(self.game_id, self.a)


if __name__ == "__main__":
    unittest.main()
