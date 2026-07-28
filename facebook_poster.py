"""Optional Facebook Page crosspost.

Egypt's deal shopping lives on Facebook far more than on Telegram, and the same
scrape costs nothing to publish twice. Entirely opt-in: with no
`FACEBOOK_PAGE_ID` / `FACEBOOK_PAGE_TOKEN` set, every function here is a no-op,
so the bot's main job cannot fail because of it.

Posted as a link post rather than a photo: Facebook renders noon's own preview
card, and the link stays clickable (captions under photos are not).
"""

import os

import requests

GRAPH_API = "https://graph.facebook.com/v21.0"
TIMEOUT = 15


def facebook_enabled() -> bool:
    return bool(os.environ.get("FACEBOOK_PAGE_ID") and os.environ.get("FACEBOOK_PAGE_TOKEN"))


def format_plain_message(product: dict, coupon: str = "", channel_handle: str = "") -> str:
    """Facebook renders no markup, so this is the Telegram caption in plain text."""
    lines = [f"🔥 {product.get('name', '')}"]
    lines.append("")
    lines.append(
        f"💰 {product.get('sale_price', 0):,.0f} ج.م "
        f"بدلاً من {product.get('original_price', 0):,.0f} ج.م"
    )
    lines.append(f"📉 خصم {product.get('discount_pct', 0)}%")
    if product.get("store_name"):
        lines.append(f"🏪 {product['store_name']}")
    if coupon:
        lines.append(f"🎟️ كود خصم إضافي عند الدفع: {coupon}")
    if channel_handle:
        lines.append("")
        lines.append(f"لعروض أكتر أول بأول: https://t.me/{channel_handle.lstrip('@')}")
    return "\n".join(lines)


def post_to_facebook(product: dict, url: str, coupon: str = "",
                     channel_handle: str = "") -> bool:
    """Publish one deal to the configured Page. Never raises."""
    page_id = os.environ.get("FACEBOOK_PAGE_ID")
    token = os.environ.get("FACEBOOK_PAGE_TOKEN")
    if not (page_id and token and url):
        return False

    try:
        resp = requests.post(
            f"{GRAPH_API}/{page_id}/feed",
            data={
                "message": format_plain_message(product, coupon, channel_handle),
                "link": url,
                "access_token": token,
            },
            timeout=TIMEOUT,
        )
        if resp.ok:
            return True
        # Graph errors are informative (expired token, missing permission) and
        # this is a side channel, so log and carry on rather than failing the run.
        print(f"  Facebook post failed: HTTP {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"  Facebook post failed: {e}")
    return False
