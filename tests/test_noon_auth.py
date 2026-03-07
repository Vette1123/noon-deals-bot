from noon_auth import AuthError, re_authenticate
import responses as rsps
import pytest
from noon_auth import _noon_login, AuthError, _LOGIN_URL
from unittest.mock import patch, MagicMock
from noon_auth import _send_otp_prompt, _poll_for_otp


@rsps.activate
def test_noon_login_returns_token():
    rsps.add(rsps.POST, _LOGIN_URL, json={"token": "tok_abc123"}, status=200)
    token = _noon_login("user@example.com", "s3cr3t")
    assert token == "tok_abc123"


@rsps.activate
def test_noon_login_raises_on_failure():
    rsps.add(rsps.POST, _LOGIN_URL, json={"error": "invalid"}, status=401)
    with pytest.raises(AuthError, match="Login failed"):
        _noon_login("user@example.com", "wrong")


def test_send_otp_prompt_calls_telegram():
    with patch("noon_auth.requests.post") as mock_post:
        mock_post.return_value = MagicMock(ok=True)
        _send_otp_prompt("bot_token_123", "admin_chat_99")
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "bot_token_123" in call_url
        assert "sendMessage" in call_url


def test_poll_for_otp_returns_first_reply():
    updates = {
        "ok": True,
        "result": [
            {
                "update_id": 1,
                "message": {
                    "from": {"id": 99},
                    "chat": {"id": 99},
                    "text": "654321",
                },
            }
        ],
    }
    with patch("noon_auth.requests.get") as mock_get:
        mock_get.return_value = MagicMock(ok=True, json=lambda: updates)
        otp = _poll_for_otp("bot_token_123", admin_chat_id="99", timeout=10)
    assert otp == "654321"


def test_poll_for_otp_raises_on_timeout():
    empty = {"ok": True, "result": []}
    with patch("noon_auth.requests.get") as mock_get:
        mock_get.return_value = MagicMock(ok=True, json=lambda: empty)
        with patch("noon_auth.time.time", side_effect=[0, 0, 5, 5, 11]):
            with pytest.raises(AuthError, match="timed out"):
                _poll_for_otp("bot_token_123", admin_chat_id="99", timeout=10)
