import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import site_builder
from site_builder import build_site

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _deal(sku="N1A", **overrides):
    d = {
        "sku": sku,
        "name": "لابتوب Lenovo IdeaPad 3",
        "brand": "Lenovo",
        "store_name": "Tech Store",
        "image_url": "https://f.nooncdn.com/p/pnsku/x.jpg",
        "url": "https://www.noon.com/egypt-en/laptop/N1A/p/?utm_medium=AFFccacc092d97d",
        "sale_price": 12500.0,
        "original_price": 18000.0,
        "discount_pct": 31,
        "rating": 4.4,
        "rating_count": 210,
        "posted_at": NOW.isoformat(),
    }
    d.update(overrides)
    return d


def _build(deals, tmp_path, **kwargs):
    out = tmp_path / "public"
    written = build_site({"deals": deals}, str(out), now=NOW, **kwargs)
    return out, written


def _read(out, path):
    return (out / path).read_text(encoding="utf-8")


def test_builds_index_deal_page_and_crawl_files(tmp_path):
    out, written = _build([_deal()], tmp_path)
    for path in ("index.html", "deals/N1A.html", "sitemap.xml", "robots.txt", "feed.xml"):
        assert (out / path).exists(), path
        assert path in written
    # Pages would otherwise run the output through Jekyll and drop files.
    assert (out / ".nojekyll").exists()


def test_deal_page_links_out_with_the_affiliate_url(tmp_path):
    out, _ = _build([_deal()], tmp_path)
    page = _read(out, "deals/N1A.html")
    assert "utm_medium=AFFccacc092d97d" in page
    # Paid links must be declared, or the site is a search-spam target.
    assert 'rel="nofollow sponsored noopener"' in page


def test_deal_page_carries_product_structured_data(tmp_path):
    out, _ = _build([_deal()], tmp_path)
    blobs = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>',
        _read(out, "deals/N1A.html"), re.S,
    )
    product = next(json.loads(b) for b in blobs if json.loads(b)["@type"] == "Product")
    assert product["offers"]["price"] == "12500.00"
    assert product["offers"]["priceCurrency"] == "EGP"
    assert product["offers"]["priceValidUntil"] > NOW.date().isoformat()
    assert product["aggregateRating"]["reviewCount"] == "210"
    assert any(json.loads(b)["@type"] == "BreadcrumbList" for b in blobs)


def test_unrated_products_claim_no_rating(tmp_path):
    # Inventing an aggregateRating is how a site loses its rich results.
    out, _ = _build([_deal(rating=None, rating_count=None)], tmp_path)
    blob = re.search(
        r'<script type="application/ld\+json">(.*?)</script>',
        _read(out, "deals/N1A.html"), re.S,
    ).group(1)
    assert "aggregateRating" not in json.loads(blob)


def test_pages_are_rtl_arabic_and_self_contained(tmp_path):
    out, _ = _build([_deal()], tmp_path)
    page = _read(out, "index.html")
    assert '<html lang="ar" dir="rtl">' in page
    assert "<style>" in page
    # No web fonts, no scripts, no external CSS: search traffic arrives on mobile data.
    assert "<script src=" not in page
    assert "fonts.googleapis" not in page
    assert "stylesheet" not in page


def test_index_and_pages_declare_the_affiliate_relationship(tmp_path):
    out, _ = _build([_deal()], tmp_path)
    for path in ("index.html", "deals/N1A.html"):
        assert "روابط تسويق بالعمولة" in _read(out, path)
        assert "غير تابع لنون" in _read(out, path)


def _body(out, path):
    """Everything the reader sees. The head carries JSON-LD copies of the same
    URLs, which would make an ordering assertion meaningless."""
    return _read(out, path).split("</head>", 1)[1]


def test_index_leads_with_the_biggest_recent_discounts(tmp_path):
    deals = [
        _deal("SMALL", name="خصم صغير", discount_pct=26),
        _deal("HUGE", name="خصم ضخم", discount_pct=70),
    ]
    out, _ = _build(deals, tmp_path)
    body = _body(out, "index.html")
    assert body.index("deals/HUGE.html") < body.index("deals/SMALL.html")
    # Spotlit deals are not repeated further down the same page.
    assert body.count('href="deals/HUGE.html"') == 1


def test_stale_deals_do_not_reach_the_spotlight(tmp_path):
    old = _deal("OLD", discount_pct=80,
                posted_at=(NOW - timedelta(days=20)).isoformat())
    fresh = _deal("FRESH", discount_pct=30)
    out, _ = _build([fresh, old], tmp_path)
    body = _body(out, "index.html")
    assert body.index("أكبر خصومات هذا الأسبوع") < body.index("deals/FRESH.html")
    assert body.index("deals/FRESH.html") < body.index("deals/OLD.html")


def test_product_names_are_html_escaped(tmp_path):
    out, _ = _build([_deal(name='ماوس "Logitech" <b>Pro</b>')], tmp_path)
    page = _read(out, "deals/N1A.html")
    assert "<b>Pro</b>" not in page
    assert "&lt;b&gt;Pro&lt;/b&gt;" in page


def test_seller_supplied_names_cannot_break_out_of_the_json_ld_script(tmp_path):
    # Marketplace sellers write these names. One of them will try this eventually.
    out, _ = _build([_deal(name='مفك </script><script>alert(1)</script>')], tmp_path)
    page = _read(out, "deals/N1A.html")
    assert "<script>alert(1)" not in page
    blob = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', page, re.S,
    ).group(1)
    assert json.loads(blob)["name"].startswith("مفك </script>")


def test_unsafe_skus_are_skipped_rather_than_written_outside_the_output(tmp_path):
    out, written = _build([_deal("../../etc/passwd"), _deal("OK")], tmp_path)
    assert written.count("deals/OK.html") == 1
    assert not any("passwd" in p for p in written)
    assert not (tmp_path / "etc").exists()


def test_sitemap_lists_the_home_page_and_every_deal(tmp_path):
    out, _ = _build([_deal("A1", brand=""), _deal("B2", brand="")], tmp_path)
    sitemap = _read(out, "sitemap.xml")
    assert f"<loc>{site_builder.SITE_BASE_URL}/</loc>" in sitemap
    assert f"<loc>{site_builder.SITE_BASE_URL}/deals/A1.html</loc>" in sitemap
    assert f"<loc>{site_builder.SITE_BASE_URL}/deals/B2.html</loc>" in sitemap
    assert sitemap.count("<url>") == 3


def test_robots_points_crawlers_at_the_sitemap(tmp_path):
    out, _ = _build([_deal()], tmp_path)
    assert f"Sitemap: {site_builder.SITE_BASE_URL}/sitemap.xml" in _read(out, "robots.txt")


def test_feed_carries_deals_with_absolute_links(tmp_path):
    out, _ = _build([_deal()], tmp_path)
    feed = _read(out, "feed.xml")
    assert f"{site_builder.SITE_BASE_URL}/deals/N1A.html" in feed
    assert "<language>ar-eg</language>" in feed


def test_coupon_is_shown_only_when_it_is_safe(tmp_path):
    out, _ = _build([_deal()], tmp_path, coupon="gado1996")
    assert "gado1996" in _read(out, "deals/N1A.html")
    out2, _ = _build([_deal()], tmp_path / "b", coupon="bad code!")
    assert "bad code!" not in _read(out2, "deals/N1A.html")


def test_empty_archive_still_produces_a_valid_site(tmp_path):
    out, written = _build([], tmp_path)
    assert "لا توجد عروض" in _read(out, "index.html")
    assert (out / "sitemap.xml").exists()
    assert written == ["index.html", "robots.txt", "sitemap.xml", "feed.xml", ".nojekyll"]


def _brand_deals(brand, n, start=0):
    return [
        _deal(f"{brand[:3].upper()}{i}", brand=brand, name=f"{brand} منتج {i}",
              discount_pct=30 + i)
        for i in range(start, start + n)
    ]


def test_brands_with_enough_deals_get_their_own_hub_page(tmp_path):
    # "عروض samsung نون" is a winnable query. "عروض نون" is a fight with noon.
    out, written = _build(_brand_deals("Samsung", 4), tmp_path)
    assert "brands/samsung.html" in written
    page = _read(out, "brands/samsung.html")
    assert "عروض وخصومات Samsung على نون مصر" in page
    assert page.count('class="card"') == 4


def test_thin_brands_get_no_page(tmp_path):
    # One deal is not a hub, it is the deal page again competing with itself.
    out, written = _build(_brand_deals("Rarebrand", 1), tmp_path)
    assert not any(p.startswith("brands/") for p in written)
    assert "brands/" not in _read(out, "index.html")


def test_deal_pages_link_up_to_their_brand_hub(tmp_path):
    out, _ = _build(_brand_deals("Samsung", 3), tmp_path)
    page = _read(out, "deals/SAM0.html")
    assert "../brands/samsung.html" in page
    trail = next(
        json.loads(b) for b in re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
        if json.loads(b)["@type"] == "BreadcrumbList"
    )
    assert [i["name"] for i in trail["itemListElement"]][1] == "Samsung"


def test_brand_hubs_are_listed_in_the_sitemap(tmp_path):
    out, _ = _build(_brand_deals("Samsung", 3), tmp_path)
    assert f"{site_builder.SITE_BASE_URL}/brands/samsung.html" in _read(out, "sitemap.xml")


def test_brands_that_slug_to_nothing_are_skipped(tmp_path):
    # An Arabic-only brand would percent-encode into an unreadable URL.
    out, written = _build(_brand_deals("ماركة", 4), tmp_path)
    assert not any(p.startswith("brands/") for p in written)


def test_deal_pages_declare_themselves_as_products(tmp_path):
    out, _ = _build([_deal()], tmp_path)
    page = _read(out, "deals/N1A.html")
    assert '<meta property="og:type" content="product">' in page
    assert '<meta property="product:price:currency" content="EGP">' in page
    assert '<meta name="robots" content="index,follow,max-image-preview:large' in page
    assert '<link rel="alternate" hreflang="ar-eg"' in page


def test_theme_follows_the_device_but_an_explicit_choice_wins(tmp_path):
    out, _ = _build([_deal()], tmp_path)
    page = _read(out, "index.html")
    # Device preference applies unless the reader has explicitly picked light.
    assert '@media (prefers-color-scheme:dark){\n  :root:not([data-theme="light"])' in page
    assert ':root[data-theme="dark"]{' in page


def test_theme_is_applied_before_paint_to_avoid_a_flash(tmp_path):
    out, _ = _build([_deal()], tmp_path)
    for path in ("index.html", "deals/N1A.html"):
        page = _read(out, path)
        head = page.split("</head>", 1)[0]
        assert "localStorage.getItem('theme')" in head
        # Still no external requests: the toggle is inline, not a bundle.
        assert "<script src=" not in page


def test_theme_toggle_is_hidden_until_javascript_reveals_it(tmp_path):
    out, _ = _build([_deal()], tmp_path)
    page = _read(out, "index.html")
    assert '<button type="button" id="theme-toggle" class="theme" hidden>' in page
    assert "b.hidden=false" in page


def test_missing_image_does_not_emit_an_empty_img_src(tmp_path):
    # <img src=""> makes the browser re-request the page itself.
    out, _ = _build([_deal(image_url=None)], tmp_path)
    page = _read(out, "index.html")
    assert 'src=""' not in page
    assert "noshot" in page


def test_subscribe_button_is_dropped_for_a_channel_with_no_public_link(tmp_path, monkeypatch):
    monkeypatch.setattr(site_builder, "_CHANNEL_URL", "")
    out, _ = _build([_deal()], tmp_path)
    page = _read(out, "index.html")
    assert "t.me/" not in page
    assert "اشترك في القناة" not in page


def test_no_em_dashes_reach_the_reader(tmp_path):
    out, written = _build([_deal()], tmp_path)
    for path in written:
        if path.endswith((".html", ".xml", ".txt")):
            assert "—" not in _read(out, path), path


# ── Deals that age out ────────────────────────────────────────────────────────

def _old(sku, days, **kw):
    return _deal(sku, posted_at=(NOW - timedelta(days=days)).isoformat(), **kw)


def test_a_stale_deal_stops_presenting_its_price_as_current(tmp_path):
    out, _ = _build([_old("N1A", site_builder.STALE_AFTER_DAYS + 1)], tmp_path)
    page = _read(out, "deals/N1A.html")
    assert "انتهى هذا العرض غالبًا" in page
    assert "شوف السعر الحالي على نون" in page
    # It still links out, and the link still carries the UTMs: a reader who
    # arrived from "سعر لابتوب لينوفو" is still worth sending to noon.
    assert "utm_medium=AFFccacc092d97d" in page


def test_a_fresh_deal_carries_no_expiry_notice(tmp_path):
    out, _ = _build([_deal()], tmp_path)
    page = _read(out, "deals/N1A.html")
    assert "انتهى هذا العرض" not in page
    assert "اشتري الآن من نون" in page


def test_price_validity_is_measured_from_when_the_deal_was_seen(tmp_path):
    # Not from the build. Otherwise every rebuild re-certifies a months-old price
    # as current, in a machine-readable format Google takes at face value.
    out, _ = _build([_old("N1A", 90)], tmp_path)
    blob = re.search(
        r'<script type="application/ld\+json">(.*?)</script>',
        _read(out, "deals/N1A.html"), re.S,
    ).group(1)
    valid_until = json.loads(blob)["offers"]["priceValidUntil"]
    assert valid_until < NOW.date().isoformat()


def test_retired_deals_keep_their_url_but_leave_the_index(tmp_path):
    archive = {"deals": [_deal("LIVE")],
               "retired": [{"sku": "GONE", "name": "منتج قديم", "brand": "Lenovo",
                            "posted_at": (NOW - timedelta(days=400)).isoformat()}]}
    out = tmp_path / "public"
    written = build_site(archive, str(out), now=NOW)
    assert "deals/GONE.html" in written
    page = (out / "deals/GONE.html").read_text(encoding="utf-8")
    assert "انتهى هذا العرض" in page
    assert '<meta name="robots" content="noindex,follow">' in page
    # Crawl budget spent on pages we told the crawler to ignore is crawl budget
    # not spent on the real ones.
    assert "deals/GONE.html" not in _read(out, "sitemap.xml")


def test_a_live_deal_is_never_overwritten_by_its_own_tombstone(tmp_path):
    archive = {"deals": [_deal("N1A")],
               "retired": [{"sku": "N1A", "name": "قديم",
                            "posted_at": (NOW - timedelta(days=400)).isoformat()}]}
    out = tmp_path / "public"
    build_site(archive, str(out), now=NOW)
    page = (out / "deals/N1A.html").read_text(encoding="utf-8")
    assert "اشتري الآن من نون" in page
    assert "noindex" not in page


# ── Category hubs ─────────────────────────────────────────────────────────────

def _cat_deals(code, n):
    return [_deal(f"C{i}", category=code, brand=f"Brand{i}", discount_pct=30 + i)
            for i in range(n)]


def test_categories_get_an_arabic_hub_page(tmp_path):
    out, written = _build(_cat_deals("beauty/fragrance", 4), tmp_path)
    assert "cat/beauty-fragrance.html" in written
    page = _read(out, "cat/beauty-fragrance.html")
    assert "عروض وخصومات عطور على نون مصر" in page
    assert page.count('class="card"') == 4


def test_categories_we_have_no_arabic_name_for_get_no_page(tmp_path):
    # A hub titled with a noon URL slug reads as machine output to a reader.
    out, written = _build(_cat_deals("some/unknown-code", 4), tmp_path)
    assert not any(p.startswith("cat/") for p in written)


def test_deal_pages_link_up_to_their_category(tmp_path):
    out, _ = _build(_cat_deals("beauty/fragrance", 3), tmp_path)
    page = _read(out, "deals/C0.html")
    assert "../cat/beauty-fragrance.html" in page
    trail = next(
        json.loads(b) for b in re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
        if json.loads(b)["@type"] == "BreadcrumbList"
    )
    assert [i["name"] for i in trail["itemListElement"]][1] == "عطور"


def test_every_hub_is_reachable_from_a_directory_page(tmp_path):
    deals = [d for i in range(30)
             for d in _brand_deals(f"Brand{i}", 2, start=i * 10)]
    out, written = _build(deals, tmp_path)
    assert "brands/index.html" in written
    directory = _read(out, "brands/index.html")
    # All 30, not just the 24 the front page has room for.
    assert directory.count('class="pill"') == 30
    assert "brands/index.html" in _read(out, "index.html")


# ── Pagination ────────────────────────────────────────────────────────────────

def test_deals_below_the_front_page_stay_reachable_by_crawling(tmp_path):
    deals = [_deal(f"P{i}", brand="") for i in range(site_builder.DEALS_PER_PAGE * 2 + 5)]
    out, written = _build(deals, tmp_path)
    assert "archive/2.html" in written
    assert "archive/3.html" in written
    assert 'href="archive/2.html"' in _read(out, "index.html")
    page2 = _read(out, "archive/2.html")
    assert 'rel="next"' in page2 and 'href="../index.html"' in page2
    assert f"{site_builder.SITE_BASE_URL}/archive/2.html" in _read(out, "sitemap.xml")


def test_a_single_page_of_deals_gets_no_pager(tmp_path):
    out, written = _build([_deal()], tmp_path)
    assert not any(p.startswith("archive/") for p in written)
    assert 'class="pager"' not in _read(out, "index.html")


# ── Related deals ─────────────────────────────────────────────────────────────

def test_related_deals_are_current_ones(tmp_path):
    # A dead page surrounded by dead pages is where the search traffic stops.
    deals = [_old("OLD", 200)] + [_deal(f"F{i}", category="beauty/fragrance") for i in range(4)]
    out, _ = _build(deals, tmp_path)
    related = _read(out, "deals/OLD.html").split("عروض أخرى قد تعجبك", 1)[1]
    assert "deals/F0.html" in related


# ── Custom domain ─────────────────────────────────────────────────────────────

def test_a_custom_domain_writes_a_cname_and_owns_every_url(tmp_path, monkeypatch):
    monkeypatch.setattr(site_builder, "SITE_DOMAIN", "deals-masr.com")
    monkeypatch.setattr(site_builder, "SITE_BASE_URL", "https://deals-masr.com")
    out, written = _build([_deal()], tmp_path)
    assert "CNAME" in written
    assert _read(out, "CNAME") == "deals-masr.com\n"
    assert "https://deals-masr.com/deals/N1A.html" in _read(out, "sitemap.xml")


# ── Sharing ───────────────────────────────────────────────────────────────────

def test_deal_pages_can_be_forwarded_to_a_whatsapp_group(tmp_path):
    out, _ = _build([_deal()], tmp_path)
    page = _read(out, "deals/N1A.html")
    assert "https://wa.me/?text=" in page
    # The page, not the product link: a group that gets this comes back.
    assert quote(f"{site_builder.SITE_BASE_URL}/deals/N1A.html", safe="") in page
