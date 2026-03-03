import json
import requests
from bs4 import BeautifulSoup

DEALS_URL = "https://www.noon.com/egypt-en/deals/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_deals_page() -> str:
    """Fetch the Noon Egypt deals page HTML."""
    response = requests.get(DEALS_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def parse_products_from_html(html: str) -> list[dict]:
    """
    Extract product list from Next.js __NEXT_DATA__ JSON embedded in page HTML.
    Returns list of dicts: name, url, image_url, sale_price, original_price, discount_pct, sku
    """
    soup = BeautifulSoup(html, "html.parser")
    script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if not script_tag:
        print("Warning: __NEXT_DATA__ not found in page")
        return []

    try:
        data = json.loads(script_tag.string)
    except (json.JSONDecodeError, TypeError):
        print("Warning: Failed to parse __NEXT_DATA__ JSON")
        return []

    items = _extract_items(data)
    if not items:
        print("Warning: No items found in __NEXT_DATA__")
        return []

    products = []
    for item in items:
        try:
            product = _normalize_item(item)
            if product:
                products.append(product)
        except (KeyError, TypeError):
            continue

    return products


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
