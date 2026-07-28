import os
import sys
import json
import time
from scraper import FETCHES_PER_RUN, fetch_products, next_task
from archive import (
    ARCHIVE_FILE,
    load_archive,
    prune_archive,
    record_deal,
    save_archive,
)
from facebook_poster import facebook_enabled, post_to_facebook
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
from telegram_poster import post_deal, with_affiliate_utms

POSTED_FILE = "posted.json"
STATE_FILE  = "state.json"
# Six runs a day. 12 keeps the channel at ~70 posts/day without the burst of 50
# near-identical cards that made readers mute it.
MAX_POSTS_PER_RUN = int(os.environ.get("MAX_POSTS_PER_RUN", "12"))
# The channel and the site want opposite things: a reader mutes a channel that
# posts 40 times a run, while the site earns more the more pages it has. So the
# top 12 go to Telegram and the top 20 are archived — the extra 8 become pages
# without ever reaching anyone's notifications.
SITE_DEALS_PER_RUN = int(os.environ.get("SITE_DEALS_PER_RUN", "20"))
DELAY_BETWEEN_POSTS = 3
# The panel lists exactly two live coupons for this campaign, `gado` and `HZICP`
# (10% cashback, capped). `gado1996` was not one of them — a reader who typed it
# at checkout got an error, which costs the coupon attribution channel and trust.
DEFAULT_COUPON_CODE = "gado"


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def run(dry_run: bool = False) -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "@noon_hot_deals")
    coupon = os.environ.get("NOON_COUPON_CODE", DEFAULT_COUPON_CODE).strip()

    if not bot_token and not dry_run:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    state = _load_state()
    start_task = state.get("next_task", 0)
    print(f"Fetching Noon Egypt deals ({FETCHES_PER_RUN} category feeds from #{start_task})...")
    products = fetch_products(start_task=start_task)
    print(f"Found {len(products)} products")

    if not products:
        # Hard failure, not a quiet no-op: a 0-product scrape means noon changed
        # the page again (that's how the 2026-06-30 breakage stayed invisible for
        # a month behind green CI runs). Reset the cursor, then fail the job.
        print("No products found — resetting the feed cursor for next run.")
        _save_state({"next_task": 0})
        raise SystemExit("Scraped 0 products — noon page format likely changed. Failing loudly.")

    already_posted = prune_posted(load_posted(POSTED_FILE))
    archive = prune_archive(load_archive(ARCHIVE_FILE))
    new_deals = filter_deals(products, already_posted)
    print(
        f"{len(new_deals)} qualifying deals "
        f"(>={MIN_DISCOUNT}% off, >=EGP {MIN_PRICE:,.0f}, not posted in {REPOST_AFTER_DAYS}d)"
    )

    to_post = new_deals[:MAX_POSTS_PER_RUN]
    # Archived first so the posted ones land on top of the archive afterwards,
    # and so a crash in the posting loop still leaves the site something to build.
    for product in reversed(new_deals[len(to_post):SITE_DEALS_PER_RUN]):
        record_deal(archive, product)
    posted = 0
    try:
        for product in to_post:
            if dry_run:
                print(
                    f"[DRY RUN] {product['name']} ({product['discount_pct']}% off) "
                    f"-> {product['url']} [coupon: {coupon}]"
                )
                mark_posted(already_posted, product["sku"])
                record_deal(archive, product)
                posted += 1
                continue

            if post_deal(product, bot_token, channel_id, coupon=coupon):
                mark_posted(already_posted, product["sku"])
                record_deal(archive, product)
                posted += 1
                print(f"Posted: {product['name']} ({product['discount_pct']}% off)")
                if facebook_enabled():
                    post_to_facebook(
                        product, with_affiliate_utms(product["url"]),
                        coupon=coupon, channel_handle=channel_id,
                    )
                if posted < len(to_post):
                    time.sleep(DELAY_BETWEEN_POSTS)
            else:
                print(f"Failed: {product['name']}")
    finally:
        # Persist even if posting blows up mid-loop — otherwise every already-sent
        # deal in this run gets posted a second time on the next one.
        save_posted(already_posted, POSTED_FILE)
        save_archive(archive, ARCHIVE_FILE)
        _save_state({"next_task": next_task(start_task)})

    print(
        f"Done. Posted {posted} deals, archived {len(archive.get('deals', []))} total. "
        f"Next run starts at feed #{next_task(start_task)}."
    )


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
