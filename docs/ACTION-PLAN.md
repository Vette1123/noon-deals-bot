# Action plan

Things only a human can do. The code side is done; none of this is blocked on more
development.

Written 2026-07-28. [MONETIZATION.md](MONETIZATION.md) explains *why* each of these
matters — this file is just the doing. Tick items off as you go.

---

## Now (about 90 minutes total, in this order)

### 1. Google Search Console — 15 min

- [ ] Open https://search.google.com/search-console
- [ ] *Add property* → **URL prefix** → `https://vette1123.github.io/noon-deals-bot/`
- [ ] Verify with the **HTML tag** method. It gives you a
      `<meta name="google-site-verification" content="…">` tag — send me the content
      value and I will add it to the site's `<head>`, or paste it into `_page()` in
      [site_builder.py](../site_builder.py) yourself.
- [ ] *Sitemaps* → submit `sitemap.xml`
- [ ] Same again at https://www.bing.com/webmasters (Bing lets you import straight
      from Search Console, so it takes about two minutes)

**Why first:** a new site nobody links to can sit uncrawled for months. Everything
else on this list is worth less until crawling starts.

**How you know it worked:** *Pages* report shows indexed URLs climbing over the next
2–6 weeks. Do not expect traffic before ~3 months.

### 2. Buy a domain — 20 min, and delaying costs you

- [ ] Register something short and Arabic-market obvious. `.com` is fine;
      `.com.eg` needs local paperwork, skip it.
- [ ] At the registrar, add these DNS records:
      - `A` → `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`
      - `CNAME` for `www` → `vette1123.github.io`
- [ ] GitHub → repo *Settings* → *Secrets and variables* → *Actions* → **Variables**
      → new variable `SITE_DOMAIN` = your domain (no `https://`, no trailing slash)
- [ ] Run the workflow once. The build writes the `CNAME` file and rewrites every
      absolute URL.
- [ ] GitHub → *Settings* → *Pages* → tick **Enforce HTTPS** once the cert issues
      (can take up to 24h)

**Why now and not later:** authority built on `vette1123.github.io/noon-deals-bot`
is on somebody else's domain and does not move with you. Migrating after the site
ranks resets the clock. This is the only item that gets **more expensive the longer
you wait** — do it before item 1 starts paying off, not after.

> If you do this *before* Search Console, register the domain first and add the
> custom domain as the Search Console property instead. Saves doing it twice.

### 3. Facebook Page — 30 min

- [ ] Create a Facebook Page for the deals brand
- [ ] Get a **long-lived Page access token** with `pages_manage_posts` via
      https://developers.facebook.com/tools/explorer
- [ ] Add two repository **secrets**: `FACEBOOK_PAGE_ID`, `FACEBOOK_PAGE_TOKEN`
- [ ] Run the workflow and check the Page

The code is written and idle. Unset, it is a no-op — there is no risk in leaving it
off, and no work left to turn it on.

### 4. Distribution — ongoing, the real bottleneck

11 subscribers is the ceiling on everything except the site.

- [ ] Set the channel description, photo, and a pinned "what this is" message
- [ ] Post the channel in Egyptian Facebook buy/sell groups
- [ ] Post in university and neighbourhood groups
- [ ] r/Egypt
- [ ] Message 5–10 other small Egyptian deal channels about cross-promotion — free,
      and the audiences overlap almost perfectly

Do **not** buy subscribers. They do not click, they wreck the engagement ratio the
Telegram ad revenue share is calculated on, and they can get a channel restricted.

---

## Recurring

### Monthly: re-check the affiliate link still credits — 10 min

noon rotates these, and a stale ID means every click earns nothing while everything
looks fine.

- [ ] Panel → campaign → **Links** tab → *Copy link*
- [ ] Paste the `s.noon.com/…` short URL into a browser and look at where it lands
- [ ] Compare `utm_medium` / `utm_source` / `utm_campaign` against the defaults in
      `with_affiliate_utms` in [telegram_poster.py](../telegram_poster.py)

As of 2026-07-28 the correct values are:

```
utm_campaign=CMP2ce0b63a6a1anoon
utm_medium=AFFccacc092d97d
utm_source=C1000264L
adjust_deeplink_js=1
```

If they differ, set `NOON_AFFILIATE_MEDIUM` / `_SOURCE` / `_CAMPAIGN` as repository
secrets — do not edit code. The site re-stamps outbound links on every build, so one
secret change repairs every archived page on the next run.

### Monthly: check the coupon is still live — 2 min

- [ ] Panel → campaign → **Coupons** tab
- [ ] Confirm `gado` is still listed and active (the other live one is `HZICP`)
- [ ] If it dies, update the `NOON_COUPON_CODE` secret

A dead code at checkout costs the coupon attribution channel and the channel's
credibility. `gado1996` was dead and posted for months.

### Weekly: glance at the Actions tab

- [ ] Any red runs? A 0-product scrape fails loudly on purpose — it means noon
      changed its page format, which they do a few times a year.

---

## Later, gated on audience size

### At ~500+ subscribers: regional affiliate networks

- [ ] Compare [Boostiny](https://boostiny.com/) and
      [ArabClicks](https://www.arabclicks.com/influencers/) against the direct noon
      rate. They sometimes carry noon at better terms and add other merchants on one
      account.

Worth doing once there is order volume to negotiate with, not before.

### At 1,000+ subscribers: Telegram ad revenue share

- [ ] Enable it via Fragment. Up to 50% of ad revenue, paid in TON. Passive income on
      top of affiliate, which is the real reason distribution is the priority.

### At a few thousand subscribers: sponsored posts

- [ ] Egyptian sellers will pay directly for placement. Highest revenue per post of
      anything on this list, and entirely gated behind audience size.

### Someday: a second merchant

Amazon.eg is invite-based rather than open signup, and the Product Advertising API
was deprecated on 15 May 2026 in favour of the Creators API — so the old design doc
at [plans/2026-03-04-amazon-support-design.md](plans/2026-03-04-amazon-support-design.md)
no longer applies. Do not start this before everything under **Now** is done.

---

## Things not to do

- **Do not raise `MAX_POSTS_PER_RUN`** to reach more people. It was 50 (300 posts a
  day) and that is what makes readers mute a channel. If you want more pages, raise
  `SITE_DEALS_PER_RUN` — that feeds the site without touching notifications.
- **Do not chase expensive electronics.** 2–3% against a per-item cap is the worst
  square on the board.
- **Do not delete deal pages** to keep the repo small. They retire into tombstones on
  purpose. A URL that took four months to rank is the one asset here that cannot be
  rebuilt.
- **Do not remove the affiliate disclosure** from the footer, and do not restyle the
  site to look like noon. Passing for the merchant is an affiliate-account-termination
  risk.
