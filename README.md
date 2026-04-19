# Noon Deals Bot

Auto-posts the best discounted products from [noon.com Egypt](https://www.noon.com/egypt-en/) to a Telegram channel, 6× a day — **fully free to run, no login required.**

- Scrapes noon's deal pages using `curl_cffi` (Chrome TLS impersonation — no paid API)
- Attaches your influencer coupon code to every post as **tap-to-copy** text
- Posts Arabic-formatted product cards with images to Telegram
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
   post to Telegram channel with:
     • product image
     • Arabic-formatted card
     • tap-to-copy coupon code (e.g. gado1996)
     • "Buy now" button → bare noon.com product URL
        │
        ▼
   commit updated state.json / posted.json
```

**Attribution model:** users tap the coupon code in the message (copies to clipboard on mobile), click "Buy now", and paste the coupon at noon's checkout. The coupon both gives the customer a discount and attributes the sale to you — no affiliate API, no login, no session management.

**Page cursor:** each run scrapes 2 pages and advances; after page 10 the cursor resets to 1 and `posted.json` is cleared so deals can be re-posted on the next cycle.

## Project layout

| File | Purpose |
| --- | --- |
| [main.py](main.py) | Entry point — orchestrates fetch → filter → post |
| [scraper.py](scraper.py) | Fetches & parses noon.com catalog pages (RSC + fallbacks) |
| [filters.py](filters.py) | Filters out already-posted SKUs and low-discount products |
| [telegram_poster.py](telegram_poster.py) | Formats & posts product cards to Telegram (includes coupon line) |
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
| `NOON_COUPON_CODE` | *(optional)* Your noon influencer coupon. Defaults to `gado1996`. |

That's it — three secrets, two of them truly required. No scraping API key, no noon.partners login, no session rotation, no OTP flow.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Schedule

Cron `0 4,8,12,16,20,0 * * *` UTC → 6×/day (every 4 hours). Triggered by [.github/workflows/bot.yml](.github/workflows/bot.yml) or manually via `workflow_dispatch`.
