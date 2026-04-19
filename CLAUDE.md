# CLAUDE.md — Project Rules

Working notes for Claude Code in this repo. Short list, only the non-obvious things.

## Stack

- Python 3.11, `pip` (no pnpm here — user's global preference is overridden by project constraints: this is a plain-Python repo running on GitHub Actions).
- Dependencies pinned exactly in [requirements.txt](requirements.txt). If you add a dep, pin to an exact version that exists on PyPI — don't guess.
- Tests use `pytest` (+ `pytest-mock`). Run `pytest -q`.

## Scraping (the important rule)

**noon.com sits behind Akamai.** Plain `requests` will be blocked.

- Use `curl_cffi` with `impersonate="chrome"` — this is the whole trick. See [scraper.py:_fetch_html](scraper.py).
- Do **not** reintroduce Zenrows or any paid scraping API. The point of the 2026-04-19 swap was to make the project free to run.
- If Akamai ever starts blocking curl_cffi, the escalation ladder is: (1) bump `impersonate` to a newer Chrome version, (2) add random `User-Agent` + `Referer` jitter, (3) fall back to Playwright + stealth. Do not add a paid service.
- noon's origin occasionally 504s on the filtered deals URL. That's not a block — just retry. The existing 3-attempt retry in `_fetch_html` handles it.

## Data shape

- Product data lives inside Next.js RSC streaming chunks (`self.__next_f.push(...)`). Parser is in [scraper.py](scraper.py); `_parse_rsc_payload` is the primary path, the `__NEXT_DATA__` and HTML-card parsers are fallbacks kept for resilience — don't delete them.
- Canonical SKU is `sku_config` (ends in `A`). The variant SKU (`catalog_sku`, sometimes ending in `V` or `B`) breaks product URLs — see [scraper.py:_normalize_item](scraper.py).

## Auth / secrets

- `NOON_SESSION_COOKIE` expires periodically. On 401 from the affiliate API, [noon_auth.py](noon_auth.py) kicks off a Telegram-mediated OTP flow and rotates the GitHub secret via the API. Do not try to "simplify" this flow without understanding it — it's how the bot survives unattended.
- Re-auth is attempted **at most once per run** to avoid spamming the admin with OTP emails. Don't remove that guard.
- Never log full cookie values or access tokens.

## Posting

- Telegram messages use MarkdownV2. Every dynamic string must go through `_escape_md2` in [telegram_poster.py](telegram_poster.py). Forgetting to escape `.` / `-` / `!` silently breaks message rendering.
- Captions are Arabic + emoji — keep that style when editing `format_message`.

## State files

- [posted.json](posted.json) and [state.json](state.json) are **committed** by the workflow after each run (`chore: update state [skip ci]`). That's intentional — they're the bot's memory. Don't add them to `.gitignore`.

## Testing conventions

- Scraper tests use inline HTML fixtures with mocked `__NEXT_DATA__` — do not hit the network in tests.
- When adding tests, prefer `pytest-mock`'s `mocker` over `unittest.mock` for consistency with existing tests.
- There's a known pre-existing failure in `tests/test_noon_auth.py::test_re_authenticate_full_flow` (keyword-arg mismatch). Unrelated to most work; leave it or fix it, don't let it scare you off a green board.

## Commit style

- Conventional commits: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`.
- Keep PR descriptions terse (user preference) — short summary + bullets, no fluff.
- State-sync commits from CI use `chore: update state [skip ci]` — don't use that prefix for code changes.

## What not to do

- Don't add scraping retries inside `fetch_products` — `_fetch_html` owns retry logic. Double-retry just slows failures.
- Don't create "helper" wrappers around `requests`/`curl_cffi` for generic HTTP. Each call site has its own client choice for a reason (curl_cffi only for noon.com catalog; plain `requests` for Telegram / noon.partners API / image downloads).
- Don't widen the scope of a bugfix. If the user asks to fix X, fix X. The project is small enough that refactors are tempting — resist.
