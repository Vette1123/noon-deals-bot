import os
import sys
import json
import time
from scraper import fetch_products, MAX_PAGES, PAGES_PER_RUN
from filters import filter_deals, load_posted, save_posted, MIN_DISCOUNT
from affiliate import build_affiliate_link
from telegram_poster import post_deal

POSTED_FILE = "posted.json"
STATE_FILE  = "state.json"
MAX_POSTS_PER_RUN = 50
DELAY_BETWEEN_POSTS = 3


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"next_page": 1}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def run(dry_run: bool = False) -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "@noon_hot_deals")
    noon_cookie = os.environ.get("NOON_SESSION_COOKIE", "")

    if not bot_token and not dry_run:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    state = _load_state()
    start_page = state.get("next_page", 1)
    print(f"Fetching Noon Egypt deals (pages {start_page}–{start_page + PAGES_PER_RUN - 1})...")
    products = fetch_products(start_page=start_page)
    print(f"Found {len(products)} products")

    already_posted = load_posted(POSTED_FILE)
    new_deals = filter_deals(products, already_posted)
    print(f"{len(new_deals)} new qualifying deals (>={MIN_DISCOUNT}% off)")

    if not new_deals:
        print("Nothing new to post.")
        return

    new_deals.sort(key=lambda x: x["discount_pct"], reverse=True)
    to_post = new_deals[:MAX_POSTS_PER_RUN]

    posted = 0
    for product in to_post:
        try:
            product["affiliate_url"] = build_affiliate_link(
                product["url"], product["name"], noon_cookie
            )
        except Exception as e:
            print(f"Affiliate link failed for {product['name']}: {e}")
            product["affiliate_url"] = product["url"]

        if dry_run:
            print(f"[DRY RUN] {product['name']} ({product['discount_pct']}% off) → {product['affiliate_url']}")
            already_posted[product["sku"]] = True
            posted += 1
            continue

        if post_deal(product, bot_token, channel_id):
            already_posted[product["sku"]] = True
            posted += 1
            print(f"Posted: {product['name']} ({product['discount_pct']}% off)")
            if posted < len(to_post):
                time.sleep(DELAY_BETWEEN_POSTS)
        else:
            print(f"Failed: {product['name']}")

    # Advance page cursor; wrap and reset history after full cycle
    next_page = start_page + PAGES_PER_RUN
    if next_page > MAX_PAGES:
        next_page = 1
        already_posted = {}
        print("Full cycle complete — resetting posted history for next round.")

    _save_state({"next_page": next_page})
    save_posted(already_posted, POSTED_FILE)
    print(f"Done. Posted {posted} deals. Next run starts at page {next_page}.")

if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
