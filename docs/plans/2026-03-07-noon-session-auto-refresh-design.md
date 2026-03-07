# Design: Noon Session Cookie Auto-Refresh

**Date:** 2026-03-07
**Status:** Approved
**Problem:** `NOON_SESSION_COOKIE` (`_npsid`) expires periodically, causing 401 errors on the affiliate API and products being posted without affiliate links.

---

## Goal

Automatically re-authenticate with noon.partners when the session expires — without any manual intervention beyond replying to a Telegram DM with a one-time OTP.

---

## Architecture

Three files change:

```
noon_auth.py                        ← new: login, OTP wait, secret rotation
affiliate.py                        ← modified: catch 401, call noon_auth, retry once
.github/workflows/bot.yml           ← modified: 4 new secrets as env vars
```

### New GitHub Secrets (one-time setup)

| Secret | Description |
|---|---|
| `NOON_EMAIL` | noon.partners login email |
| `NOON_PASSWORD` | noon.partners login password |
| `TELEGRAM_ADMIN_CHAT_ID` | Admin's personal Telegram chat ID (not the channel) |
| `GH_PAT` | GitHub Personal Access Token with `repo` secrets write scope |

---

## Flow

```
affiliate.py gets 401
  → calls noon_auth.re_authenticate()
      → POST /auth/login {email, password}        # noon sends OTP to email
      → send Telegram DM to admin: "Reply with OTP"
      → poll getUpdates every 3s, up to 3 min
      → admin replies with OTP
      → POST /auth/verify {otp, token}
      → extract _npsid from response cookies
      → encrypt + update NOON_SESSION_COOKIE GitHub Secret via API
      → return new cookie
  → affiliate.py retries with new cookie          # succeeds
```

---

## Module: `noon_auth.py`

### Public API

```python
def re_authenticate() -> str:
    """
    Full re-auth flow. Returns new _npsid cookie string.
    Reads NOON_EMAIL, NOON_PASSWORD, TELEGRAM_BOT_TOKEN,
    TELEGRAM_ADMIN_CHAT_ID, GH_PAT, GITHUB_REPOSITORY from env.
    Raises AuthError on failure.
    """
```

### Internal steps

1. **Login** — `POST` to noon.partners login endpoint with `{email, password}`; response contains intermediate session token.
2. **Telegram prompt** — send DM to `TELEGRAM_ADMIN_CHAT_ID` via Bot API.
3. **OTP poll** — long-poll `getUpdates` (30s timeout × 6 = 3 min max); filter by `admin_chat_id`.
4. **Verify** — `POST` OTP + token to noon.partners verify endpoint; extract `_npsid` from `Set-Cookie`.
5. **Rotate secret** — fetch repo public key → encrypt with PyNaCl → `PUT /repos/{owner}/{repo}/actions/secrets/NOON_SESSION_COOKIE`.
6. **Return** new cookie string for immediate use in current run.

### Endpoint discovery note

Exact login/verify endpoint paths must be confirmed by inspecting the Network tab in browser devtools during a real noon.partners login session. This is a one-time discovery step at the start of implementation.

---

## Changes to `affiliate.py`

Catch 401 specifically, call `re_authenticate()`, retry once. Max one retry — no infinite loop.

---

## Changes to `bot.yml`

Add 4 new secrets to the `env:` block: `NOON_EMAIL`, `NOON_PASSWORD`, `TELEGRAM_ADMIN_CHAT_ID`, `GH_PAT`.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| OTP timeout (3 min) | Raise `AuthError`; fall back to plain URL; DM admin "OTP timed out" |
| Login endpoint changed | Raise `AuthError` with descriptive log message |
| GitHub Secret update fails | Log warning; new cookie used in-memory for current run |
| New cookie also 401s | Raise `AffiliateError` immediately — no further retry |

---

## New Dependency

`pynacl` — for encrypting secret value before GitHub API call. Add to `requirements.txt`.

---

## One-Time Setup Checklist

- [ ] Inspect noon.partners login flow in browser devtools → confirm endpoint paths
- [ ] Create GitHub PAT with `repo` scope → add as `GH_PAT` secret
- [ ] Add `NOON_EMAIL`, `NOON_PASSWORD` as GitHub Secrets
- [ ] Get personal Telegram chat ID (message @userinfobot) → add as `TELEGRAM_ADMIN_CHAT_ID`
- [ ] Add `pynacl` to `requirements.txt`
