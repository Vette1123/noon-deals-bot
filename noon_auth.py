import os
import base64
import time
import requests
import nacl.public
from nacl.public import SealedBox
from nacl.encoding import Base64Encoder


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


_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _send_otp_prompt(bot_token: str, admin_chat_id: str) -> None:
    """Send a Telegram DM to the admin requesting the OTP."""
    url = _TELEGRAM_API.format(token=bot_token, method="sendMessage")
    requests.post(url, json={
        "chat_id": admin_chat_id,
        "text": "Noon session expired. Reply here with the OTP from your email to refresh it.",
    }, timeout=10)


def _poll_for_otp(bot_token: str, admin_chat_id: str, timeout: int = 180) -> str:
    """
    Long-poll Telegram getUpdates until admin replies with a message.
    Returns the OTP text. Raises AuthError if timeout exceeded.
    """
    url = _TELEGRAM_API.format(token=bot_token, method="getUpdates")
    offset = 0
    deadline = time.time() + timeout

    while time.time() < deadline:
        resp = requests.get(url, params={"offset": offset, "timeout": 30}, timeout=35)
        if not resp.ok:
            time.sleep(3)
            continue

        for update in resp.json().get("result", []):
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            sender_id = str(msg.get("from", {}).get("id", ""))
            text = msg.get("text", "").strip()
            if sender_id == str(admin_chat_id) and text:
                return text

    raise AuthError("OTP timed out — no reply received within 3 minutes")


def _noon_verify(otp: str, token: str) -> str:
    """POST OTP + token, extract _npsid from Set-Cookie. Returns '_npsid=<value>'."""
    try:
        resp = requests.post(
            _VERIFY_URL,
            json={"otp": otp, "token": token},
            headers={"content-type": "application/json", "x-platform": "web"},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.HTTPError:
        raise AuthError(f"OTP verification failed: {resp.status_code} {resp.text}")
    except requests.RequestException as e:
        raise AuthError(f"OTP verify request failed: {e}")

    # Extract _npsid from Set-Cookie header
    set_cookie = resp.headers.get("Set-Cookie", "")
    for part in set_cookie.split(";"):
        part = part.strip()
        if part.startswith("_npsid="):
            return part  # e.g. "_npsid=6a47b96536734d769711874c914cce55"

    raise AuthError(f"_npsid not found in Set-Cookie: {set_cookie!r}")


def _update_github_secret(secret_name: str, value: str, pat: str, repo: str) -> None:
    """Encrypt value with repo public key and PUT to GitHub Secrets API."""
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base_url = f"https://api.github.com/repos/{repo}/actions"

    # Fetch repo public key
    key_resp = requests.get(f"{base_url}/public-key", headers=headers, timeout=10)
    key_resp.raise_for_status()
    key_data = key_resp.json()
    public_key_bytes = base64.b64decode(key_data["key"])

    # Encrypt with libsodium SealedBox
    box = SealedBox(nacl.public.PublicKey(public_key_bytes))
    encrypted = box.encrypt(value.encode("utf-8"))
    encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")

    # Update the secret
    put_resp = requests.put(
        f"{base_url}/secrets/{secret_name}",
        headers=headers,
        json={"encrypted_value": encrypted_b64, "key_id": key_data["key_id"]},
        timeout=10,
    )
    if put_resp.status_code not in (201, 204):
        print(f"  Warning: GitHub secret update returned {put_resp.status_code}")
    else:
        print(f"  GitHub secret {secret_name!r} updated successfully")


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
