# Noon Session Auto-Refresh Implementation Plan

> **⚠️ Historical doc (2026-03-07).** Zenrows was removed on 2026-04-19 and replaced with `curl_cffi` — ignore any `ZENROWS_API_KEY` references below.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically re-authenticate with noon.partners on 401, prompt admin for OTP via Telegram DM, and rotate the GitHub Secret — all without manual intervention.

**Architecture:** New `noon_auth.py` module handles login → OTP prompt → verify → GitHub secret rotation. `affiliate.py` catches 401 and calls `re_authenticate()` once before giving up. Four new GitHub Secrets are added and passed through `bot.yml`.

**Tech Stack:** Python 3.11, `requests`, `python-telegram-bot==20.7`, `pynacl`, `pytest`, `responses` (mock HTTP)

---

## Task 1: Discover noon.partners login API endpoints (manual step)

> This is a research task — no code. Must be done before Tasks 3–6.

**Step 1: Open browser devtools**

- Go to https://affiliates.noon.partners
- Open DevTools → Network tab → check "Preserve log"

**Step 2: Log in with email + password**

Watch for a POST request after submitting your credentials. Record:
- Full URL (e.g. `https://affiliates.noon.partners/auth/login` or similar)
- Request body shape: `{email, password}` or different field names?
- Response body shape: does it return a token? session id? what field name?

**Step 3: Submit the OTP**

After the OTP arrives in your email and you enter it, watch for another POST. Record:
- Full URL (e.g. `https://affiliates.noon.partners/auth/verify-otp`)
- Request body shape: `{otp, token}` or different field names?
- Response: does `Set-Cookie` contain `_npsid`? Any other relevant cookies?

**Step 4: Fill in constants**

Open `noon_auth.py` (you'll create it in Task 3) and set:
```python
_LOGIN_URL  = "https://affiliates.noon.partners/<actual-path>"
_VERIFY_URL = "https://affiliates.noon.partners/<actual-path>"
_LOGIN_BODY_FIELDS  = {"email": ..., "password": ...}   # actual field names
_VERIFY_BODY_FIELDS = {"otp": ..., "token": ...}         # actual field names
_TOKEN_RESPONSE_KEY = "<field name that holds intermediate token>"
```

---

## Task 2: Add pynacl dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add pynacl**

Append to `requirements.txt`:
```
pynacl==1.5.0
```

**Step 2: Install and verify**

```bash
pip install pynacl==1.5.0
python -c "from nacl.public import SealedBox; print('ok')"
```
Expected: `ok`

**Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add pynacl for GitHub secret encryption"
```

---

## Task 3: Create noon_auth.py skeleton

**Files:**
- Create: `noon_auth.py`
- Create: `tests/test_noon_auth.py`

**Step 1: Write the failing test**

Create `tests/test_noon_auth.py`:
```python
from noon_auth import AuthError, re_authenticate
```

Run:
```bash
pytest tests/test_noon_auth.py -v
```
Expected: `ImportError` — module doesn't exist yet.

**Step 2: Create skeleton `noon_auth.py`**

```python
import os
import base64
import time
import requests


class AuthError(Exception):
    pass


# ── Fill these in after Task 1 endpoint discovery ──────────────────────────
_LOGIN_URL  = "https://affiliates.noon.partners/auth/login"   # TODO: confirm
_VERIFY_URL = "https://affiliates.noon.partners/auth/verify"  # TODO: confirm
# ───────────────────────────────────────────────────────────────────────────


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
```

**Step 3: Run import test**

```bash
pytest tests/test_noon_auth.py -v
```
Expected: PASS (import succeeds, no tests run yet).

**Step 4: Commit**

```bash
git add noon_auth.py tests/test_noon_auth.py
git commit -m "feat: scaffold noon_auth module and AuthError"
```

---

## Task 4: Implement _noon_login()

**Files:**
- Modify: `noon_auth.py`
- Modify: `tests/test_noon_auth.py`

**Step 1: Write failing test**

Add to `tests/test_noon_auth.py`:
```python
import responses as rsps
import pytest
from noon_auth import _noon_login, AuthError, _LOGIN_URL


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
```

Run:
```bash
pytest tests/test_noon_auth.py::test_noon_login_returns_token -v
```
Expected: FAIL — `_noon_login` not defined.

**Step 2: Implement `_noon_login`**

Add to `noon_auth.py` (above `re_authenticate`):
```python
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
```

> **Note:** If Task 1 revealed different request body field names or response key names, adjust `"email"`, `"password"`, and `"token"` accordingly.

**Step 3: Run tests**

```bash
pytest tests/test_noon_auth.py::test_noon_login_returns_token tests/test_noon_auth.py::test_noon_login_raises_on_failure -v
```
Expected: both PASS.

**Step 4: Commit**

```bash
git add noon_auth.py tests/test_noon_auth.py
git commit -m "feat: implement _noon_login with tests"
```

---

## Task 5: Implement Telegram OTP prompt and polling

**Files:**
- Modify: `noon_auth.py`
- Modify: `tests/test_noon_auth.py`

**Step 1: Write failing tests**

Add to `tests/test_noon_auth.py`:
```python
from unittest.mock import patch, MagicMock
from noon_auth import _send_otp_prompt, _poll_for_otp


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
```

Run:
```bash
pytest tests/test_noon_auth.py::test_send_otp_prompt_calls_telegram -v
```
Expected: FAIL — `_send_otp_prompt` not defined.

**Step 2: Implement `_send_otp_prompt` and `_poll_for_otp`**

Add to `noon_auth.py`:
```python
_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _send_otp_prompt(bot_token: str, admin_chat_id: str) -> None:
    """Send a Telegram DM to the admin requesting the OTP."""
    url = _TELEGRAM_API.format(token=bot_token, method="sendMessage")
    requests.post(url, json={
        "chat_id": admin_chat_id,
        "text": "🔑 Noon session expired. Reply here with the OTP from your email to refresh it.",
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
```

**Step 3: Run tests**

```bash
pytest tests/test_noon_auth.py::test_send_otp_prompt_calls_telegram tests/test_noon_auth.py::test_poll_for_otp_returns_first_reply tests/test_noon_auth.py::test_poll_for_otp_raises_on_timeout -v
```
Expected: all PASS.

**Step 4: Commit**

```bash
git add noon_auth.py tests/test_noon_auth.py
git commit -m "feat: implement Telegram OTP prompt and polling"
```

---

## Task 6: Implement _noon_verify()

**Files:**
- Modify: `noon_auth.py`
- Modify: `tests/test_noon_auth.py`

**Step 1: Write failing test**

Add to `tests/test_noon_auth.py`:
```python
from noon_auth import _noon_verify, _VERIFY_URL


@rsps.activate
def test_noon_verify_extracts_npsid():
    rsps.add(
        rsps.POST, _VERIFY_URL,
        json={"status": "ok"},
        status=200,
        headers={"Set-Cookie": "_npsid=newcookie99; Path=/; HttpOnly"},
    )
    cookie = _noon_verify("123456", "tok_abc123")
    assert cookie == "_npsid=newcookie99"


@rsps.activate
def test_noon_verify_raises_when_no_cookie():
    rsps.add(rsps.POST, _VERIFY_URL, json={"status": "ok"}, status=200)
    with pytest.raises(AuthError, match="_npsid"):
        _noon_verify("123456", "tok_abc123")
```

Run:
```bash
pytest tests/test_noon_auth.py::test_noon_verify_extracts_npsid -v
```
Expected: FAIL.

**Step 2: Implement `_noon_verify`**

Add to `noon_auth.py`:
```python
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
```

> **Note:** If Task 1 revealed different OTP request body field names, adjust `"otp"` and `"token"` accordingly.

**Step 3: Run tests**

```bash
pytest tests/test_noon_auth.py::test_noon_verify_extracts_npsid tests/test_noon_auth.py::test_noon_verify_raises_when_no_cookie -v
```
Expected: both PASS.

**Step 4: Commit**

```bash
git add noon_auth.py tests/test_noon_auth.py
git commit -m "feat: implement _noon_verify with Set-Cookie extraction"
```

---

## Task 7: Implement _update_github_secret()

**Files:**
- Modify: `noon_auth.py`
- Modify: `tests/test_noon_auth.py`

**Step 1: Write failing test**

Add to `tests/test_noon_auth.py`:
```python
from noon_auth import _update_github_secret


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


import base64
```

Run:
```bash
pytest tests/test_noon_auth.py::test_update_github_secret_calls_api -v
```
Expected: FAIL.

**Step 2: Implement `_update_github_secret`**

Add to top of `noon_auth.py`:
```python
from nacl.public import SealedBox
from nacl.encoding import Base64Encoder
import nacl.utils
```

Add function:
```python
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
```

Add `import nacl.public` to the nacl imports line.

**Step 3: Run tests**

```bash
pytest tests/test_noon_auth.py::test_update_github_secret_calls_api -v
```
Expected: PASS.

**Step 4: Commit**

```bash
git add noon_auth.py tests/test_noon_auth.py
git commit -m "feat: implement GitHub secret rotation with PyNaCl encryption"
```

---

## Task 8: Implement re_authenticate()

**Files:**
- Modify: `noon_auth.py`
- Modify: `tests/test_noon_auth.py`

**Step 1: Write failing test**

Add to `tests/test_noon_auth.py`:
```python
def test_re_authenticate_full_flow(monkeypatch):
    monkeypatch.setenv("NOON_EMAIL", "user@example.com")
    monkeypatch.setenv("NOON_PASSWORD", "pass123")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot:TOKEN")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "99")
    monkeypatch.setenv("GH_PAT", "ghp_test")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

    with patch("noon_auth._noon_login", return_value="tok_abc") as mock_login, \
         patch("noon_auth._send_otp_prompt") as mock_prompt, \
         patch("noon_auth._poll_for_otp", return_value="123456") as mock_poll, \
         patch("noon_auth._noon_verify", return_value="_npsid=fresh99") as mock_verify, \
         patch("noon_auth._update_github_secret") as mock_update:

        result = re_authenticate()

    assert result == "_npsid=fresh99"
    mock_login.assert_called_once_with("user@example.com", "pass123")
    mock_prompt.assert_called_once_with("bot:TOKEN", "99")
    mock_poll.assert_called_once_with("bot:TOKEN", "99", timeout=180)
    mock_verify.assert_called_once_with("123456", "tok_abc")
    mock_update.assert_called_once_with(
        secret_name="NOON_SESSION_COOKIE",
        value="_npsid=fresh99",
        pat="ghp_test",
        repo="owner/repo",
    )
```

Run:
```bash
pytest tests/test_noon_auth.py::test_re_authenticate_full_flow -v
```
Expected: FAIL — `re_authenticate` raises `NotImplementedError`.

**Step 2: Implement `re_authenticate`**

Replace the `raise NotImplementedError` stub in `noon_auth.py`:
```python
def re_authenticate() -> str:
    email    = os.environ["NOON_EMAIL"]
    password = os.environ["NOON_PASSWORD"]
    bot_token      = os.environ["TELEGRAM_BOT_TOKEN"]
    admin_chat_id  = os.environ["TELEGRAM_ADMIN_CHAT_ID"]
    gh_pat   = os.environ["GH_PAT"]
    gh_repo  = os.environ["GITHUB_REPOSITORY"]

    print("  [noon_auth] Session expired — starting re-authentication flow")

    token = _noon_login(email, password)
    print("  [noon_auth] Login submitted — waiting for OTP from admin via Telegram")

    _send_otp_prompt(bot_token, admin_chat_id)
    otp = _poll_for_otp(bot_token, admin_chat_id, timeout=180)
    print("  [noon_auth] OTP received — verifying")

    new_cookie = _noon_verify(otp, token)
    print(f"  [noon_auth] New session cookie obtained")

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
```

**Step 3: Run all noon_auth tests**

```bash
pytest tests/test_noon_auth.py -v
```
Expected: all PASS.

**Step 4: Commit**

```bash
git add noon_auth.py tests/test_noon_auth.py
git commit -m "feat: implement re_authenticate orchestration"
```

---

## Task 9: Modify affiliate.py to catch 401 and retry

**Files:**
- Modify: `affiliate.py`
- Modify: `tests/test_affiliate.py`

**Step 1: Write failing test**

Add to `tests/test_affiliate.py`:
```python
from unittest.mock import patch

@responses.activate
def test_retries_after_401_with_new_cookie():
    """On 401, calls re_authenticate() then retries once and succeeds."""
    responses.add(
        responses.POST,
        "https://affiliates.noon.partners/_svc/affiliate/affiliate/campaign/custom_link",
        json={"error": "UnAuthenticated"},
        status=401,
    )
    responses.add(
        responses.POST,
        "https://affiliates.noon.partners/_svc/affiliate/affiliate/campaign/custom_link",
        json={"url": "https://s.noon.com/refreshed"},
        status=200,
    )

    with patch("affiliate.re_authenticate", return_value="_npsid=fresh99") as mock_reauth:
        result = build_affiliate_link(
            product_url="https://www.noon.com/egypt-en/product/p/SKU/",
            product_name="Test",
            session_cookie="expired_cookie",
        )

    assert result == "https://s.noon.com/refreshed"
    mock_reauth.assert_called_once()


@responses.activate
def test_raises_if_retry_also_fails():
    """If the retried call also 401s, raises AffiliateError without looping."""
    responses.add(
        responses.POST,
        "https://affiliates.noon.partners/_svc/affiliate/affiliate/campaign/custom_link",
        json={"error": "UnAuthenticated"},
        status=401,
    )
    responses.add(
        responses.POST,
        "https://affiliates.noon.partners/_svc/affiliate/affiliate/campaign/custom_link",
        json={"error": "UnAuthenticated"},
        status=401,
    )

    with patch("affiliate.re_authenticate", return_value="_npsid=fresh99"):
        with pytest.raises(AffiliateError):
            build_affiliate_link(
                product_url="https://www.noon.com/egypt-en/product/p/SKU/",
                product_name="Test",
                session_cookie="expired_cookie",
            )
```

Run:
```bash
pytest tests/test_affiliate.py::test_retries_after_401_with_new_cookie -v
```
Expected: FAIL.

**Step 2: Modify `affiliate.py`**

Add import at top of `affiliate.py`:
```python
from noon_auth import re_authenticate, AuthError
```

Replace the `except requests.HTTPError` block in `build_affiliate_link`:
```python
    except requests.HTTPError as e:
        if response.status_code == 401:
            print("  Affiliate API 401 — attempting session refresh")
            try:
                new_cookie = re_authenticate()
                # Retry once with the fresh cookie — no recursion
                return build_affiliate_link(product_url, product_name, session_cookie=new_cookie)
            except (AuthError, AffiliateError) as reauth_err:
                raise AffiliateError(f"Re-auth failed, cannot generate affiliate link: {reauth_err}") from reauth_err
        raise AffiliateError(f"Affiliate API error {response.status_code}: {response.text}") from e
```

**Step 3: Prevent infinite retry loop**

The retry call passes the fresh `new_cookie` directly. If that also 401s it will try `re_authenticate()` again. Add a `_retry` guard parameter:

Replace the function signature:
```python
def build_affiliate_link(product_url: str, product_name: str, session_cookie: str = None, _retried: bool = False) -> str:
```

And the retry block:
```python
        if response.status_code == 401 and not _retried:
            print("  Affiliate API 401 — attempting session refresh")
            try:
                new_cookie = re_authenticate()
                return build_affiliate_link(product_url, product_name, session_cookie=new_cookie, _retried=True)
            except (AuthError, AffiliateError) as reauth_err:
                raise AffiliateError(f"Re-auth failed: {reauth_err}") from reauth_err
        raise AffiliateError(f"Affiliate API error {response.status_code}: {response.text}") from e
```

**Step 4: Run all affiliate tests**

```bash
pytest tests/test_affiliate.py -v
```
Expected: all PASS.

**Step 5: Commit**

```bash
git add affiliate.py tests/test_affiliate.py
git commit -m "feat: catch 401 in affiliate.py, re-authenticate and retry once"
```

---

## Task 10: Update bot.yml with new secrets

**Files:**
- Modify: `.github/workflows/bot.yml`

**Step 1: Add 4 new env vars to the `Run bot` step**

Find the `env:` block under `- name: Run bot` and add:
```yaml
          NOON_EMAIL: ${{ secrets.NOON_EMAIL }}
          NOON_PASSWORD: ${{ secrets.NOON_PASSWORD }}
          TELEGRAM_ADMIN_CHAT_ID: ${{ secrets.TELEGRAM_ADMIN_CHAT_ID }}
          GH_PAT: ${{ secrets.GH_PAT }}
```

The full `env:` block should look like:
```yaml
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHANNEL_ID: ${{ secrets.TELEGRAM_CHANNEL_ID }}
          NOON_SESSION_COOKIE: ${{ secrets.NOON_SESSION_COOKIE }}
          ZENROWS_API_KEY: ${{ secrets.ZENROWS_API_KEY }}
          NOON_EMAIL: ${{ secrets.NOON_EMAIL }}
          NOON_PASSWORD: ${{ secrets.NOON_PASSWORD }}
          TELEGRAM_ADMIN_CHAT_ID: ${{ secrets.TELEGRAM_ADMIN_CHAT_ID }}
          GH_PAT: ${{ secrets.GH_PAT }}
```

**Step 2: Commit**

```bash
git add .github/workflows/bot.yml
git commit -m "chore: pass new auth secrets to bot workflow"
```

---

## Task 11: One-time GitHub Secrets setup (manual)

> Do this in the GitHub repository settings before the next bot run.

**Step 1: Create a GitHub PAT**

- Go to https://github.com/settings/tokens → "Fine-grained tokens" → Generate new token
- Repository access: select this repo only
- Permissions: `Secrets` → Read and write
- Copy the token

**Step 2: Add all 4 secrets**

Go to repo → Settings → Secrets and variables → Actions → New repository secret:

| Name | Value |
|---|---|
| `NOON_EMAIL` | Your noon.partners login email |
| `NOON_PASSWORD` | Your noon.partners password |
| `TELEGRAM_ADMIN_CHAT_ID` | Your personal chat ID (get it by messaging @userinfobot on Telegram) |
| `GH_PAT` | The PAT you just created |

**Step 3: Verify**

Trigger the workflow manually (Actions → Run workflow). Watch the logs — on the next 401 you should see:
```
  Affiliate API 401 — attempting session refresh
  [noon_auth] Session expired — starting re-authentication flow
  [noon_auth] Login submitted — waiting for OTP from admin via Telegram
```
Then receive a Telegram DM and reply with the OTP.

---

## Task 12: Run full test suite

```bash
pytest tests/ -v
```
Expected: all tests PASS (no regressions).

```bash
git add -A
git commit -m "test: verify full test suite passes after noon auth integration"
```

---

## Summary of files changed

| File | Change |
|---|---|
| `noon_auth.py` | Created — full re-auth module |
| `affiliate.py` | 401 catch + retry logic |
| `.github/workflows/bot.yml` | 4 new secrets in env block |
| `requirements.txt` | `pynacl==1.5.0` |
| `tests/test_noon_auth.py` | Created — full test coverage |
| `tests/test_affiliate.py` | 2 new tests for 401 retry |
