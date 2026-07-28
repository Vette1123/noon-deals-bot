import os
import sys
import json
import time
from scraper import fetch_products, MAX_PAGES, PAGES_PER_RUN
from filters import (
    MIN_DISCOUNT,
    MIN_PRICE,
    REPOST_AFTER_DAYS,
    filter_deals,
    load_posted,
    mark_posted,
    prune_posted,
    save_posted,
)
from telegram_poster import post_deal

POSTED_FILE = "posted.json"
STATE_FILE  = "state.json"
# Six runs a day. 12 keeps the channel at ~70 posts/day without the burst of 50
# near-identical cards that made readers mute it.
MAX_POSTS_PER_RUN = int(os.environ.get("MAX_POSTS_PER_RUN", "12"))
DELAY_BETWEEN_POSTS = 3
DEFAULT_COUPON_CODE = "gado1996"


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"next_page": 1}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _next_page(start_page: int) -> int:
    """Advance the pagination cursor, wrapping at the end of the catalogue."""
    following = start_page + PAGES_PER_RUN
    if following > MAX_PAGES:
        return 1
    return following


def run(dry_run: bool = False) -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "@noon_hot_deals")
    coupon = os.environ.get("NOON_COUPON_CODE", DEFAULT_COUPON_CODE).strip()

    if not bot_token and not dry_run:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    state = _load_state()
    start_page = state.get("next_page", 1)
    print(f"Fetching Noon Egypt deals (pages {start_page}–{start_page + PAGES_PER_RUN - 1})...")
    products = fetch_products(start_page=start_page)
    print(f"Found {len(products)} products")

    if not products:
        # Hard failure, not a quiet no-op: a 0-product scrape means noon changed
        # the page again (that's how the 2026-06-30 breakage stayed invisible for
        # a month behind green CI runs). Reset the cursor, then fail the job.
        print("No products found — resetting page cursor to 1 for next run.")
        _save_state({"next_page": 1})
        raise SystemExit("Scraped 0 products — noon page format likely changed. Failing loudly.")

    already_posted = prune_posted(load_posted(POSTED_FILE))
    new_deals = filter_deals(products, already_posted)
    print(
        f"{len(new_deals)} qualifying deals "
        f"(>={MIN_DISCOUNT}% off, >=EGP {MIN_PRICE:,.0f}, not posted in {REPOST_AFTER_DAYS}d)"
    )

    to_post = new_deals[:MAX_POSTS_PER_RUN]
    posted = 0
    try:
        for product in to_post:
            if dry_run:
                print(
                    f"[DRY RUN] {product['name']} ({product['discount_pct']}% off) "
                    f"-> {product['url']} [coupon: {coupon}]"
                )
                mark_posted(already_posted, product["sku"])
                posted += 1
                continue

            if post_deal(product, bot_token, channel_id, coupon=coupon):
                mark_posted(already_posted, product["sku"])
                posted += 1
                print(f"Posted: {product['name']} ({product['discount_pct']}% off)")
                if posted < len(to_post):
                    time.sleep(DELAY_BETWEEN_POSTS)
            else:
                print(f"Failed: {product['name']}")
    finally:
        # Persist even if posting blows up mid-loop — otherwise every already-sent
        # deal in this run gets posted a second time on the next one.
        save_posted(already_posted, POSTED_FILE)
        _save_state({"next_page": _next_page(start_page)})

    print(f"Done. Posted {posted} deals. Next run starts at page {_next_page(start_page)}.")


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
