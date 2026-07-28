import os, tempfile
from datetime import datetime, timedelta, timezone

from filters import (
    COMMISSION_CAP_EGP,
    REPOST_AFTER_DAYS,
    deal_score,
    expected_commission,
    filter_deals,
    load_posted,
    mark_posted,
    prune_posted,
    recently_posted_skus,
    save_posted,
)

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)

PRODUCTS = [
    {"sku": "A1", "name": "Good", "brand": "B", "discount_pct": 25, "sale_price": 100, "original_price": 133},
    {"sku": "A2", "name": "Bad",  "brand": "B", "discount_pct": 5,  "sale_price": 95,  "original_price": 100},
    {"sku": "A3", "name": "Best", "brand": "B", "discount_pct": 50, "sale_price": 50,  "original_price": 100},
    {"sku": "A4", "name": "Old",  "brand": "B", "discount_pct": 30, "sale_price": 70,  "original_price": 100},
]


def _posted(*skus, days_ago=0):
    stamp = (NOW - timedelta(days=days_ago)).isoformat()
    return {sku: stamp for sku in skus}


def test_filter_keeps_qualifying_new_deals():
    kept = filter_deals(PRODUCTS, _posted("A4"), min_discount=20, min_price=0, now=NOW)
    skus = [p["sku"] for p in kept]
    assert "A1" in skus and "A3" in skus
    assert "A2" not in skus and "A4" not in skus


def test_filter_drops_cheap_items_regardless_of_discount():
    # A3 is 50% off but only EGP 50 — the commission on it is not worth a post slot.
    skus = [p["sku"] for p in filter_deals(PRODUCTS, {}, min_discount=20, min_price=100, now=NOW)]
    assert skus == ["A1"]


def test_filter_defaults_enforce_both_gates():
    products = [
        {"sku": "OK",    "brand": "B", "discount_pct": 25, "sale_price": 150},
        {"sku": "CHEAP", "brand": "B", "discount_pct": 60, "sale_price": 149},
        {"sku": "WEAK",  "brand": "B", "discount_pct": 24, "sale_price": 900},
    ]
    assert [p["sku"] for p in filter_deals(products, {}, now=NOW)] == ["OK"]


def test_badly_rated_products_are_dropped_only_with_enough_reviews():
    products = [
        {"sku": "HATED",  "discount_pct": 40, "sale_price": 500, "rating": 2.1, "rating_count": 400},
        {"sku": "UNSURE", "discount_pct": 40, "sale_price": 500, "rating": 2.1, "rating_count": 3},
    ]
    assert [p["sku"] for p in filter_deals(products, {}, now=NOW)] == ["UNSURE"]


def test_results_are_ranked_by_deal_score_not_raw_discount():
    cheap_junk = {"sku": "JUNK", "discount_pct": 68, "sale_price": 190,
                  "rating": 3.6, "rating_count": 90}
    pricey_good = {"sku": "GOOD", "discount_pct": 45, "sale_price": 1500,
                   "rating": 4.7, "rating_count": 900, "is_bestseller": True,
                   "fulfilled_by_noon": True}
    ranked = [p["sku"] for p in filter_deals([cheap_junk, pricey_good], {}, now=NOW)]
    assert ranked == ["GOOD", "JUNK"]
    assert deal_score(pricey_good) > deal_score(cheap_junk)


def test_one_seller_cannot_take_over_a_run():
    flood = [
        {"sku": f"S{i}", "brand": "B", "discount_pct": 60, "sale_price": 300,
         "store_name": "ELLE Cosmetics"}
        for i in range(8)
    ]
    other = {"sku": "OTHER", "brand": "B", "discount_pct": 30, "sale_price": 300,
             "store_name": "Someone Else"}
    kept = filter_deals(flood + [other], {}, now=NOW)
    assert sum(1 for p in kept if p["store_name"] == "ELLE Cosmetics") == 2
    assert "OTHER" in [p["sku"] for p in kept]


def test_identical_listings_from_different_sellers_post_once():
    resold = [
        {"sku": "X1", "name": "Women's two-piece pajama set", "brand": "B",
         "discount_pct": 71, "sale_price": 300, "store_name": "Store A"},
        {"sku": "X2", "name": "  women's TWO-piece   pajama set ", "brand": "B",
         "discount_pct": 71, "sale_price": 300, "store_name": "Store B"},
    ]
    assert [p["sku"] for p in filter_deals(resold, {}, now=NOW)] == ["X1"]


def test_unbranded_unreviewed_filler_never_qualifies():
    filler = {"sku": "F", "name": "2 pcs set", "discount_pct": 70, "sale_price": 220}
    assert filter_deals([filler], {}, now=NOW) == []
    # A brand or a single review is enough to make it a product again.
    assert filter_deals([{**filler, "brand": "Zara"}], {}, now=NOW) != []
    assert filter_deals([{**filler, "rating_count": 4}], {}, now=NOW) != []


def test_commission_rate_beats_basket_size_in_the_ranking():
    # The panel caps commission per item, so the expensive low-rate product is
    # worth less than the mid-priced high-rate one. Ranking on price got this
    # exactly backwards for a month.
    television = {"sku": "TV", "brand": "LG", "discount_pct": 40, "sale_price": 45000,
                  "category": "electronics-and-mobiles/home-audio"}
    fragrance = {"sku": "PERF", "brand": "Dior", "discount_pct": 40, "sale_price": 6000,
                 "category": "beauty/fragrance"}
    assert expected_commission(television) == COMMISSION_CAP_EGP
    assert expected_commission(fragrance) == 480.0
    assert [p["sku"] for p in filter_deals([television, fragrance], {}, now=NOW)] == ["TV", "PERF"]

    # …and once the television is merely expensive rather than cap-breaking, the
    # 8% category wins outright.
    cheaper_tv = {**television, "sale_price": 12000}
    assert expected_commission(cheaper_tv) < expected_commission(fragrance)
    assert [p["sku"] for p in filter_deals([cheaper_tv, fragrance], {}, now=NOW)] == ["PERF", "TV"]


def test_untagged_products_still_get_a_rate():
    # Deals archived before categories existed must not score zero forever.
    assert expected_commission({"sale_price": 1000}) == 50.0


def test_recently_posted_blocks_but_old_entries_expire():
    posted = {}
    posted.update(_posted("RECENT", days_ago=1))
    posted.update(_posted("STALE", days_ago=REPOST_AFTER_DAYS + 1))
    assert recently_posted_skus(posted, now=NOW) == {"RECENT"}

    products = [
        {"sku": "RECENT", "discount_pct": 40, "sale_price": 400},
        {"sku": "STALE",  "discount_pct": 40, "sale_price": 400},
    ]
    assert [p["sku"] for p in filter_deals(products, posted, now=NOW)] == ["STALE"]


def test_legacy_true_entries_are_migrated_not_reposted():
    posted = {"OLD": True}
    # Read as "posted just now" so an upgrade does not re-flood the channel...
    assert recently_posted_skus(posted, now=NOW) == {"OLD"}
    # ...and rewritten with a real stamp so they can eventually expire.
    pruned = prune_posted(posted, now=NOW)
    assert pruned == {"OLD": NOW.isoformat()}
    assert recently_posted_skus(pruned, now=NOW + timedelta(days=REPOST_AFTER_DAYS + 1)) == set()


def test_prune_drops_expired_entries():
    posted = {}
    posted.update(_posted("KEEP", days_ago=2))
    posted.update(_posted("DROP", days_ago=REPOST_AFTER_DAYS + 5))
    assert list(prune_posted(posted, now=NOW)) == ["KEEP"]


def test_mark_posted_writes_an_iso_timestamp():
    posted = {}
    mark_posted(posted, "SKU1", now=NOW)
    assert posted["SKU1"] == NOW.isoformat()
    assert recently_posted_skus(posted, now=NOW) == {"SKU1"}


def test_load_posted_missing_file():
    assert load_posted("/nonexistent/posted.json") == {}


def test_save_and_load_roundtrip():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        save_posted({"SKU1": NOW.isoformat()}, tmp)
        assert load_posted(tmp) == {"SKU1": NOW.isoformat()}
    finally:
        os.unlink(tmp)
