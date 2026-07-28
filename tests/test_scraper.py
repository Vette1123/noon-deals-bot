import json
import scraper
from scraper import _is_akamai_challenge, parse_products_from_html

MOCK_NEXT_DATA = {
    "props": {
        "pageProps": {
            "catalog": {
                "items": [
                    {
                        "name": "Samsung Galaxy A15",
                        "sku": "N12345678A",
                        "slug": "samsung-galaxy-a15",
                        "sale_price": 2999,
                        "price": 4000,
                        "image_keys": ["https://f.nooncdn.com/p/v1633090704/N12345678A_1.jpg"],
                        "discount": 25
                    },
                    {
                        "name": "Cheap Item",
                        "sku": "N99999999A",
                        "slug": "cheap-item",
                        "sale_price": 100,
                        "price": 110,
                        "image_keys": ["https://f.nooncdn.com/p/v1633090704/N99999999A_1.jpg"],
                        "discount": 9
                    }
                ]
            }
        }
    }
}

MOCK_HTML = f"""
<html><body>
<script id="__NEXT_DATA__" type="application/json">{json.dumps(MOCK_NEXT_DATA)}</script>
</body></html>
"""

def test_parse_products_extracts_fields():
    products = parse_products_from_html(MOCK_HTML)
    assert len(products) == 2
    p = products[0]
    assert p["name"] == "Samsung Galaxy A15"
    assert p["sale_price"] == 2999.0
    assert p["original_price"] == 4000.0
    assert p["discount_pct"] == 25
    assert "noon.com/egypt-en" in p["url"]
    assert p["image_url"].startswith("https://")

def test_parse_returns_empty_on_bad_html():
    products = parse_products_from_html("<html><body>no data</body></html>")
    assert products == []

# Trimmed copy of a real noon SSR response (2026-07-28): reference-serialized
# JavaScript, unquoted keys, `!0`/`!1` booleans, `\x3C` escapes — not JSON.
MOCK_EMBEDDED_HTML = (
    '<script>window.__ssr={facetsV2:null,search:$R[10]={limit:50,page:1},'
    'hits:$R[11]=[$R[12]={offer_code:"e16214c834f87cce",catalog_sku:"N23157381A-1",'
    'sku:"N23157381A",sku_config:"N23157381A",brand:"CeraVe",'
    'name:"Moisturising Lotion \\x26 Ceramides 236ml",price:640,sale_price:320,'
    'url:"moisturising-lotion-ceramides-236ml",'
    'image_url:"https://f.nooncdn.com/p/pzsku/Z038Z/45/_/1779179010/67bb178e.jpg",'
    'is_buyable:!0,show_3d:!1,product_rating:$R[13]={best_rating:5,count:7235,value:4.53},'
    'estimated_delivery_date:"Get it \\x3Cb\\x3ETomorrow\\x3C/b\\x3E",store_name:"noon",'
    'flags:$R[14]=["fbn"],assets:$R[15]={}},'
    '$R[16]={sku_config:"N99999999A",name:"No Price Item",url:"no-price-item"}],'
    'mpHits:$R[17]=[]}</script>'
)


def test_parse_embedded_js_payload():
    products = parse_products_from_html(MOCK_EMBEDDED_HTML)
    # The second hit has no price and must be dropped, not crash the parse.
    assert len(products) == 1
    p = products[0]
    assert p["name"] == "Moisturising Lotion & Ceramides 236ml"
    assert p["sku"] == "N23157381A"
    assert p["sale_price"] == 320.0
    assert p["original_price"] == 640.0
    assert p["discount_pct"] == 50
    assert p["brand"] == "CeraVe"
    assert p["rating"] == 4.5
    assert p["rating_count"] == 7235
    assert p["store_name"] == "noon"
    # \x3C escapes decode to real tags, which _normalize_item then strips.
    assert p["estimated_delivery"] == "Get it Tomorrow"


def test_embedded_payload_url_carries_offer_code():
    p = parse_products_from_html(MOCK_EMBEDDED_HTML)[0]
    assert p["url"] == (
        "https://www.noon.com/egypt-en/moisturising-lotion-ceramides-236ml"
        "/N23157381A/p/?o=e16214c834f87cce"
    )


def test_embedded_payload_prefers_ready_made_image_url():
    p = parse_products_from_html(MOCK_EMBEDDED_HTML)[0]
    assert p["image_url"] == "https://f.nooncdn.com/p/pzsku/Z038Z/45/_/1779179010/67bb178e.jpg"


def test_parse_product_cards_reads_current_data_qa():
    html = """
    <div data-qa="plp-product-box">
      <a href="/egypt-en/some-item/N11111111A/p/?o=abc">
        <div data-qa="plp-product-box-name">Some Item</div>
        <div data-qa="plp-product-box-price">EGP 250</div>
        <s>EGP 500</s>
        <img src="https://f.nooncdn.com/p/x.jpg">
      </a>
    </div>
    """
    products = parse_products_from_html(html)
    assert len(products) == 1
    assert products[0]["sku"] == "N11111111A"
    assert products[0]["sale_price"] == 250.0
    assert products[0]["discount_pct"] == 50


def test_akamai_challenge_is_not_mistaken_for_a_page():
    challenge = '<html><body><div id="sec-if-cpt-container"></div></body></html>'
    assert _is_akamai_challenge(challenge)
    assert not _is_akamai_challenge(MOCK_EMBEDDED_HTML)


def test_parse_calculates_discount_if_missing():
    html = json.dumps({"props": {"pageProps": {"catalog": {"items": [
        {"name": "Item", "sku": "ABC123", "slug": "item",
         "sale_price": 75, "price": 100, "image_keys": []}
    ]}}}})
    full_html = f'<script id="__NEXT_DATA__" type="application/json">{html}</script>'
    products = parse_products_from_html(full_html)
    assert products[0]["discount_pct"] == 25


# ── Feed rotation ─────────────────────────────────────────────────────────────

def test_every_category_is_visited_before_any_second_page():
    tasks = scraper.feed_tasks()
    first_round = tasks[:len(scraper.FEED_CODES)]
    # Page 1 of a category beats page 7 of another one, so breadth comes first.
    assert {page for _, page in first_round} == {1}
    assert len({code for code, _ in first_round}) == len(scraper.FEED_CODES)


def test_the_cursor_wraps_instead_of_running_off_the_end():
    total = len(scraper.feed_tasks())
    assert scraper.next_task(total - scraper.FETCHES_PER_RUN) == 0
    assert scraper.next_task(total - 1) < total


def test_products_are_tagged_with_the_feed_they_came_from(mocker):
    mocker.patch.object(scraper, "FETCHES_PER_RUN", 1)
    mocker.patch.object(scraper, "_fetch_html", return_value="<html></html>")
    mocker.patch.object(scraper, "parse_products_from_html",
                        return_value=[{"sku": "A", "name": "x"}])
    products = scraper.fetch_products(start_task=0)
    assert products[0]["category"] == scraper.feed_tasks()[0][0]


def test_one_dead_category_does_not_cost_the_whole_run(mocker):
    # noon retires browse paths without warning. A run that fetches nothing
    # still fails hard, in main.py, because the product list stays empty.
    mocker.patch.object(scraper, "FETCHES_PER_RUN", 2)
    mocker.patch.object(scraper, "_fetch_html",
                        side_effect=[RuntimeError("gone"), "<html></html>"])
    mocker.patch.object(scraper, "parse_products_from_html",
                        return_value=[{"sku": "A", "name": "x"}])
    assert len(scraper.fetch_products(start_task=0)) == 1


def test_feed_urls_keep_the_price_drop_filter_on_every_page():
    assert "f[min_offer_price]=365_days" in scraper.feed_url("beauty/fragrance", 1)
    assert scraper.feed_url("beauty/fragrance", 3).endswith("&page=3")
    assert "/egypt-en/beauty/fragrance/" in scraper.feed_url("beauty/fragrance", 1)
