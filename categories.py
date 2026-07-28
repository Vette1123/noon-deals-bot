"""noon category codes, what they pay, and what they are called in Arabic.

One table with three consumers, on purpose:

- [scraper.py](scraper.py) uses `code` as a URL path — `/egypt-en/{code}/` is a
  real product-list page. (The marketing slugs linked off noon's homepage,
  `/egypt-en/beauty/` and friends, are curated landing pages with no catalog
  payload in them. Verified 2026-07-28; do not use those.)
- [filters.py](filters.py) turns `rate` into an expected-commission score.
- [site_builder.py](site_builder.py) uses `label` for the category hub pages.

Splitting the three apart is how a typo silently un-tags a whole category and
nobody notices for a month, so they live together.

`rate` is the commission percentage from the noon affiliate panel
(Everyday Campaign, read 2026-07-28). **Commission is capped per item**, which
is why a rate alone never ranks a deal — see `filters.expected_commission`.
"""

# (code, Arabic label, commission rate)
#
# Ordered high-rate first, but the order that actually matters is the rotation
# in scraper.feed_tasks(). Categories are chosen for rate × typical basket, not
# rate alone: fashion pays 10% but sells at EGP 400, while a small appliance
# pays 8% of EGP 4,000.
CATEGORIES: tuple[tuple[str, str, float], ...] = (
    # Apparel, footwear, bags and jewellery — the top rate on the panel at 10%.
    ("fashion/women-31229", "أزياء نسائية", 0.10),
    ("fashion/men-31225", "أزياء رجالية", 0.10),
    ("fashion/luggage-and-bags", "شنط وحقائب سفر", 0.10),
    ("fashion/girls-31223", "أزياء بناتي", 0.10),
    ("fashion/boys-31221", "أزياء ولادي", 0.10),
    # Stationery and office supplies, 9%.
    ("office-supplies/stationery-16397", "أدوات مكتبية وقرطاسية", 0.09),
    # Beauty: colour cosmetics, fragrance and personal care all pay 8%.
    ("beauty/fragrance", "عطور", 0.08),
    ("beauty/makeup-16142", "مكياج", 0.08),
    ("beauty/skin-care-16813", "العناية بالبشرة", 0.08),
    ("beauty/hair-care", "العناية بالشعر", 0.08),
    ("beauty/personal-care-16343", "العناية الشخصية", 0.08),
    ("beauty/gift-sets-new", "أطقم هدايا التجميل", 0.08),
    # Health and nutrition, 8%.
    ("health/vitamins-and-dietary-supplements", "فيتامينات ومكملات غذائية", 0.08),
    ("health/sports-nutrition", "تغذية رياضية", 0.08),
    ("health/medical-supplies-and-equipment", "مستلزمات طبية", 0.08),
    # Toys, 8%.
    ("toys-and-games/games-18311", "ألعاب", 0.08),
    ("toys-and-games/building-toys", "ألعاب تركيب ومكعبات", 0.08),
    # Baby, consumable and not, both 8%.
    ("baby-products/baby-transport", "عربات ومقاعد أطفال", 0.08),
    ("baby-products/diapering", "حفاضات ومستلزماتها", 0.08),
    ("baby-products/feeding-16153", "مستلزمات رضاعة وتغذية", 0.08),
    # Sports and outdoor, 8%.
    ("sports-and-outdoors/exercise-and-fitness", "أجهزة لياقة ورياضة", 0.08),
    ("sports-and-outdoors/sports", "مستلزمات رياضية", 0.08),
    # Automotive, 8%.
    ("automotive/car-care", "العناية بالسيارة", 0.08),
    ("automotive/interior-accessories", "إكسسوارات داخلية للسيارة", 0.08),
    # noon files small appliances (8%) and large appliances (5%) under one
    # browse path, so this feed is scored at a blend rather than at either rate.
    ("home-and-kitchen/home-appliances-31235", "أجهزة منزلية", 0.06),
    # Kitchen, decor, bath and bedding, furniture: 6%.
    ("home-and-kitchen/kitchen-and-dining", "أدوات مطبخ ومائدة", 0.06),
    ("home-and-kitchen/home-decor", "ديكور منزلي", 0.06),
    ("home-and-kitchen/bedding-16171", "مفروشات ومراتب", 0.06),
    ("home-and-kitchen/bath-16182", "مستلزمات الحمام", 0.06),
    ("home-and-kitchen/furniture-10180", "أثاث", 0.06),
    # Home improvement, 6%.
    ("tools-and-home-improvement/power-and-hand-tools", "عدد وأدوات كهربائية", 0.06),
    # Electronics pay the worst rates on the panel (laptops 3%, mobiles 2%), but
    # they are what makes a deals channel worth subscribing to. Kept deliberately
    # few, and the scorer already knows they earn little.
    ("electronics-and-mobiles/computers-and-accessories", "كمبيوتر وإكسسوارات", 0.04),
    ("electronics-and-mobiles/wearable-technology", "ساعات ذكية وأجهزة قابلة للارتداء", 0.03),
    ("electronics-and-mobiles/home-audio", "صوتيات منزلية", 0.03),
)

FEED_CODES: tuple[str, ...] = tuple(code for code, _, _ in CATEGORIES)

_LABELS: dict[str, str] = {code: label for code, label, _ in CATEGORIES}
_RATES: dict[str, float] = {code: rate for code, _, rate in CATEGORIES}

# Rates for categories we do not have a feed for. An archived deal keeps whatever
# category it was scraped under forever, and noon reshuffles its browse tree, so
# a code that is no longer a feed still has to resolve to a number.
_RATE_PREFIXES: tuple[tuple[str, float], ...] = (
    ("fashion", 0.10),
    ("books", 0.09),
    ("music-movies-and-tv-shows", 0.09),
    ("office-supplies", 0.09),
    ("beauty", 0.08),
    ("health", 0.08),
    ("toys-and-games", 0.08),
    ("baby-products", 0.08),
    ("sports-and-outdoors", 0.08),
    ("automotive", 0.08),
    ("home-and-kitchen", 0.06),
    ("tools-and-home-improvement", 0.06),
    ("grocery-store", 0.05),
    ("pet-supplies", 0.05),
    ("electronics-and-mobiles/accessories-and-supplies", 0.04),
    ("electronics-and-mobiles/computers-and-accessories", 0.04),
    ("electronics-and-mobiles/mobiles-and-accessories", 0.02),
    ("electronics-and-mobiles", 0.03),
)

# What an untagged product is assumed to earn. Deals archived before categories
# existed have no code at all, and the mid-table rate is the honest guess.
DEFAULT_RATE = 0.05


def commission_rate(category: str | None) -> float:
    """The panel's commission rate for a category code.

    Falls back to the longest matching parent prefix, then to `DEFAULT_RATE`.
    """
    code = (category or "").strip()
    if not code:
        return DEFAULT_RATE
    if code in _RATES:
        return _RATES[code]
    best = DEFAULT_RATE
    best_len = 0
    for prefix, rate in _RATE_PREFIXES:
        if (code == prefix or code.startswith(prefix + "/")) and len(prefix) > best_len:
            best, best_len = rate, len(prefix)
    return best


def category_label(category: str | None) -> str:
    """The Arabic name for a category code, or "" when we have no name for it.

    An unlabelled category gets no hub page rather than a page titled with a
    noon URL slug, which would read as machine output to an Arabic reader.
    """
    return _LABELS.get((category or "").strip(), "")
