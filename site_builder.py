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
from urllib.parse import quote

from archive import ARCHIVE_FILE, load_archive, prune_archive
from categories import category_label

OUT_DIR = "public"
# A custom domain is worth buying *before* the site ranks: ranking earned on a
# github.io path cannot move with you, and a migration resets the clock. Setting
# this writes the CNAME file Pages needs and rewrites every absolute URL.
SITE_DOMAIN = os.environ.get("SITE_DOMAIN", "").strip().lower().lstrip(".")
_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
if SITE_DOMAIN and not _DOMAIN_RE.fullmatch(SITE_DOMAIN):
    # A malformed CNAME takes the whole site off the internet until someone
    # notices, so a bad value is ignored rather than published.
    print(f"Ignoring malformed SITE_DOMAIN: {SITE_DOMAIN!r}")
    SITE_DOMAIN = ""
SITE_BASE_URL = (
    f"https://{SITE_DOMAIN}" if SITE_DOMAIN
    else os.environ.get("SITE_BASE_URL", "https://vette1123.github.io/noon-deals-bot")
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
# Structured-data prices go stale as noon re-prices. A week from when the deal
# was *seen* — not from the build — or every rebuild would silently re-certify a
# six-month-old price as current, which is a lie told to Google in a machine
# format it trusts.
PRICE_VALID_DAYS = 7
# Past this, the page still earns (the affiliate link works, and "سعر X" is still
# the query that brought the reader) but it stops presenting the price as today's.
STALE_AFTER_DAYS = 14
# Deals per page in the paginated archive. Without it, every deal below the first
# 96 is reachable only from sitemap.xml, and a page nothing links to ranks like
# a page nothing links to.
DEALS_PER_PAGE = 60
MAX_ARCHIVE_PAGES = 250

_SKU_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")
# Two is enough for a hub to beat the deal pages it collects. At one it *is* one
# of them, competing with its own child for the same query.
MIN_DEALS_PER_BRAND = 2
MIN_DEALS_PER_CATEGORY = 3
INDEX_BRANDS = 24
BRAND_PAGE_DEALS = 96
CATEGORY_PAGE_DEALS = 96


# ── Formatting helpers ────────────────────────────────────────────────────────

def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _ltr(value) -> str:
    """Isolate a number, date or percentage inside an Arabic sentence.

    Without it bidi reorders the run against the surrounding text: `2026-07-28`
    renders as `28-07-2026`, and `خصم 53%` puts the percent sign on the wrong
    side of the digits. Both are wrong rather than merely ugly.
    """
    return f'<bdi dir="ltr">{_esc(value)}</bdi>'


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


def _category_index(deals: list[dict]) -> dict[str, dict]:
    """Categories worth their own page: {slug: {"name":…, "deals":[…]}}.

    "عروض العطور على نون مصر" is a query an Arabic shopper actually types. It is
    also the one page type that keeps working when a brand only ever has one deal.
    """
    groups: dict[str, dict] = {}
    for deal in deals:
        label = category_label(deal.get("category"))
        slug = _brand_slug(deal.get("category"))
        if not label or not slug or not _deal_path(deal):
            continue
        group = groups.setdefault(slug, {"name": label, "deals": []})
        group["deals"].append(deal)
    return {s: g for s, g in groups.items() if len(g["deals"]) >= MIN_DEALS_PER_CATEGORY}


def _is_stale(deal: dict, now: datetime) -> bool:
    return _parse_stamp(deal.get("posted_at"), now) < now - timedelta(days=STALE_AFTER_DAYS)


def _price_valid_until(deal: dict, now: datetime) -> str:
    seen = _parse_stamp(deal.get("posted_at"), now)
    return (seen + timedelta(days=PRICE_VALID_DAYS)).date().isoformat()


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

# Inline and first in <head>: it has to run before the page paints or a reader who
# picked light gets a dark flash on every navigation. Inline also means no extra
# request, which is the reason the rest of the site has no JavaScript at all.
_THEME_BOOT_JS = (
    "(function(){try{var t=localStorage.getItem('theme');"
    "if(t==='dark'||t==='light')document.documentElement.setAttribute('data-theme',t);}"
    "catch(e){}})();"
)

# Cycles device preference -> light -> dark. The button starts hidden and is only
# revealed here, so it never sits there dead when JavaScript is unavailable.
_THEME_TOGGLE_JS = (
    "(function(){var b=document.getElementById('theme-toggle');if(!b)return;"
    "var L={auto:'تلقائي',light:'فاتح',dark:'داكن'},order=['auto','light','dark'];"
    "function cur(){try{return localStorage.getItem('theme')||'auto';}catch(e){return 'auto';}}"
    "function paint(m){b.textContent='المظهر: '+L[m];}"
    "function apply(m){var r=document.documentElement;"
    "if(m==='auto'){r.removeAttribute('data-theme');}else{r.setAttribute('data-theme',m);}"
    "try{if(m==='auto'){localStorage.removeItem('theme');}else{localStorage.setItem('theme',m);}}"
    "catch(e){}paint(m);}"
    "b.hidden=false;paint(cur());"
    "b.addEventListener('click',function(){apply(order[(order.indexOf(cur())+1)%3]);});})();"
)

_CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#f4f6f8; --surface:#fff; --line:#e2e6ea; --ink:#14181c; --muted:#5c6670;
  --accent:#c81e4a; --accent-ink:#fff; --accent-soft:#fdeaef;
  --radius:14px; --shadow:0 1px 2px rgba(20,24,28,.06),0 8px 24px rgba(20,24,28,.05);
}
/* Dark tokens live in one place and are applied two ways: by the device
   preference unless the reader has explicitly chosen light, or by an explicit
   choice stored in localStorage. `data-theme` always wins over the device. */
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#101315; --surface:#181c20; --line:#272d33; --ink:#eef1f4; --muted:#9aa4ad;
    --accent:#ff5c7f; --accent-ink:#1a0a10; --accent-soft:#2a1219;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
  }
}
:root[data-theme="dark"]{
  --bg:#101315; --surface:#181c20; --line:#272d33; --ink:#eef1f4; --muted:#9aa4ad;
  --accent:#ff5c7f; --accent-ink:#1a0a10; --accent-soft:#2a1219;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
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
.theme{background:transparent;color:var(--muted);border:1px solid var(--line);
  border-radius:999px;padding:9px 16px;font:inherit;font-size:14px;font-weight:600;
  cursor:pointer;transition:border-color .15s ease,color .15s ease}
.theme:hover{border-color:var(--accent);color:var(--accent)}
.theme:active{transform:translateY(1px)}
.actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
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
/* The count is a separate fact from the name, so it reads as a separate object.
   Same weight and colour as the label made it look like part of the brand. */
.pill span{display:inline-block;min-width:24px;margin-inline-start:7px;
  padding:1px 7px;border-radius:999px;background:var(--accent-soft);
  color:var(--accent);font-weight:700;font-size:12px;line-height:1.6;
  text-align:center;font-variant-numeric:tabular-nums}
.pill:hover span{background:var(--accent);color:var(--accent-ink)}
.buy{margin:20px 0 10px;display:flex;gap:10px;flex-wrap:wrap}
.buy .cta{padding:13px 28px;font-size:16px}
.coupon{margin:14px 0;font-size:14px}
.coupon code{background:var(--accent-soft);color:var(--accent);font-weight:700;
  padding:4px 10px;border-radius:8px;font-size:15px;letter-spacing:.04em}
.caveat{color:var(--muted);font-size:13px;margin:14px 0 0}
.notice{border:1px solid var(--line);border-inline-start:3px solid var(--accent);
  background:var(--surface);border-radius:var(--radius);padding:12px 14px;margin:0 0 16px;
  font-size:14px}
.notice strong{color:var(--accent)}
.share{margin:18px 0 0;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.share span{color:var(--muted);font-size:13px}
.share a{border:1px solid var(--line);background:var(--surface);border-radius:999px;
  padding:6px 14px;font-size:13.5px;font-weight:600;
  transition:border-color .15s ease,color .15s ease}
.share a:hover{border-color:var(--accent);color:var(--accent)}
.pager{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:center;
  padding-block:26px;font-size:14px}
.pager a,.pager strong{border:1px solid var(--line);background:var(--surface);
  border-radius:10px;padding:7px 14px;font-variant-numeric:tabular-nums}
.pager strong{border-color:var(--accent);color:var(--accent)}
.pager a:hover{border-color:var(--accent);color:var(--accent)}
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


_ROBOTS_INDEX = "index,follow,max-image-preview:large,max-snippet:-1"
# A tombstone has no price, no picture and nothing to say. It exists so an old
# link does not 404. `follow` still passes its equity on to the hubs it links to.
_ROBOTS_TOMBSTONE = "noindex,follow"


def _page(*, title: str, description: str, canonical: str, body: str,
          depth: int, og_image: str = "", extra_head: str = "",
          og_type: str = "website", robots: str = _ROBOTS_INDEX) -> str:
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
<script>{_THEME_BOOT_JS}</script>
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description)}">
<link rel="canonical" href="{_esc(canonical)}">
<link rel="alternate" hreflang="ar-eg" href="{_esc(canonical)}">
<!-- max-image-preview:large is what makes these eligible for full-size thumbnails
     in Google results and Discover, which is most of the click-through. -->
<meta name="robots" content="{_esc(robots)}">
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
  <div class="actions">
    <button type="button" id="theme-toggle" class="theme" hidden>المظهر: تلقائي</button>
    {subscribe}
  </div>
</div></header>
{body}
<footer><div class="wrap">
  <p>{_esc(SITE_NAME)} موقع مستقل وغير تابع لنون. الروابط هنا روابط تسويق بالعمولة،
  وقد نحصل على عمولة عند الشراء من خلالها دون أي تكلفة إضافية عليك.
  الأسعار تتغير باستمرار، والسعر المعتمد هو المعروض على نون وقت الشراء.</p>
  {subscribe_ghost}
</div></footer>
<script>{_THEME_TOGGLE_JS}</script>
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

def _hub_links_html(kind: str, groups: dict[str, dict], limit: int,
                    all_label: str = "") -> str:
    """Pill links to hub pages, biggest first, with a link to the full list."""
    ranked = sorted(groups.items(), key=lambda kv: len(kv[1]["deals"]), reverse=True)
    pills = "".join(
        f'<a class="pill" href="{kind}/{_esc(slug)}.html">'
        f'{_esc(group["name"])} <span>{len(group["deals"])}</span></a>'
        for slug, group in ranked[:limit]
    )
    if all_label and len(ranked) > limit:
        pills += f'<a class="pill" href="{kind}/index.html">{_esc(all_label)}</a>'
    return f'<nav class="pills">{pills}</nav>'


def _hub_rank(now: datetime):
    """Live deals before dead ones, deepest discount first within each."""
    return lambda d: (not _is_stale(d, now), d.get("discount_pct") or 0)


def _hub_html(kind: str, slug: str, group: dict, now: datetime, limit: int) -> str:
    """A hub page per brand or per category.

    This is where the long-tail traffic lands: "عروض samsung نون" and
    "عروض عطور نون" are queries someone types. "عروض نون" is a fight with noon.
    """
    name = group["name"]
    canonical = f"{SITE_BASE_URL}/{kind}/{slug}.html"
    deals = sorted(group["deals"], key=_hub_rank(now), reverse=True)[:limit]
    cards = "\n".join(
        _card(d, f"../{_deal_path(d)}", eager=(i < 4)) for i, d in enumerate(deals)
    )
    best = deals[0].get("discount_pct", 0)
    body = f"""<nav class="wrap crumbs"><a href="../index.html">الرئيسية</a> ‹ {_esc(name)}</nav>
<main class="wrap">
  <section>
    <h1>عروض وخصومات {_esc(name)} على نون مصر</h1>
    <p class="updated"><span>{len(deals)} عرض</span><span>أعلى خصم {_ltr(str(best) + "%")}</span></p>
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


def _directory_html(kind: str, groups: dict[str, dict], title: str,
                    description: str, heading: str) -> str:
    """One page listing every hub of a kind.

    Without it the brands below the front page's top 24 are reachable only from
    sitemap.xml, and a hub nothing links to collects no authority to pass on.
    """
    canonical = f"{SITE_BASE_URL}/{kind}/index.html"
    ranked = sorted(groups.items(), key=lambda kv: len(kv[1]["deals"]), reverse=True)
    pills = "".join(
        f'<a class="pill" href="{_esc(slug)}.html">{_esc(group["name"])} '
        f'<span>{len(group["deals"])}</span></a>'
        for slug, group in ranked
    )
    body = f"""<nav class="wrap crumbs"><a href="../index.html">الرئيسية</a> ‹ {_esc(heading)}</nav>
<main class="wrap">
  <section>
    <h1>{_esc(heading)}</h1>
    <p class="updated"><span>{len(ranked)} صفحة</span></p>
  </section>
  <section><nav class="pills">{pills}</nav></section>
</main>"""
    return _page(title=f"{title} | {SITE_NAME}", description=description,
                 canonical=canonical, body=body, depth=1)


def _tombstone_html(entry: dict, now: datetime, brand_slug: str = "",
                    category_slug: str = "") -> str:
    """The page an expired deal leaves behind.

    Its whole job is to not be a 404. GitHub Pages cannot serve a redirect or a
    410, so a URL that once ranked and then vanished from the archive would hand
    every visitor and every crawler a dead end. This hands them the hubs instead,
    and stays out of the index because there is nothing here worth indexing.
    """
    canonical = f"{SITE_BASE_URL}/{_deal_path(entry)}"
    posted = _day(entry.get("posted_at"), now)
    links = ['<a href="../index.html">أحدث عروض نون مصر</a>']
    if category_slug:
        links.append(
            f'<a href="../cat/{_esc(category_slug)}.html">'
            f'{_esc(category_label(entry.get("category")))}</a>'
        )
    if brand_slug and entry.get("brand"):
        links.append(f'<a href="../brands/{_esc(brand_slug)}.html">'
                     f'عروض {_esc(entry["brand"])}</a>')
    body = f"""<nav class="wrap crumbs"><a href="../index.html">الرئيسية</a> ‹ {_esc(_title(entry))}</nav>
<main class="wrap">
  <section>
    <h1>{_esc(_title(entry))}</h1>
    <p class="notice"><strong>انتهى هذا العرض.</strong>
    رُصد يوم <time datetime="{_esc(posted)}">{_ltr(posted)}</time> ولم نعد نتابع سعره.</p>
    <p class="more">{" · ".join(links)}</p>
  </section>
</main>"""
    return _page(
        title=f"{_title(entry)} | {SITE_NAME}",
        description=f"{_title(entry)} — انتهى هذا العرض على نون مصر.",
        canonical=canonical, body=body, depth=1, robots=_ROBOTS_TOMBSTONE,
    )


def _pager_html(current: int, total: int, home: str, page_fmt: str) -> str:
    """Numbered links between archive pages.

    Page 1 *is* the front page, so it is linked by `home` rather than by a
    number; `page_fmt` addresses the rest relative to whoever is rendering.
    """
    if total < 2:
        return ""
    def href(n: int) -> str:
        return home if n == 1 else page_fmt.format(n=n)
    parts = []
    if current > 1:
        parts.append(f'<a rel="prev" href="{href(current - 1)}">السابق</a>')
    for n in range(1, total + 1):
        # Every page links to its neighbours and to the ends; a 250-page strip of
        # numbers would be more markup than content on a phone.
        if n in (1, total) or abs(n - current) <= 2:
            parts.append(f"<strong>{n}</strong>" if n == current
                         else f'<a href="{href(n)}">{n}</a>')
    if current < total:
        parts.append(f'<a rel="next" href="{href(current + 1)}">التالي</a>')
    return f'<nav class="pager">{"".join(parts)}</nav>'


def _archive_page_html(page: int, total: int, deals: list[tuple[dict, str]],
                       now: datetime) -> str:
    canonical = f"{SITE_BASE_URL}/archive/{page}.html"
    cards = "\n".join(_card(d, f"../{p}", eager=(i < 4))
                      for i, (d, p) in enumerate(deals))
    body = f"""<nav class="wrap crumbs"><a href="../index.html">الرئيسية</a> ‹ صفحة {page}</nav>
<main class="wrap">
  <section>
    <h1>عروض نون مصر — صفحة {page} من {total}</h1>
  </section>
  <section><div class="grid">{cards}</div></section>
</main>
<div class="wrap">{_pager_html(page, total, "../index.html", "{n}.html")}</div>"""
    return _page(
        title=f"عروض وخصومات نون مصر — صفحة {page} | {SITE_NAME}",
        description=f"الصفحة {page} من أرشيف عروض نون مصر، {len(deals)} عرض.",
        canonical=canonical, body=body, depth=1,
        og_image=next((d.get("image_url") for d, _ in deals if d.get("image_url")), ""),
    )


def _index_html(deals: list[dict], now: datetime, total_pages: int = 1) -> str:
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
        f'<span>آخر تحديث: {_ltr(now.strftime("%Y-%m-%d %H:%M"))} بتوقيت جرينتش</span></p>'
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
    cats = _category_index(deals)
    if cats:
        parts.append(
            '<section><h2>تصفح حسب القسم</h2>'
            f'{_hub_links_html("cat", cats, INDEX_BRANDS, "كل الأقسام")}</section>'
        )
    brands = _brand_index(deals)
    if brands:
        parts.append(
            '<section><h2>تصفح حسب الماركة</h2>'
            f'{_hub_links_html("brands", brands, INDEX_BRANDS, "كل الماركات")}</section>'
        )
    if rest:
        cards = "\n".join(_card(d, p, eager=False) for d, p in rest)
        parts.append(f'<section><h2>أحدث العروض</h2><div class="grid">{cards}</div></section>')
    parts.append("</main>")
    if total_pages > 1:
        pager = _pager_html(1, total_pages, "index.html", "archive/{n}.html")
        parts.append(f'<div class="wrap">{pager}</div>')

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
            "priceValidUntil": _price_valid_until(deal, now),
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


def _share_html(deal: dict, canonical: str) -> str:
    """Share the page, not the product link.

    A WhatsApp group that receives a noon URL produces one order. The same group
    given this page produces the order *and* a handful of readers who come back
    for the next deal. WhatsApp leads because that is where Egypt forwards things.
    """
    text = quote(f"{_title(deal)} بخصم {deal.get('discount_pct', 0)}% على نون مصر", safe="")
    url = quote(canonical, safe="")
    targets = (
        ("واتساب", f"https://wa.me/?text={text}%20{url}"),
        ("تيليجرام", f"https://t.me/share/url?url={url}&text={text}"),
        ("فيسبوك", f"https://www.facebook.com/sharer/sharer.php?u={url}"),
    )
    links = "".join(
        f'<a href="{_esc(href)}" rel="noopener nofollow" target="_blank">{name}</a>'
        for name, href in targets
    )
    return f'<div class="share"><span>شارك العرض:</span>{links}</div>'


def _deal_html(deal: dict, related: list[tuple[dict, str]], now: datetime,
               coupon: str = "", brand_slug: str = "", category_slug: str = "") -> str:
    canonical = f"{SITE_BASE_URL}/{_deal_path(deal)}"
    stale = _is_stale(deal, now)
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
    crumbs_html = ['<a href="../index.html">الرئيسية</a> ‹ ']
    more_links = []
    if category_slug:
        href = f"../cat/{_esc(category_slug)}.html"
        label = _esc(category_label(deal.get("category")))
        crumbs_html.append(f'<a href="{href}">{label}</a> ‹ ')
        more_links.append(f'<a href="{href}">كل عروض {label}</a>')
    if brand_slug and deal.get("brand"):
        href = f"../brands/{_esc(brand_slug)}.html"
        crumbs_html.append(f'<a href="{href}">{_esc(deal["brand"])}</a> ‹ ')
        more_links.append(f'<a href="{href}">كل عروض {_esc(deal["brand"])}</a>')
    more_html = (
        '<p class="more">' + " · ".join(more_links) + "</p>" if more_links else ""
    )

    # A stale page keeps earning — the affiliate link still works and "سعر س" is
    # still what brought the reader — but it stops presenting a month-old number
    # as today's price.
    if stale:
        notice = (
            '<p class="notice"><strong>انتهى هذا العرض غالبًا.</strong> '
            f'السعر بالأسفل هو السعر وقت رصد العرض يوم {_ltr(posted)}. '
            'اضغط الزر لمعرفة السعر الحالي على نون.</p>'
        )
        buy_label = "شوف السعر الحالي على نون"
        caveat = (
            f'<p class="caveat">رُصد هذا العرض يوم <time datetime="{_esc(posted)}">'
            f'{_ltr(posted)}</time> ولم يعد محدَّثًا.</p>'
        )
    else:
        notice = ""
        buy_label = "اشتري الآن من نون"
        caveat = (
            f'<p class="caveat">رُصد هذا العرض يوم <time datetime="{_esc(posted)}">'
            f'{_ltr(posted)}</time>. نون تغيّر أسعارها باستمرار، فتأكد من السعر في '
            'صفحة المنتج قبل إتمام الشراء.</p>'
        )

    body = f"""<nav class="wrap crumbs">{"".join(crumbs_html)}{_esc(_title(deal))}</nav>
<main class="wrap detail">
  {shot}
  <div>
    <h1>{_esc(_title(deal))}</h1>
    {notice}
    <div class="pricebox">
      <span class="now">{_money(deal.get('sale_price'))} ج.م</span>
      <span class="was">{_money(deal.get('original_price'))} ج.م</span>
      <span class="save">وفّر {_money(saved)} ج.م</span>
      <span class="save">خصم {_ltr(str(deal.get('discount_pct', 0)) + "%")}</span>
    </div>
    {facts_html}
    {coupon_html}
    <div class="buy"><a class="cta" href="{_esc(deal.get('url', ''))}"
      rel="nofollow sponsored noopener" target="_blank">{buy_label}</a></div>
    {caveat}
    {more_html}
    {_share_html(deal, canonical)}
  </div>
</main>
{related_html}"""

    ld = _ld_json(_product_ld(deal, canonical, now))
    trail = [{"@type": "ListItem", "position": 1, "name": "الرئيسية",
              "item": f"{SITE_BASE_URL}/"}]
    if category_slug:
        trail.append({"@type": "ListItem", "position": len(trail) + 1,
                      "name": category_label(deal.get("category")),
                      "item": f"{SITE_BASE_URL}/cat/{category_slug}.html"})
    if brand_slug and deal.get("brand"):
        trail.append({"@type": "ListItem", "position": len(trail) + 1,
                      "name": deal["brand"],
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


def _related_picker(linkable: list[tuple[dict, str]], now: datetime):
    """Pick fresh deals to show alongside another one.

    Deliberately not "the next few entries in the archive": a two-month-old page
    surrounded by two-month-old deals is a dead end, and dead ends are where the
    search traffic this whole site exists to collect stops being worth anything.
    Same category first, then anything current.
    """
    fresh = [(d, p) for d, p in linkable if not _is_stale(d, now)]
    fresh.sort(key=lambda dp: dp[0].get("discount_pct") or 0, reverse=True)
    by_category: dict[str, list[tuple[dict, str]]] = {}
    for pair in fresh:
        by_category.setdefault(_brand_slug(pair[0].get("category")), []).append(pair)

    def pick(deal: dict) -> list[tuple[dict, str]]:
        sku = deal.get("sku")
        chosen: list[tuple[dict, str]] = []
        seen: set = {sku}
        for pool in (by_category.get(_brand_slug(deal.get("category")), []), fresh):
            for candidate, path in pool:
                if len(chosen) >= RELATED_DEALS:
                    return chosen
                if candidate.get("sku") in seen:
                    continue
                seen.add(candidate.get("sku"))
                chosen.append((candidate, path))
        return chosen

    return pick


def build_site(archive: dict, out_dir: str = OUT_DIR, now: datetime | None = None,
               coupon: str = "") -> list[str]:
    """Render the archive into `out_dir`. Returns the site-relative paths written."""
    now = now or datetime.now(timezone.utc)
    deals = archive.get("deals", [])
    linkable = [(d, _deal_path(d)) for d in deals]
    linkable = [(d, p) for d, p in linkable if p]

    pages = [linkable[i:i + DEALS_PER_PAGE] for i in range(0, len(linkable), DEALS_PER_PAGE)]
    total_pages = min(len(pages), MAX_ARCHIVE_PAGES) or 1

    written = ["index.html", "robots.txt", "sitemap.xml", "feed.xml", ".nojekyll"]
    _write(out_dir, "index.html", _index_html(deals, now, total_pages))
    _write(out_dir, "robots.txt", _robots_txt())
    _write(out_dir, "feed.xml", _feed_xml(linkable, now))
    # Pages is a static host with no server config, so this is the only way to
    # stop Jekyll from swallowing the generated files.
    _write(out_dir, ".nojekyll", "")
    if SITE_DOMAIN:
        _write(out_dir, "CNAME", f"{SITE_DOMAIN}\n")
        written.append("CNAME")

    hubs: list[tuple[str, str]] = []
    brands = _brand_index(deals)
    cats = _category_index(deals)
    for kind, groups, limit in (
        ("brands", brands, BRAND_PAGE_DEALS),
        ("cat", cats, CATEGORY_PAGE_DEALS),
    ):
        for slug, group in groups.items():
            path = f"{kind}/{slug}.html"
            _write(out_dir, path, _hub_html(kind, slug, group, now, limit))
            written.append(path)
            hubs.append((path, now.date().isoformat()))

    if brands:
        _write(out_dir, "brands/index.html", _directory_html(
            "brands", brands, "كل ماركات عروض نون مصر",
            "كل الماركات التي رصدنا لها عروضًا على نون مصر.", "كل الماركات"))
        written.append("brands/index.html")
        hubs.append(("brands/index.html", now.date().isoformat()))
    if cats:
        _write(out_dir, "cat/index.html", _directory_html(
            "cat", cats, "كل أقسام عروض نون مصر",
            "كل أقسام المنتجات التي رصدنا لها عروضًا على نون مصر.", "كل الأقسام"))
        written.append("cat/index.html")
        hubs.append(("cat/index.html", now.date().isoformat()))

    # Page 1 is the front page, so only 2..N are written out.
    for number in range(2, total_pages + 1):
        path = f"archive/{number}.html"
        _write(out_dir, path, _archive_page_html(number, total_pages, pages[number - 1], now))
        written.append(path)
        hubs.append((path, now.date().isoformat()))

    pick_related = _related_picker(linkable, now)
    for deal, path in linkable:
        brand = _brand_slug(deal.get("brand"))
        category = _brand_slug(deal.get("category"))
        _write(out_dir, path, _deal_html(
            deal, pick_related(deal), now, coupon=coupon,
            brand_slug=brand if brand in brands else "",
            category_slug=category if category in cats else "",
        ))
        written.append(path)

    # Tombstones last, and never over a live page: a SKU that came back is a
    # real deal again, and `prune_archive` already keeps the two sets disjoint.
    live_paths = {p for _, p in linkable}
    for entry in archive.get("retired", []):
        path = _deal_path(entry)
        if not path or path in live_paths:
            continue
        brand = _brand_slug(entry.get("brand"))
        category = _brand_slug(entry.get("category"))
        _write(out_dir, path, _tombstone_html(
            entry, now,
            brand_slug=brand if brand in brands else "",
            category_slug=category if category in cats else "",
        ))
        written.append(path)

    # Tombstones are deliberately absent: they are noindex, and asking a crawler
    # to spend its budget on pages we told it to ignore is how the real pages
    # get crawled less often.
    sitemap = [("", now.date().isoformat())]
    sitemap += hubs
    sitemap += [(p, _day(d.get("posted_at"), now)) for d, p in linkable]
    _write(out_dir, "sitemap.xml", _sitemap_xml(sitemap))
    return written


if __name__ == "__main__":
    built = build_site(
        prune_archive(load_archive(ARCHIVE_FILE)),
        coupon=os.environ.get("NOON_COUPON_CODE", "gado").strip(),
    )
    print(f"Built {len(built)} files into {OUT_DIR}/ for {SITE_BASE_URL}")
