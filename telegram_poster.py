import asyncio
import os
import re
import requests
from io import BytesIO
from urllib.parse import quote
import telegram
from telegram import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import RetryAfter


def _escape_md2(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", str(text))


def with_affiliate_utms(url: str) -> str:
    """Decorate a noon.com URL with this affiliate's tracking UTMs.

    Idempotent (URLs already carrying utm_medium are returned unchanged) and
    opt-out-able (set NOON_AFFILIATE_MEDIUM to empty to disable, e.g. local dev).
    Defaults are this project's real campaign IDs — they are not secrets, they
    appear in every public link the affiliate panel generates.

    Public because every surface that publishes a product link has to earn on it:
    Telegram, the static site, and the Facebook crosspost all go through here.
    """
    if not url or "utm_medium=" in url:
        return url
    # Read out of a link the panel generated on 2026-07-28, by resolving the
    # short link it hands you and reading the query it lands on. The previous
    # value here (AFFc944753cc349) was not this account's ID, so every click the
    # bot ever sent was unattributed. Re-check the same way if commissions stop.
    medium = os.environ.get("NOON_AFFILIATE_MEDIUM", "AFFccacc092d97d")
    if not medium:
        return url
    campaign = os.environ.get("NOON_AFFILIATE_CAMPAIGN", "CMP2ce0b63a6a1anoon")
    source = os.environ.get("NOON_AFFILIATE_SOURCE", "C1000264L")
    qs = (
        f"utm_campaign={campaign}"
        f"&utm_medium={medium}"
        f"&utm_source={source}"
        f"&adjust_deeplink_js=1"
    )
    base, _, frag = url.partition("#")
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{qs}" + (f"#{frag}" if frag else "")


def _trust_badges(product: dict) -> list[str]:
    """Short trust markers — they lift click-through, which is what gets paid.

    All literals here are already MarkdownV2-safe (no reserved characters), so
    they deliberately skip `_escape_md2`.
    """
    badges = []
    if product.get("is_bestseller"):
        badges.append("🔥 الأكثر مبيعاً")
    if product.get("fulfilled_by_noon"):
        badges.append("✅ شحن نون")
    if product.get("free_delivery"):
        badges.append("🚚 توصيل مجاني")
    return badges


def format_message(product: dict, coupon: str = "") -> str:
    name = _escape_md2(product["name"])
    sale = _escape_md2(f"{product['sale_price']:,.0f}")
    orig = _escape_md2(f"{product['original_price']:,.0f}")
    disc = _escape_md2(f"{product['discount_pct']}%")
    url  = with_affiliate_utms(product.get("url", ""))

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

    badges = _trust_badges(product)
    if badges:
        lines.append(" • ".join(badges))

    # Coupon (tap-to-copy on mobile Telegram via MarkdownV2 code span).
    # The value is constrained to [A-Za-z0-9_-] so no escaping is needed inside the span.
    if coupon and re.fullmatch(r"[A-Za-z0-9_-]+", coupon):
        lines.append("")
        lines.append(f"🎟️ كود خصم إضافي عند الدفع: `{coupon}`")

    lines.append("")
    lines.append(f"👉 *[🛒 اشتري دلوقتي]({url})*")

    return "\n".join(lines)


def channel_share_url(channel_id: str, product_name: str = "") -> str:
    """A `t.me/share` link that forwards the *channel*, not the deal.

    Forwards are how a Telegram channel actually grows, and a subscriber is worth
    far more than the single click a shared product link would earn. Only public
    @handles can be shared this way — numeric chat IDs have no public URL.
    """
    handle = (channel_id or "").strip().lstrip("@")
    if not handle or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", handle):
        return ""
    text = quote(f"{product_name}\nعروض نون كل يوم 🔥", safe="")
    return f"https://t.me/share/url?url={quote(f'https://t.me/{handle}', safe='')}&text={text}"


def _build_markup(url: str, coupon: str = "", share_url: str = "") -> InlineKeyboardMarkup:
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
    buy = InlineKeyboardButton("🛒 اشتري دلوقتي", url=url)
    if share_url:
        # Same row: sharing must never compete with buying for vertical attention.
        rows.append([buy, InlineKeyboardButton("📤 شارك", url=share_url)])
    else:
        rows.append([buy])
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

    url = with_affiliate_utms(product.get("url", ""))
    markup = _build_markup(url, coupon, channel_share_url(channel_id, product.get("name", "")))

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
