import os
import base64
import time
import requests


class AuthError(Exception):
    pass


# ── Fill these in after browser devtools endpoint discovery ────────────────
_LOGIN_URL  = "https://affiliates.noon.partners/auth/login"   # TODO: confirm
_VERIFY_URL = "https://affiliates.noon.partners/auth/verify"  # TODO: confirm
# ──────────────────────────────────────────────────────────────────────────


def _noon_login(email: str, password: str) -> str:
    """POST credentials. Returns intermediate token string."""
    try:
        resp = requests.post(
            _LOGIN_URL,
            json={"email": email, "password": password},
            headers={"content-type": "application/json", "x-platform": "web"},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.HTTPError:
        raise AuthError(f"Login failed: {resp.status_code} {resp.text}")
    except requests.RequestException as e:
        raise AuthError(f"Login request failed: {e}")

    token = resp.json().get("token")
    if not token:
        raise AuthError(f"Login response missing token: {resp.text}")
    return token


def re_authenticate() -> str:
    """
    Full re-auth flow. Returns new _npsid cookie string.

    Reads from environment:
        NOON_EMAIL, NOON_PASSWORD
        TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID
        GH_PAT, GITHUB_REPOSITORY (auto-set by Actions as "owner/repo")

    Raises AuthError on any failure.
    """
    raise NotImplementedError
