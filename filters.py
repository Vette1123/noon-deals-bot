import json
import math
import os
from datetime import datetime, timedelta, timezone

from categories import commission_rate

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
# The affiliate panel caps commission at AED 50 per item. In EGP that is roughly
# 700 at mid-2026 rates; override it when the peg moves rather than editing code.
#
# The cap is the single most important number here. It means a 40,000 EGP TV at
# 3% earns exactly what a 22,000 EGP one does, and less than a 9,000 EGP
# fragrance set at 8% — so "expensive" is not the same as "worth posting".
COMMISSION_CAP_EGP = float(os.environ.get("COMMISSION_CAP_EGP", "700"))
# Below this, a listing with no brand and no reviews is marketplace filler: no
# search demand, cents of commission, and a deal page that is thin by construction.
FILLER_PRICE = 400


# ── Qualification ─────────────────────────────────────────────────────────────

def _rating_disqualifies(product: dict) -> bool:
    """Only judge a rating that enough people contributed to."""
    rating = product.get("rating")
    count = product.get("rating_count") or 0
    if rating is None or count < RATING_CONFIDENCE:
        return False
    return rating < MIN_RATING


def _is_filler(product: dict) -> bool:
    """Cheap, unbranded, never reviewed by anyone. Not a deal, a listing."""
    return (
        not (product.get("brand") or "").strip()
        and not (product.get("rating_count") or 0)
        and (product.get("sale_price") or 0) < FILLER_PRICE
    )


def _qualifies(product: dict, min_discount: int, min_price: float) -> bool:
    if product.get("discount_pct", 0) < min_discount:
        return False
    if product.get("sale_price", 0) < min_price:
        return False
    if _is_filler(product):
        return False
    return not _rating_disqualifies(product)


# ── Ranking ───────────────────────────────────────────────────────────────────
#
# Deals are ranked by expected commission in pounds, not by a points total.
# `expected_commission` is what the sale pays if it happens; the multipliers
# below are the odds that it happens at all. Multiplying them is the estimate
# of what the post is actually worth.

def expected_commission(product: dict) -> float:
    """What one sale of this product pays, in EGP.

    Rate comes from the product's category and the panel caps the payout per
    item, so this is `min(cap, rate × price)` and nothing more clever.
    """
    price = product.get("sale_price") or 0
    if price <= 0:
        return 0.0
    return min(COMMISSION_CAP_EGP, commission_rate(product.get("category")) * price)


def _discount_multiplier(product: dict) -> float:
    """A deeper discount converts better, with diminishing returns — nobody buys
    twice as often because a thing is 80% off rather than 40%."""
    return 1.0 + min(0.6, (product.get("discount_pct") or 0) / 100.0)


def _rating_multiplier(product: dict) -> float:
    """Only judge a rating enough people contributed to."""
    rating = product.get("rating")
    if rating is None or (product.get("rating_count") or 0) < RATING_CONFIDENCE:
        return 1.0
    return max(0.6, min(1.3, 1.0 + (rating - 4.0) * 0.3))


def _demand_multiplier(product: dict) -> float:
    """Review count is the only demand signal in the payload, and demand is what
    search volume is made of: a product 2,000 people rated is one people look
    for by name, and its deal page can rank. One nobody rated cannot."""
    count = product.get("rating_count") or 0
    if count <= 0:
        return 0.85
    return min(1.5, 0.9 + 0.2 * math.log10(count))


def _trust_multiplier(product: dict) -> float:
    """Fulfilment and bestseller flags drive conversion, and an order that never
    completes pays nothing. A refund voids the commission outright."""
    multiplier = 1.0
    if product.get("fulfilled_by_noon"):
        multiplier *= 1.15
    if product.get("free_delivery"):
        multiplier *= 1.05
    if product.get("is_bestseller"):
        multiplier *= 1.2
    return multiplier


def deal_score(product: dict) -> float:
    """Expected earnings from posting this deal, in EGP.

    Replaces a points total that summed discount and price. That total ranked a
    45,000 EGP television above a 6,000 EGP fragrance set, when the television
    pays 3% capped at EGP 700 and the fragrance set pays 8% of every pound.
    """
    return expected_commission(product) * (
        _discount_multiplier(product)
        * _rating_multiplier(product)
        * _demand_multiplier(product)
        * _trust_multiplier(product)
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
