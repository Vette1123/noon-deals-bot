# Monetization

Where the money actually comes from, what is already built, and what is left for a
human to do. Written 2026-07-28.

## The binding constraint

`@noon_hot_deals` had **11 subscribers** when this was written.

The scraper works, the links carry the affiliate UTMs, the coupon is valid, the deals
are ranked by expected earnings. None of that matters at 11 readers. 72 well-chosen
posts a day in front of 11 people is roughly EGP 0/day, and it would still be roughly
EGP 0/day if the commission rate doubled.

So the ranking below is not "best commission first". It is **"reaches more people
first"**, because reach is the multiplier on every other number.

## What is built

| Surface | Status | Earns via |
|---|---|---|
| Telegram channel | Live since 2026-03 | Affiliate UTMs + coupon `gado1996` |
| Telegram share button | Built 2026-07-28 | Forwards win subscribers, subscribers compound |
| Static SEO site | Built 2026-07-28 | Same affiliate links, but from Google traffic |
| RSS feed | Built 2026-07-28 | Syndication into aggregators and IFTTT-style reposters |
| Facebook Page crosspost | Built 2026-07-28, **needs credentials** | Same affiliate links, on the surface where Egypt shops |

### The static site is the important one

[site_builder.py](../site_builder.py) turns [deals.json](../deals.json) into a page per
deal, published to GitHub Pages by the `publish-site` job in
[bot.yml](../.github/workflows/bot.yml). It costs nothing to run and it does not need
a single subscriber: someone searching "سعر لابتوب لينوفو نون" can land on a deal page
and click the affiliate link. Every deal page carries `Product` structured data, so it
is eligible for price-and-rating rich results.

Realistically it takes 2 to 4 months before Google trusts a new domain enough to send
meaningful traffic. Starting it now is the whole point.

## What still needs a human

Ranked by expected return per hour of effort.

### 1. Distribution (nothing below this works without it)

- Post the channel link where Egyptian bargain hunters already are: Facebook buy/sell
  groups, university and neighbourhood groups, Reddit r/Egypt, Twitter/X.
- Cross-promote with other small Egyptian deal channels. Free, and the audiences
  overlap almost perfectly.
- Set a channel description, photo, and pinned "what this is" message. A bare channel
  converts visitors badly.

### 2. Turn on the Facebook Page crosspost

Facebook is where deal commerce in Egypt actually happens, and the code is already
written. Create a Page, then add two repository secrets:

- `FACEBOOK_PAGE_ID`
- `FACEBOOK_PAGE_TOKEN` (a long-lived Page access token with `pages_manage_posts`)

With those unset the bot skips Facebook entirely, so there is no risk in leaving it off.

### 3. Verify the affiliate IDs still credit

The UTMs in [telegram_poster.py](../telegram_poster.py) (`AFFc944753cc349` /
`C1000264L` / `CMP2ce0b63a6a1anoon`) were copied from the affiliate panel. noon rotates
these. Generate a fresh link in the panel, compare the parameters, and if they differ
set `NOON_AFFILIATE_MEDIUM` / `_SOURCE` / `_CAMPAIGN` as repository secrets. Every hour
the IDs are stale is unpaid traffic.

### 4. Compare regional networks against the direct rate

noon's direct program pays roughly $1.50 per order, or a category percentage up to
about 10%. Regional networks sometimes carry noon at better terms and add other
merchants on the same account:

- [Boostiny](https://boostiny.com/)
- [ArabClicks](https://www.arabclicks.com/influencers/)

Worth doing once there is real order volume to negotiate with, not before.

### 5. Telegram ad revenue sharing

Telegram pays channel owners up to 50% of the revenue from ads shown in their channel,
in TON via Fragment. The gate is **1,000+ subscribers**. It is passive money on top of
affiliate income, so it is a reason to treat item 1 as the priority, not a separate
project.

### 6. A second merchant: Amazon.eg

There is an old design doc for this at
[2026-03-04-amazon-support-design.md](plans/2026-03-04-amazon-support-design.md), but it
is out of date in two ways that matter:

- Amazon's Egypt Associates program is effectively invite-based rather than open signup.
- The Product Advertising API was deprecated on 15 May 2026 in favour of the Creators
  API, so the fetching approach in that doc no longer applies.

Do not start this before items 1 to 3 are done.

### 7. Sponsored posts

Once the channel is a few thousand subscribers, Egyptian sellers will pay directly for
placement. This is usually the highest revenue per post of anything on this list, and it
is entirely gated behind audience size.

## What not to do

- **Do not buy subscribers.** Bot subscribers do not click, they wreck the engagement
  ratio that Telegram's ad revenue share is calculated on, and they can get a channel
  restricted.
- **Do not raise `MAX_POSTS_PER_RUN` to "reach more people".** It was 50 (300 posts a
  day) and that is what makes readers mute a channel. See the channel-economics section
  in [CLAUDE.md](../CLAUDE.md).
- **Do not drop the affiliate disclosure** from the site footer, and do not restyle the
  site to look like noon. Passing for the merchant is what gets an affiliate account
  terminated.
