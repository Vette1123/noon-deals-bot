import asyncio
import re
import requests
from io import BytesIO
import telegram
from telegram import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import RetryAfter


def _escape_md2(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", str(text))


def format_message(product: dict, coupon: str = "") -> str:
    name = _escape_md2(product["name"])
    sale = _escape_md2(f"{product['sale_price']:,.0f}")
    orig = _escape_md2(f"{product['original_price']:,.0f}")
    disc = _escape_md2(f"{product['discount_pct']}%")
    url  = product.get("url", "")

    lines = [f"🔥 *{name}*"]

    if product.get("brand"):
        lines.append(f"🏷️ {_escape_md2(product['brand'])}")

    lines.append("")
    lines.append(f"💰 EGP {sale} ~\\(كان EGP {orig}\\)~")
    lines.append(f"📉 خصم {disc}")

    if product.get("rating"):
        stars = "⭐" * round(product["rating"])
        r = _escape_md2(f"{product['rating']}")
        cnt = f" \\({_escape_md2(str(product['rating_count']))} تقييم\\)" if product.get("rating_count") else ""
        lines.append(f"{stars} {r}/5{cnt}")

    if product.get("estimated_delivery"):
        lines.append(f"🚚 {_escape_md2(product['estimated_delivery'])}")

    if product.get("store_name"):
        lines.append(f"🏪 {_escape_md2(product['store_name'])}")

    # Coupon (tap-to-copy on mobile Telegram via MarkdownV2 code span).
    # The value is constrained to [A-Za-z0-9_-] so no escaping is needed inside the span.
    if coupon and re.fullmatch(r"[A-Za-z0-9_-]+", coupon):
        lines.append("")
        lines.append(f"🎟️ كود خصم إضافي عند الدفع: `{coupon}`")

    lines.append("")
    lines.append(f"👉 *[🛒 اشتري دلوقتي]({url})*")

    return "\n".join(lines)


def _build_markup(url: str, coupon: str = "") -> InlineKeyboardMarkup:
    rows = []
    # Native one-tap copy button (Bot API 7.8+). Shows the coupon value in the label so
    # users can see exactly what gets copied, and the 📋 icon signals the action.
    if coupon and re.fullmatch(r"[A-Za-z0-9_-]+", coupon):
        rows.append([
            InlineKeyboardButton(
                f"📋 نسخ كود الخصم: {coupon}",
                copy_text=CopyTextButton(text=coupon),
            )
        ])
    rows.append([InlineKeyboardButton("🛒 اشتري دلوقتي", url=url)])
    return InlineKeyboardMarkup(rows)


def _download_image(url: str) -> BytesIO | None:
    """Download image to memory so Telegram doesn't have to fetch it from noon's CDN."""
    try:
        resp = requests.get(
            url, timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        if resp.ok and resp.content:
            return BytesIO(resp.content)
    except Exception as e:
        print(f"  Image download failed: {e}")
    return None


def post_deal(product: dict, bot_token: str, channel_id: str, coupon: str = "") -> bool:
    bot = telegram.Bot(token=bot_token)
    caption = format_message(product, coupon=coupon)

    url = product.get("url", "")
    markup = _build_markup(url, coupon)

    image_url = product.get("image_url")

    async def _attempt():
        print(f"  URL: {url}")
        if image_url:
            try:
                await bot.send_photo(
                    chat_id=channel_id,
                    photo=image_url,
                    caption=caption,
                    parse_mode="MarkdownV2",
                    reply_markup=markup,
                )
                return True
            except RetryAfter:
                raise  # flood-limit isn't image-specific — skip fallbacks, let outer handler wait
            except Exception as e:
                print(f"  Direct URL photo failed: {e}")

            photo = _download_image(image_url)
            if photo:
                try:
                    await bot.send_photo(
                        chat_id=channel_id,
                        photo=photo,
                        caption=caption,
                        parse_mode="MarkdownV2",
                        reply_markup=markup,
                    )
                    return True
                except RetryAfter:
                    raise
                except Exception as e:
                    print(f"  Uploaded photo failed: {e}")

        await bot.send_message(
            chat_id=channel_id,
            text=caption,
            parse_mode="MarkdownV2",
            reply_markup=markup,
        )
        return True

    async def _run():
        try:
            return await _attempt()
        except RetryAfter as e:
            wait = int(e.retry_after) + 1
            print(f"  Flood-limited by Telegram — waiting {wait}s then retrying once")
            await asyncio.sleep(wait)
            return await _attempt()

    try:
        return asyncio.run(_run())
    except Exception as e:
        print(f"Failed to post {product.get('name', '?')}: {e}")
        return False
