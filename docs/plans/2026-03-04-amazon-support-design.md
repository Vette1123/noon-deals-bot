# Amazon Egypt Support — Design Doc
**Date:** 2026-03-04

> **⚠️ Historical doc.** Zenrows was removed on 2026-04-19 and replaced with `curl_cffi` — ignore any Zenrows references below.

## Goal
Add Amazon Egypt (amazon.eg) as a second deal source alongside Noon, posting 50 deals from each source per run (100 total) to the same Telegram channel, interleaved, using identical card formatting.

## Architecture

```
main.py
├── fetch Noon deals        (existing — 2 Zenrows pages)
├── fetch Amazon deals      (new — PA-API SearchItems)
├── filter each independently (already_posted + min_discount)
├── sort each by discount % desc, cap at 50
├── interleave [N1, A1, N2, A2, ...]
└── post 100 deals with 3s delay
```

## New File: `amazon_scraper.py`

- Uses `paapi5-python-sdk` (official Amazon PA-API 5 client)
- Calls `SearchItems` with `DealsOnly=True` across a rotating list of categories:
  `Electronics, HomeAndKitchen, Fashion, Sports, BeautyPersonalCare, Toys, Books`
- `amazon_category_index` in `state.json` determines which category this run uses,
  increments each run and wraps around
- Returns normalized product dicts matching Noon's schema:
  `name, sku (ASIN), url, image_url, sale_price, original_price, discount_pct, brand, rating, rating_count, store_name, estimated_delivery, affiliate_url`
- Affiliate URL built as: `https://www.amazon.eg/dp/{ASIN}?tag={PARTNER_TAG}`
  (PA-API also returns a direct affiliate URL — use whichever is available)

## Modified Files

### `main.py`
- Import `amazon_scraper.fetch_amazon_products`
- Run both scrapers, filter each against `already_posted`
- Interleave results, post sequentially
- `MAX_POSTS_PER_RUN = 50` applies per source (unchanged constant, used twice)

### `state.json`
Gains one new field:
```json
{ "next_page": 3, "amazon_category_index": 2 }
```

### `requirements.txt`
Add: `paapi5-python-sdk`

### `.github/workflows/bot.yml`
Add three new env vars passed to `python main.py`:
- `AMAZON_ACCESS_KEY`
- `AMAZON_SECRET_KEY`
- `AMAZON_PARTNER_TAG`

## Card Format
Amazon posts reuse `format_message()` from `telegram_poster.py` unchanged.
Same Arabic copy, same emoji layout, same inline button. No source badge.

## Secrets (GitHub)
| Secret | Description |
|---|---|
| `AMAZON_ACCESS_KEY` | PA-API access key from Amazon Associates |
| `AMAZON_SECRET_KEY` | PA-API secret key |
| `AMAZON_PARTNER_TAG` | Your Associates tag (e.g. `mystore-21`) |

## Runtime Estimate
- Zenrows (Noon): ~120s
- PA-API (Amazon): ~5s
- Posting 100 deals × 3s: ~300s
- **Total: ~7 min/run** — well within GitHub Actions limits

## Out of Scope
- No separate Amazon Telegram channel
- No source badge on cards
- No change to Noon scraping logic
- No change to affiliate link building for Noon
