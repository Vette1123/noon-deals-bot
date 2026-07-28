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
# A month of history. Long enough for search engines to find a page and send
# traffic, short enough that deals.json stays a few hundred KB in git.
KEEP_DAYS = 30
# Hard ceiling regardless of age. At 12 posts × 6 runs a day, 30 days is ~2,100
# deals; this only bites if the post cap is raised a lot.
MAX_DEALS = 3000

# Only what the site actually renders. Copying the whole scraped item would bloat
# the file and commit noon's internal fields into git forever.
_FIELDS = (
    "sku", "name", "brand", "store_name", "image_url",
    "sale_price", "original_price", "discount_pct",
    "rating", "rating_count",
    "fulfilled_by_noon", "free_delivery", "is_bestseller",
)


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
    """Add a freshly posted deal, newest first, one entry per SKU."""
    entry = deal_entry(product, now=now)
    deals = archive.setdefault("deals", [])
    sku = entry.get("sku")
    if sku:
        # Re-posting after the cooldown refreshes the existing page instead of
        # creating a duplicate one competing with itself in search results.
        deals[:] = [d for d in deals if d.get("sku") != sku]
    deals.insert(0, entry)


def prune_archive(archive: dict, now: datetime | None = None) -> dict:
    """Drop deals older than KEEP_DAYS, newest first, capped at MAX_DEALS."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=KEEP_DAYS)
    deals = [
        d for d in archive.get("deals", [])
        if isinstance(d, dict) and _parse_stamp(d.get("posted_at"), now) > cutoff
    ]
    deals.sort(key=lambda d: _parse_stamp(d.get("posted_at"), now), reverse=True)
    return {"deals": deals[:MAX_DEALS]}


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
