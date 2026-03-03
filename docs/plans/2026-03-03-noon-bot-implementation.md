# Noon Affiliate Telegram Bot — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an automated Python bot that scrapes Noon Egypt deals every 4 hours, attaches affiliate links, and posts them to a Telegram channel — hosted free on GitHub Actions.

**Architecture:** Python script runs on GitHub Actions cron schedule. Scrapes noon.com/egypt-en by parsing the Next.js `__NEXT_DATA__` JSON embedded in the page HTML (more reliable than CSS selectors). Posts deals to Telegram using Bot API. Tracks posted products in `posted.json` committed back to the repo to prevent duplicates.

**Tech Stack:** Python 3.11, requests, BeautifulSoup4, python-telegram-bot 20.x, GitHub Actions

---

## Pre-requisites (manual steps before coding)

1. **Revoke old bot token** — Go to @BotFather → `/revoke` → select @NoonHotDealsBot → copy new token
2. **Add bot to channel** — Go to @noon_hot_deals → Settings → Administrators → Add Admin → search @NoonHotDealsBot → give "Post Messages" permission
3. **Verify affiliate link format** — Log into https://affiliates.noon.partners → find "Create Link" or "Deep Link" tool → create one test link for any Noon Egypt product → note the URL format (we'll use it in Task 3)
4. **Create GitHub repo** — Go to github.com → New repo → name it `noon-deals-bot` → private → no README (we'll push existing code)

---

### Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `posted.json`
- Create: `.env.example`
- Create: `.gitignore`

**Step 1: Create requirements.txt**

```
requests==2.31.0
beautifulsoup4==4.12.3
python-telegram-bot==20.7
```

**Step 2: Create posted.json**

```json
{}
```

**Step 3: Create .env.example**

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHANNEL_ID=@noon_hot_deals
```

**Step 4: Create .gitignore**

```
.env
__pycache__/
*.pyc
.pytest_cache/
```

**Step 5: Commit**

```bash
git add requirements.txt posted.json .env.example .gitignore
git commit -m "feat: project scaffold"
```

---

### Task 2: Affiliate Link Builder

**Files:**
- Create: `affiliate.py`
- Create: `tests/test_affiliate.py`

**Context:** Noon affiliate links work by appending your tracking parameter to any noon.com product URL. The exact parameter needs to be confirmed from your dashboard (Step 3 in Pre-requisites). Most common format is `?o=AFFccacc092d97d` or `?affiliate_id=AFFccacc092d97d`. We'll use `?o=AFFccacc092d97d` — update `AFFILIATE_PARAM` if your dashboard shows a different format.

**Step 1: Write the failing test**

Create `tests/__init__.py` (empty file), then create `tests/test_affiliate.py`:

```python
from affiliate import build_affiliate_link

def test_adds_param_to_clean_url():
    url = "https://www.noon.com/egypt-en/apple-iphone-15/p/N52187204A/"
    result = build_affiliate_link(url)
    assert "AFFccacc092d97d" in result
    assert result.startswith("https://www.noon.com/egypt-en/")

def test_replaces_existing_affiliate_param():
    url = "https://www.noon.com/egypt-en/apple-iphone-15/p/N52187204A/?o=someother"
    result = build_affiliate_link(url)
    assert result.count("AFFccacc092d97d") == 1
    assert "someother" not in result

def test_preserves_other_query_params():
    url = "https://www.noon.com/egypt-en/product/p/SKU123/?color=red"
    result = build_affiliate_link(url)
    assert "color=red" in result
    assert "AFFccacc092d97d" in result
```

**Step 2: Run to verify it fails**

```bash
cd /c/Users/booga/OneDrive/Desktop/noon-deals-bot
pip install -r requirements.txt
python -m pytest tests/test_affiliate.py -v
```

Expected: `ModuleNotFoundError: No module named 'affiliate'`

**Step 3: Implement affiliate.py**

```python
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

AFFILIATE_ID = "AFFccacc092d97d"
# NOTE: Change "o" to the actual parameter name if your dashboard shows a different one
AFFILIATE_PARAM_KEY = "o"

def build_affiliate_link(product_url: str) -> str:
    """Append Noon affiliate tracking parameter to a product URL."""
    parsed = urlparse(product_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params[AFFILIATE_PARAM_KEY] = [AFFILIATE_ID]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_affiliate.py -v
```

Expected: 3 tests PASS

**Step 5: Commit**

```bash
git add affiliate.py tests/
git commit -m "feat: affiliate link builder with tests"
```

---

### Task 3: Noon Scraper

**Files:**
- Create: `scraper.py`
- Create: `tests/test_scraper.py`

**Context:** Noon Egypt is built with Next.js. The page HTML contains a `<script id="__NEXT_DATA__">` tag with all product data as JSON. This is more reliable than CSS selector scraping. We parse that JSON to extract deals. If `__NEXT_DATA__` doesn't contain deals (can vary by page), we fall back to parsing `<script>` tags for product JSON-LD or use BeautifulSoup on product cards.

**Step 1: Write failing tests using mock HTML**

Create `tests/test_scraper.py`:

```python
import json
from unittest.mock import patch, MagicMock
from scraper import parse_products_from_html, fetch_deals_page

MOCK_NEXT_DATA = {
    "props": {
        "pageProps": {
            "catalog": {
                "items": [
                    {
                        "name": "Samsung Galaxy A15",
                        "sku": "N12345678A",
                        "slug": "samsung-galaxy-a15",
                        "sale_price": 2999,
                        "price": 4000,
                        "image_keys": ["https://f.nooncdn.com/p/v1633090704/N12345678A_1.jpg"],
                        "discount": 25
                    },
                    {
                        "name": "Cheap Item",
                        "sku": "N99999999A",
                        "slug": "cheap-item",
                        "sale_price": 100,
                        "price": 110,
                        "image_keys": ["https://f.nooncdn.com/p/v1633090704/N99999999A_1.jpg"],
                        "discount": 9
                    }
                ]
            }
        }
    }
}

MOCK_HTML = f"""
<html><body>
<script id="__NEXT_DATA__" type="application/json">{json.dumps(MOCK_NEXT_DATA)}</script>
</body></html>
"""

def test_parse_products_extracts_fields():
    products = parse_products_from_html(MOCK_HTML)
    assert len(products) == 2
    p = products[0]
    assert p["name"] == "Samsung Galaxy A15"
    assert p["sale_price"] == 2999
    assert p["original_price"] == 4000
    assert p["discount_pct"] == 25
    assert "noon.com/egypt-en" in p["url"]
    assert p["image_url"].startswith("https://")

def test_parse_returns_empty_on_bad_html():
    products = parse_products_from_html("<html><body>no data</body></html>")
    assert products == []
```

**Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_scraper.py -v
```

Expected: `ModuleNotFoundError: No module named 'scraper'`

**Step 3: Implement scraper.py**

```python
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
    Returns list of dicts with: name, url, image_url, sale_price, original_price, discount_pct, sku
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

    # Navigate the JSON tree — path may vary, try common paths
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

    sale_price = item.get("sale_price") or item.get("price") or item.get("now_price")
    original_price = item.get("price") or item.get("was_price") or sale_price
    discount_pct = item.get("discount") or item.get("discount_percent") or 0

    # Calculate discount if not provided
    if not discount_pct and original_price and sale_price and original_price > sale_price:
        discount_pct = round((1 - sale_price / original_price) * 100)

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
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_scraper.py -v
```

Expected: 2 tests PASS

**Step 5: Quick live sanity check (not a test, just verify the scraper works on real data)**

```bash
python -c "
from scraper import fetch_deals_page, parse_products_from_html
html = fetch_deals_page()
products = parse_products_from_html(html)
print(f'Found {len(products)} products')
if products:
    print('First product:', products[0])
"
```

If 0 products found, the `__NEXT_DATA__` path is different. In that case, debug with:

```bash
python -c "
import json, requests
from bs4 import BeautifulSoup
from scraper import HEADERS, DEALS_URL
html = requests.get(DEALS_URL, headers=HEADERS).text
soup = BeautifulSoup(html, 'html.parser')
tag = soup.find('script', {'id': '__NEXT_DATA__'})
if tag:
    data = json.loads(tag.string)
    print(list(data.get('props', {}).get('pageProps', {}).keys()))
else:
    print('No __NEXT_DATA__ found')
"
```

Use the output to update `_extract_items()` paths in scraper.py.

**Step 6: Commit**

```bash
git add scraper.py tests/test_scraper.py
git commit -m "feat: noon deals scraper with next.js data parsing"
```

---

### Task 4: Deal Filter + Duplicate Tracker

**Files:**
- Create: `filters.py`
- Create: `tests/test_filters.py`

**Step 1: Write failing tests**

Create `tests/test_filters.py`:

```python
import json, os, tempfile
from filters import filter_deals, load_posted, save_posted, is_new_product

SAMPLE_PRODUCTS = [
    {"sku": "A1", "name": "Good Deal", "discount_pct": 25, "sale_price": 100, "original_price": 133},
    {"sku": "A2", "name": "Bad Deal", "discount_pct": 5, "sale_price": 95, "original_price": 100},
    {"sku": "A3", "name": "Great Deal", "discount_pct": 50, "sale_price": 50, "original_price": 100},
    {"sku": "A4", "name": "Already Posted", "discount_pct": 30, "sale_price": 70, "original_price": 100},
]

def test_filter_keeps_deals_above_threshold():
    already_posted = {"A4": True}
    results = filter_deals(SAMPLE_PRODUCTS, already_posted, min_discount=20)
    skus = [p["sku"] for p in results]
    assert "A1" in skus
    assert "A3" in skus
    assert "A2" not in skus   # below 20%
    assert "A4" not in skus   # already posted

def test_load_posted_returns_empty_dict_if_file_missing():
    result = load_posted("/nonexistent/path/posted.json")
    assert result == {}

def test_save_and_load_posted():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        tmp_path = f.name
    try:
        save_posted({"SKU1": True, "SKU2": True}, tmp_path)
        loaded = load_posted(tmp_path)
        assert loaded == {"SKU1": True, "SKU2": True}
    finally:
        os.unlink(tmp_path)
```

**Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_filters.py -v
```

Expected: `ModuleNotFoundError: No module named 'filters'`

**Step 3: Implement filters.py**

```python
import json
import os

MIN_DISCOUNT = 20  # percent

def filter_deals(products: list[dict], already_posted: dict, min_discount: int = MIN_DISCOUNT) -> list[dict]:
    """Return products that are new and meet the minimum discount threshold."""
    return [
        p for p in products
        if p.get("discount_pct", 0) >= min_discount
        and p["sku"] not in already_posted
    ]

def load_posted(path: str = "posted.json") -> dict:
    """Load the set of already-posted SKUs from JSON file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_posted(posted: dict, path: str = "posted.json") -> None:
    """Save updated posted SKUs dict to JSON file."""
    with open(path, "w") as f:
        json.dump(posted, f, indent=2)

def is_new_product(sku: str, already_posted: dict) -> bool:
    return sku not in already_posted
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_filters.py -v
```

Expected: 3 tests PASS

**Step 5: Commit**

```bash
git add filters.py tests/test_filters.py
git commit -m "feat: deal filter and duplicate tracker"
```

---

### Task 5: Telegram Poster

**Files:**
- Create: `telegram_poster.py`
- Create: `tests/test_telegram_poster.py`

**Step 1: Write failing tests**

Create `tests/test_telegram_poster.py`:

```python
from telegram_poster import format_message

def test_format_message_contains_key_info():
    product = {
        "name": "Samsung Galaxy A15",
        "sale_price": 2999.0,
        "original_price": 4000.0,
        "discount_pct": 25,
        "affiliate_url": "https://www.noon.com/egypt-en/samsung/p/SKU/?o=AFFccacc092d97d"
    }
    msg = format_message(product)
    assert "Samsung Galaxy A15" in msg
    assert "2,999" in msg or "2999" in msg
    assert "25%" in msg
    assert "noon.com" in msg

def test_format_message_has_emoji():
    product = {
        "name": "Test Product",
        "sale_price": 100.0,
        "original_price": 200.0,
        "discount_pct": 50,
        "affiliate_url": "https://www.noon.com/test"
    }
    msg = format_message(product)
    assert "🔥" in msg or "💰" in msg or "📉" in msg
```

**Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_telegram_poster.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Implement telegram_poster.py**

```python
import os
import asyncio
import telegram

def format_message(product: dict) -> str:
    """Format a product into a Telegram message caption."""
    name = product["name"]
    sale = product["sale_price"]
    original = product["original_price"]
    discount = product["discount_pct"]
    url = product["affiliate_url"]

    sale_fmt = f"{sale:,.0f}"
    original_fmt = f"{original:,.0f}"

    return (
        f"🔥 *{name}*\n\n"
        f"💰 EGP {sale_fmt} ~~(كان EGP {original_fmt})~~\n"
        f"📉 خصم {discount}%\n\n"
        f"🛒 [اشتري دلوقتي]({url})"
    )

async def _send_photo(bot: telegram.Bot, channel_id: str, image_url: str, caption: str) -> None:
    await bot.send_photo(
        chat_id=channel_id,
        photo=image_url,
        caption=caption,
        parse_mode="MarkdownV2"
    )

async def _send_message(bot: telegram.Bot, channel_id: str, caption: str) -> None:
    await bot.send_message(
        chat_id=channel_id,
        text=caption,
        parse_mode="MarkdownV2"
    )

def post_deal(product: dict, bot_token: str, channel_id: str) -> bool:
    """Post a single deal to the Telegram channel. Returns True on success."""
    bot = telegram.Bot(token=bot_token)
    caption = format_message(product)

    async def _run():
        if product.get("image_url"):
            try:
                await _send_photo(bot, channel_id, product["image_url"], caption)
                return True
            except Exception:
                pass
        await _send_message(bot, channel_id, caption)
        return True

    try:
        return asyncio.run(_run())
    except Exception as e:
        print(f"Failed to post {product.get('name', 'unknown')}: {e}")
        return False
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_telegram_poster.py -v
```

Expected: 2 tests PASS

**Step 5: Commit**

```bash
git add telegram_poster.py tests/test_telegram_poster.py
git commit -m "feat: telegram message formatter and poster"
```

---

### Task 6: Main Orchestrator

**Files:**
- Create: `main.py`

**No unit tests for the orchestrator** — it just wires together already-tested components. We'll verify it works via a dry-run flag.

**Step 1: Create main.py**

```python
import os
import time
from scraper import fetch_deals_page, parse_products_from_html
from filters import filter_deals, load_posted, save_posted
from affiliate import build_affiliate_link
from telegram_poster import post_deal

POSTED_FILE = "posted.json"
MAX_POSTS_PER_RUN = 5  # avoid spamming channel in a single run
DELAY_BETWEEN_POSTS = 3  # seconds between messages

def run(dry_run: bool = False):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "@noon_hot_deals")

    if not bot_token and not dry_run:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

    print("Fetching Noon Egypt deals page...")
    html = fetch_deals_page()

    print("Parsing products...")
    products = parse_products_from_html(html)
    print(f"Found {len(products)} products on page")

    print("Loading posted products...")
    already_posted = load_posted(POSTED_FILE)

    print("Filtering deals...")
    new_deals = filter_deals(products, already_posted)
    print(f"{len(new_deals)} new deals qualify (≥20% discount, not yet posted)")

    if not new_deals:
        print("No new deals to post. Done.")
        return

    # Sort by discount descending — best deals first
    new_deals.sort(key=lambda x: x["discount_pct"], reverse=True)
    deals_to_post = new_deals[:MAX_POSTS_PER_RUN]

    posted_count = 0
    for product in deals_to_post:
        product["affiliate_url"] = build_affiliate_link(product["url"])

        if dry_run:
            print(f"[DRY RUN] Would post: {product['name']} ({product['discount_pct']}% off)")
            already_posted[product["sku"]] = True
            posted_count += 1
            continue

        success = post_deal(product, bot_token, channel_id)
        if success:
            already_posted[product["sku"]] = True
            posted_count += 1
            print(f"Posted: {product['name']} ({product['discount_pct']}% off)")
            if posted_count < len(deals_to_post):
                time.sleep(DELAY_BETWEEN_POSTS)
        else:
            print(f"Failed to post: {product['name']}")

    print(f"Saving {len(already_posted)} posted products to {POSTED_FILE}...")
    save_posted(already_posted, POSTED_FILE)
    print(f"Done. Posted {posted_count} deals.")

if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
```

**Step 2: Test with dry run**

```bash
python main.py --dry-run
```

Expected output:
```
Fetching Noon Egypt deals page...
Parsing products...
Found X products on page
Loading posted products...
Filtering deals...
N new deals qualify (≥20% discount, not yet posted)
[DRY RUN] Would post: ...
```

If "Found 0 products" — go back to Task 3 and debug the scraper against live data.

**Step 3: Commit**

```bash
git add main.py posted.json
git commit -m "feat: main orchestrator with dry-run mode"
```

---

### Task 7: GitHub Actions Workflow

**Files:**
- Create: `.github/workflows/bot.yml`

**Step 1: Create workflow file**

```bash
mkdir -p .github/workflows
```

Create `.github/workflows/bot.yml`:

```yaml
name: Noon Deals Bot

on:
  schedule:
    # Runs every 4 hours: at 6am, 10am, 2pm, 6pm, 10pm, 2am Cairo time (UTC+2 = UTC-2h)
    - cron: '0 4,8,12,16,20,0 * * *'
  workflow_dispatch:  # allows manual trigger from GitHub UI

jobs:
  post-deals:
    runs-on: ubuntu-latest
    permissions:
      contents: write  # needed to commit posted.json back

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run bot
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHANNEL_ID: ${{ secrets.TELEGRAM_CHANNEL_ID }}
        run: python main.py

      - name: Commit updated posted.json
        run: |
          git config user.name "noon-bot"
          git config user.email "bot@noon-deals"
          git add posted.json
          git diff --staged --quiet || git commit -m "chore: update posted products [skip ci]"
          git push
```

**Step 2: Commit**

```bash
git add .github/
git commit -m "feat: github actions workflow (runs every 4h)"
```

---

### Task 8: Deploy to GitHub + Add Secrets

**Step 1: Create GitHub repo and push**

Go to https://github.com/new and create a private repo named `noon-deals-bot` with no README.

Then push:

```bash
git remote add origin https://github.com/YOUR_USERNAME/noon-deals-bot.git
git branch -M main
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username.

**Step 2: Add secrets to GitHub repo**

Go to your repo → Settings → Secrets and variables → Actions → New repository secret

Add these two secrets:

| Name | Value |
|------|-------|
| `TELEGRAM_BOT_TOKEN` | Your new bot token from @BotFather |
| `TELEGRAM_CHANNEL_ID` | `@noon_hot_deals` |

**Step 3: Trigger a manual test run**

Go to your repo → Actions tab → "Noon Deals Bot" → Run workflow → Run workflow

Watch the logs. It should:
1. Install dependencies
2. Fetch Noon deals
3. Post deals to your Telegram channel
4. Commit updated posted.json

**Step 4: Verify in Telegram**

Check @noon_hot_deals — deal messages should appear with product images and affiliate links.

**Step 5: Final commit if any fixes were needed**

```bash
git add .
git commit -m "fix: adjust scraper/affiliate link based on live test"
git push
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Found 0 products" | Run Task 3 debug command to inspect `__NEXT_DATA__` paths |
| Affiliate link param wrong | Check noon.partners dashboard → link creator → copy exact param format |
| MarkdownV2 parse error in Telegram | Escape special chars: `.`, `-`, `(`, `)` with `\` in format_message() |
| GitHub Actions not running | Check cron syntax; note GitHub may delay by 15-30 min |
| Bot can't post to channel | Verify bot is admin with "Post Messages" permission in channel settings |

## Verification Checklist
- [ ] `python -m pytest` — all tests pass
- [ ] `python main.py --dry-run` — finds deals, no errors
- [ ] GitHub Actions manual run succeeds
- [ ] Deal messages appear in @noon_hot_deals with correct affiliate links
- [ ] Running again doesn't re-post the same products (posted.json working)
