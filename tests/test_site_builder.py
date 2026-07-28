import json
import re
from datetime import datetime, timedelta, timezone

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
        "url": "https://www.noon.com/egypt-en/laptop/N1A/p/?utm_medium=AFFc944753cc349",
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
    assert "utm_medium=AFFc944753cc349" in page
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
    out, _ = _build([_deal("A1"), _deal("B2")], tmp_path)
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
    out, written = _build(_brand_deals("Rarebrand", 2), tmp_path)
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
