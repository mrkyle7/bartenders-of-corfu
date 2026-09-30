"""Unit tests for app/push.py — no Supabase or network required."""

import os
import unittest
from unittest.mock import patch, MagicMock


class TestGetPublicKey(unittest.TestCase):
    def test_returns_env_var(self):
        with patch.dict(os.environ, {"VAPID_PUBLIC_KEY": "test-public-key"}):
            import importlib
            import app.push as push_mod

            importlib.reload(push_mod)
            self.assertEqual(push_mod.get_public_key(), "test-public-key")

    def test_returns_empty_string_when_unset(self):
        env = {k: v for k, v in os.environ.items() if k != "VAPID_PUBLIC_KEY"}
        with patch.dict(os.environ, env, clear=True):
            import importlib
            import app.push as push_mod

            importlib.reload(push_mod)
            self.assertEqual(push_mod.get_public_key(), "")


class TestSendPush(unittest.TestCase):
    """Tests for send_push() — pywebpush.webpush is always mocked."""

    _SUB = {
        "endpoint": "https://push.example.com/sub/abc",
        "keys": {"p256dh": "FAKE_P256DH", "auth": "FAKE_AUTH"},
    }

    def setUp(self):
        # Reload with a VAPID key present so the function doesn't early-return
        import importlib
        import app.push as push_mod

        with patch.dict(
            os.environ,
            {
                "VAPID_PRIVATE_KEY": "FAKE_PRIVATE_KEY",
                "VAPID_PUBLIC_KEY": "FAKE_PUBLIC_KEY",
            },
        ):
            importlib.reload(push_mod)
        self.push_mod = push_mod

    def _send(self, mock_webpush):
        return self.push_mod.send_push(
            subscription_info=self._SUB,
            title="Test",
            body="Hello",
            url="/game?id=1",
        )

    @patch("app.push._VAPID_PRIVATE_KEY", "FAKE_PRIVATE_KEY")
    @patch("app.push.webpush")
    def test_returns_true_on_success(self, mock_webpush):
        mock_webpush.return_value = None
        result = self._send(mock_webpush)
        self.assertTrue(result)
        mock_webpush.assert_called_once()

    @patch("app.push._VAPID_PRIVATE_KEY", "FAKE_PRIVATE_KEY")
    @patch("app.push.webpush")
    def test_sends_json_payload(self, mock_webpush):
        import json

        mock_webpush.return_value = None
        self.push_mod.send_push(
            subscription_info=self._SUB,
            title="Bartenders of Corfu",
            body="It's your turn!",
            url="/game?id=42",
        )
        call_kwargs = mock_webpush.call_args
        data_arg = call_kwargs[1].get("data") or call_kwargs[0][1]
        payload = json.loads(data_arg)
        self.assertEqual(payload["title"], "Bartenders of Corfu")
        self.assertEqual(payload["body"], "It's your turn!")
        self.assertEqual(payload["url"], "/game?id=42")

    @patch("app.push._VAPID_PRIVATE_KEY", "FAKE_PRIVATE_KEY")
    @patch("app.push.webpush")
    def test_returns_false_on_404(self, mock_webpush):
        from pywebpush import WebPushException

        response_mock = MagicMock()
        response_mock.status_code = 404
        mock_webpush.side_effect = WebPushException("Not Found", response=response_mock)
        result = self._send(mock_webpush)
        self.assertFalse(result)

    @patch("app.push._VAPID_PRIVATE_KEY", "FAKE_PRIVATE_KEY")
    @patch("app.push.webpush")
    def test_returns_false_on_410(self, mock_webpush):
        from pywebpush import WebPushException

        response_mock = MagicMock()
        response_mock.status_code = 410
        mock_webpush.side_effect = WebPushException("Gone", response=response_mock)
        result = self._send(mock_webpush)
        self.assertFalse(result)

    @patch("app.push._VAPID_PRIVATE_KEY", "FAKE_PRIVATE_KEY")
    @patch("app.push.webpush")
    def test_returns_true_on_transient_webpush_error(self, mock_webpush):
        from pywebpush import WebPushException

        response_mock = MagicMock()
        response_mock.status_code = 500
        mock_webpush.side_effect = WebPushException(
            "Server Error", response=response_mock
        )
        result = self._send(mock_webpush)
        self.assertTrue(result)

    @patch("app.push._VAPID_PRIVATE_KEY", "FAKE_PRIVATE_KEY")
    @patch("app.push.webpush")
    def test_returns_true_on_webpush_exception_no_response(self, mock_webpush):
        from pywebpush import WebPushException

        mock_webpush.side_effect = WebPushException("Connection error", response=None)
        result = self._send(mock_webpush)
        self.assertTrue(result)

    @patch("app.push._VAPID_PRIVATE_KEY", "FAKE_PRIVATE_KEY")
    @patch("app.push.webpush")
    def test_returns_true_on_unexpected_exception(self, mock_webpush):
        mock_webpush.side_effect = RuntimeError("unexpected")
        result = self._send(mock_webpush)
        self.assertTrue(result)

    @patch("app.push._VAPID_PRIVATE_KEY", "")
    @patch("app.push.webpush")
    def test_no_op_when_private_key_not_configured(self, mock_webpush):
        result = self._send(mock_webpush)
        self.assertTrue(result)
        mock_webpush.assert_not_called()

    @patch("app.push._VAPID_PRIVATE_KEY", "FAKE_PRIVATE_KEY")
    @patch("app.push.webpush")
    def test_keeps_the_notification_while_the_device_is_offline(self, mock_webpush):
        """pywebpush's default TTL of 0 drops it unless the device is reachable now."""
        import json

        self.push_mod.send_push(
            subscription_info=self._SUB,
            title="t",
            body="b",
            url="/game?id=42",
            tag="game-42",
        )
        kwargs = mock_webpush.call_args[1]
        self.assertEqual(kwargs["ttl"], 24 * 60 * 60)
        self.assertTrue(kwargs["timeout"])
        self.assertEqual(kwargs["headers"], {"Urgency": "high"})
        self.assertEqual(json.loads(kwargs["data"])["tag"], "game-42")

    @patch("app.push._VAPID_PRIVATE_KEY", "FAKE_PRIVATE_KEY")
    @patch("app.push.webpush")
    def test_each_push_service_gets_its_own_audience(self, mock_webpush):
        """pywebpush writes the first endpoint's origin into the claims it's
        given as "aud"; sharing one dict would sign every later push for the
        wrong push service, which rejects it."""
        audiences = []

        def like_pywebpush(subscription_info, vapid_claims, **_):
            if not vapid_claims.get("aud"):
                vapid_claims["aud"] = subscription_info["endpoint"].split("/sub")[0]
            audiences.append(vapid_claims["aud"])

        mock_webpush.side_effect = like_pywebpush
        for endpoint in (
            "https://fcm.googleapis.com/sub/1",
            "https://web.push.apple.com/sub/2",
        ):
            self.push_mod.send_push(
                subscription_info={**self._SUB, "endpoint": endpoint},
                title="t",
                body="b",
                url="/",
            )
        self.assertEqual(
            audiences, ["https://fcm.googleapis.com", "https://web.push.apple.com"]
        )
        self.assertNotIn("aud", self.push_mod._VAPID_CLAIMS)


class TestValidEndpoint(unittest.TestCase):
    def test_accepts_push_services(self):
        from app.push import valid_endpoint

        for endpoint in (
            "https://fcm.googleapis.com/fcm/send/abc",
            "https://updates.push.services.mozilla.com/wpush/v2/abc",
            "https://web.push.apple.com/QK4",
        ):
            self.assertTrue(valid_endpoint(endpoint), endpoint)

    def test_rejects_addresses_on_the_servers_network(self):
        from app.push import valid_endpoint

        for endpoint in (
            "http://fcm.googleapis.com/fcm/send/abc",
            "https://127.0.0.1/x",
            "https://10.0.0.5/x",
            "https://[::1]/x",
            "https://localhost/x",
            "https://db.localhost/x",
            "https://metadata.google.internal/computeMetadata/v1/",
            "https://intranet/x",
            "https://user:pw@push.example.com/x",
            "ftp://push.example.com/x",
            "not a url",
            "https://push.example.com/" + "x" * 1000,
        ):
            self.assertFalse(valid_endpoint(endpoint), endpoint)


if __name__ == "__main__":
    unittest.main()
