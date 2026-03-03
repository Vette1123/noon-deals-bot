import os
import re
import json
import requests
from bs4 import BeautifulSoup

DEALS_URL = (
    "https://www.noon.com/egypt-en/all-products/"
    "?f[discount_percent][min]=20&sort[by]=discount_percent&sort[order]=desc"
)


def fetch_products() -> list[dict]:
    """Fetch discounted Noon Egypt products via ScraperAPI (bypasses Akamai)."""
    html = _fetch_html()
    products = parse_products_from_html(html)
    if not products:
        raise RuntimeError(
            "Scraped page returned 0 products. "
            "The page structure may have changed — check raw HTML in logs."
        )
    return products


def _fetch_html() -> str:
    """Fetch Noon deals page via ScraperAPI residential proxy."""
    api_key = os.environ.get("SCRAPERAPI_KEY", "")
    if not api_key:
        raise RuntimeError("SCRAPERAPI_KEY is not set. Add it as a GitHub secret.")

    resp = requests.get(
        "http://api.scraperapi.com",
        params={
            "api_key": api_key,
            "url": DEALS_URL,
            "render": "true",
            "country_code": "eg",
        },
        timeout=120,
    )
    resp.raise_for_status()
    html = resp.text
    print(f"  Fetched {len(html):,} bytes via ScraperAPI")
    return html


# ── HTML parsing ──────────────────────────────────────────────────────────────

def parse_products_from_html(html: str) -> list[dict]:
    products = _parse_next_data(html)
    return products or _parse_product_cards(html)


def _parse_next_data(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if not tag:
        return []
    try:
        data = json.loads(tag.string)
    except (json.JSONDecodeError, TypeError):
        return []
    items = _extract_items(data)
    return [p for p in (_normalize_item(i) for i in items) if p]


def _parse_product_cards(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("div", {"data-qa": "product-block"})
    if not cards:
        print(f"Warning: no product-block cards found. Page length: {len(html):,}")
        return []
    results = []
    for card in cards:
        try:
            p = _parse_card(card)
            if p:
                results.append(p)
        except Exception:
            continue
    return results


def _parse_card(card) -> dict | None:
    link = card.find("a", href=True)
    if not link:
        return None
    href = link["href"]
    url = href if href.startswith("http") else f"https://www.noon.com{href}"
    sku_match = re.search(r"/p/([A-Z0-9]+)", url)
    sku = sku_match.group(1) if sku_match else None

    name_tag = (
        card.find(attrs={"data-qa": "product-name"})
        or card.find("h2")
        or card.find("h3")
    )
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

    img = card.find("img")
    image_url = (img.get("src") or img.get("data-src")) if img else None

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
            if isinstance(node, list) and node:
                return node
        except (KeyError, TypeError):
            continue
    return []


def _normalize_item(item: dict) -> dict | None:
    name = item.get("name") or item.get("title")
    sku = item.get("sku") or item.get("id")
    slug = item.get("slug") or item.get("url_key") or sku

    sale_price = item.get("sale_price") or item.get("now_price")
    original_price = item.get("price") or item.get("was_price") or sale_price
    discount_pct = item.get("discount") or item.get("discount_percent") or 0

    if not discount_pct and original_price and sale_price:
        op, sp = float(original_price), float(sale_price)
        if op > sp:
            discount_pct = round((1 - sp / op) * 100)

    images = item.get("image_keys") or item.get("images") or []
    image_url = images[0] if images else None

    if not all([name, sku, sale_price]):
        return None

    return {
        "name": name,
        "sku": str(sku),
        "url": f"https://www.noon.com/egypt-en/{slug}/p/{sku}/",
        "image_url": image_url,
        "sale_price": float(sale_price),
        "original_price": float(original_price),
        "discount_pct": int(discount_pct),
    }
