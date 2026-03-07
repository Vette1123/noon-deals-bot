import os
import base64
import secrets
import string
import time
import requests
import nacl.public
from nacl.public import SealedBox
from nacl.encoding import Base64Encoder


class AuthError(Exception):
    pass


_OTP_GENERATE_URL  = "https://login.noon.partners/_svc/mp-partner-identity/public/user/credential/generate"
_OTP_VALIDATE_URL  = "https://login.noon.partners/_svc/mp-partner-identity/public/user/validate"
_SESSION_CREATE_URL = "https://login.noon.partners/_svc/mp-partner-identity/public/user/session/create"
_PROJECT_CODE = "PRJ496018"

_HEADERS = {
    "content-type": "application/json",
    "x-platform": "web",
    "origin": "https://login.noon.partners",
}

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _generate_pkce_params() -> tuple:
    """Generate a fresh (code_verifier, pkce_key) pair for PKCE flow."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(96)).rstrip(b"=").decode()
    chars = string.ascii_letters + string.digits
    pkce_key = "pkce:web:" + "".join(secrets.choice(chars) for _ in range(10))
    return code_verifier, pkce_key


def _request_otp(user_code: str, code_verifier: str, pkce_key: str) -> None:
    """Step 1: Request OTP — noon sends OTP to the user's registered email."""
    try:
        resp = requests.post(
            _OTP_GENERATE_URL,
            json={
                "channelCode": "emailotp",
                "userCode": user_code,
                "client_code": "web",
                "code_verifier": code_verifier,
                "pkce_key": pkce_key,
            },
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
    except requests.HTTPError:
        raise AuthError(f"OTP generation failed: {resp.status_code} {resp.text}")
    except requests.RequestException as e:
        raise AuthError(f"OTP generation request failed: {e}")


def _validate_otp(user_code: str, email: str, otp: str, code_verifier: str, pkce_key: str) -> str:
    """Step 2: Validate OTP. Returns the accessToken string."""
    try:
        resp = requests.post(
            _OTP_VALIDATE_URL,
            json={
                "channel_code": "emailotp",
                "user_code": user_code,
                "channel_identifier": email,
                "channel_credential": otp,
                "client_code": "web",
                "code_verifier": code_verifier,
                "pkce_key": pkce_key,
            },
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
    except requests.HTTPError:
        raise AuthError(f"OTP validation failed: {resp.status_code} {resp.text}")
    except requests.RequestException as e:
        raise AuthError(f"OTP validation request failed: {e}")

    access_token = resp.json().get("accessToken")
    if not access_token:
        raise AuthError(f"OTP validation response missing accessToken: {resp.text}")
    return access_token


def _create_session(user_code: str, access_token: str, code_verifier: str, pkce_key: str) -> str:
    """Step 3: Create session. Returns '_npsid=<value>'."""
    try:
        resp = requests.post(
            _SESSION_CREATE_URL,
            json={
                "userCode": user_code,
                "accessToken": access_token,
                "projectCode": _PROJECT_CODE,
                "clientCode": "web",
                "code_verifier": code_verifier,
                "pkce_key": pkce_key,
            },
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
    except requests.HTTPError:
        raise AuthError(f"Session creation failed: {resp.status_code} {resp.text}")
    except requests.RequestException as e:
        raise AuthError(f"Session creation request failed: {e}")

    npsid_value = resp.cookies.get("_npsid")
    if not npsid_value:
        raise AuthError(f"_npsid not found in response cookies: {dict(resp.cookies)}")
    return f"_npsid={npsid_value}"


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
    Full re-auth flow using 3-step PKCE login. Returns new _npsid cookie string.

    Reads from environment:
        NOON_EMAIL, NOON_USER_CODE
        TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID
        GH_PAT, GITHUB_REPOSITORY (auto-set by Actions as "owner/repo")

    Raises AuthError on any failure.
    """
    email         = os.environ["NOON_EMAIL"]
    user_code     = os.environ["NOON_USER_CODE"]
    bot_token     = os.environ["TELEGRAM_BOT_TOKEN"]
    admin_chat_id = os.environ["TELEGRAM_ADMIN_CHAT_ID"]
    gh_pat        = os.environ["GH_PAT"]
    gh_repo       = os.environ["GITHUB_REPOSITORY"]

    print("  [noon_auth] Session expired — starting re-authentication flow")

    code_verifier, pkce_key = _generate_pkce_params()

    _request_otp(user_code, code_verifier, pkce_key)
    print("  [noon_auth] OTP requested — waiting for OTP from admin via Telegram")

    _send_otp_prompt(bot_token, admin_chat_id)
    otp = _poll_for_otp(bot_token, admin_chat_id, timeout=180)
    print("  [noon_auth] OTP received — validating")

    access_token = _validate_otp(user_code, email, otp, code_verifier, pkce_key)
    print("  [noon_auth] OTP validated — creating session")

    new_cookie = _create_session(user_code, access_token, code_verifier, pkce_key)
    print("  [noon_auth] New session cookie obtained")

    try:
        _update_github_secret(
            secret_name="NOON_SESSION_COOKIE",
            value=new_cookie,
            pat=gh_pat,
            repo=gh_repo,
        )
    except Exception as e:
        print(f"  [noon_auth] Warning: could not update GitHub secret: {e}")

    return new_cookie
