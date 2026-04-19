# Noon Deals Bot

Auto-posts the best discounted products from [noon.com Egypt](https://www.noon.com/egypt-en/) to a Telegram channel, 6× a day, fully free to run.

- Scrapes noon's deal pages using `curl_cffi` (Chrome TLS impersonation — no paid API needed)
- Generates affiliate short-links via the noon.partners API
- Posts Arabic-formatted product cards with images to Telegram
- Auto-refreshes noon's session cookie when it expires (OTP via Telegram DM)
- Runs on GitHub Actions — no server required

## How it works

```
GitHub Actions (cron, 6×/day)
        │
        ▼
   fetch 2 pages of deals  ── curl_cffi + Chrome fingerprint ──▶  noon.com
        │
        ▼
   filter new deals (≥5% off, not already posted)
        │
        ▼
   build affiliate links  ──────────────────────────────────▶  noon.partners API
        │                                                      (auto-reauth via OTP on 401)
        ▼
   post to Telegram channel  ───────────────────────────────▶  @noon_hot_deals
        │
        ▼
   commit updated state.json / posted.json
```

**Page cursor:** each run scrapes 2 pages and advances; after page 10 the cursor resets to 1 and `posted.json` is cleared so deals can be re-posted on the next cycle.

## Project layout

| File | Purpose |
| --- | --- |
| [main.py](main.py) | Entry point — orchestrates fetch → filter → post |
| [scraper.py](scraper.py) | Fetches & parses noon.com catalog pages (RSC + fallbacks) |
| [filters.py](filters.py) | Filters out already-posted SKUs and low-discount products |
| [affiliate.py](affiliate.py) | Builds noon.partners affiliate tracking links |
| [noon_auth.py](noon_auth.py) | 3-step PKCE OTP re-auth when session cookie expires |
| [telegram_poster.py](telegram_poster.py) | Formats and posts product cards to Telegram |
| [posted.json](posted.json) | SKUs already posted this cycle (reset at page wraparound) |
| [state.json](state.json) | `{"next_page": N}` — pagination cursor |

## Local setup

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in values
python main.py --dry-run   # prints what would be posted, skips Telegram
python main.py             # real run
```

## Required secrets (GitHub Actions)

| Secret | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Bot that posts to the channel |
| `TELEGRAM_CHANNEL_ID` | Channel handle (e.g. `@noon_hot_deals`) |
| `TELEGRAM_ADMIN_CHAT_ID` | Your personal chat ID (receives OTP prompts) |
| `NOON_SESSION_COOKIE` | `_npsid=…` from affiliates.noon.partners (auto-rotated) |
| `NOON_EMAIL` | noon.partners login email (for re-auth) |
| `NOON_USER_CODE` | noon.partners user code (for re-auth) |
| `GH_PAT` | Fine-grained PAT with `secrets:write` (lets the bot rotate `NOON_SESSION_COOKIE`) |

No scraping API key required — `curl_cffi` handles Akamai.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Schedule

Cron `0 4,8,12,16,20,0 * * *` UTC → 6×/day (every 4 hours). Triggered by [.github/workflows/bot.yml](.github/workflows/bot.yml) or manually via `workflow_dispatch`.
