import json
from datetime import datetime, timedelta, timezone

from archive import (
    KEEP_DAYS,
    MAX_DEALS,
    load_archive,
    prune_archive,
    record_deal,
    save_archive,
)

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _product(sku="N1A", **overrides):
    p = {
        "sku": sku,
        "name": "لابتوب Lenovo IdeaPad 3",
        "brand": "Lenovo",
        "store_name": "Tech Store",
        "image_url": "https://f.nooncdn.com/p/pnsku/x.jpg",
        "url": f"https://www.noon.com/egypt-en/laptop/{sku}/p/?o=abc",
        "sale_price": 12500.0,
        "original_price": 18000.0,
        "discount_pct": 31,
        "rating": 4.4,
        "rating_count": 210,
    }
    p.update(overrides)
    return p


def test_recorded_url_carries_the_affiliate_utms():
    archive = {"deals": []}
    record_deal(archive, _product(), now=NOW)
    assert "utm_medium=AFFccacc092d97d" in archive["deals"][0]["url"]
    assert archive["deals"][0]["posted_at"] == NOW.isoformat()


def test_newest_deal_is_first():
    archive = {"deals": []}
    record_deal(archive, _product("OLD"), now=NOW - timedelta(hours=2))
    record_deal(archive, _product("NEW"), now=NOW)
    assert [d["sku"] for d in archive["deals"]] == ["NEW", "OLD"]


def test_reposted_sku_refreshes_its_entry_instead_of_duplicating():
    # Two pages for one product would compete with each other in search results.
    archive = {"deals": []}
    record_deal(archive, _product("N1A", sale_price=999.0), now=NOW - timedelta(days=25))
    record_deal(archive, _product("N1A", sale_price=850.0), now=NOW)
    assert len(archive["deals"]) == 1
    assert archive["deals"][0]["sale_price"] == 850.0
    assert archive["deals"][0]["posted_at"] == NOW.isoformat()


def test_deals_past_the_window_are_retired_not_deleted():
    # Deleting the entry would 404 the URL, and a URL that took four months to
    # rank is the one thing here that cannot be rebuilt.
    archive = {"deals": []}
    record_deal(archive, _product("KEEP"), now=NOW - timedelta(days=2))
    record_deal(archive, _product("OLD"), now=NOW - timedelta(days=KEEP_DAYS + 1))
    pruned = prune_archive(archive, now=NOW)
    assert [d["sku"] for d in pruned["deals"]] == ["KEEP"]
    assert [d["sku"] for d in pruned["retired"]] == ["OLD"]


def test_a_retired_entry_keeps_only_what_a_tombstone_needs():
    archive = {"deals": []}
    record_deal(archive, _product("OLD"), now=NOW - timedelta(days=KEEP_DAYS + 1))
    entry = prune_archive(archive, now=NOW)["retired"][0]
    assert entry["name"] and entry["brand"]
    # A year-old price is not information, it is a wrong answer.
    assert "sale_price" not in entry and "url" not in entry


def test_prune_caps_total_size_and_retires_the_overflow():
    deals = [
        {"sku": f"S{i}", "posted_at": (NOW - timedelta(minutes=i)).isoformat()}
        for i in range(MAX_DEALS + 50)
    ]
    pruned = prune_archive({"deals": deals}, now=NOW)
    assert len(pruned["deals"]) == MAX_DEALS
    assert len(pruned["retired"]) == 50


def test_a_deal_that_comes_back_stops_being_a_tombstone():
    archive = {"deals": [], "retired": [{"sku": "N1A", "name": "old"}]}
    record_deal(archive, _product("N1A"), now=NOW)
    assert archive["retired"] == []
    pruned = prune_archive(archive, now=NOW)
    assert [d["sku"] for d in pruned["deals"]] == ["N1A"]
    assert "retired" not in pruned


def test_retired_entries_are_never_duplicated_across_runs():
    archive = {"deals": []}
    record_deal(archive, _product("OLD"), now=NOW - timedelta(days=KEEP_DAYS + 1))
    once = prune_archive(archive, now=NOW)
    twice = prune_archive(once, now=NOW)
    assert len(twice["retired"]) == 1


def test_prune_sorts_newest_first_and_survives_junk_entries():
    archive = {"deals": [
        {"sku": "OLDER", "posted_at": (NOW - timedelta(hours=5)).isoformat()},
        "not-a-dict",
        {"sku": "NEWER", "posted_at": (NOW - timedelta(hours=1)).isoformat()},
    ]}
    assert [d["sku"] for d in prune_archive(archive, now=NOW)["deals"]] == ["NEWER", "OLDER"]


def test_only_the_fields_the_site_renders_are_stored():
    archive = {"deals": []}
    record_deal(archive, _product(offer_code="secret", some_internal_noon_field=1), now=NOW)
    entry = archive["deals"][0]
    assert "offer_code" not in entry
    assert "some_internal_noon_field" not in entry
    assert entry["name"] and entry["sale_price"]


def test_load_missing_or_corrupt_file_gives_an_empty_archive(tmp_path):
    assert load_archive(str(tmp_path / "nope.json")) == {"deals": []}
    broken = tmp_path / "deals.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_archive(str(broken)) == {"deals": []}
    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text('["a"]', encoding="utf-8")
    assert load_archive(str(wrong_shape)) == {"deals": []}


def test_roundtrip_keeps_arabic_readable(tmp_path):
    path = str(tmp_path / "deals.json")
    archive = {"deals": []}
    record_deal(archive, _product(), now=NOW)
    save_archive(archive, path)
    with open(path, encoding="utf-8") as f:
        assert "لابتوب" in f.read()  # not \u-escaped, so diffs stay reviewable
    assert load_archive(path) == json.loads(json.dumps(archive))
