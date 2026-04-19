# CLAUDE.md — Project Rules

Working notes for Claude Code in this repo. Short list, only the non-obvious things.

## Stack

- Python 3.11, `pip` (no pnpm — this is a plain-Python repo running on GitHub Actions).
- Dependencies pinned exactly in [requirements.txt](requirements.txt). If you add a dep, pin to an exact version that exists on PyPI — don't guess.
- Tests use `pytest` (+ `pytest-mock`). Run `pytest -q`.

## Scraping (the important rule)

**noon.com sits behind Akamai.** Plain `requests` will be blocked.

- Use `curl_cffi` with `impersonate="chrome"` — this is the whole trick. See [scraper.py:_fetch_html](scraper.py).
- Do **not** reintroduce Zenrows or any paid scraping API. The project's goal is to stay 100% free to run.
- If Akamai ever starts blocking curl_cffi, the escalation ladder is: (1) bump `impersonate` to a newer Chrome version, (2) add random `User-Agent` + `Referer` jitter, (3) fall back to Playwright + stealth. Do not add a paid service.
- noon's origin occasionally 504s on the filtered deals URL. That's not a block — just retry. The existing 3-attempt retry in `_fetch_html` handles it.

## Affiliate attribution (read this before touching posting)

**There is no noon.partners login, session cookie, or affiliate API in this project anymore (removed 2026-04-19).**

- Attribution happens via an **influencer coupon code** shown in the Telegram message body. Users copy it and paste at checkout. That's the whole mechanism.
- The coupon is configurable via `NOON_COUPON_CODE` (defaults to `gado1996` — see [main.py](main.py)).
- Do **not** reintroduce `noon_auth.py`, `affiliate.py`, OTP flows, or session cookies. If you think you need them, you're solving the wrong problem — the coupon-in-message approach is the intentional design.
- URL-based coupon params (`?coupon=…`, `?sellerCode=…`, etc.) are ignored by noon.com. Do not bother appending them.

## Telegram message formatting (MarkdownV2)

- Every dynamic string goes through `_escape_md2` in [telegram_poster.py](telegram_poster.py). Forgetting to escape `.` / `-` / `!` silently breaks rendering.
- The coupon uses a MarkdownV2 code span (`` `gado1996` ``) — on mobile Telegram this becomes **tap-to-copy**. That's the UX contract, don't change it to a regular string.
- The coupon value is validated against `^[A-Za-z0-9_-]+$` before being placed inside the code span, so no escaping is needed inside. Keep that guard — it's what lets us skip escaping safely.
- Captions are Arabic + emoji — keep that style when editing `format_message`.

## Data shape

- Product data lives inside Next.js RSC streaming chunks (`self.__next_f.push(...)`). Parser is in [scraper.py](scraper.py); `_parse_rsc_payload` is the primary path, the `__NEXT_DATA__` and HTML-card parsers are fallbacks kept for resilience — don't delete them.
- Canonical SKU is `sku_config` (ends in `A`). The variant SKU (`catalog_sku`, sometimes ending in `V` or `B`) breaks product URLs — see [scraper.py:_normalize_item](scraper.py).

## State files

- [posted.json](posted.json) and [state.json](state.json) are **committed** by the workflow after each run (`chore: update state [skip ci]`). That's intentional — they're the bot's memory. Don't add them to `.gitignore`.

## Testing conventions

- Scraper tests use inline HTML fixtures with mocked `__NEXT_DATA__` — do not hit the network in tests.
- When adding tests, prefer `pytest-mock`'s `mocker` over `unittest.mock` for consistency with existing tests.

## Commit style

- Conventional commits: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`.
- Keep PR descriptions terse (user preference) — short summary + bullets, no fluff.
- State-sync commits from CI use `chore: update state [skip ci]` — don't use that prefix for code changes.

## What not to do

- Don't add scraping retries inside `fetch_products` — `_fetch_html` owns retry logic. Double-retry just slows failures.
- Don't create "helper" wrappers around `requests`/`curl_cffi` for generic HTTP. Each call site has its own client choice for a reason (curl_cffi only for noon.com catalog; plain `requests` for Telegram and image downloads).
- Don't widen the scope of a bugfix. If the user asks to fix X, fix X. The project is small enough that refactors are tempting — resist.
