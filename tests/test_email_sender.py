"""Sending email through Brevo. Runs without Supabase or network."""

import io
import json
import urllib.error

import pytest

from app import email_sender


class _Response:
    status = 201

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_urlopen(request, timeout):
        seen.append(request)
        return _Response()

    monkeypatch.setattr(email_sender.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_sends_through_brevo_with_the_configured_sender(monkeypatch, calls):
    monkeypatch.setenv("BREVO_API_KEY", "xkeysib-test")
    monkeypatch.setenv("EMAIL_FROM", "hello@cheetahmoongames.com")
    monkeypatch.setenv("EMAIL_FROM_NAME", "Cheetah Moon")
    assert email_sender.send_email("a@example.com", "Ann", "Hi", "<p>Hi</p>", "Hi")
    [request] = calls
    assert request.full_url == "https://api.brevo.com/v3/smtp/email"
    assert request.get_header("Api-key") == "xkeysib-test"
    body = json.loads(request.data)
    assert body["sender"] == {
        "email": "hello@cheetahmoongames.com",
        "name": "Cheetah Moon",
    }
    assert body["to"] == [{"email": "a@example.com", "name": "Ann"}]
    assert body["subject"] == "Hi"
    assert body["htmlContent"] == "<p>Hi</p>"
    assert body["textContent"] == "Hi"


@pytest.mark.parametrize("key", [None, "", "not-set"])
def test_without_a_key_nothing_is_sent(monkeypatch, calls, key):
    if key is None:
        monkeypatch.delenv("BREVO_API_KEY", raising=False)
    else:
        monkeypatch.setenv("BREVO_API_KEY", key)
    assert email_sender.send_email("a@example.com", "Ann", "Hi", "h", "t") is False
    assert calls == []


def test_a_rejected_email_is_reported_not_raised(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "xkeysib-test")

    def rejecting(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"message":"sender not valid"}'),
        )

    monkeypatch.setattr(email_sender.urllib.request, "urlopen", rejecting)
    assert email_sender.send_email("a@example.com", "Ann", "Hi", "h", "t") is False
