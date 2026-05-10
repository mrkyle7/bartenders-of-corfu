"""Supabase-dependent API tests for push notification endpoints."""

import os
import time
import unittest
from unittest.mock import patch

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
        resp = self.client.post("/v1/push-subscriptions", json=self._sub(), cookies={'userjwt': 'invalid'})
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
            cookies={"userjwt": "invalid"}
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


if __name__ == "__main__":
    unittest.main()
