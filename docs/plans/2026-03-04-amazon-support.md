# Amazon Egypt Support Implementation Plan

> **⚠️ Historical doc (2026-03-04).** Zenrows was removed on 2026-04-19 and replaced with `curl_cffi` — ignore any `ZENROWS_API_KEY` references below.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Amazon Egypt (PA-API) as a second deal source, posting 50 Noon + 50 Amazon deals per run interleaved into the same Telegram channel with identical card formatting.

**Architecture:** A new `amazon_scraper.py` calls Amazon PA-API 5 to fetch up to 50 deals from a rotating category, returning product dicts in the same schema as Noon. `main.py` runs both scrapers, filters each independently, interleaves the results, and posts 100 total. Amazon affiliate URLs are built directly from the ASIN + partner tag — no separate affiliate helper needed.

**Tech Stack:** `paapi5-python-sdk`, existing `python-telegram-bot`, GitHub Actions secrets

---

### Task 1: Add dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add the SDK**

Open `requirements.txt` and append:
```
paapi5-python-sdk
```

**Step 2: Verify install locally**

```bash
pip install paapi5-python-sdk
python -c "from paapi5_python_sdk.api.default_api import DefaultApi; print('OK')"
```
Expected: `OK`

**Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add paapi5-python-sdk dependency"
```

---

### Task 2: Write failing tests for `amazon_scraper.py`

**Files:**
- Create: `tests/test_amazon_scraper.py`

**Step 1: Write the tests**

```python
# tests/test_amazon_scraper.py
from unittest.mock import MagicMock, patch
import pytest
from amazon_scraper import _normalize_item, fetch_amazon_products, CATEGORIES


def _make_item(asin="B001TEST01", title="Test Product", brand="TestBrand",
               sale=100.0, original=200.0, discount_pct=50,
               image_url="https://example.com/img.jpg", rating=4.5, review_count=123):
    item = MagicMock()
    item.asin = asin
    item.item_info.title.display_value = title
    item.item_info.by_line_info.brand.display_value = brand
    item.offers.listings[0].price.amount = sale
    item.offers.listings[0].price.savings.percentage = discount_pct
    item.offers.listings[0].saving_basis.amount = original
    item.images.primary.large.url = image_url
    item.customer_reviews.star_rating.value = rating
    item.customer_reviews.count = review_count
    return item


def test_normalize_item_returns_correct_schema():
    item = _make_item()
    result = _normalize_item(item, partner_tag="mytag-21")
    assert result["sku"] == "B001TEST01"
    assert result["name"] == "Test Product"
    assert result["sale_price"] == 100.0
    assert result["original_price"] == 200.0
    assert result["discount_pct"] == 50
    assert result["brand"] == "TestBrand"
    assert result["rating"] == 4.5
    assert result["rating_count"] == 123
    assert result["affiliate_url"] == "https://www.amazon.eg/dp/B001TEST01?tag=mytag-21"
    assert result["image_url"] == "https://example.com/img.jpg"
    # Fields telegram_poster.py expects but amazon doesn't provide
    assert result["store_name"] == ""
    assert result["estimated_delivery"] == ""


def test_normalize_item_returns_none_when_missing_required_fields():
    item = MagicMock()
    item.asin = None
    item.item_info.title.display_value = None
    item.offers.listings = []
    assert _normalize_item(item, partner_tag="mytag-21") is None


def test_normalize_item_handles_missing_optional_fields():
    item = _make_item()
    item.item_info.by_line_info = None
    item.customer_reviews = None
    result = _normalize_item(item, partner_tag="mytag-21")
    assert result is not None
    assert result["brand"] == ""
    assert result["rating"] is None
    assert result["rating_count"] is None


def test_fetch_amazon_products_returns_list(monkeypatch):
    mock_item = _make_item()
    mock_response = MagicMock()
    mock_response.search_result.items = [mock_item]

    mock_client = MagicMock()
    mock_client.search_items.return_value = mock_response

    monkeypatch.setenv("AMAZON_ACCESS_KEY", "key")
    monkeypatch.setenv("AMAZON_SECRET_KEY", "secret")
    monkeypatch.setenv("AMAZON_PARTNER_TAG", "mytag-21")

    with patch("amazon_scraper.DefaultApi", return_value=mock_client):
        with patch("amazon_scraper.time.sleep"):
            results = fetch_amazon_products(category_index=0)

    assert isinstance(results, list)
    assert len(results) > 0
    assert results[0]["sku"] == "B001TEST01"


def test_fetch_amazon_products_raises_without_credentials(monkeypatch):
    monkeypatch.delenv("AMAZON_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AMAZON_SECRET_KEY", raising=False)
    monkeypatch.delenv("AMAZON_PARTNER_TAG", raising=False)
    with pytest.raises(RuntimeError, match="credentials"):
        fetch_amazon_products()


def test_categories_list_is_nonempty():
    assert len(CATEGORIES) > 0


def test_category_index_wraps_around(monkeypatch):
    """category_index beyond list length should wrap via modulo."""
    mock_response = MagicMock()
    mock_response.search_result.items = []
    mock_client = MagicMock()
    mock_client.search_items.return_value = mock_response

    monkeypatch.setenv("AMAZON_ACCESS_KEY", "k")
    monkeypatch.setenv("AMAZON_SECRET_KEY", "s")
    monkeypatch.setenv("AMAZON_PARTNER_TAG", "t-21")

    with patch("amazon_scraper.DefaultApi", return_value=mock_client):
        # Should not raise even with large index
        results = fetch_amazon_products(category_index=9999)
    assert isinstance(results, list)
```

**Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_amazon_scraper.py -v
```
Expected: `ImportError: No module named 'amazon_scraper'`

**Step 3: Commit**

```bash
git add tests/test_amazon_scraper.py
git commit -m "test: add failing tests for amazon_scraper"
```

---

### Task 3: Implement `amazon_scraper.py`

**Files:**
- Create: `amazon_scraper.py`

**Step 1: Write the implementation**

```python
import os
import time

from paapi5_python_sdk.api.default_api import DefaultApi
from paapi5_python_sdk.models.partner_type import PartnerType
from paapi5_python_sdk.models.search_items_request import SearchItemsRequest
from paapi5_python_sdk.models.search_items_resource import SearchItemsResource
from paapi5_python_sdk.rest import ApiException

CATEGORIES = [
    "Electronics",
    "HomeAndKitchen",
    "Fashion",
    "SportingGoods",
    "Beauty",
    "Toys",
    "Books",
]

_RESOURCES = [
    SearchItemsResource.ITEMINFO_TITLE,
    SearchItemsResource.ITEMINFO_BYLINEINFO,
    SearchItemsResource.OFFERS_LISTINGS_PRICE,
    SearchItemsResource.OFFERS_LISTINGS_SAVINGBASIS,
    SearchItemsResource.IMAGES_PRIMARY_LARGE,
    SearchItemsResource.CUSTOMERREVIEWS_COUNT,
    SearchItemsResource.CUSTOMERREVIEWS_STARRATING,
]

PAGES_PER_RUN = 5   # 5 pages × 10 items = 50 candidates
ITEMS_PER_PAGE = 10
MIN_SAVING_PERCENT = 5


def fetch_amazon_products(category_index: int = 0) -> list[dict]:
    """Fetch up to 50 discounted products from Amazon Egypt PA-API."""
    access_key = os.environ.get("AMAZON_ACCESS_KEY", "")
    secret_key = os.environ.get("AMAZON_SECRET_KEY", "")
    partner_tag = os.environ.get("AMAZON_PARTNER_TAG", "")

    if not all([access_key, secret_key, partner_tag]):
        raise RuntimeError("Amazon PA-API credentials not set. Add AMAZON_ACCESS_KEY, AMAZON_SECRET_KEY, AMAZON_PARTNER_TAG as secrets.")

    category = CATEGORIES[category_index % len(CATEGORIES)]
    client = DefaultApi(
        access_key=access_key,
        secret_key=secret_key,
        host="webservices.amazon.eg",
        region="eu-west-1",
    )

    all_products: list[dict] = []
    seen_asins: set[str] = set()

    for page in range(1, PAGES_PER_RUN + 1):
        try:
            request = SearchItemsRequest(
                partner_tag=partner_tag,
                partner_type=PartnerType.ASSOCIATES,
                keywords="deals sale discount",
                search_index=category,
                item_count=ITEMS_PER_PAGE,
                item_page=page,
                min_saving_percent=MIN_SAVING_PERCENT,
                resources=_RESOURCES,
            )
            response = client.search_items(request)

            if not response.search_result or not response.search_result.items:
                print(f"  Amazon page {page}: no results — stopping.")
                break

            new_count = 0
            for item in response.search_result.items:
                if item.asin not in seen_asins:
                    seen_asins.add(item.asin)
                    normalized = _normalize_item(item, partner_tag)
                    if normalized:
                        all_products.append(normalized)
                        new_count += 1

            print(f"  Amazon page {page} ({category}): {new_count} new products")

            if page < PAGES_PER_RUN:
                time.sleep(1)  # PA-API rate limit: 1 req/sec

        except ApiException as e:
            print(f"  PA-API error on page {page}: {e}")
            break

    print(f"Amazon total: {len(all_products)} products from category '{category}'")
    return all_products


def _normalize_item(item, partner_tag: str) -> dict | None:
    """Convert a PA-API item object to the standard product dict schema."""
    try:
        asin = item.asin
        title = (
            item.item_info.title.display_value
            if item.item_info and item.item_info.title
            else None
        )

        brand = ""
        if (item.item_info and item.item_info.by_line_info
                and item.item_info.by_line_info.brand):
            brand = item.item_info.by_line_info.brand.display_value or ""

        listing = None
        if item.offers and item.offers.listings:
            listing = item.offers.listings[0]

        sale_price = listing.price.amount if listing and listing.price else None
        original_price = (
            listing.saving_basis.amount
            if listing and listing.saving_basis
            else sale_price
        )
        discount_pct = 0
        if listing and listing.price and listing.price.savings:
            discount_pct = int(listing.price.savings.percentage or 0)
        elif original_price and sale_price and float(original_price) > float(sale_price):
            discount_pct = round((1 - float(sale_price) / float(original_price)) * 100)

        image_url = None
        if item.images and item.images.primary and item.images.primary.large:
            image_url = item.images.primary.large.url

        rating = None
        rating_count = None
        if item.customer_reviews:
            if item.customer_reviews.star_rating:
                rating = round(float(item.customer_reviews.star_rating.value), 1)
            if item.customer_reviews.count:
                rating_count = int(item.customer_reviews.count)

        if not all([title, asin, sale_price]):
            return None

        return {
            "name": title,
            "sku": asin,
            "url": f"https://www.amazon.eg/dp/{asin}",
            "affiliate_url": f"https://www.amazon.eg/dp/{asin}?tag={partner_tag}",
            "image_url": image_url,
            "sale_price": float(sale_price),
            "original_price": float(original_price or sale_price),
            "discount_pct": discount_pct,
            "brand": brand,
            "rating": rating,
            "rating_count": rating_count,
            "store_name": "",
            "estimated_delivery": "",
            "source": "amazon",
        }
    except Exception as e:
        print(f"  Skipping Amazon item: {e}")
        return None
```

**Step 2: Run tests**

```bash
pytest tests/test_amazon_scraper.py -v
```
Expected: all tests PASS

**Step 3: Commit**

```bash
git add amazon_scraper.py
git commit -m "feat: add amazon_scraper with PA-API integration"
```

---

### Task 4: Write failing tests for `main.py` changes

**Files:**
- Modify: `tests/test_main.py` (create if missing)

**Step 1: Write interleave test**

Add to `tests/test_main.py`:

```python
# tests/test_main.py
from main import _interleave


def test_interleave_equal_length():
    a = [1, 3, 5]
    b = [2, 4, 6]
    assert _interleave(a, b) == [1, 2, 3, 4, 5, 6]


def test_interleave_noon_longer():
    a = [1, 3, 5, 7]
    b = [2, 4]
    assert _interleave(a, b) == [1, 2, 3, 4, 5, 7]


def test_interleave_amazon_longer():
    a = [1]
    b = [2, 4, 6]
    assert _interleave(a, b) == [1, 2, 4, 6]


def test_interleave_empty():
    assert _interleave([], []) == []
    assert _interleave([1, 2], []) == [1, 2]
    assert _interleave([], [1, 2]) == [1, 2]
```

**Step 2: Run to confirm fail**

```bash
pytest tests/test_main.py -v
```
Expected: `ImportError: cannot import name '_interleave' from 'main'`

**Step 3: Commit**

```bash
git add tests/test_main.py
git commit -m "test: add failing tests for _interleave helper"
```

---

### Task 5: Modify `main.py`

**Files:**
- Modify: `main.py`

**Step 1: Add import and `_interleave` helper**

At the top of `main.py`, add the import:
```python
from amazon_scraper import fetch_amazon_products
```

After the existing imports, add the helper function:
```python
def _interleave(list_a: list, list_b: list) -> list:
    """Interleave two lists: [a1, b1, a2, b2, ...], remainder appended."""
    result = []
    for a, b in zip(list_a, list_b):
        result.append(a)
        result.append(b)
    result.extend(list_a[len(list_b):])
    result.extend(list_b[len(list_a):])
    return result
```

**Step 2: Update `run()` to fetch from both sources**

Replace the existing `run()` function body with:

```python
def run(dry_run: bool = False) -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID", "@noon_hot_deals")
    noon_cookie = os.environ.get("NOON_SESSION_COOKIE", "")

    if not bot_token and not dry_run:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    state = _load_state()
    start_page = state.get("next_page", 1)
    amazon_category_index = state.get("amazon_category_index", 0)

    # ── Noon ──────────────────────────────────────────────────────────────────
    print(f"Fetching Noon Egypt deals (pages {start_page}–{start_page + PAGES_PER_RUN - 1})...")
    noon_products = fetch_products(start_page=start_page)
    print(f"Found {len(noon_products)} Noon products")

    already_posted = load_posted(POSTED_FILE)
    noon_new = filter_deals(noon_products, already_posted)
    print(f"{len(noon_new)} new Noon qualifying deals (>={MIN_DISCOUNT}% off)")
    noon_new.sort(key=lambda x: x["discount_pct"], reverse=True)
    noon_to_post = noon_new[:MAX_POSTS_PER_RUN]

    # ── Amazon ────────────────────────────────────────────────────────────────
    print(f"Fetching Amazon Egypt deals (category index {amazon_category_index})...")
    try:
        amazon_products = fetch_amazon_products(category_index=amazon_category_index)
        print(f"Found {len(amazon_products)} Amazon products")
    except Exception as e:
        print(f"Amazon scraper failed: {e} — skipping Amazon this run.")
        amazon_products = []

    amazon_new = filter_deals(amazon_products, already_posted)
    print(f"{len(amazon_new)} new Amazon qualifying deals (>={MIN_DISCOUNT}% off)")
    amazon_new.sort(key=lambda x: x["discount_pct"], reverse=True)
    amazon_to_post = amazon_new[:MAX_POSTS_PER_RUN]

    # ── Interleave ────────────────────────────────────────────────────────────
    to_post = _interleave(noon_to_post, amazon_to_post)

    if not to_post:
        print("Nothing new to post.")
        _advance_state(state, start_page, amazon_category_index, already_posted)
        return

    # ── Build affiliate links & post ─────────────────────────────────────────
    posted = 0
    for product in to_post:
        if product.get("source") != "amazon":
            try:
                product["affiliate_url"] = build_affiliate_link(
                    product["url"], product["name"], noon_cookie
                )
            except Exception as e:
                print(f"Affiliate link failed for {product['name']}: {e}")
                product["affiliate_url"] = product["url"]

        if dry_run:
            src = product.get("source", "noon")
            print(f"[DRY RUN][{src}] {product['name']} ({product['discount_pct']}% off) → {product.get('affiliate_url', product['url'])}")
            already_posted[product["sku"]] = True
            posted += 1
            continue

        if post_deal(product, bot_token, channel_id):
            already_posted[product["sku"]] = True
            posted += 1
            print(f"Posted: {product['name']} ({product['discount_pct']}% off)")
            if posted < len(to_post):
                time.sleep(DELAY_BETWEEN_POSTS)
        else:
            print(f"Failed: {product['name']}")

    _advance_state(state, start_page, amazon_category_index, already_posted)
    print(f"Done. Posted {posted} deals.")
```

**Step 3: Add `_advance_state` helper**

Add below `_save_state`:

```python
def _advance_state(state: dict, start_page: int, amazon_category_index: int, already_posted: dict) -> None:
    next_page = start_page + PAGES_PER_RUN
    next_amazon_index = amazon_category_index + 1

    if next_page > MAX_PAGES:
        next_page = 1
        already_posted = {}
        print("Full cycle complete — resetting posted history for next round.")

    _save_state({"next_page": next_page, "amazon_category_index": next_amazon_index})
    save_posted(already_posted, POSTED_FILE)
    print(f"Next run: Noon page {next_page}, Amazon category index {next_amazon_index}.")
```

**Step 4: Run tests**

```bash
pytest tests/test_main.py -v
```
Expected: all PASS

**Step 5: Smoke test with dry run (requires credentials in env)**

```bash
TELEGRAM_BOT_TOKEN=fake AMAZON_ACCESS_KEY=x AMAZON_SECRET_KEY=x AMAZON_PARTNER_TAG=x-21 python main.py --dry-run
```
Expected: prints noon products, Amazon error handled gracefully (or posts if creds are real)

**Step 6: Commit**

```bash
git add main.py
git commit -m "feat: integrate Amazon source with interleaved posting"
```

---

### Task 6: Update GitHub Actions workflow

**Files:**
- Modify: `.github/workflows/bot.yml`

**Step 1: Add the three new env vars to the "Run bot" step**

Find this block:
```yaml
      - name: Run bot
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHANNEL_ID: ${{ secrets.TELEGRAM_CHANNEL_ID }}
          NOON_SESSION_COOKIE: ${{ secrets.NOON_SESSION_COOKIE }}
          ZENROWS_API_KEY: ${{ secrets.ZENROWS_API_KEY }}
        run: python main.py
```

Replace with:
```yaml
      - name: Run bot
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHANNEL_ID: ${{ secrets.TELEGRAM_CHANNEL_ID }}
          NOON_SESSION_COOKIE: ${{ secrets.NOON_SESSION_COOKIE }}
          ZENROWS_API_KEY: ${{ secrets.ZENROWS_API_KEY }}
          AMAZON_ACCESS_KEY: ${{ secrets.AMAZON_ACCESS_KEY }}
          AMAZON_SECRET_KEY: ${{ secrets.AMAZON_SECRET_KEY }}
          AMAZON_PARTNER_TAG: ${{ secrets.AMAZON_PARTNER_TAG }}
        run: python main.py
```

**Step 2: Add the three secrets in GitHub**

Go to: **GitHub repo → Settings → Secrets and variables → Actions → New repository secret**

Add:
- `AMAZON_ACCESS_KEY` — from Amazon Associates PA-API credentials page
- `AMAZON_SECRET_KEY` — from Amazon Associates PA-API credentials page
- `AMAZON_PARTNER_TAG` — your Associates tag (e.g. `mystore-21`), found in Associates dashboard

**Step 3: Run all tests one final time**

```bash
pytest -v
```
Expected: all tests PASS

**Step 4: Commit and push**

```bash
git add .github/workflows/bot.yml
git commit -m "feat: add Amazon PA-API secrets to workflow"
git push
```

---

## Post-Deployment Verification

After the next scheduled run (or trigger manually via Actions → Run workflow):
1. Check GitHub Actions log — should see both "Noon" and "Amazon" fetch lines
2. Check Telegram channel — posts should alternate Noon/Amazon style
3. Check `state.json` in the repo — should have both `next_page` and `amazon_category_index`
