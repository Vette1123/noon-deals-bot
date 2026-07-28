# Monetization

Where the money actually comes from, what is already built, and what is left for a
human to do. Rewritten 2026-07-28 after reading the affiliate panel directly —
most of the earlier version was guesswork, and some of it was wrong.

## The two constraints

**1. `@noon_hot_deals` had 11 subscribers.** 72 well-chosen posts a day in front of
11 people is roughly EGP 0/day, and it would still be roughly EGP 0/day if the
commission rate doubled. Reach is the multiplier on every other number here.

**2. Commission is capped at AED 50 per item** (~EGP 700). This is the number that
should drive every decision about *what* gets posted, and it was not known when the
filters were first written.

## What the panel actually pays

Everyday Campaign, read from the panel on 2026-07-28:

| Rate | Categories |
|---|---|
| **10%** | apparel, footwear, bags & luggage, jewellery |
| **9%** | stationery & office supplies, eyewear, watches, books & media |
| **8%** | beauty (cosmetics, fragrance, hair & personal care), health & nutrition, toys, baby, sports & outdoor, automotive, small appliances, electronic personal care |
| **6%** | furniture, kitchen & dining, home improvement, home decor, bath & bedding |
| **5%** | grocery, large appliances |
| **4%** | laptop accessories, mobile accessories |
| **3%** | audio/video, headphones, wearables, cameras, **laptops**, consoles |
| **2%** | **mobiles** |

Read that bottom half again. **Electronics pay the worst rates on the board.** The
intuition that a deals channel should chase laptops and phones is exactly backwards:
a 12,000 EGP laptop pays 3% (EGP 360) while a 6,000 EGP fragrance set pays 8%
(EGP 480) — and the fragrance set is the cheaper thing to sell.

The cap then flattens the top. Past the price where `rate × price` reaches EGP 700,
a more expensive product pays nothing extra:

| Category | Rate | Price where the cap bites |
|---|---|---|
| Apparel | 10% | EGP 7,000 |
| Beauty / small appliances | 8% | EGP 8,750 |
| Kitchen & home | 6% | EGP 11,700 |
| Laptops | 3% | EGP 23,300 |
| Mobiles | 2% | EGP 35,000 |

So a 45,000 EGP television is worth precisely what a 23,000 EGP one is worth, and
less than a 9,000 EGP perfume. [filters.py](../filters.py) now ranks on
`min(cap, rate × price)` multiplied by conversion odds, instead of the old points
total that summed discount and price and got this backwards for months.

`COMMISSION_CAP_EGP` is an environment variable — update it when the EGP/AED rate
moves rather than editing code.

## What is built

| Surface | Status | Earns via |
|---|---|---|
| Telegram channel | Live since 2026-03 | Affiliate UTMs + coupon `gado` |
| Telegram share button | Built 2026-07-28 | Forwards win subscribers, subscribers compound |
| Static SEO site | Built 2026-07-28 | Same affiliate links, but from Google traffic |
| Category & brand hubs | Built 2026-07-28 | Long-tail queries the deal pages cannot win |
| Page-level share buttons | Built 2026-07-28 | WhatsApp forwarding, which is how Egypt shares |
| RSS feed | Built 2026-07-28 | Syndication into aggregators |
| Facebook Page crosspost | Built 2026-07-28, **needs credentials** | Same links, on the surface where Egypt shops |

### The static site is the important one

[site_builder.py](../site_builder.py) turns [deals.json](../deals.json) into a page
per deal, a hub per category and brand, a paginated archive, and the crawl files —
published to GitHub Pages by the `publish-site` job. It costs nothing to run and it
needs no subscribers: someone searching "سعر عطر ديور نون" lands on a deal page and
clicks the affiliate link.

Two things about it are load-bearing and easy to undo by accident:

- **Deal pages never 404.** A deal that ages out of the archive is not deleted, it
  becomes a `noindex` tombstone that links on to its hubs. Google takes two to four
  months to trust a new domain, so the original 30-day retention was deleting every
  page at roughly the moment it started to rank.
- **`priceValidUntil` is measured from when the deal was seen**, not from the build.
  Otherwise every rebuild re-certifies a months-old price as current, in a machine
  format Google trusts.

Realistically it is still 2 to 4 months before search traffic means anything.

## What still needs a human

Ranked by expected return per hour of effort.

### 1. Verify the affiliate link still credits — 15 minutes, do this first

On 2026-07-28 the `utm_medium` in this repo was `AFFc944753cc349`. The account's real
ID is **`AFFccacc092d97d`**. Every click the bot had ever sent was unattributed.

It is fixed now, but noon rotates these. To re-check: open the campaign in the panel,
*Links* tab, copy a link, open the short `s.noon.com/…` URL and read the query string
it lands on. Compare against `with_affiliate_utms` in
[telegram_poster.py](../telegram_poster.py). Overrides are `NOON_AFFILIATE_MEDIUM` /
`_SOURCE` / `_CAMPAIGN`.

Same trip, check the *Coupons* tab. `gado1996` was **not** a live coupon — the two
live ones are `gado` and `HZICP`. A reader who types a dead code at checkout gets an
error, which costs the coupon attribution channel and the channel's credibility.

### 2. Google Search Console + Bing Webmaster Tools — 15 minutes

Add the site, verify it, submit `sitemap.xml`. A new site nobody links to can sit
uncrawled for months. This is the cheapest item on the list and nothing downstream
happens without it.

### 3. Buy a domain — 20 minutes, and it gets more expensive to delay

`vette1123.github.io/noon-deals-bot` is a path on somebody else's domain. Authority
built there does not move with you, and migrating later resets the clock. Buy one,
point the DNS at Pages, and set the `SITE_DOMAIN` repository variable — the build
writes the CNAME and rewrites every absolute URL.

### 4. Distribution

Nothing above the site works without it.

- Post the channel where Egyptian bargain hunters already are: Facebook buy/sell
  groups, university and neighbourhood groups, r/Egypt.
- Cross-promote with other small Egyptian deal channels. Free, overlapping audiences.
- Set a channel description, photo and pinned "what this is" message.

### 5. Turn on the Facebook Page crosspost

Create a Page, add `FACEBOOK_PAGE_ID` and `FACEBOOK_PAGE_TOKEN` (long-lived, with
`pages_manage_posts`). Unset, the bot skips Facebook entirely, so leaving it off
costs nothing but earns nothing.

### 6. Compare regional networks against the direct rate

[Boostiny](https://boostiny.com/) and [ArabClicks](https://www.arabclicks.com/influencers/)
sometimes carry noon at better terms and add other merchants on one account. Worth
doing once there is order volume to negotiate with, not before.

### 7. Telegram ad revenue sharing

Up to 50% of ad revenue, paid in TON via Fragment. Gate is **1,000+ subscribers**.
Passive income on top of affiliate, which is a reason to treat distribution as the
priority rather than a separate project.

### 8. Sponsored posts

Egyptian sellers pay directly for placement once a channel is a few thousand strong.
Highest revenue per post of anything here, entirely gated behind audience size.

## What not to do

- **Do not chase expensive electronics.** 2–3% against a cap is the worst square on
  the board. The scorer already knows this; do not "fix" it by re-adding a raw price
  bonus.
- **Do not buy subscribers.** They do not click, they wreck the engagement ratio the
  ad revenue share is calculated on, and they can get a channel restricted.
- **Do not raise `MAX_POSTS_PER_RUN` to reach more people.** It was 50 (300 posts a
  day) and that is what makes readers mute a channel. If you want more pages, raise
  `SITE_DEALS_PER_RUN` instead — that feeds the site without touching notifications.
- **Do not delete deal pages to keep the repo small.** Retire them. A URL that took
  four months to rank is the one asset here that cannot be rebuilt.
- **Do not drop the affiliate disclosure** from the site footer, and do not restyle
  the site to look like noon. Passing for the merchant is what gets an affiliate
  account terminated.
