from datetime import datetime, timedelta, timezone

import indexnow
from indexnow import changed_urls, key_file, ping_recent, submit

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
BASE = "https://vette1123.github.io/noon-deals-bot"


def _deal(sku="N1A", posted_at=None, **overrides):
    d = {
        "sku": sku,
        "name": "لابتوب Lenovo IdeaPad 3",
        "brand": "Lenovo",
        "category": "laptops",
        "url": "https://www.noon.com/egypt-en/laptop/N1A/p/",
        "sale_price": 12500.0,
        "discount_pct": 31,
        "posted_at": (posted_at or NOW).isoformat(),
    }
    d.update(overrides)
    return d


class _Resp:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


def test_key_file_is_the_key_plus_txt():
    assert key_file() == f"{indexnow.KEY}.txt"


def test_only_pages_this_run_changed_are_submitted():
    old = _deal("OLD1", posted_at=NOW - timedelta(days=3))
    fresh = _deal("NEW1")
    urls = changed_urls({"deals": [old, fresh]}, BASE, now=NOW)
    assert f"{BASE}/deals/NEW1.html" in urls
    # Re-announcing an unchanged page every four hours is what gets a host
    # rate-limited, and past that ignored entirely.
    assert f"{BASE}/deals/OLD1.html" not in urls
    # The front page always reshuffles, so it always changed.
    assert urls[0] == f"{BASE}/"


def test_touched_hubs_are_submitted_but_only_when_they_exist():
    # Two Lenovo deals clear MIN_DEALS_PER_BRAND, so brands/lenovo.html is built.
    deals = [_deal("N1A"), _deal("N2A"), _deal("N3A", brand="Dell")]
    urls = changed_urls({"deals": deals}, BASE, now=NOW)
    assert f"{BASE}/brands/lenovo.html" in urls
    # One Dell deal does not earn a hub page, and submitting a 404 burns the quota.
    assert f"{BASE}/brands/dell.html" not in urls


def test_nothing_is_submitted_when_no_deal_is_recent(mocker):
    post = mocker.patch.object(indexnow.requests, "post")
    stale = {"deals": [_deal("OLD1", posted_at=NOW - timedelta(days=3))]}
    assert changed_urls(stale, BASE, now=NOW) == []
    assert ping_recent(stale, BASE, now=NOW) is False
    post.assert_not_called()


def test_payload_declares_the_key_location(mocker):
    post = mocker.patch.object(indexnow.requests, "post", return_value=_Resp())
    assert submit([f"{BASE}/deals/N1A.html"], BASE) is True
    payload = post.call_args.kwargs["json"]
    assert payload["host"] == "vette1123.github.io"
    assert payload["key"] == indexnow.KEY
    # On a project-pages URL the key file is not at the domain root, so without
    # keyLocation the engine looks in the wrong place and answers 403.
    assert payload["keyLocation"] == f"{BASE}/{key_file()}"
    assert payload["urlList"] == [f"{BASE}/deals/N1A.html"]


def test_202_counts_as_accepted(mocker):
    # 202 is the normal answer while a freshly published key is still verifying.
    mocker.patch.object(indexnow.requests, "post", return_value=_Resp(202, ""))
    assert submit([f"{BASE}/"], BASE) is True


def test_a_rejection_or_a_network_error_never_raises(mocker):
    mocker.patch.object(indexnow.requests, "post", return_value=_Resp(429, "slow down"))
    assert submit([f"{BASE}/"], BASE) is False
    mocker.patch.object(
        indexnow.requests, "post",
        side_effect=indexnow.requests.RequestException("boom"),
    )
    assert submit([f"{BASE}/"], BASE) is False


def test_batch_is_capped_at_the_protocol_limit(mocker):
    post = mocker.patch.object(indexnow.requests, "post", return_value=_Resp())
    submit([f"{BASE}/deals/N{i}.html" for i in range(indexnow.MAX_URLS + 50)], BASE)
    assert len(post.call_args.kwargs["json"]["urlList"]) == indexnow.MAX_URLS
