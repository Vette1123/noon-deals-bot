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
   fresh link out of the panel and compare the params — noon does rotate them. To read the real ones:
   panel → campaign → *Links* → copy a link → open the `s.noon.com/…` short URL and read where it lands.
   - `with_affiliate_utms` **re-stamps**: it strips our four params and reapplies them, keeping noon's
     own `o=` pin. It used to return URLs that already had a `utm_medium` unchanged, which meant the
     archive's stored URLs kept serving a wrong ID forever. The site re-stamps at render time
     (`site_builder._out_url`), so fixing the ID here repairs every archived page on the next build.
2. **Influencer coupon code** shown in the message body. Users copy it and paste at checkout.
- The coupon is configurable via `NOON_COUPON_CODE` (defaults to `gado` — see [main.py](main.py); the panel is the source of truth for which codes are live).
- Do **not** reintroduce `noon_auth.py`, `affiliate.py`, OTP flows, or session cookies. If you think you need them, you're solving the wrong problem — the coupon-in-message approach is the intentional design.
- URL-based coupon params (`?coupon=…`, `?sellerCode=…`, etc.) are ignored by noon.com. Do not bother appending them.

## Telegram message formatting (MarkdownV2)

- Every dynamic string goes through `_escape_md2` in [telegram_poster.py](telegram_poster.py). Forgetting to escape `.` / `-` / `!` silently breaks rendering.
- The coupon uses a MarkdownV2 code span (`` `gado` ``) — on mobile Telegram this becomes **tap-to-copy**. That's the UX contract, don't change it to a regular string.
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

## Where the money comes from (read before touching filters.py)

Commission rates are **per category** and the panel **caps payout at AED 50 per item**
(~EGP 700). Both facts are in [categories.py](categories.py) and
[docs/MONETIZATION.md](docs/MONETIZATION.md).

- Apparel/bags/jewellery pay 10%, beauty/health/toys/baby/sports/small-appliances 8%,
  home 6%, and **electronics 2–4%** — laptops 3%, mobiles 2%. Chasing expensive
  electronics is the worst square on the board, and the old points-based `deal_score`
  did exactly that by adding a raw price bonus.
- `deal_score` is now **expected commission in EGP** (`min(cap, rate × price)`)
  multiplied by conversion odds (discount, rating, demand, fulfilment). Do not
  re-add a term that rewards price on its own — the cap is what makes that wrong.
- Category comes from the feed a product was scraped out of, not from the payload
  (there is no category field in it). Anything that bypasses `fetch_products` gets
  `DEFAULT_RATE`.

## Deals URL (what still works)

- **Scraping is per category, not out of `all-products`.** `/egypt-en/{category-code}/`
  is a real PLP and takes the same filter params; the marketing slugs off the homepage
  (`/egypt-en/beauty/`, `/egypt-en/electronics/`) are curated landing pages with **no
  catalog payload at all**. Verified 2026-07-28 — do not "simplify" back to those.
- `f[category]=…` as a *query param* on `all-products` returns 0 hits when combined
  with `min_offer_price`. The browse path is what works.
- `all-products` reports `nbPages:10` against 109k hits, and past page ~10 it re-serves
  earlier pages. The old `MAX_PAGES=60` cursor therefore spent most of its cycle
  re-reading the same ~500 products. `PAGES_PER_FEED = 10` is not arbitrary.
- `f[discount_percent][min]=…` and `sort[by]=discount_percent` were **removed** in the rewrite. So was
  `sort[order]` (now `sort[dir]`). Unknown params are silently ignored — the server just falls back to
  `sort[by]=popularity`, which is exactly how the June breakage hid for a month.
- Surviving facets: `is_fbn`, `category`, `brand`, `price`, `deal_tag`, `min_offer_price`,
  `new_arrivals`, `grade`, `colour_family`, `item_condition`, `partner`. Format is `f[facet]=value`.
- `deal_tag` codes (`big-yellow-sale`, `bys-flash-sale`, `bys-mega`) are campaign-scoped and die when
  the campaign does. `min_offer_price=365_days` ("lowest price in a year") is the durable one, and is
  what `DEALS_QUERY` uses. Real discount filtering happens in [filters.py](filters.py).
- To re-check which params still bite: request the URL and look at the `search:{f:…,sort:…}` object
  echoed back in the payload. If your param isn't in there, noon dropped it.

## Failing loudly

- A 0-product scrape raises `SystemExit` in [main.py](main.py). Do not soften this back to a quiet
  `return` — a green CI run that posts nothing is the exact failure mode that cost a month of uptime.
- Akamai's bot check answers **HTTP 200** with a ~2 KB JS interstitial. `_is_akamai_challenge` treats
  it as a failed fetch so it burns a retry instead of parsing to 0 products.

## Channel economics (why the filters look like this)

Every rule in [filters.py](filters.py) exists because it was measured, not guessed. Don't relax one
without re-measuring.

- **`MIN_PRICE = 150`** — commission is a percentage of basket value. A 60%-off EGP 40 item earns
  nothing and still burns a post slot.
- **`MIN_RATING = 3.5`, only above `RATING_CONFIDENCE` reviews** — a 2.1★ product with 3 reviews is
  noise; with 400 reviews it's a refund waiting to happen, and refunds void commission.
- **`deal_score`** ranks by expected commission in EGP — see the money section above.
- **`_is_filler`** drops listings with no brand, no reviews and a price under EGP 400.
  They have no search demand, earn cents, and their deal pages are thin by construction.
- **`MAX_PER_SELLER = 2`** — in one live sample a single store ("ELLE Cosmetics") owned 18 of 72
  qualifying deals, including 8 near-identical body splashes. Uncapped, the channel becomes its
  catalogue and readers mute it.
- **`_dedupe_by_name`** — the same listing is often resold by several stores under the identical name.
- **`MAX_POSTS_PER_RUN = 12`** (env-overridable) — was 50, i.e. 300 posts/day. Nobody stays subscribed
  to that. **`SITE_DEALS_PER_RUN = 20`** is the separate, larger cap for the archive: the channel and
  the site want opposite volumes, so everything between the two caps becomes a page without ever
  becoming a notification. Raise that one, never the post cap.
- **`REPOST_AFTER_DAYS = 21`** against a rotation of ~34 category feeds × 10 pages, six fetches a run:
  roughly a ten-day cycle over ~14,000 products, with the 21-day per-SKU cooldown on top.

## Publishing surfaces (Telegram is not the only one)

The same scrape is published three ways. Read [docs/MONETIZATION.md](docs/MONETIZATION.md)
before changing any of them — the reasoning behind each is there, not here.

- **Telegram** — [telegram_poster.py](telegram_poster.py). The share button forwards the
  *channel*, not the product: a subscriber is worth far more than one click. Only public
  `@handles` can be shared, so `channel_share_url` returns `""` for numeric chat IDs.
- **The static site** — [archive.py](archive.py) records every posted deal into
  [deals.json](deals.json); [site_builder.py](site_builder.py) renders it into `public/`
  and the `publish-site` job in [bot.yml](.github/workflows/bot.yml) deploys it to Pages.
  It needs no subscribers, which is the whole point of it.
- **Facebook** — [facebook_poster.py](facebook_poster.py), opt-in via `FACEBOOK_PAGE_ID`
  + `FACEBOOK_PAGE_TOKEN`. Unset, it is a no-op. It must never fail the run: it swallows
  its own errors on purpose.

`with_affiliate_utms` is public and is the single place link attribution is added.
Anything that publishes a product URL goes through it, or that traffic is unpaid.

## The static site (rules that are load-bearing)

- **No external requests at all: no web fonts, no CSS files, no script bundles.** Search
  traffic lands on Egyptian mobile data; every request is LCP and LCP is ranking. Arabic
  type comes from the system stack. There is a test asserting this — do not "improve" it
  with a font CDN.
- The **only** JavaScript is the theme toggle, inlined in two small blocks. The one in
  `<head>` must stay first and inline: it applies the stored theme before paint, and
  moving it or deferring it brings back the light/dark flash on every navigation.
- Theme resolution order is device preference, then an explicit choice. The dark tokens
  are duplicated on purpose (`@media` + `:root[data-theme="dark"]`) because CSS has no
  way to reuse a block across both without a preprocessor.
- **Never inline scraped text into a `<script>` without `_ld_json`.** Product names are
  written by marketplace sellers. `html.escape` cannot be used inside JSON-LD, so
  `_ld_json` escapes `< > &` as `\uXXXX`, which is valid JSON and cannot close the tag.
- **Only claim an `aggregateRating` noon actually reported.** Inventing review counts is
  how a site loses rich results permanently.
- **Keep the affiliate disclosure in the footer and keep the palette off noon's yellow.**
  Looking like the merchant is an affiliate-account-termination risk, not a style choice.
- Outbound product links are `rel="nofollow sponsored noopener"`.
- Deal filenames come from the SKU and are validated against `^[A-Za-z0-9_-]+$` — a SKU
  is scraped data, and `../../` in a filename writes outside the output directory.
- **A deal page must never start 404ing.** Deals that age out become `noindex`
  tombstones (`archive.prune_archive` → `archive["retired"]`) that link on to their
  hubs. Deleting the entry instead throws away the one asset here that takes months
  to rebuild. Tombstones stay out of `sitemap.xml` on purpose.
- `priceValidUntil` is measured from `posted_at`, **not** from build time. Building
  from `now` silently re-certifies a months-old price as current, to a consumer that
  takes it at face value.
- Numbers, dates and percentages inside an Arabic sentence go through `_ltr()`.
  Without it bidi renders `2026-07-28` as `28-07-2026` and puts the `%` on the wrong
  side of the digits. Test with a screenshot — `innerText` shows logical order and
  will look fine while the page is wrong.

## State files

- [posted.json](posted.json), [state.json](state.json) and [deals.json](deals.json) are **committed** by the workflow after each run (`chore: update state [skip ci]`). That's intentional — they're the bot's memory. Don't add them to `.gitignore`.
- `deals.json` is the site's data source, capped at 365 days / 12,000 live deals by
  `prune_archive`, plus up to 50,000 tombstones under `"retired"`. Generated HTML is
  **not** committed — `publish-site` rebuilds it.
- `posted.json` is `{sku: ISO-8601 timestamp}`. The legacy `{sku: true}` form still loads — those
  entries are read as "posted just now" and rewritten with a real stamp by `prune_posted`, so an
  upgrade never re-floods the channel.
- The save step runs `if: always()` and `main.run` writes state in a `finally` block, so a crash
  partway through posting cannot cause every deal in that run to be sent twice.
- The workflow has a `concurrency` group. Two overlapping runs would both commit state and the loser
  would push a version that forgets what the other posted.

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
