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
    """Fetch discounted Noon Egypt products via Zenrows (bypasses Akamai)."""
    html = _fetch_html()
    products = parse_products_from_html(html)
    if not products:
        raise RuntimeError(
            "Scraped page returned 0 products. "
            "The page structure may have changed — check raw HTML in logs."
        )
    return products


def _fetch_html() -> str:
    """Fetch Noon deals page via Zenrows (Akamai anti-bot bypass)."""
    api_key = os.environ.get("ZENROWS_API_KEY", "")
    if not api_key:
        raise RuntimeError("ZENROWS_API_KEY is not set. Add it as a GitHub secret.")

    params = {"apikey": api_key, "url": DEALS_URL, "antibot": "true", "js_render": "true"}
    resp = requests.get("https://api.zenrows.com/v1/", params=params, timeout=120)

    if resp.status_code == 422:
        print("  Zenrows 422 — retrying with premium proxy...")
        params["premium_proxy"] = "true"
        resp = requests.get("https://api.zenrows.com/v1/", params=params, timeout=120)

    if not resp.ok:
        raise RuntimeError(f"Zenrows error {resp.status_code}: {resp.text[:300]}")
    print(f"  Fetched {len(resp.text):,} bytes via Zenrows")
    return resp.text


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_products_from_html(html: str) -> list[dict]:
    # Next.js App Router RSC streaming payload (self.__next_f.push)
    products = _parse_rsc_payload(html)
    if products:
        return products
    # Legacy Next.js Pages Router (__NEXT_DATA__ script tag)
    products = _parse_next_data(html)
    if products:
        return products
    # Last resort: HTML product cards
    return _parse_product_cards(html)


def _parse_rsc_payload(html: str) -> list[dict]:
    """
    Parse the Next.js App Router RSC streaming format:
      self.__next_f.push([1, "CHUNK_ID:JSON_PAYLOAD"])
    Product data lives under ssrCatalog.items inside one of these chunks.
    """
    soup = BeautifulSoup(html, "html.parser")
    decoder = json.JSONDecoder()

    for script in soup.find_all("script"):
        text = script.string or ""
        if "ssrCatalog" not in text:
            continue

        idx = text.find("self.__next_f.push(")
        if idx < 0:
            continue

        # Parse the JS array argument as JSON
        start = idx + len("self.__next_f.push(")
        try:
            arr, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue

        if not (isinstance(arr, list) and len(arr) >= 2 and isinstance(arr[1], str)):
            continue

        raw = arr[1]  # e.g. "29:[["$","$L69",null,{"ssrCatalog":{...}}]]"
        colon = raw.find(":")
        if colon < 0:
            continue
        try:
            data = json.loads(raw[colon + 1:])
        except json.JSONDecodeError:
            continue

        catalog = _find_key(data, "ssrCatalog")
        if not catalog:
            continue

        print(f"  ssrCatalog keys: {list(catalog.keys())}")
        items = (
            catalog.get("hits") or catalog.get("items")
            or catalog.get("products") or []
        )
        if not items:
            print("  ssrCatalog found but hits/items list is empty")
            continue

        results = [p for p in (_normalize_item(i) for i in items) if p]
        if results:
            return results

    return []


def _find_key(data, key):
    """Recursively find first occurrence of key in nested dicts/lists."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for v in data.values():
            found = _find_key(v, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_key(item, key)
            if found is not None:
                return found
    return None


def _normalize_item(item: dict) -> dict | None:
    name = item.get("name") or item.get("title")
    # catalog_sku is the parent product SKU used in noon.com URLs
    catalog_sku = item.get("catalog_sku") or item.get("sku") or item.get("id")
    sku = item.get("sku") or catalog_sku

    raw = item.get("url") or item.get("slug") or item.get("url_key") or ""
    slug = re.sub(r"^[a-z]+-[a-z]+/", "", raw) or catalog_sku

    sale_price = (
        item.get("sale_price") or item.get("now_price")
        or item.get("price") or item.get("selling_price")
    )
    original_price = (
        item.get("price") or item.get("was_price")
        or item.get("original_price") or item.get("mrp")
        or sale_price
    )
    discount_pct = (
        item.get("discount") or item.get("discount_percent")
        or item.get("discount_percentage") or 0
    )
    if not discount_pct and original_price and sale_price:
        op, sp = float(original_price), float(sale_price)
        if op > sp:
            discount_pct = round((1 - sp / op) * 100)

    image_key = item.get("image_key")
    if not image_key:
        keys = item.get("image_keys") or []
        image_key = keys[0] if keys else None
    image_url = f"https://f.nooncdn.com/p/{image_key}_t300.jpg" if image_key else None

    # Rating
    rating_raw = item.get("product_rating")
    if isinstance(rating_raw, dict):
        rating = rating_raw.get("value") or rating_raw.get("average")
        rating_count = rating_raw.get("count") or rating_raw.get("nb_reviews")
    elif rating_raw:
        rating, rating_count = float(rating_raw), None
    else:
        rating, rating_count = None, None

    if not all([name, catalog_sku, sale_price]):
        return None

    # Strip Algolia variant suffix (e.g. "ZA0AB67C35C636E494094Z-1" → "ZA0AB67C35C636E494094Z")
    clean_sku = re.sub(r"-\d+$", "", str(catalog_sku))

    return {
        "name": name,
        "sku": clean_sku,
        "url": f"https://www.noon.com/egypt-en/{slug}/p/{clean_sku}/",
        "image_url": image_url,
        "sale_price": float(sale_price),
        "original_price": float(original_price),
        "discount_pct": int(discount_pct),
        "brand": item.get("brand") or "",
        "rating": round(float(rating), 1) if rating else None,
        "rating_count": int(rating_count) if rating_count else None,
        "store_name": item.get("store_name") or "",
        "estimated_delivery": re.sub(r"<[^>]+>", "", item.get("estimated_delivery_date") or "").strip(),
    }


# ── Legacy HTML parsers (kept for tests / fallback) ───────────────────────────

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
