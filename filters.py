import json
import os
from datetime import datetime, timedelta, timezone

MIN_DISCOUNT = 25
# Affiliate commission is a percentage of basket value, so a 60%-off EGP 40 item
# is worth roughly nothing while still costing a post slot and reader attention.
MIN_PRICE = 150
# Only enforced once a product has enough reviews for the score to mean anything.
MIN_RATING = 3.5
RATING_CONFIDENCE = 20
# A SKU may be posted again after this long. Replaces the old "wipe posted.json
# at the end of every page cycle", which recycled the same ~500 products daily.
REPOST_AFTER_DAYS = 21
# Per-run cap on any one seller. Without it a single store ("ELLE Cosmetics" had
# 18 of 72 qualifying deals in one sample) turns the channel into its catalogue.
MAX_PER_SELLER = 2


# ── Qualification ─────────────────────────────────────────────────────────────

def _rating_disqualifies(product: dict) -> bool:
    """Only judge a rating that enough people contributed to."""
    rating = product.get("rating")
    count = product.get("rating_count") or 0
    if rating is None or count < RATING_CONFIDENCE:
        return False
    return rating < MIN_RATING


def _qualifies(product: dict, min_discount: int, min_price: float) -> bool:
    if product.get("discount_pct", 0) < min_discount:
        return False
    if product.get("sale_price", 0) < min_price:
        return False
    return not _rating_disqualifies(product)


# ── Ranking ───────────────────────────────────────────────────────────────────

def _rating_bonus(product: dict) -> float:
    rating = product.get("rating")
    if rating is None or (product.get("rating_count") or 0) < RATING_CONFIDENCE:
        return 0.0
    return max(-10.0, min(6.0, (rating - 4.0) * 10))


def _value_bonus(product: dict) -> float:
    """Commission scales with basket value, so a pricier item is worth more."""
    return min(10.0, product.get("sale_price", 0) / 100)


def _trust_bonus(product: dict) -> float:
    bonus = 0.0
    if product.get("fulfilled_by_noon"):
        bonus += 4.0
    if product.get("free_delivery"):
        bonus += 2.0
    if product.get("is_bestseller"):
        bonus += 3.0
    return bonus


def deal_score(product: dict) -> float:
    """Rank deals by expected earnings, not by headline discount alone.

    A 40%-off EGP 1,500 bestseller rated 4.6 beats a 68%-off EGP 190 no-name.
    """
    return (
        product.get("discount_pct", 0)
        + _rating_bonus(product)
        + _value_bonus(product)
        + _trust_bonus(product)
    )


def _name_key(product: dict) -> str:
    return " ".join((product.get("name") or "").lower().split())


def _dedupe_by_name(products: list[dict]) -> list[dict]:
    """Drop identically-named listings — the same item resold by several stores."""
    seen: set[str] = set()
    kept = []
    for product in products:
        key = _name_key(product)
        if key and key in seen:
            continue
        seen.add(key)
        kept.append(product)
    return kept


def _seller_key(product: dict) -> str:
    return (product.get("store_name") or product.get("brand") or "?").strip().lower()


def _cap_per_seller(products: list[dict], max_per_seller: int) -> list[dict]:
    """Keep the best `max_per_seller` deals per seller, preserving input order."""
    seen: dict[str, int] = {}
    kept = []
    for product in products:
        key = _seller_key(product)
        if seen.get(key, 0) >= max_per_seller:
            continue
        seen[key] = seen.get(key, 0) + 1
        kept.append(product)
    return kept


# ── Public API ────────────────────────────────────────────────────────────────

def filter_deals(
    products: list[dict],
    already_posted: dict,
    min_discount: int = MIN_DISCOUNT,
    min_price: float = MIN_PRICE,
    max_per_seller: int = MAX_PER_SELLER,
    now: datetime | None = None,
) -> list[dict]:
    """Qualifying, not-recently-posted deals, best first, seller-diversified."""
    blocked = recently_posted_skus(already_posted, now=now)
    fresh = [
        p for p in products
        if _qualifies(p, min_discount, min_price) and p["sku"] not in blocked
    ]
    fresh.sort(key=deal_score, reverse=True)
    return _cap_per_seller(_dedupe_by_name(fresh), max_per_seller)


# ── posted.json ───────────────────────────────────────────────────────────────
#
# Format is {sku: "2026-07-28T07:53:08+00:00"}. The legacy format was {sku: true};
# those entries are read as "posted just now" so an upgrade never re-floods the
# channel with everything it already sent.

def _parse_stamp(value, fallback: datetime) -> datetime:
    if not isinstance(value, str):
        return fallback
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return fallback


def recently_posted_skus(posted: dict, now: datetime | None = None) -> set[str]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=REPOST_AFTER_DAYS)
    return {sku for sku, stamp in posted.items() if _parse_stamp(stamp, now) > cutoff}


def prune_posted(posted: dict, now: datetime | None = None) -> dict:
    """Drop entries old enough to be posted again — keeps posted.json bounded.

    Also normalises legacy `true` values to a real timestamp; left as-is they
    would re-read as "just posted" on every run and never expire.
    """
    now = now or datetime.now(timezone.utc)
    keep = recently_posted_skus(posted, now=now)
    return {
        sku: _parse_stamp(posted[sku], now).isoformat()
        for sku in posted
        if sku in keep
    }


def mark_posted(posted: dict, sku: str, now: datetime | None = None) -> None:
    posted[sku] = (now or datetime.now(timezone.utc)).isoformat()


def load_posted(path: str = "posted.json") -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_posted(posted: dict, path: str = "posted.json") -> None:
    with open(path, "w") as f:
        json.dump(posted, f, indent=2)
