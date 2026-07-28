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
- **GitHub Actions datacenter IPs are blocked by Akamai** regardless of TLS fingerprint. CI routes noon.com through **Cloudflare WARP (free)** in proxy mode — see the "Set up Cloudflare WARP" step in [bot.yml](.github/workflows/bot.yml). Scraper reads `SCRAPER_PROXY`; when unset (local dev) it hits noon directly. Only the scraper uses the proxy — Telegram does not.
- If Akamai ever starts blocking curl_cffi *from a clean residential IP*, the escalation ladder is: (1) bump `impersonate` to a newer Chrome version, (2) add random `User-Agent` + `Referer` jitter, (3) fall back to Playwright + stealth. Do not add a paid service.
- **As of 2026-07-28 a cold curl_cffi request from a residential IP also gets challenged** (HTTP 200 + JS interstitial), so `python main.py --dry-run` on a laptop will fail at fetch. WARP-routed CI still gets clean HTML. To debug parsing locally, pull the page in a real browser and run `parse_products_from_html` on that HTML — don't "fix" the scraper against a challenge page.
- noon's origin occasionally 504s on the filtered deals URL. That's not a block — just retry. The existing 3-attempt retry in `_fetch_html` handles it.

## Affiliate attribution (read this before touching posting)

**There is no noon.partners login, session cookie, or affiliate API in this project anymore (removed 2026-04-19).**

Two attribution channels run in parallel — both are message-side, neither needs a login:

1. **Affiliate UTMs on every product link** — `_with_affiliate_utms` in [telegram_poster.py](telegram_poster.py)
   appends `utm_campaign` / `utm_medium=AFF…` / `utm_source=C…` / `adjust_deeplink_js=1`. These are the
   IDs from the affiliate panel, not secrets. Overridable via `NOON_AFFILIATE_MEDIUM` / `_CAMPAIGN` /
   `_SOURCE`; set `NOON_AFFILIATE_MEDIUM=""` to disable locally. If commissions stop landing, re-copy a
   fresh link out of the panel and compare the params — noon does rotate them.
2. **Influencer coupon code** shown in the message body. Users copy it and paste at checkout.
- The coupon is configurable via `NOON_COUPON_CODE` (defaults to `gado1996` — see [main.py](main.py)).
- Do **not** reintroduce `noon_auth.py`, `affiliate.py`, OTP flows, or session cookies. If you think you need them, you're solving the wrong problem — the coupon-in-message approach is the intentional design.
- URL-based coupon params (`?coupon=…`, `?sellerCode=…`, etc.) are ignored by noon.com. Do not bother appending them.

## Telegram message formatting (MarkdownV2)

- Every dynamic string goes through `_escape_md2` in [telegram_poster.py](telegram_poster.py). Forgetting to escape `.` / `-` / `!` silently breaks rendering.
- The coupon uses a MarkdownV2 code span (`` `gado1996` ``) — on mobile Telegram this becomes **tap-to-copy**. That's the UX contract, don't change it to a regular string.
- The coupon value is validated against `^[A-Za-z0-9_-]+$` before being placed inside the code span, so no escaping is needed inside. Keep that guard — it's what lets us skip escaping safely.
- Captions are Arabic + emoji — keep that style when editing `format_message`.

## Data shape (rewritten 2026-06-30 — noon dropped Next.js)

- Product data is inlined in the SSR HTML as **reference-serialized JavaScript**, not JSON:
  `…,hits:$R[8621]=[$R[8622]={offer_code:"e162…",sku_config:"N23157381A",price:640,sale_price:225,…}],…`
  Unquoted keys, `!0`/`!1` booleans, `\x3C` escapes, and a `$R[n]=` alias binding in front of every
  value. `json.loads` cannot read it — `_parse_embedded_payload` + the `_js_parse_*` literal parser
  in [scraper.py](scraper.py) handle it. That is the **primary** path now.
- Fallback order after it: `_parse_rsc_payload` (old `self.__next_f.push` chunks) → `_parse_next_data`
  (`__NEXT_DATA__`) → `_parse_product_cards` (HTML). Keep all of them — noon rewrites its frontend.
- Card CSS classes are content-hashed per build (`_linkWrapper_1w7gv_1`) — **never** select on them.
  `data-qa` is the only stable hook: `plp-product-box` / `-name` / `-price` (was `product-block`).
- Canonical SKU is `sku_config` (ends in `A`). The variant SKU (`catalog_sku`, sometimes ending in `V` or `B`) breaks product URLs — see [scraper.py:_normalize_item](scraper.py).
- Product URLs are `…/{slug}/{SKU}/p/?o={offer_code}`. The `o=` param pins the seller/offer the
  advertised price belongs to — drop it and the user can land on a pricier offer for the same SKU.

## Deals URL (what still works)

- `f[discount_percent][min]=…` and `sort[by]=discount_percent` were **removed** in the rewrite. So was
  `sort[order]` (now `sort[dir]`). Unknown params are silently ignored — the server just falls back to
  `sort[by]=popularity`, which is exactly how the June breakage hid for a month.
- Surviving facets: `is_fbn`, `category`, `brand`, `price`, `deal_tag`, `min_offer_price`,
  `new_arrivals`, `grade`, `colour_family`, `item_condition`, `partner`. Format is `f[facet]=value`.
- `deal_tag` codes (`big-yellow-sale`, `bys-flash-sale`, `bys-mega`) are campaign-scoped and die when
  the campaign does. `min_offer_price=365_days` ("lowest price in a year") is the durable one, and is
  what `DEALS_URL` uses. Real discount filtering happens in [filters.py](filters.py).
- To re-check which params still bite: request the URL and look at the `search:{f:…,sort:…}` object
  echoed back in the payload. If your param isn't in there, noon dropped it.

## Failing loudly

- A 0-product scrape raises `SystemExit` in [main.py](main.py). Do not soften this back to a quiet
  `return` — a green CI run that posts nothing is the exact failure mode that cost a month of uptime.
- Akamai's bot check answers **HTTP 200** with a ~2 KB JS interstitial. `_is_akamai_challenge` treats
  it as a failed fetch so it burns a retry instead of parsing to 0 products.

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
