"""Unit tests for app/push.py — no Supabase or network required."""

import os
import unittest
from unittest.mock import patch, MagicMock


class FakeDb:
    """The two vapid_keys calls, like the database: the first pair saved wins."""

    def __init__(self, keys=None, fail=False):
        self.keys = keys
        self.fail = fail
        self.saves = 0

    def get_vapid_keys(self):
        if self.fail:
            raise RuntimeError("database down")
        return self.keys

    def save_vapid_keys(self, keys):
        self.saves += 1
        if self.keys is None:
            self.keys = dict(keys)


class TestKeys(unittest.TestCase):
    """The key pair lives in the database; the server makes it if needed."""

    def setUp(self):
        import app.push as push_mod

        self.push_mod = push_mod
        push_mod._keys = None
        self.addCleanup(setattr, push_mod, "_keys", None)
        no_env = {k: v for k, v in os.environ.items() if not k.startswith("VAPID_")}
        env = patch.dict(os.environ, no_env, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def _with_db(self, db):
        p = patch("app.push._db", return_value=db)
        p.start()
        self.addCleanup(p.stop)
        return db

    def test_uses_the_stored_pair(self):
        db = self._with_db(
            FakeDb({"public_key": "stored-pub", "private_key": "stored-priv"})
        )
        self.assertEqual(self.push_mod.get_public_key(), "stored-pub")
        self.assertEqual(db.saves, 0)

    def test_makes_and_saves_a_pair_when_there_is_none(self):
        db = self._with_db(FakeDb())
        public_key = self.push_mod.get_public_key()
        self.assertTrue(public_key)
        self.assertEqual(db.keys["public_key"], public_key)
        self.assertEqual(len(db.keys["private_key"]), 43, "32 bytes, base64url")
        # Cached: the database isn't asked again.
        db.fail = True
        self.assertEqual(self.push_mod.get_public_key(), public_key)

    def test_keeps_the_pair_from_secret_manager_when_the_database_has_none(self):
        db = self._with_db(FakeDb())
        with patch.dict(
            os.environ, {"VAPID_PUBLIC_KEY": "env-pub", "VAPID_PRIVATE_KEY": "env-priv"}
        ):
            self.assertEqual(self.push_mod.get_public_key(), "env-pub")
        self.assertEqual(db.keys, {"public_key": "env-pub", "private_key": "env-priv"})

    def test_ignores_terraform_placeholders(self):
        with patch.dict(
            os.environ, {"VAPID_PUBLIC_KEY": "not-set", "VAPID_PRIVATE_KEY": "not-set"}
        ):
            self.assertIsNone(self.push_mod.keys_from_env())

    def test_another_servers_pair_wins(self):
        class Racing(FakeDb):
            def get_vapid_keys(self):
                if self.saves == 0 and self.keys is None:
                    # Another server saves its pair between our read and save.
                    self.keys = {"public_key": "other-pub", "private_key": "other-priv"}
                    return None
                return self.keys

        self._with_db(Racing())
        self.assertEqual(self.push_mod.get_public_key(), "other-pub")

    def test_no_notifications_while_the_database_is_down(self):
        db = self._with_db(FakeDb(fail=True))
        self.assertEqual(self.push_mod.get_public_key(), "")
        db.fail = False
        db.keys = {"public_key": "pub", "private_key": "priv"}
        self.assertEqual(self.push_mod.get_public_key(), "pub", "tried again next time")


class TestSendPush(unittest.TestCase):
    """Tests for send_push() — pywebpush.webpush is always mocked."""

    _SUB = {
        "endpoint": "https://push.example.com/sub/abc",
        "keys": {"p256dh": "FAKE_P256DH", "auth": "FAKE_AUTH"},
    }

    def setUp(self):
        # Keys already loaded, so send_push doesn't go to the database.
        import app.push as push_mod

        push_mod._keys = {
            "public_key": "FAKE_PUBLIC_KEY",
            "private_key": "FAKE_PRIVATE_KEY",
        }
        self.addCleanup(setattr, push_mod, "_keys", None)
        self.push_mod = push_mod

    def _send(self, mock_webpush):
        return self.push_mod.send_push(
            subscription_info=self._SUB,
            title="Test",
            body="Hello",
            url="/game?id=1",
        )

    @patch("app.push.webpush")
    def test_returns_true_on_success(self, mock_webpush):
        mock_webpush.return_value = None
        result = self._send(mock_webpush)
        self.assertTrue(result)
        mock_webpush.assert_called_once()

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

    @patch("app.push.webpush")
    def test_returns_false_on_404(self, mock_webpush):
        from pywebpush import WebPushException

        response_mock = MagicMock()
        response_mock.status_code = 404
        mock_webpush.side_effect = WebPushException("Not Found", response=response_mock)
        result = self._send(mock_webpush)
        self.assertFalse(result)

    @patch("app.push.webpush")
    def test_returns_false_on_410(self, mock_webpush):
        from pywebpush import WebPushException

        response_mock = MagicMock()
        response_mock.status_code = 410
        mock_webpush.side_effect = WebPushException("Gone", response=response_mock)
        result = self._send(mock_webpush)
        self.assertFalse(result)

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

    @patch("app.push.webpush")
    def test_returns_true_on_webpush_exception_no_response(self, mock_webpush):
        from pywebpush import WebPushException

        mock_webpush.side_effect = WebPushException("Connection error", response=None)
        result = self._send(mock_webpush)
        self.assertTrue(result)

    @patch("app.push.webpush")
    def test_returns_true_on_unexpected_exception(self, mock_webpush):
        mock_webpush.side_effect = RuntimeError("unexpected")
        result = self._send(mock_webpush)
        self.assertTrue(result)

    @patch("app.push.get_keys", return_value=None)
    @patch("app.push.webpush")
    def test_no_op_without_keys(self, mock_webpush, _keys):
        result = self._send(mock_webpush)
        self.assertTrue(result)
        mock_webpush.assert_not_called()


if __name__ == "__main__":
    unittest.main()
