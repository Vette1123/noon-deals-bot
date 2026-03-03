# Noon Affiliate Telegram Bot — Design Document
Date: 2026-03-03

## Overview
An automated system that scrapes discounted products from Noon Egypt, generates affiliate links, and posts them to a Telegram channel every 4 hours. Entirely free to run using GitHub Actions.

## Goals
- Find hot deals on noon.com/egypt-en automatically
- Attach affiliate ID (AFFccacc092d97d) to every product link
- Post formatted deal messages to Telegram channel @noon_hot_deals
- Run 24/7 with zero hosting cost

## Target Platform
- Noon Egypt: noon.com/egypt-en
- Currency: EGP
- Affiliate account: noon.partners (ID: AFFccacc092d97d, Project: PRJ496018)
- Telegram channel: @noon_hot_deals
- Telegram bot: @NoonHotDealsBot

## Deal Filtering Criteria (Option D)
- Noon featured/flash sale deals (any discount)
- AND/OR any product with ≥20% discount

## Architecture

```
GitHub Actions (cron: every 4 hours)
        │
        ▼
  scraper.py
  ├── Scrapes noon.com/egypt-en/deals/
  ├── Filters: Noon featured + ≥20% discount
  ├── Skips already-posted products (posted.json)
  ├── Builds affiliate links
  └── Posts to Telegram channel via Bot API
        │
        ▼
  Telegram Channel (@noon_hot_deals)
        │
        ▼
  posted.json committed back to repo
```

## Tech Stack
- Python 3.x
- requests + BeautifulSoup4 — scrape Noon
- python-telegram-bot — post to channel
- GitHub Actions — free scheduler (every 4 hours)
- GitHub repo — stores posted.json state (no database)

## Affiliate Link Format
Base product URL + affiliate tracking parameter from noon.partners.
Format to be confirmed by inspecting the dashboard link creator.
Likely: `https://www.noon.com/egypt-en/[product-path]/?o=AFFccacc092d97d`
Or via noon.partners redirect.

## Telegram Message Format
```
🔥 [Product Name]

💰 EGP [sale price] (was EGP [original price])
📉 [X]% OFF

🛒 [affiliate link]
```
Product image attached to each message.

## Project Structure
```
noon-deals-bot/
├── .github/
│   └── workflows/
│       └── bot.yml          ← GitHub Actions schedule
├── scraper.py               ← main script
├── posted.json              ← tracks posted products (auto-updated)
├── requirements.txt         ← Python dependencies
└── .env.example             ← documents needed secrets
```

## GitHub Secrets Required
- TELEGRAM_BOT_TOKEN — bot token from @BotFather
- TELEGRAM_CHANNEL_ID — @noon_hot_deals
- GH_TOKEN — GitHub token to commit posted.json back to repo

## Constraints
- No server / VPS — must be serverless
- Free hosting only
- Posting frequency: every 4 hours
- No duplicate posts (tracked via posted.json)

## Out of Scope
- Admin dashboard
- User interaction / chatbot replies
- Multi-country support (Egypt only for now)
- Price history tracking
