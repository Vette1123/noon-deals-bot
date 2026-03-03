import json
import asyncio
import re
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup

# Products page filtered to ≥20% discount, sorted by best discount first
DEALS_URL = (
    "https://www.noon.com/egypt-en/all-products/"
    "?f[discount_percent][min]=20&sort[by]=discount_percent&sort[order]=desc"
)


async def _fetch_html(url: str) -> str:
    """Fetch a JS-rendered Noon page using headless Chromium."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-EG",
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            try:
                await page.wait_for_selector("[data-qa='product-block']", timeout=15000)
            except PlaywrightTimeout:
                pass
            html = await page.content()
        finally:
            await browser.close()
    return html


def fetch_deals_page() -> str:
    """Fetch the Noon Egypt discounted products page using headless browser."""
    return asyncio.run(_fetch_html(DEALS_URL))


def parse_products_from_html(html: str) -> list[dict]:
    """
    Extract products from rendered HTML.
    Tries __NEXT_DATA__ JSON first (SSR), falls back to parsing product card HTML (CSR).
    Returns list of dicts: name, url, image_url, sale_price, original_price, discount_pct, sku
    """
    # 1. Try __NEXT_DATA__ (server-side rendered pages)
    products = _parse_next_data(html)
    if products:
        return products

    # 2. Fall back to HTML product cards (client-side rendered pages)
    return _parse_product_cards(html)


def _parse_next_data(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if not script_tag:
        return []
    try:
        data = json.loads(script_tag.string)
    except (json.JSONDecodeError, TypeError):
        return []
    items = _extract_items(data)
    products = []
    for item in items:
        try:
            product = _normalize_item(item)
            if product:
                products.append(product)
        except (KeyError, TypeError):
            continue
    return products


def _parse_product_cards(html: str) -> list[dict]:
    """Parse product cards from Playwright-rendered HTML."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("div", {"data-qa": "product-block"})
    if not cards:
        print(f"Warning: no product-block cards found. Page length: {len(html)}")
        return []
    products = []
    for card in cards:
        try:
            product = _parse_card(card)
            if product:
                products.append(product)
        except Exception:
            continue
    return products


def _parse_card(card) -> dict | None:
    link_tag = card.find("a", href=True)
    if not link_tag:
        return None
    href = link_tag["href"]
    url = href if href.startswith("http") else f"https://www.noon.com{href}"

    sku_match = re.search(r"/p/([A-Z0-9]+)", url)
    sku = sku_match.group(1) if sku_match else None

    name_tag = card.find(attrs={"data-qa": "product-name"}) or card.find("h2") or card.find("h3")
    name = name_tag.get_text(strip=True) if name_tag else None

    sale_tag = card.find(attrs={"data-qa": "product-price"})
    orig_tag = card.find(attrs={"data-qa": "product-was-price"}) or card.find("s")
    sale_price = _extract_price(sale_tag)
    original_price = _extract_price(orig_tag) or sale_price

    badge = card.find(attrs={"data-qa": "product-discount"})
    discount_pct = 0
    if badge:
        m = re.search(r"(\d+)", badge.get_text())
        discount_pct = int(m.group(1)) if m else 0
    if not discount_pct and original_price and sale_price and float(original_price) > float(sale_price):
        discount_pct = round((1 - float(sale_price) / float(original_price)) * 100)

    img_tag = card.find("img")
    image_url = None
    if img_tag:
        image_url = img_tag.get("src") or img_tag.get("data-src")

    if not all([name, sale_price]):
        return None

    return {
        "name": name,
        "sku": sku or re.sub(r"[^A-Z0-9]", "", name.upper())[:15],
        "url": url,
        "image_url": image_url,
        "sale_price": float(sale_price),
        "original_price": float(original_price),
        "discount_pct": int(discount_pct),
    }


def _extract_price(tag) -> float | None:
    if not tag:
        return None
    text = tag.get_text(strip=True).replace(",", "")
    m = re.search(r"[\d]+\.?\d*", text)
    return float(m.group()) if m else None


def _extract_items(data: dict) -> list:
    """Try multiple known paths to find the product list in Next.js data."""
    paths = [
        ["props", "pageProps", "catalog", "items"],
        ["props", "pageProps", "initialData", "catalog", "items"],
        ["props", "pageProps", "products"],
        ["props", "pageProps", "items"],
        ["props", "pageProps", "initialState", "catalog", "items"],
    ]
    for path in paths:
        node = data
        try:
            for key in path:
                node = node[key]
            if isinstance(node, list) and len(node) > 0:
                return node
        except (KeyError, TypeError):
            continue
    return []


def _normalize_item(item: dict) -> dict | None:
    """Normalize a raw item dict into a consistent product dict."""
    name = item.get("name") or item.get("title")
    sku = item.get("sku") or item.get("id")
    slug = item.get("slug") or item.get("url_key") or sku

    sale_price = item.get("sale_price") or item.get("now_price")
    original_price = item.get("price") or item.get("was_price") or sale_price
    discount_pct = item.get("discount") or item.get("discount_percent") or 0

    if not discount_pct and original_price and sale_price and float(original_price) > float(sale_price):
        discount_pct = round((1 - float(sale_price) / float(original_price)) * 100)

    images = item.get("image_keys") or item.get("images") or []
    image_url = images[0] if images else None

    if not all([name, sku, sale_price]):
        return None

    return {
        "name": name,
        "sku": sku,
        "url": f"https://www.noon.com/egypt-en/{slug}/p/{sku}/",
        "image_url": image_url,
        "sale_price": float(sale_price),
        "original_price": float(original_price),
        "discount_pct": int(discount_pct),
    }
