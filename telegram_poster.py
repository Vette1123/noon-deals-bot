import asyncio
import re
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

def post_deal(product: dict, bot_token: str, channel_id: str) -> bool:
    bot = telegram.Bot(token=bot_token)
    caption = format_message(product)

    async def _run():
        if product.get("image_url"):
            print(f"  Sending photo: {product['image_url']}")
            try:
                await bot.send_photo(chat_id=channel_id, photo=product["image_url"],
                                     caption=caption, parse_mode="MarkdownV2")
                return True
            except Exception as e:
                print(f"  Photo failed ({e}), falling back to text")
        await bot.send_message(chat_id=channel_id, text=caption, parse_mode="MarkdownV2")
        return True

    try:
        return asyncio.run(_run())
    except Exception as e:
        print(f"Failed to post {product.get('name', '?')}: {e}")
        return False
