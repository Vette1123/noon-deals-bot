import asyncio
import re
import requests
from io import BytesIO
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _escape_md2(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", str(text))


def format_message(product: dict) -> str:
    name = _escape_md2(product["name"])
    sale = _escape_md2(f"{product['sale_price']:,.0f}")
    orig = _escape_md2(f"{product['original_price']:,.0f}")
    disc = _escape_md2(f"{product['discount_pct']}%")

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

    return "\n".join(lines)


def _buy_button(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛒 اشتري دلوقتي", url=url)]])


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


def post_deal(product: dict, bot_token: str, channel_id: str) -> bool:
    bot = telegram.Bot(token=bot_token)
    caption = format_message(product)

    url = product.get("affiliate_url", "")
    markup = _buy_button(url)

    async def _run():
        print(f"  URL: {url}")
        if product.get("image_url"):
            photo = _download_image(product["image_url"])
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
                except Exception as e:
                    print(f"  Photo send failed: {e}")
        await bot.send_message(
            chat_id=channel_id,
            text=caption,
            parse_mode="MarkdownV2",
            reply_markup=markup,
        )
        return True

    try:
        return asyncio.run(_run())
    except Exception as e:
        print(f"Failed to post {product.get('name', '?')}: {e}")
        return False
