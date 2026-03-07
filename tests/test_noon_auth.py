import base64
import pytest
import responses as rsps
from unittest.mock import patch, MagicMock

from noon_auth import (
    AuthError,
    re_authenticate,
    _generate_pkce_params,
    _request_otp,
    _validate_otp,
    _create_session,
    _OTP_GENERATE_URL,
    _OTP_VALIDATE_URL,
    _SESSION_CREATE_URL,
    _send_otp_prompt,
    _poll_for_otp,
    _update_github_secret,
)


# ── _generate_pkce_params ─────────────────────────────────────────────────────

def test_generate_pkce_params_format():
    cv, pk = _generate_pkce_params()
    assert len(cv) > 80  # base64url of 96 bytes
    assert "=" not in cv  # no padding
    assert pk.startswith("pkce:web:")
    assert len(pk) == len("pkce:web:") + 10


# ── _request_otp ──────────────────────────────────────────────────────────────

@rsps.activate
def test_request_otp_succeeds():
    rsps.add(rsps.POST, _OTP_GENERATE_URL, json={"status": "ok"}, status=200)
    # should not raise
    _request_otp("user123", "verifier", "pkce:web:abc")


@rsps.activate
def test_request_otp_raises_on_failure():
    rsps.add(rsps.POST, _OTP_GENERATE_URL, json={"error": "bad"}, status=400)
    with pytest.raises(AuthError, match="OTP generation failed"):
        _request_otp("user123", "verifier", "pkce:web:abc")


# ── _validate_otp ─────────────────────────────────────────────────────────────

@rsps.activate
def test_validate_otp_returns_access_token():
    rsps.add(rsps.POST, _OTP_VALIDATE_URL, json={"accessToken": "nav1.public.abc"}, status=200)
    token = _validate_otp("user123", "user@example.com", "123456", "verifier", "pkce:web:abc")
    assert token == "nav1.public.abc"


@rsps.activate
def test_validate_otp_raises_on_missing_token():
    rsps.add(rsps.POST, _OTP_VALIDATE_URL, json={"status": "ok"}, status=200)
    with pytest.raises(AuthError, match="accessToken"):
        _validate_otp("user123", "user@example.com", "123456", "verifier", "pkce:web:abc")


# ── _create_session ───────────────────────────────────────────────────────────

@rsps.activate
def test_create_session_returns_npsid():
    rsps.add(rsps.POST, _SESSION_CREATE_URL, json={"status": "ok"}, status=200,
             headers={"Set-Cookie": "_npsid=fresh123; Path=/; HttpOnly"})
    result = _create_session("user123", "nav1.public.abc", "verifier", "pkce:web:abc")
    assert result == "_npsid=fresh123"


@rsps.activate
def test_create_session_raises_when_no_npsid():
    rsps.add(rsps.POST, _SESSION_CREATE_URL, json={"status": "ok"}, status=200)
    with pytest.raises(AuthError, match="_npsid"):
        _create_session("user123", "nav1.public.abc", "verifier", "pkce:web:abc")


# ── _send_otp_prompt ──────────────────────────────────────────────────────────

def test_send_otp_prompt_calls_telegram():
    with patch("noon_auth.requests.post") as mock_post:
        mock_post.return_value = MagicMock(ok=True)
        _send_otp_prompt("bot_token_123", "admin_chat_99")
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "bot_token_123" in call_url
        assert "sendMessage" in call_url


# ── _poll_for_otp ─────────────────────────────────────────────────────────────

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


# ── _update_github_secret ─────────────────────────────────────────────────────

def test_update_github_secret_calls_api():
    pub_key_resp = {"key_id": "key123", "key": base64.b64encode(b"A" * 32).decode()}

    with patch("noon_auth.requests.get") as mock_get, \
         patch("noon_auth.requests.put") as mock_put:
        mock_get.return_value = MagicMock(ok=True, json=lambda: pub_key_resp)
        mock_put.return_value = MagicMock(status_code=204)

        _update_github_secret(
            secret_name="NOON_SESSION_COOKIE",
            value="_npsid=abc123",
            pat="ghp_test",
            repo="owner/repo",
        )

        mock_get.assert_called_once()
        mock_put.assert_called_once()
        put_body = mock_put.call_args[1]["json"]
        assert put_body["key_id"] == "key123"
        assert "encrypted_value" in put_body


# ── re_authenticate ───────────────────────────────────────────────────────────

def test_re_authenticate_full_flow(monkeypatch):
    monkeypatch.setenv("NOON_EMAIL", "user@example.com")
    monkeypatch.setenv("NOON_USER_CODE", "prd-abc@idp.noon.partners")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot:TOKEN")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "99")
    monkeypatch.setenv("GH_PAT", "ghp_test")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

    with patch("noon_auth._generate_pkce_params", return_value=("cv123", "pkce:web:XYZ")), \
         patch("noon_auth._request_otp") as mock_req_otp, \
         patch("noon_auth._send_otp_prompt") as mock_prompt, \
         patch("noon_auth._poll_for_otp", return_value="654321") as mock_poll, \
         patch("noon_auth._validate_otp", return_value="nav1.public.TOKEN") as mock_validate, \
         patch("noon_auth._create_session", return_value="_npsid=fresh99") as mock_session, \
         patch("noon_auth._update_github_secret") as mock_update:

        result = re_authenticate()

    assert result == "_npsid=fresh99"
    mock_req_otp.assert_called_once_with("prd-abc@idp.noon.partners", "cv123", "pkce:web:XYZ")
    mock_prompt.assert_called_once_with("bot:TOKEN", "99")
    mock_poll.assert_called_once_with("bot:TOKEN", "99", timeout=180)
    mock_validate.assert_called_once_with("prd-abc@idp.noon.partners", "user@example.com", "654321", "cv123", "pkce:web:XYZ")
    mock_session.assert_called_once_with("prd-abc@idp.noon.partners", "nav1.public.TOKEN", "cv123", "pkce:web:XYZ")
