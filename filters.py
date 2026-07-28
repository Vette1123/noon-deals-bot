import json
import os

MIN_DISCOUNT = 25
# Affiliate commission is a percentage of basket value, so a 60%-off EGP 40 item
# is worth roughly nothing while still costing a post slot and reader attention.
MIN_PRICE = 150


def _qualifies(product: dict, min_discount: int, min_price: float) -> bool:
    return (
        product.get("discount_pct", 0) >= min_discount
        and product.get("sale_price", 0) >= min_price
    )


def filter_deals(
    products: list[dict],
    already_posted: dict,
    min_discount: int = MIN_DISCOUNT,
    min_price: float = MIN_PRICE,
) -> list[dict]:
    return [
        p for p in products
        if _qualifies(p, min_discount, min_price) and p["sku"] not in already_posted
    ]

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
