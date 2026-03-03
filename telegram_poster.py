import asyncio
import re
import requests
from io import BytesIO
import telegram


def _escape_md2(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", str(text))


def format_message(product: dict) -> str:
    name = _escape_md2(product["name"])
    sale = _escape_md2(f"{product['sale_price']:,.0f}")
    orig = _escape_md2(f"{product['original_price']:,.0f}")
    disc = _escape_md2(f"{product['discount_pct']}%")
    url  = product["affiliate_url"]
    return (
        f"🔥 *{name}*\n\n"
        f"💰 EGP {sale} ~\\(كان EGP {orig}\\)~\n"
        f"📉 خصم {disc}\n\n"
        f"🛒 [اشتري دلوقتي]({url})"
    )


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

    async def _run():
        if product.get("image_url"):
            photo = _download_image(product["image_url"])
            if photo:
                try:
                    await bot.send_photo(
                        chat_id=channel_id,
                        photo=photo,
                        caption=caption,
                        parse_mode="MarkdownV2",
                    )
                    return True
                except Exception as e:
                    print(f"  Photo send failed: {e}")
        await bot.send_message(chat_id=channel_id, text=caption, parse_mode="MarkdownV2")
        return True

    try:
        return asyncio.run(_run())
    except Exception as e:
        print(f"Failed to post {product.get('name', '?')}: {e}")
        return False
