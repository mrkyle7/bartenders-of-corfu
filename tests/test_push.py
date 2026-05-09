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
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": "FAKE_PRIVATE_KEY", "VAPID_PUBLIC_KEY": "FAKE_PUBLIC_KEY"}):
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
        mock_webpush.side_effect = WebPushException("Server Error", response=response_mock)
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


if __name__ == "__main__":
    unittest.main()
