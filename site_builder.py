"""Static site generator for the deal archive.

A Telegram post earns from whoever scrolls past in the next hour. A page that
ranks for "خصم لابتوب نون" earns from everyone who searches for it, forever, and
needs no subscribers at all. This turns [deals.json](deals.json) into that page.

Design notes (they are load-bearing, not decoration):
- **No framework, no web fonts, no JavaScript.** Search traffic lands on mobile
  data in Egypt. Every byte is LCP, and LCP is ranking. The Arabic type comes
  from the system stack, so it costs zero requests.
- **RTL Arabic, one accent, one radius scale, light and dark via
  `prefers-color-scheme`.**
- **Not a noon lookalike.** The palette deliberately avoids noon's yellow and the
  footer states this is an independent affiliate site. Passing for the merchant
  would be dishonest and would put the affiliate account at risk.
"""

import html
import json
import os
import re
from datetime import datetime, timedelta, timezone

from archive import ARCHIVE_FILE, load_archive, prune_archive

OUT_DIR = "public"
SITE_BASE_URL = os.environ.get(
    "SITE_BASE_URL", "https://vette1123.github.io/noon-deals-bot"
).rstrip("/")
SITE_NAME = os.environ.get("SITE_NAME", "ديلز مصر")
CHANNEL_HANDLE = os.environ.get("TELEGRAM_CHANNEL_ID", "@noon_hot_deals").strip().lstrip("@")
# Only a public @handle has a t.me page. A numeric chat ID would render a dead
# link on every page of the site, which is worse than showing no button.
_CHANNEL_URL = (
    f"https://t.me/{CHANNEL_HANDLE}"
    if re.fullmatch(r"[A-Za-z0-9_]{5,32}", CHANNEL_HANDLE) else ""
)

# How many deals the front page carries. The rest stay reachable through
# sitemap.xml — Google indexes them, the reader is not asked to scroll 2,000 cards.
INDEX_DEALS = 96
# Four fills the spotlight row exactly at desktop width and splits 2x2 on a phone.
SPOTLIGHT_DEALS = 4
SPOTLIGHT_WINDOW_DAYS = 7
FEED_ITEMS = 40
RELATED_DEALS = 4
# Structured-data prices go stale as noon re-prices. A week is honest and keeps
# rich results from advertising a price the merchant no longer offers.
PRICE_VALID_DAYS = 7

_SKU_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")
# A brand needs a few deals before its own page is worth more than a thin-content
# penalty. Below this the brand simply has no hub.
MIN_DEALS_PER_BRAND = 3
INDEX_BRANDS = 24


# ── Formatting helpers ────────────────────────────────────────────────────────

def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _money(value) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "0"


def _ld_json(data: dict) -> str:
    """JSON-LD that is safe to inline in a `<script>` tag.

    Product names come from marketplace sellers, so one of them will eventually
    contain `</script>`. `html.escape` cannot be used here (it would corrupt the
    JSON), but escaping the three characters as `\\uXXXX` is valid JSON and
    cannot close the tag.
    """
    blob = json.dumps(data, ensure_ascii=False)
    return blob.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _parse_stamp(value, fallback: datetime) -> datetime:
    if not isinstance(value, str):
        return fallback
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return fallback


def _day(value, fallback: datetime) -> str:
    return _parse_stamp(value, fallback).date().isoformat()


def _deal_path(deal: dict) -> str:
    """Site-relative path for a deal, or "" when the SKU is not filename-safe."""
    sku = deal.get("sku") or ""
    if not _SKU_RE.fullmatch(sku):
        return ""
    return f"deals/{sku}.html"


def _brand_slug(brand) -> str:
    """A filename-safe slug, or "" when the brand has nothing latin to slug.

    Arabic-only brand names would percent-encode into unreadable URLs, and an
    unreadable URL is a worse landing page than no page at all.
    """
    slug = _SLUG_STRIP_RE.sub("-", str(brand or "").lower()).strip("-")
    return slug[:60]


def _brand_index(deals: list[dict]) -> dict[str, dict]:
    """Brands worth their own page: {slug: {"name":…, "deals":[…]}}."""
    groups: dict[str, dict] = {}
    for deal in deals:
        slug = _brand_slug(deal.get("brand"))
        if not slug or not _deal_path(deal):
            continue
        group = groups.setdefault(slug, {"name": deal["brand"], "deals": []})
        group["deals"].append(deal)
    return {s: g for s, g in groups.items() if len(g["deals"]) >= MIN_DEALS_PER_BRAND}


def _title(deal: dict) -> str:
    return (deal.get("name") or "منتج").strip()


def _summary(deal: dict) -> str:
    """The meta description. Reads as a sentence, carries the money words."""
    return (
        f"{_title(deal)} من نون مصر بسعر {_money(deal.get('sale_price'))} جنيه "
        f"بدلاً من {_money(deal.get('original_price'))} جنيه، "
        f"بخصم {deal.get('discount_pct', 0)}%."
    )


# ── Page chrome ───────────────────────────────────────────────────────────────

_CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#f4f6f8; --surface:#fff; --line:#e2e6ea; --ink:#14181c; --muted:#5c6670;
  --accent:#c81e4a; --accent-ink:#fff; --accent-soft:#fdeaef;
  --radius:14px; --shadow:0 1px 2px rgba(20,24,28,.06),0 8px 24px rgba(20,24,28,.05);
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#101315; --surface:#181c20; --line:#272d33; --ink:#eef1f4; --muted:#9aa4ad;
    --accent:#ff5c7f; --accent-ink:#1a0a10; --accent-soft:#2a1219;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
  }
}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--bg);color:var(--ink);
  font-family:"Noto Sans Arabic","IBM Plex Sans Arabic","Segoe UI",Tahoma,system-ui,sans-serif;
  line-height:1.6;font-size:16px;
}
a{color:inherit;text-decoration:none}
img{max-width:100%;display:block}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px}
.masthead{border-bottom:1px solid var(--line);background:var(--surface)}
.masthead .wrap{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:center;
  justify-content:space-between;padding-block:18px}
.brand{font-size:20px;font-weight:800;letter-spacing:-.01em;display:inline-block}
.brand span{color:var(--accent)}
.tagline{color:var(--muted);font-size:14px;margin:2px 0 0}
.cta{
  display:inline-block;background:var(--accent);color:var(--accent-ink);
  padding:10px 20px;border-radius:999px;font-weight:700;font-size:15px;
  transition:transform .15s ease,filter .15s ease;white-space:nowrap;
}
.cta:hover{filter:brightness(1.06)}
.cta:active{transform:translateY(1px)}
.cta.ghost{background:transparent;color:var(--accent);border:1.5px solid var(--accent)}
h1{font-size:clamp(22px,3.4vw,32px);line-height:1.25;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:19px;margin:0 0 14px;letter-spacing:-.01em}
section{padding-block:26px}
section:first-of-type{padding-block:26px 6px}
.updated{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums;
  display:flex;flex-wrap:wrap;gap:4px 18px;margin:0}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(168px,1fr))}
.grid.spotlight{grid-template-columns:repeat(auto-fill,minmax(232px,1fr))}
.card{
  background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  overflow:hidden;display:flex;flex-direction:column;
  transition:transform .15s ease,border-color .15s ease,box-shadow .15s ease;
}
.card:hover{transform:translateY(-2px);border-color:var(--accent);box-shadow:var(--shadow)}
.shot{position:relative;background:#fff}
.shot img{aspect-ratio:1;object-fit:contain;width:100%;padding:8px}
.noshot{display:block;aspect-ratio:1;background:var(--bg)}
.badge{
  position:absolute;inset-block-start:8px;inset-inline-start:8px;
  background:var(--accent);color:var(--accent-ink);font-weight:800;font-size:12px;
  padding:3px 9px;border-radius:999px;font-variant-numeric:tabular-nums;
}
.card-body{padding:10px 12px 12px;display:flex;flex-direction:column;gap:6px;flex:1}
.name{font-size:13.5px;font-weight:600;margin:0;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.spotlight .name{font-size:15px}
.price{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-top:auto;
  font-variant-numeric:tabular-nums}
.now{font-size:17px;font-weight:800}
.was{color:var(--muted);font-size:13px;text-decoration:line-through}
.seller{color:var(--muted);font-size:12px;margin:0;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.detail{display:grid;gap:28px;grid-template-columns:minmax(0,5fr) minmax(0,6fr);
  align-items:start;padding-block:28px}
.detail .shot{border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}
/* Capped, or a square product shot pushes the price and the buy button below
   the fold on a laptop. */
.detail .shot img{padding:16px;max-height:400px;margin-inline:auto}
.crumbs{font-size:13px;color:var(--muted);padding-top:18px}
.crumbs a:hover{color:var(--accent)}
.pricebox{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin:14px 0 6px;
  font-variant-numeric:tabular-nums}
.pricebox .now{font-size:30px;color:var(--accent)}
.pricebox .was{font-size:16px}
.save{background:var(--accent-soft);color:var(--accent);font-weight:700;font-size:13px;
  padding:3px 10px;border-radius:999px}
.facts{margin:18px 0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:8px}
.facts li{border:1px solid var(--line);border-radius:999px;padding:5px 12px;font-size:13px;
  color:var(--muted);background:var(--surface)}
.pills{display:flex;flex-wrap:wrap;gap:8px}
.pill{border:1px solid var(--line);background:var(--surface);border-radius:999px;
  padding:7px 14px;font-size:14px;font-weight:600;
  transition:border-color .15s ease,color .15s ease}
.pill:hover{border-color:var(--accent);color:var(--accent)}
.pill span{color:var(--muted);font-weight:500;font-size:12.5px;
  font-variant-numeric:tabular-nums}
.buy{margin:20px 0 10px;display:flex;gap:10px;flex-wrap:wrap}
.buy .cta{padding:13px 28px;font-size:16px}
.coupon{margin:14px 0;font-size:14px}
.coupon code{background:var(--accent-soft);color:var(--accent);font-weight:700;
  padding:4px 10px;border-radius:8px;font-size:15px;letter-spacing:.04em}
.caveat{color:var(--muted);font-size:13px;margin:14px 0 0}
.more{margin:14px 0 0;font-size:14px;font-weight:600}
.more a{color:var(--accent);border-bottom:1px solid transparent}
.more a:hover{border-bottom-color:var(--accent)}
footer{border-top:1px solid var(--line);background:var(--surface);margin-top:24px}
footer .wrap{padding-block:24px;color:var(--muted);font-size:13px;display:flex;
  flex-wrap:wrap;gap:10px 24px;align-items:center;justify-content:space-between}
footer p{margin:0;max-width:62ch}
.empty{text-align:center;color:var(--muted);padding:56px 0}
@media (max-width:760px){
  .detail{grid-template-columns:1fr;gap:18px}
  .masthead .wrap{padding-block:14px}
  /* Two per row, spotlight included. Most of this traffic is a phone, and one
     card per screenful means the reader sees one deal before deciding to leave. */
  .grid,.grid.spotlight{grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
}
@media (prefers-reduced-motion:reduce){
  *{transition:none!important}
}
"""


def _page(*, title: str, description: str, canonical: str, body: str,
          depth: int, og_image: str = "", extra_head: str = "",
          og_type: str = "website") -> str:
    """One complete HTML document. `depth` is how many folders deep the page is."""
    up = "../" * depth
    og = (
        f'\n<meta property="og:image" content="{_esc(og_image)}">'
        f'\n<meta property="og:image:alt" content="{_esc(title)}">'
        if og_image else ""
    )
    subscribe = (
        f'<a class="cta" href="{_esc(_CHANNEL_URL)}">اشترك في القناة</a>'
        if _CHANNEL_URL else ""
    )
    subscribe_ghost = subscribe.replace('class="cta"', 'class="cta ghost"')
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description)}">
<link rel="canonical" href="{_esc(canonical)}">
<link rel="alternate" hreflang="ar-eg" href="{_esc(canonical)}">
<!-- max-image-preview:large is what makes these eligible for full-size thumbnails
     in Google results and Discover, which is most of the click-through. -->
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<meta name="theme-color" content="#f4f6f8" media="(prefers-color-scheme:light)">
<meta name="theme-color" content="#101315" media="(prefers-color-scheme:dark)">
<meta property="og:type" content="{_esc(og_type)}">
<meta property="og:site_name" content="{_esc(SITE_NAME)}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(description)}">
<meta property="og:url" content="{_esc(canonical)}">
<meta property="og:locale" content="ar_EG">{og}
<meta name="twitter:card" content="summary_large_image">
<!-- Every product image is served from noon's CDN; the handshake is on the LCP path. -->
<link rel="preconnect" href="https://f.nooncdn.com" crossorigin>
<link rel="dns-prefetch" href="https://f.nooncdn.com">
<link rel="alternate" type="application/rss+xml" title="{_esc(SITE_NAME)}" href="{up}feed.xml">
<style>{_CSS}</style>{extra_head}
</head>
<body>
<header class="masthead"><div class="wrap">
  <div>
    <a class="brand" href="{up}index.html">ديلز <span>مصر</span></a>
    <p class="tagline">أقوى خصومات نون مصر، مُحدَّثة كل ٤ ساعات</p>
  </div>
  {subscribe}
</div></header>
{body}
<footer><div class="wrap">
  <p>{_esc(SITE_NAME)} موقع مستقل وغير تابع لنون. الروابط هنا روابط تسويق بالعمولة،
  وقد نحصل على عمولة عند الشراء من خلالها دون أي تكلفة إضافية عليك.
  الأسعار تتغير باستمرار، والسعر المعتمد هو المعروض على نون وقت الشراء.</p>
  {subscribe_ghost}
</div></footer>
</body>
</html>
"""


def _card(deal: dict, href: str, eager: bool) -> str:
    loading = 'loading="eager" fetchpriority="high"' if eager else 'loading="lazy"'
    image = deal.get("image_url")
    # An <img src=""> makes the browser re-request the page itself, so a deal
    # without a picture gets a shaped blank instead.
    shot = (
        f'<img src="{_esc(image)}" alt="{_esc(_title(deal))}" {loading} decoding="async">'
        if image else '<span class="noshot"></span>'
    )
    seller = deal.get("store_name") or deal.get("brand") or ""
    seller_html = f'<p class="seller">{_esc(seller)}</p>' if seller else ""
    return f"""<a class="card" href="{_esc(href)}">
  <div class="shot"><span class="badge">{_esc(deal.get('discount_pct', 0))}%</span>{shot}</div>
  <div class="card-body">
    <p class="name">{_esc(_title(deal))}</p>
    {seller_html}
    <p class="price"><span class="now">{_money(deal.get('sale_price'))} ج.م</span>
      <span class="was">{_money(deal.get('original_price'))}</span></p>
  </div>
</a>"""


# ── Pages ─────────────────────────────────────────────────────────────────────

def _brand_links_html(brands: dict[str, dict], prefix: str = "") -> str:
    """Pill links to the brand hubs, biggest first."""
    ranked = sorted(brands.items(), key=lambda kv: len(kv[1]["deals"]), reverse=True)
    pills = "".join(
        f'<a class="pill" href="{prefix}brands/{_esc(slug)}.html">'
        f'{_esc(group["name"])} <span>{len(group["deals"])}</span></a>'
        for slug, group in ranked[:INDEX_BRANDS]
    )
    return f'<nav class="pills">{pills}</nav>'


def _brand_html(slug: str, group: dict, now: datetime) -> str:
    """A hub page per brand. This is where the long-tail search traffic lands:
    "عروض samsung نون" is a query, "عروض نون" is a fight with noon itself."""
    name = group["name"]
    canonical = f"{SITE_BASE_URL}/brands/{slug}.html"
    deals = sorted(group["deals"], key=lambda d: d.get("discount_pct") or 0, reverse=True)
    cards = "\n".join(
        _card(d, f"../{_deal_path(d)}", eager=(i < 4)) for i, d in enumerate(deals)
    )
    best = deals[0].get("discount_pct", 0)
    body = f"""<nav class="wrap crumbs"><a href="../index.html">الرئيسية</a> ‹ {_esc(name)}</nav>
<main class="wrap">
  <section>
    <h1>عروض وخصومات {_esc(name)} على نون مصر</h1>
    <p class="updated"><span>{len(deals)} عرض</span><span>أعلى خصم {_esc(best)}%</span></p>
  </section>
  <section><div class="grid">{cards}</div></section>
</main>"""
    ld = _ld_json({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": f"عروض {name} على نون مصر",
        "url": canonical,
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": len(deals),
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1,
                 "url": f"{SITE_BASE_URL}/{_deal_path(d)}", "name": _title(d)}
                for i, d in enumerate(deals[:30])
            ],
        },
    })
    return _page(
        title=f"عروض وخصومات {name} على نون مصر | {SITE_NAME}",
        description=(
            f"{len(deals)} عرض على منتجات {name} من نون مصر، أعلى خصم {best}%. "
            "الأسعار قبل وبعد الخصم محدّثة يوميًا."
        ),
        canonical=canonical,
        body=body,
        depth=1,
        og_image=next((d.get("image_url") for d in deals if d.get("image_url")), ""),
        extra_head=f'\n<script type="application/ld+json">{ld}</script>',
    )


def _index_html(deals: list[dict], now: datetime) -> str:
    linkable = [(d, _deal_path(d)) for d in deals]
    linkable = [(d, p) for d, p in linkable if p]

    recent_cutoff = now - timedelta(days=SPOTLIGHT_WINDOW_DAYS)
    recent = [
        (d, p) for d, p in linkable
        if _parse_stamp(d.get("posted_at"), now) > recent_cutoff
    ]
    recent.sort(key=lambda dp: dp[0].get("discount_pct") or 0, reverse=True)
    spotlight = recent[:SPOTLIGHT_DEALS]
    spotlight_skus = {d.get("sku") for d, _ in spotlight}
    rest = [(d, p) for d, p in linkable if d.get("sku") not in spotlight_skus][:INDEX_DEALS]

    if not linkable:
        body = '<div class="wrap"><p class="empty">لا توجد عروض منشورة بعد.</p></div>'
        return _page(
            title=f"عروض وخصومات نون مصر اليوم | {SITE_NAME}",
            description="أقوى خصومات نون مصر، محدّثة يوميًا.",
            canonical=f"{SITE_BASE_URL}/", body=body, depth=0,
        )

    parts = ['<main class="wrap">']
    parts.append(
        '<section>'
        '<h1>أقوى عروض وخصومات نون مصر اليوم</h1>'
        # Two spans, not one line with a separator: a middle dot between an Arabic
        # phrase and a timestamp reorders unpredictably under bidi.
        f'<p class="updated"><span>{len(linkable)} عرض</span>'
        f'<span>آخر تحديث: {_esc(now.strftime("%Y-%m-%d %H:%M"))} بتوقيت جرينتش</span></p>'
        '</section>'
    )
    if spotlight:
        cards = "\n".join(
            _card(d, p, eager=(i < 3)) for i, (d, p) in enumerate(spotlight)
        )
        parts.append(
            f'<section><h2>أكبر خصومات هذا الأسبوع</h2>'
            f'<div class="grid spotlight">{cards}</div></section>'
        )
    brands = _brand_index(deals)
    if brands:
        parts.append(
            f'<section><h2>تصفح حسب الماركة</h2>{_brand_links_html(brands)}</section>'
        )
    if rest:
        cards = "\n".join(_card(d, p, eager=False) for d, p in rest)
        parts.append(f'<section><h2>أحدث العروض</h2><div class="grid">{cards}</div></section>')
    parts.append("</main>")

    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"عروض نون مصر - {SITE_NAME}",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "url": f"{SITE_BASE_URL}/{path}",
                "name": _title(deal),
            }
            for i, (deal, path) in enumerate((spotlight + rest)[:30])
        ],
    }
    site_ld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": SITE_NAME,
        "url": f"{SITE_BASE_URL}/",
        "inLanguage": "ar-EG",
        "description": "أقوى خصومات نون مصر، محدّثة يوميًا.",
    }
    return _page(
        title=f"عروض وخصومات نون مصر اليوم | {SITE_NAME}",
        description=(
            "أقوى خصومات نون مصر محدّثة كل بضع ساعات: أسعار قبل وبعد الخصم، "
            "نسبة التخفيض، وكود خصم إضافي عند الدفع."
        ),
        canonical=f"{SITE_BASE_URL}/",
        body="\n".join(parts),
        depth=0,
        og_image=next((d.get("image_url") for d, _ in spotlight + rest if d.get("image_url")), ""),
        extra_head=(
            f'\n<script type="application/ld+json">{_ld_json(site_ld)}</script>'
            f'\n<script type="application/ld+json">{_ld_json(item_list)}</script>'
        ),
    )


def _product_ld(deal: dict, canonical: str, now: datetime) -> dict:
    ld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": _title(deal),
        "sku": deal.get("sku"),
        "offers": {
            "@type": "Offer",
            "url": deal.get("url") or canonical,
            "priceCurrency": "EGP",
            "price": f"{float(deal.get('sale_price') or 0):.2f}",
            "availability": "https://schema.org/InStock",
            "priceValidUntil": (now + timedelta(days=PRICE_VALID_DAYS)).date().isoformat(),
        },
    }
    if deal.get("image_url"):
        ld["image"] = [deal["image_url"]]
    if deal.get("brand"):
        ld["brand"] = {"@type": "Brand", "name": deal["brand"]}
    if deal.get("store_name"):
        ld["offers"]["seller"] = {"@type": "Organization", "name": deal["store_name"]}
    # Only when noon actually reported one. Inventing ratings is how a site gets
    # its rich results pulled, and it is a lie to the reader.
    if deal.get("rating") and (deal.get("rating_count") or 0) > 0:
        ld["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": str(deal["rating"]),
            "reviewCount": str(deal["rating_count"]),
        }
    return ld


def _deal_html(deal: dict, related: list[tuple[dict, str]], now: datetime,
               coupon: str = "", brand_slug: str = "") -> str:
    canonical = f"{SITE_BASE_URL}/{_deal_path(deal)}"
    saved = (deal.get("original_price") or 0) - (deal.get("sale_price") or 0)
    image = deal.get("image_url")
    shot = (
        f'<div class="shot"><img src="{_esc(image)}" alt="{_esc(_title(deal))}" '
        f'fetchpriority="high" decoding="async"></div>'
        if image else ""
    )

    facts = []
    if deal.get("store_name"):
        facts.append(f"البائع: {deal['store_name']}")
    if deal.get("brand"):
        facts.append(f"الماركة: {deal['brand']}")
    if deal.get("rating") and deal.get("rating_count"):
        facts.append(f"التقييم: {deal['rating']}/5 من {deal['rating_count']} تقييم")
    if deal.get("fulfilled_by_noon"):
        facts.append("شحن نون")
    if deal.get("free_delivery"):
        facts.append("توصيل مجاني")
    if deal.get("is_bestseller"):
        facts.append("الأكثر مبيعًا")
    facts_html = (
        "<ul class=\"facts\">" + "".join(f"<li>{_esc(f)}</li>" for f in facts) + "</ul>"
        if facts else ""
    )

    coupon_html = ""
    if coupon and re.fullmatch(r"[A-Za-z0-9_-]+", coupon):
        coupon_html = (
            f'<p class="coupon">كود خصم إضافي عند الدفع: <code>{_esc(coupon)}</code></p>'
        )

    related_html = ""
    if related:
        cards = "\n".join(_card(d, f"../{p}", eager=False) for d, p in related)
        related_html = (
            f'<section class="wrap"><h2>عروض أخرى قد تعجبك</h2>'
            f'<div class="grid">{cards}</div></section>'
        )

    posted = _day(deal.get("posted_at"), now)
    brand_link = ""
    crumb_brand = ""
    if brand_slug and deal.get("brand"):
        href = f"../brands/{_esc(brand_slug)}.html"
        brand_link = f'<p class="more"><a href="{href}">كل عروض {_esc(deal["brand"])}</a></p>'
        crumb_brand = f'<a href="{href}">{_esc(deal["brand"])}</a> ‹ '

    body = f"""<nav class="wrap crumbs"><a href="../index.html">الرئيسية</a> ‹ {crumb_brand}{_esc(_title(deal))}</nav>
<main class="wrap detail">
  {shot}
  <div>
    <h1>{_esc(_title(deal))}</h1>
    <div class="pricebox">
      <span class="now">{_money(deal.get('sale_price'))} ج.م</span>
      <span class="was">{_money(deal.get('original_price'))} ج.م</span>
      <span class="save">وفّر {_money(saved)} ج.م</span>
      <span class="save">خصم {_esc(deal.get('discount_pct', 0))}%</span>
    </div>
    {facts_html}
    {coupon_html}
    <div class="buy"><a class="cta" href="{_esc(deal.get('url', ''))}"
      rel="nofollow sponsored noopener" target="_blank">اشتري الآن من نون</a></div>
    <p class="caveat">رُصد هذا العرض يوم <time datetime="{_esc(posted)}">{_esc(posted)}</time>.
    نون تغيّر أسعارها باستمرار، فتأكد من السعر في صفحة المنتج قبل إتمام الشراء.</p>
    {brand_link}
  </div>
</main>
{related_html}"""

    ld = _ld_json(_product_ld(deal, canonical, now))
    trail = [{"@type": "ListItem", "position": 1, "name": "الرئيسية",
              "item": f"{SITE_BASE_URL}/"}]
    if brand_slug and deal.get("brand"):
        trail.append({"@type": "ListItem", "position": 2, "name": deal["brand"],
                      "item": f"{SITE_BASE_URL}/brands/{brand_slug}.html"})
    trail.append({"@type": "ListItem", "position": len(trail) + 1,
                  "name": _title(deal), "item": canonical})
    crumbs = _ld_json({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": trail,
    })
    return _page(
        title=f"{_title(deal)} بخصم {deal.get('discount_pct', 0)}% على نون مصر | {SITE_NAME}",
        description=_summary(deal),
        canonical=canonical,
        body=body,
        depth=1,
        og_image=image or "",
        og_type="product",
        extra_head=(
            f'\n<meta property="product:price:amount" content="{_esc(deal.get("sale_price") or 0)}">'
            '\n<meta property="product:price:currency" content="EGP">'
            f'\n<script type="application/ld+json">{ld}</script>'
            f'\n<script type="application/ld+json">{crumbs}</script>'
        ),
    )


# ── Feeds and crawl files ─────────────────────────────────────────────────────

def _sitemap_xml(paths: list[tuple[str, str]]) -> str:
    urls = "".join(
        f"<url><loc>{_esc(SITE_BASE_URL)}/{_esc(path)}</loc>"
        f"<lastmod>{_esc(lastmod)}</lastmod></url>"
        for path, lastmod in paths
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>\n"
    )


def _robots_txt() -> str:
    return f"User-agent: *\nAllow: /\nSitemap: {SITE_BASE_URL}/sitemap.xml\n"


def _feed_xml(deals: list[tuple[dict, str]], now: datetime) -> str:
    stamp = now.strftime("%a, %d %b %Y %H:%M:%S +0000")
    items = "".join(
        f"<item><title>{_esc(_title(d))} بخصم {_esc(d.get('discount_pct', 0))}%</title>"
        f"<link>{_esc(SITE_BASE_URL)}/{_esc(p)}</link>"
        f"<guid isPermaLink=\"true\">{_esc(SITE_BASE_URL)}/{_esc(p)}</guid>"
        f"<description>{_esc(_summary(d))}</description>"
        f"<pubDate>{_esc(_parse_stamp(d.get('posted_at'), now).strftime('%a, %d %b %Y %H:%M:%S +0000'))}</pubDate>"
        "</item>"
        for d, p in deals[:FEED_ITEMS]
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        f"<title>{_esc(SITE_NAME)}</title>"
        f"<link>{_esc(SITE_BASE_URL)}/</link>"
        "<description>أقوى خصومات نون مصر، محدّثة يوميًا.</description>"
        "<language>ar-eg</language>"
        f"<lastBuildDate>{_esc(stamp)}</lastBuildDate>"
        f"{items}</channel></rss>\n"
    )


# ── Build ─────────────────────────────────────────────────────────────────────

def _write(out_dir: str, path: str, content: str) -> None:
    full = os.path.join(out_dir, path.replace("/", os.sep))
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


def build_site(archive: dict, out_dir: str = OUT_DIR, now: datetime | None = None,
               coupon: str = "") -> list[str]:
    """Render the archive into `out_dir`. Returns the site-relative paths written."""
    now = now or datetime.now(timezone.utc)
    deals = archive.get("deals", [])
    linkable = [(d, _deal_path(d)) for d in deals]
    linkable = [(d, p) for d, p in linkable if p]

    written = ["index.html", "robots.txt", "sitemap.xml", "feed.xml", ".nojekyll"]
    _write(out_dir, "index.html", _index_html(deals, now))
    _write(out_dir, "robots.txt", _robots_txt())
    _write(out_dir, "feed.xml", _feed_xml(linkable, now))
    # Pages is a static host with no server config, so this is the only way to
    # stop Jekyll from swallowing the generated files.
    _write(out_dir, ".nojekyll", "")

    brands = _brand_index(deals)
    for slug, group in brands.items():
        path = f"brands/{slug}.html"
        _write(out_dir, path, _brand_html(slug, group, now))
        written.append(path)

    for i, (deal, path) in enumerate(linkable):
        related = [dp for dp in linkable[i + 1: i + 1 + RELATED_DEALS]]
        slug = _brand_slug(deal.get("brand"))
        _write(out_dir, path, _deal_html(
            deal, related, now, coupon=coupon,
            brand_slug=slug if slug in brands else "",
        ))
        written.append(path)

    sitemap = [("", now.date().isoformat())]
    sitemap += [(f"brands/{slug}.html", now.date().isoformat()) for slug in brands]
    sitemap += [(p, _day(d.get("posted_at"), now)) for d, p in linkable]
    _write(out_dir, "sitemap.xml", _sitemap_xml(sitemap))
    return written


if __name__ == "__main__":
    built = build_site(
        prune_archive(load_archive(ARCHIVE_FILE)),
        coupon=os.environ.get("NOON_COUPON_CODE", "gado1996").strip(),
    )
    print(f"Built {len(built)} files into {OUT_DIR}/ for {SITE_BASE_URL}")
