"""The deal archive — every deal the bot has published, kept for a month.

Telegram posts vanish down a feed and earn only from the 11 people who happen to
scroll past. The archive turns the same scrape into a second, permanent surface:
[site_builder.py](site_builder.py) renders it into a static site that Google can
index, so a deal keeps earning long after it left the channel.

Shape is `{"deals": [ … ]}`, newest first, one entry per SKU. Stored URLs are
already affiliate-decorated — whatever we publish anywhere must earn.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from telegram_poster import with_affiliate_utms

ARCHIVE_FILE = "deals.json"
# A year of history, not the month this started with. Google takes two to four
# months to trust a new domain, so a 30-day window deleted every page at roughly
# the moment it began to rank — the site could never accumulate anything.
KEEP_DAYS = 365
# Hard ceiling regardless of age, whichever binds first.
MAX_DEALS = 12000
# Deals that fall out of the window are not forgotten, only stripped down to a
# tombstone (see `_retire`). A URL that once ranked must never start 404ing.
#
# This is a ceiling, not a promise of forever: every tombstone is still a built
# HTML file with the site's CSS inlined in it, so 50,000 of them is a few hundred
# MB of artifact per deploy. At ~120 archived deals a day that is over a year of
# runway. If it ever binds, give tombstones their own minimal template rather
# than lowering this — the whole point is that the URL survives.
MAX_RETIRED = 50000

# Only what the site actually renders. Copying the whole scraped item would bloat
# the file and commit noon's internal fields into git forever.
_FIELDS = (
    "sku", "name", "brand", "category", "store_name", "image_url",
    "sale_price", "original_price", "discount_pct",
    "rating", "rating_count",
    "fulfilled_by_noon", "free_delivery", "is_bestseller",
)

# Enough to keep the URL alive and point the reader somewhere useful. Prices are
# deliberately dropped: a year-old price is not information, it is a wrong answer.
_RETIRED_FIELDS = ("sku", "name", "brand", "category", "posted_at")


def _parse_stamp(value, fallback: datetime) -> datetime:
    if not isinstance(value, str):
        return fallback
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return fallback


def deal_entry(product: dict, now: datetime | None = None) -> dict:
    """One archive record: the site's whole view of a product."""
    now = now or datetime.now(timezone.utc)
    entry = {field: product.get(field) for field in _FIELDS}
    entry["url"] = with_affiliate_utms(product.get("url", ""))
    entry["posted_at"] = now.isoformat()
    return entry


def record_deal(archive: dict, product: dict, now: datetime | None = None) -> None:
    """Add a freshly seen deal, newest first, one entry per SKU."""
    entry = deal_entry(product, now=now)
    deals = archive.setdefault("deals", [])
    sku = entry.get("sku")
    if sku:
        # Re-posting after the cooldown refreshes the existing page instead of
        # creating a duplicate one competing with itself in search results.
        deals[:] = [d for d in deals if d.get("sku") != sku]
        # A deal coming back is alive again, so it stops being a tombstone.
        retired = archive.get("retired")
        if isinstance(retired, list):
            retired[:] = [d for d in retired if d.get("sku") != sku]
    deals.insert(0, entry)


def _retire(deal: dict) -> dict:
    return {field: deal.get(field) for field in _RETIRED_FIELDS}


def prune_archive(archive: dict, now: datetime | None = None) -> dict:
    """Age deals out of the live set without ever dropping their URL.

    Anything past KEEP_DAYS, or past the MAX_DEALS ceiling, becomes a tombstone:
    the site keeps serving that path as a small "this offer ended" page that
    links on to the brand and category hubs. Deleting the entry instead would
    404 every link and every search result the page had earned.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=KEEP_DAYS)
    stamp = lambda d: _parse_stamp(d.get("posted_at"), now)  # noqa: E731

    live, expired = [], []
    for deal in archive.get("deals", []):
        if not isinstance(deal, dict):
            continue
        (live if stamp(deal) > cutoff else expired).append(deal)

    live.sort(key=stamp, reverse=True)
    expired.extend(live[MAX_DEALS:])
    live = live[:MAX_DEALS]

    live_skus = {d.get("sku") for d in live}
    retired = [_retire(d) for d in expired]
    retired += [
        d for d in archive.get("retired", [])
        if isinstance(d, dict) and d.get("sku") not in live_skus
    ]
    seen: set = set()
    deduped = []
    for entry in retired:
        sku = entry.get("sku")
        if sku in seen or sku in live_skus:
            continue
        seen.add(sku)
        deduped.append(entry)
    deduped.sort(key=stamp, reverse=True)

    pruned = {"deals": live}
    if deduped:
        pruned["retired"] = deduped[:MAX_RETIRED]
    return pruned


def load_archive(path: str = ARCHIVE_FILE) -> dict:
    if not os.path.exists(path):
        return {"deals": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"deals": []}
    if not isinstance(data, dict) or not isinstance(data.get("deals"), list):
        return {"deals": []}
    return data


def save_archive(archive: dict, path: str = ARCHIVE_FILE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        # ensure_ascii=False keeps the Arabic product names readable in diffs.
        json.dump(archive, f, ensure_ascii=False, indent=1)
