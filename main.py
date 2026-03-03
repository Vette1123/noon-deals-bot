import os
import sys
import time
from scraper import fetch_deals_page, parse_products_from_html
from filters import filter_deals, load_posted, save_posted
from affiliate import build_affiliate_link
from telegram_poster import post_deal

POSTED_FILE = "posted.json"
MAX_POSTS_PER_RUN = 5
DELAY_BETWEEN_POSTS = 3

def run(dry_run: bool = False) -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "@noon_hot_deals")
    noon_cookie = os.environ.get("NOON_SESSION_COOKIE", "")

    if not bot_token and not dry_run:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    print("Fetching Noon Egypt deals...")
    html = fetch_deals_page()
    products = parse_products_from_html(html)
    print(f"Found {len(products)} products")

    already_posted = load_posted(POSTED_FILE)
    new_deals = filter_deals(products, already_posted)
    print(f"{len(new_deals)} new qualifying deals (>=20% off)")

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

    save_posted(already_posted, POSTED_FILE)
    print(f"Done. Posted {posted} deals.")

if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
