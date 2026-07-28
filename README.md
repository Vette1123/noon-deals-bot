# Noon Deals Bot

<!-- Badge labels stay Latin: shields.io renders SVG text with no Arabic shaper, so
     "ديلز مصر" came out as disconnected letters in the wrong order. The Arabic name
     goes in the prose below, where GitHub shapes it properly. -->

[![Telegram channel](https://img.shields.io/badge/Telegram-%40noon__hot__deals-2CA5E0?logo=telegram&logoColor=white)](https://t.me/noon_hot_deals)
[![Deals site](https://img.shields.io/badge/deals%20site-live-c81e4a)](https://vette1123.github.io/noon-deals-bot/)
[![Bot](https://github.com/Vette1123/noon-deals-bot/actions/workflows/bot.yml/badge.svg)](https://github.com/Vette1123/noon-deals-bot/actions/workflows/bot.yml)

**Channel:** [t.me/noon_hot_deals](https://t.me/noon_hot_deals) · **Site:** ديلز مصر — [vette1123.github.io/noon-deals-bot](https://vette1123.github.io/noon-deals-bot/)

Auto-posts the best discounted products from [noon.com Egypt](https://www.noon.com/egypt-en/) to a Telegram channel, 6× a day — **fully free to run, no login required.**

- Scrapes noon's deal pages using `curl_cffi` (Chrome TLS impersonation — no paid API)
- Attaches your influencer coupon code to every post as **tap-to-copy** text
- Posts Arabic-formatted product cards with images to Telegram
- Republishes the same deals as a **static Arabic site on GitHub Pages** so search traffic earns too
- Optionally crossposts to a **Facebook Page**
- Runs on GitHub Actions — no server required

## How it works

```
GitHub Actions (cron, 6×/day)
        │
        ▼
   fetch 6 category feeds  ── curl_cffi + Chrome fingerprint ──▶  noon.com
        │                     (rotating ~34 categories × 10 pages)
        ▼
   filter, then rank by expected commission in EGP
        │
        ▼
   post to Telegram channel with:
     • product image
     • Arabic-formatted card
     • tap-to-copy coupon code (e.g. gado)
     • "Buy now" button → noon.com product URL + affiliate UTMs
        │
        ▼
   commit updated state.json / posted.json / deals.json
        │
        ├──▶  crosspost to a Facebook Page (only if secrets are set)
        │
        ▼
   rebuild the static site from deals.json ──▶ GitHub Pages
```

**Attribution model:** two channels, both message-side, neither needs a login. Every "Buy now" link carries the affiliate campaign UTMs, and the message body shows a tap-to-copy coupon code that users paste at noon's checkout.

**What gets posted:** at least **25% off**, at least **EGP 150**, not rated below 3.5 by 20+ buyers, and not unbranded-and-unreviewed filler. Survivors are ranked by **expected commission in pounds** — `min(cap, category rate × price)` times conversion odds — deduplicated by name, capped at **2 per seller**. The top **12** go to Telegram; the top **20** are archived for the site.

Rates are per category and payout is **capped at AED 50 per item**, which makes expensive electronics (laptops 3%, mobiles 2%) the worst thing on the board and mid-priced beauty, toys and small appliances (8%) the best. See [docs/MONETIZATION.md](docs/MONETIZATION.md) for the full table.

**Feed cursor:** noon's category browse paths are real product lists; each run walks 6 of them and advances through a rotation of ~34 categories × 10 pages (~14,000 products, roughly a 10-day cycle). A SKU already posted is on cooldown for **21 days**.

## The static site

Every deal is archived to [deals.json](deals.json) and rendered into an Arabic (RTL) site: a front page, one page per deal with `Product` structured data, a hub per **category** and per **brand**, a directory of each, a paginated archive, `sitemap.xml`, `robots.txt` and an RSS feed. No web fonts, no CSS files, no script bundles — search traffic arrives on mobile data, and page speed is ranking. It follows the device's light/dark setting, with a toggle that remembers an explicit choice.

It matters because it earns **without an audience**: a Telegram post reaches today's subscribers, a page that ranks reaches everyone who searches.

Two rules it will not break:

- **Deal pages never 404.** A deal that ages out becomes a `noindex` tombstone linking on to its hubs, because a URL that took four months to rank is the one thing here that cannot be rebuilt.
- **`priceValidUntil` comes from when the deal was seen**, not from the build, so a rebuild never re-certifies an old price as current.

Enable it once under *Settings → Pages → Source: GitHub Actions*; the `publish-site` job does the rest. To move it onto your own domain, set the `SITE_DOMAIN` repository variable and point the DNS at Pages — worth doing before it ranks, not after.

Preview it locally:

```bash
python site_builder.py && python -m http.server -d public 8000
```

See [docs/MONETIZATION.md](docs/MONETIZATION.md) for what earns, what is built, and what still needs a human.

## Project layout

| File | Purpose |
| --- | --- |
| [main.py](main.py) | Entry point — orchestrates fetch → filter → post |
| [scraper.py](scraper.py) | Fetches & parses noon.com catalog pages (inline JS payload + fallbacks) |
| [filters.py](filters.py) | Filters out already-posted SKUs, weak discounts and filler; ranks by expected commission |
| [categories.py](categories.py) | noon category codes, their commission rates, and their Arabic names |
| [telegram_poster.py](telegram_poster.py) | Formats & posts product cards to Telegram (includes coupon line) |
| [archive.py](archive.py) | Records deals into `deals.json` (1-year window, then tombstoned) |
| [site_builder.py](site_builder.py) | Renders `deals.json` into the static site in `public/` |
| [facebook_poster.py](facebook_poster.py) | Optional Facebook Page crosspost (no-op without secrets) |
| [posted.json](posted.json) | `{sku: ISO timestamp}` — per-SKU repost cooldown |
| [state.json](state.json) | `{"next_task": N}` — cursor into the category-feed rotation |
| [deals.json](deals.json) | The published-deal archive the site is built from |

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
| `NOON_COUPON_CODE` | *(optional)* Your noon influencer coupon. Defaults to `gado`. |
| `FACEBOOK_PAGE_ID` | *(optional)* Enables the Facebook crosspost. Skipped when unset. |
| `FACEBOOK_PAGE_TOKEN` | *(optional)* Long-lived Page token with `pages_manage_posts`. |

Two are truly required. No scraping API key, no noon.partners login, no session rotation, no OTP flow.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Schedule

Cron `0 4,8,12,16,20,0 * * *` UTC → 6×/day (every 4 hours). Triggered by [.github/workflows/bot.yml](.github/workflows/bot.yml) or manually via `workflow_dispatch`.
