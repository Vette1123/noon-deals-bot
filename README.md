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
     • "Buy now" button → noon.com product URL + affiliate UTMs
        │
        ▼
   commit updated state.json / posted.json
```

**Attribution model:** two channels, both message-side, neither needs a login. Every "Buy now" link carries the affiliate campaign UTMs, and the message body shows a tap-to-copy coupon code that users paste at noon's checkout.

**What gets posted:** at least **25% off**, at least **EGP 150**, and not rated below 3.5 by 20+ buyers. Survivors are ranked by a `deal_score` (discount + rating + basket value + trust flags), deduplicated by name, capped at **2 per seller**, and the top **12** go out. Commission is a percentage of basket value, so cheap deep-discount filler earns nothing and only costs subscribers.

**Page cursor:** each run scrapes 2 pages and advances, wrapping at page 60 (~3,000 products, a 5-day cycle). A SKU already posted is on cooldown for **21 days**.

## Project layout

| File | Purpose |
| --- | --- |
| [main.py](main.py) | Entry point — orchestrates fetch → filter → post |
| [scraper.py](scraper.py) | Fetches & parses noon.com catalog pages (inline JS payload + fallbacks) |
| [filters.py](filters.py) | Filters out already-posted SKUs, weak discounts and low-value items |
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

> Since mid-2026 Akamai also challenges cold requests from residential IPs, so a local run may fail at
> the fetch step with `Akamai JS challenge`. CI is unaffected (it egresses through Cloudflare WARP).
> To debug parsing locally, save the page HTML from a real browser and feed it to
> `scraper.parse_products_from_html`.

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
