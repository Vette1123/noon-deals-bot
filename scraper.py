import os
import re
import json
import time
import random
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

# Optional SOCKS5/HTTP proxy for noon.com traffic only (not Telegram).
# In CI we route through Cloudflare WARP to escape datacenter-IP reputation
# checks by Akamai — see .github/workflows/bot.yml.
_PROXY_URL = os.environ.get("SCRAPER_PROXY")
_PROXIES = {"http": _PROXY_URL, "https": _PROXY_URL} if _PROXY_URL else None

# noon dropped the `discount_percent` facet and the `sort[order]` param in the
# 2026-06-30 site rewrite — both are now silently ignored (the server falls back
# to `sort[by]=popularity`). The closest durable substitute is the
# `min_offer_price` facet ("Price drop"), which only returns items currently at
# their lowest price in a year. Real discount filtering happens in filters.py.
DEALS_URL = (
    "https://www.noon.com/egypt-en/all-products/"
    "?limit=50&f[min_offer_price]=365_days&sort[by]=popularity&sort[dir]=desc"
)


MAX_PAGES = 10
PAGES_PER_RUN = 2


def fetch_products(start_page: int = 1) -> list[dict]:
    """Fetch PAGES_PER_RUN pages starting from start_page."""
    all_products: list[dict] = []
    seen_skus: set[str] = set()

    for page in range(start_page, start_page + PAGES_PER_RUN):
        html = _fetch_html(page)
        products = parse_products_from_html(html)

        new_count = 0
        for p in products:
            if p["sku"] not in seen_skus:
                seen_skus.add(p["sku"])
                all_products.append(p)
                new_count += 1

        print(f"  Page {page}: {len(products)} products ({new_count} new)")

        if len(products) == 0:
            print(f"  Page {page} empty — reached end of results.")
            break

    if not all_products:
        print("Warning: Scraped 0 products. Page structure may have changed or we reached the end.")
    return all_products


# Impersonation targets to rotate across on retries (newest first).
# Rotating varies the JA3/JA4 + HTTP/2 fingerprint if Akamai flags a specific
# profile. Only targets available in curl_cffi >=0.15 are listed.
_IMPERSONATE_POOL = ["chrome146", "chrome142", "chrome136", "chrome131"]


def _fetch_html(page: int = 1, max_attempts: int = 4) -> str:
    """Fetch a Noon deals page using Chrome TLS impersonation (curl_cffi).

    Retries on Akamai 403s (transient bot-check) and 5xx/network errors
    (noon's origin occasionally 504s on the filtered deals URL).

    Uses a Session with a homepage warm-up request so the Akamai bot-manager
    cookie is set before the deals URL is hit — a cold request to a deep
    filtered URL is a classic bot signal.
    """
    url = DEALS_URL if page == 1 else f"{DEALS_URL}&page={page}"
    last_err: str | None = None

    if _PROXIES:
        print(f"  Using proxy: {_PROXY_URL}")
    with cffi_requests.Session(proxies=_PROXIES) as session:
        # Warm-up: looks like a real user landing on the homepage first. Failure
        # here isn't fatal — the main request has its own retry loop.
        try:
            session.get(
                "https://www.noon.com/egypt-en/",
                impersonate=_IMPERSONATE_POOL[0],
                timeout=30,
            )
        except Exception as e:
            print(f"  Warm-up request failed (continuing anyway): {e}")

        for attempt in range(1, max_attempts + 1):
            impersonate = _IMPERSONATE_POOL[(attempt - 1) % len(_IMPERSONATE_POOL)]
            try:
                resp = session.get(
                    url,
                    headers={"Referer": "https://www.noon.com/egypt-en/"},
                    impersonate=impersonate,
                    timeout=90,
                )
            except Exception as e:
                last_err = f"network error: {e}"
            else:
                if resp.ok and _is_akamai_challenge(resp.text):
                    # Akamai serves the JS bot-check with HTTP 200 — treat it as a
                    # block, not as a page, or we'd "successfully" parse 0 products.
                    last_err = f"Akamai JS challenge ({len(resp.text):,} bytes)"
                elif resp.ok:
                    print(f"  Page {page}: fetched {len(resp.text):,} bytes ({impersonate})")
                    return resp.text
                else:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                # 4xx other than 403 is a hard no (404, 410, …) — don't burn retries.
                if 400 <= resp.status_code < 500 and resp.status_code != 403:
                    break

            print(f"  Page {page} attempt {attempt}/{max_attempts} failed ({impersonate}): {last_err}")
            if attempt < max_attempts:
                time.sleep(2 * attempt + random.uniform(0.5, 1.5))

    raise RuntimeError(f"Fetch failed for page {page} after {max_attempts} attempts: {last_err}")


_CHALLENGE_MARKERS = ("sec-if-cpt-container", "_sec_bot_detect", "Powered and protected by")


def _is_akamai_challenge(html: str) -> bool:
    """Akamai's interstitial returns HTTP 200 with a tiny JS bot-check page."""
    return len(html) < 50_000 and any(m in html for m in _CHALLENGE_MARKERS)


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_products_from_html(html: str) -> list[dict]:
    # Current: reference-serialized JS payload inlined in the SSR HTML (hits:$R[n]=[…])
    products = _parse_embedded_payload(html)
    if products:
        return products
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


# ── Embedded JS payload (current noon.com format) ─────────────────────────────
#
# Since 2026-06-30 noon inlines the catalog as *JavaScript*, not JSON:
#
#   …,hits:$R[8621]=[$R[8622]={offer_code:"e162…",sku_config:"N23157381A",…}],…
#
# Every value may be prefixed with a `$R[n]=` alias binding. Keys are unquoted,
# booleans are minified to `!0`/`!1`, and strings use JS escapes (`\x3C`). It is
# not JSON, so `json.loads` cannot touch it — hence the small literal parser
# below. Field names inside each hit are unchanged from the old RSC payload, so
# `_normalize_item` still applies as-is.

_HITS_RE = re.compile(r"hits:(?:\$R\[\d+\]=)?\[")
_REF_RE = re.compile(r"\$R\[\d+\]=")
_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_NUM_RE = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_JS_WS = " \t\r\n"
_JS_ESCAPES = {
    '"': '"', "'": "'", "\\": "\\", "/": "/", "`": "`",
    "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "0": "\0",
}
# No token here is a prefix of another, so match order does not matter.
_JS_LITERALS = (
    ("undefined", None), ("void 0", None), ("false", False),
    ("true", True), ("null", None), ("NaN", None), ("!0", True), ("!1", False),
)
# A truncated or unexpected payload should fall through to the next parser, not
# kill the run — the literal parser signals all of those by raising.
_JS_PARSE_ERRORS = (ValueError, IndexError, RecursionError)


def _parse_embedded_payload(html: str) -> list[dict]:
    """Products from the largest `hits:[…]` array in the page.

    Largest, not first: recommendation rails and sponsored strips use the same key,
    and on some pages they are serialized ahead of the main catalog.
    """
    best: list[dict] = []
    for match in _HITS_RE.finditer(html):
        try:
            items, _ = _js_parse_value(html, match.end() - 1)
        except _JS_PARSE_ERRORS:
            continue
        if not isinstance(items, list):
            continue
        products = [p for p in (_normalize_item(i) for i in items if isinstance(i, dict)) if p]
        if len(products) > len(best):
            best = products
    return best


def _js_skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in _JS_WS:
        i += 1
    return i


def _fix_surrogates(text: str) -> str:
    """Recombine \\uD83D\\uDE00-style surrogate pairs into real characters."""
    if not any("\ud800" <= c <= "\udfff" for c in text):
        return text
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def _js_parse_string(text: str, i: int) -> tuple[str, int]:
    quote = text[i]
    i += 1
    out: list[str] = []
    while i < len(text):
        char = text[i]
        if char == quote:
            return _fix_surrogates("".join(out)), i + 1
        if char != "\\":
            out.append(char)
            i += 1
            continue
        esc = text[i + 1]
        if esc == "x":
            out.append(chr(int(text[i + 2:i + 4], 16)))
            i += 4
        elif esc == "u" and text[i + 2] == "{":
            close = text.index("}", i + 3)
            out.append(chr(int(text[i + 3:close], 16)))
            i = close + 1
        elif esc == "u":
            out.append(chr(int(text[i + 2:i + 6], 16)))
            i += 6
        elif esc == "\n":  # line continuation
            i += 2
        else:
            out.append(_JS_ESCAPES.get(esc, esc))
            i += 2
    raise ValueError("unterminated string")


def _js_parse_key(text: str, i: int) -> tuple[str, int]:
    if text[i] in "\"'":
        return _js_parse_string(text, i)
    match = _IDENT_RE.match(text, i) or _NUM_RE.match(text, i)
    if not match:
        raise ValueError(f"bad object key at {i}: {text[i:i + 20]!r}")
    return match.group(0), match.end()


def _js_parse_object(text: str, i: int) -> tuple[dict, int]:
    obj: dict = {}
    i = _js_skip_ws(text, i + 1)
    if text[i] == "}":
        return obj, i + 1
    while True:
        key, i = _js_parse_key(text, _js_skip_ws(text, i))
        i = _js_skip_ws(text, i)
        if text[i] != ":":
            raise ValueError(f"expected ':' at {i}")
        obj[key], i = _js_parse_value(text, i + 1)
        i = _js_skip_ws(text, i)
        if text[i] == ",":
            i += 1
        elif text[i] == "}":
            return obj, i + 1
        else:
            raise ValueError(f"expected ',' or '}}' at {i}")


def _js_parse_array(text: str, i: int) -> tuple[list, int]:
    arr: list = []
    i = _js_skip_ws(text, i + 1)
    if text[i] == "]":
        return arr, i + 1
    while True:
        value, i = _js_parse_value(text, i)
        arr.append(value)
        i = _js_skip_ws(text, i)
        if text[i] == ",":
            i += 1
        elif text[i] == "]":
            return arr, i + 1
        else:
            raise ValueError(f"expected ',' or ']' at {i}")


def _js_parse_value(text: str, i: int):
    i = _js_skip_ws(text, i)
    # Strip any number of `$R[n]=` alias bindings preceding the actual value.
    while (ref := _REF_RE.match(text, i)) is not None:
        i = ref.end()
    if i >= len(text):
        raise ValueError("unexpected end of payload")
    char = text[i]
    if char == "{":
        return _js_parse_object(text, i)
    if char == "[":
        return _js_parse_array(text, i)
    if char in "\"'":
        return _js_parse_string(text, i)
    for token, value in _JS_LITERALS:
        if text.startswith(token, i):
            return value, i + len(token)
    match = _NUM_RE.match(text, i)
    if match:
        return _js_number(match.group(0)), match.end()
    raise ValueError(f"unexpected token at {i}: {text[i:i + 30]!r}")


def _js_number(raw: str) -> int | float:
    if any(c in raw for c in ".eE"):
        return float(raw)
    return int(raw)


_CATALOG_KEYS = ("ssrCatalog", "catalogData", "ssrProductList", "productList", "catalog")
_ITEMS_KEYS   = ("hits", "items", "products", "results")


def _extract_catalog_items(data) -> list:
    """Try all known catalog wrapper keys, return first non-empty items list."""
    for catalog_key in _CATALOG_KEYS:
        catalog = _find_key(data, catalog_key)
        if not catalog:
            continue
        print(f"  Found catalog key '{catalog_key}': {list(catalog.keys()) if isinstance(catalog, dict) else type(catalog)}")
        if isinstance(catalog, list):
            return catalog
        for items_key in _ITEMS_KEYS:
            items = catalog.get(items_key)
            if items:
                return items
        print(f"  '{catalog_key}' found but none of {_ITEMS_KEYS} had data")
    return []


def _parse_rsc_chunk(raw: str) -> list[dict]:
    """Parse one RSC chunk string (everything after the colon) for products."""
    decoder = json.JSONDecoder()
    colon = raw.find(":")
    if colon < 0:
        return []
    try:
        data = json.loads(raw[colon + 1:])
    except json.JSONDecodeError:
        return []
    items = _extract_catalog_items(data)
    if not items:
        return []
    results = [p for p in (_normalize_item(i) for i in items) if p]
    return results


def _parse_rsc_payload(html: str) -> list[dict]:
    """
    Parse the Next.js App Router RSC streaming format:
      self.__next_f.push([1, "CHUNK_ID:JSON_PAYLOAD"])
    Product data lives under a catalog key inside one of these chunks.
    """
    soup = BeautifulSoup(html, "html.parser")
    decoder = json.JSONDecoder()

    # Collect all RSC push chunks that might contain product data
    candidate_chunks: list[str] = []
    for script in soup.find_all("script"):
        text = script.string or ""
        idx = text.find("self.__next_f.push(")
        if idx < 0:
            continue
        start = idx + len("self.__next_f.push(")
        try:
            arr, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if not (isinstance(arr, list) and len(arr) >= 2 and isinstance(arr[1], str)):
            continue
        raw = arr[1]
        # Check for any catalog-related keyword before doing heavier parsing
        if any(k in raw for k in _CATALOG_KEYS):
            results = _parse_rsc_chunk(raw)
            if results:
                return results
            candidate_chunks.append(raw[:120])  # keep snippet for debug

    if candidate_chunks:
        print(f"  RSC chunks with catalog keys found but no products extracted. Snippets: {candidate_chunks[:3]}")

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
    # sku_config = parent/configurable SKU (used in noon.com URLs, always ends in "A")
    # catalog_sku may be variant-specific (ends in "V", "B", etc.) — wrong for URLs
    sku_config = item.get("sku_config") or item.get("catalog_sku") or item.get("sku") or item.get("id")
    sku = item.get("sku") or sku_config
    catalog_sku = sku_config  # alias for rest of function

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
            # Floor, not round — matches the "48% OFF" badge noon renders itself.
            discount_pct = int((1 - sp / op) * 100)

    image_url = _pick_image_url(item)

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

    # Out-of-stock offers still appear in the catalog. Posting them burns a slot
    # and sends readers to a dead "sold out" page.
    if item.get("is_buyable") is False:
        return None

    # Strip Algolia variant suffix (e.g. "ZA0AB67C35C636E494094Z-1" → "ZA0AB67C35C636E494094Z")
    clean_sku = re.sub(r"-\d+$", "", str(catalog_sku))

    # `offer_code` pins the exact seller/offer the discount belongs to — without it
    # noon may land the user on a different (pricier) offer for the same SKU.
    offer_code = item.get("offer_code")
    offer_qs = f"?o={offer_code}" if offer_code else ""

    return {
        "name": name,
        "sku": clean_sku,
        "url": f"https://www.noon.com/egypt-en/{slug}/{clean_sku}/p/{offer_qs}",
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


def _pick_image_url(item: dict) -> str | None:
    """Best available product image.

    Current payloads ship ready-made `image_url`/`image_urls`. Older ones only had
    an `image_key` that needed the `_t300.jpg` CDN suffix — keep that path for the
    fallback parsers, but never re-prefix a value that is already a URL.
    """
    for key in ("image_url", "image_urls"):
        value = item.get(key)
        if isinstance(value, list):
            value = value[0] if value else None
        if value:
            return value

    image_key = item.get("image_key")
    if not image_key:
        keys = item.get("image_keys") or []
        image_key = keys[0] if keys else None
    if not image_key:
        return None
    if str(image_key).startswith("http"):
        return image_key
    return f"https://f.nooncdn.com/p/{image_key}_t300.jpg"


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


# "plp-product-box" is the current card marker; "product-block" was its pre-2026-06-30
# name. CSS class names are content-hashed per build, so data-qa is the only stable hook.
_CARD_QA_NAMES = ("plp-product-box", "product-block")


def _parse_product_cards(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all(attrs={"data-qa": lambda v: v in _CARD_QA_NAMES})
    if not cards:
        print(f"Warning: no product cards found. Page length: {len(html):,}")
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


def _find_by_qa(card, *names: str):
    """First descendant whose data-qa matches any of `names`, in the given order."""
    for name in names:
        tag = card.find(attrs={"data-qa": name})
        if tag:
            return tag
    return None


def _parse_card(card) -> dict | None:
    link = card.find("a", href=True)
    if not link:
        return None
    href = link["href"]
    url = href if href.startswith("http") else f"https://www.noon.com{href}"
    # Current URLs put the SKU before the /p/ marker (…/{slug}/{SKU}/p/?o=…);
    # older ones put it after. Accept both.
    sku_match = re.search(r"/([A-Z0-9]+)/p/", url) or re.search(r"/p/([A-Z0-9]+)", url)
    sku = sku_match.group(1) if sku_match else None

    name_tag = (
        _find_by_qa(card, "plp-product-box-name", "product-name")
        or card.find("h2")
        or card.find("h3")
    )
    name = name_tag.get_text(strip=True) if name_tag else None

    sale_tag = _find_by_qa(card, "plp-product-box-price", "product-price")
    orig_tag = _find_by_qa(card, "product-was-price") or card.find("s")
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
