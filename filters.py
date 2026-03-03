import json
import os

MIN_DISCOUNT = 5

def filter_deals(products: list[dict], already_posted: dict, min_discount: int = MIN_DISCOUNT) -> list[dict]:
    return [p for p in products if p.get("discount_pct", 0) >= min_discount and p["sku"] not in already_posted]

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
