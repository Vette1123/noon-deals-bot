import os, tempfile
from filters import filter_deals, load_posted, save_posted

PRODUCTS = [
    {"sku": "A1", "name": "Good", "discount_pct": 25, "sale_price": 100, "original_price": 133},
    {"sku": "A2", "name": "Bad",  "discount_pct": 5,  "sale_price": 95,  "original_price": 100},
    {"sku": "A3", "name": "Best", "discount_pct": 50, "sale_price": 50,  "original_price": 100},
    {"sku": "A4", "name": "Old",  "discount_pct": 30, "sale_price": 70,  "original_price": 100},
]

def test_filter_keeps_qualifying_new_deals():
    skus = [p["sku"] for p in filter_deals(PRODUCTS, {"A4": True}, min_discount=20, min_price=0)]
    assert "A1" in skus and "A3" in skus
    assert "A2" not in skus and "A4" not in skus

def test_filter_drops_cheap_items_regardless_of_discount():
    # A3 is 50% off but only EGP 50 — the commission on it is not worth a post slot.
    skus = [p["sku"] for p in filter_deals(PRODUCTS, {}, min_discount=20, min_price=100)]
    assert skus == ["A1"]

def test_filter_defaults_enforce_both_gates():
    products = [
        {"sku": "OK",    "discount_pct": 25, "sale_price": 150},
        {"sku": "CHEAP", "discount_pct": 60, "sale_price": 149},
        {"sku": "WEAK",  "discount_pct": 24, "sale_price": 900},
    ]
    assert [p["sku"] for p in filter_deals(products, {})] == ["OK"]

def test_load_posted_missing_file():
    assert load_posted("/nonexistent/posted.json") == {}

def test_save_and_load_roundtrip():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        save_posted({"SKU1": True}, tmp)
        assert load_posted(tmp) == {"SKU1": True}
    finally:
        os.unlink(tmp)
