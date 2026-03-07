import json
from scraper import parse_products_from_html

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

def test_parse_calculates_discount_if_missing():
    html = json.dumps({"props": {"pageProps": {"catalog": {"items": [
        {"name": "Item", "sku": "ABC123", "slug": "item",
         "sale_price": 75, "price": 100, "image_keys": []}
    ]}}}})
    full_html = f'<script id="__NEXT_DATA__" type="application/json">{html}</script>'
    products = parse_products_from_html(full_html)
    assert products[0]["discount_pct"] == 25
