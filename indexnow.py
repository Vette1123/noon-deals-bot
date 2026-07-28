"""IndexNow ping — tell Bing, Yandex and Seznam a page exists the minute it ships.

The sitemap already lists every page, so why this: a deal is worth traffic for
about two weeks, and organic discovery of a brand-new URL on a young domain
routinely takes longer than that. IndexNow collapses the delay to minutes. It is
one HTTP POST and it costs nothing.

Google does **not** participate in IndexNow — there, `sitemap.xml` + `lastmod` is
still the only lever. This is upside on the other engines, not a replacement for
anything already here.

Two rules that are easy to get wrong:

- **The key is public by design.** It is published at `{key}.txt` on the site
  itself, and serving it is exactly what proves ownership. Do not move it into
  GitHub secrets — the site builder has to be able to write it, and a key the
  crawler cannot fetch fails verification with HTTP 403.
- **Ping after the deploy, never before.** The crawlers fetch submitted URLs
  within minutes; a URL that 404s because Pages has not swapped the artifact yet
  gets dropped, and re-submitting the same URL later is throttled.

Only URLs that actually changed are submitted. Firing the whole 12,000-deal
archive every four hours is what gets a host rate-limited (HTTP 429) and, past
that, ignored.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests

ENDPOINT = "https://api.indexnow.org/indexnow"
# Shared by every participating engine — api.indexnow.org fans the submission out,
# so pinging bing.com and yandex.com separately would only duplicate it.

# Any of a-z, A-Z, 0-9 and "-", 8–128 chars. This one is not a credential (see
# the module docstring); a fork wanting its own just sets INDEXNOW_KEY to a fresh
# random hex string — `python -c "import secrets;print(secrets.token_hex(16))"`.
KEY = (
    os.environ.get("INDEXNOW_KEY", "").strip() or "7c3f1b9e42a84d6fa0e5b8d17c62934f"
)
_KEY_RE = re.compile(r"^[A-Za-z0-9-]{8,128}$")
if not _KEY_RE.fullmatch(KEY):
    # The key becomes a filename written into the output directory, so a bad one
    # is dropped rather than published — same rule as SKUs and the CNAME.
    print(f"Ignoring malformed INDEXNOW_KEY: {KEY!r}")
    KEY = ""

# How far back a deal counts as "new enough to announce". The workflow runs every
# four hours; the wider window costs nothing and covers a run that failed to ping.
RECENT_HOURS = 24
# Protocol cap per request. Reaching it means something is wrong with the window,
# not that the site suddenly published 10k pages.
MAX_URLS = 10_000
TIMEOUT = 20


def key_file() -> str:
    """Filename of the ownership file the site must serve, or "" when disabled."""
    return f"{KEY}.txt" if KEY else ""


def changed_urls(archive: dict, base_url: str, now: datetime | None = None,
                 hours: int = RECENT_HOURS) -> list[str]:
    """Absolute URLs worth announcing: the pages this run actually changed.

    That is the front page (it always reshuffles), every deal page posted inside
    the window, and the brand/category hubs those deals landed on — a hub whose
    listing changed is a page the crawler should re-read, and it is usually the
    one that ranks.
    """
    # Deferred so that `import site_builder` (which imports this module for the
    # key file) does not become a circular import at load time.
    from site_builder import (
        _brand_index, _brand_slug, _category_index, _deal_path, _parse_stamp,
    )

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    deals = archive.get("deals", [])
    fresh = [
        d for d in deals
        if _deal_path(d) and _parse_stamp(d.get("posted_at"), now) >= cutoff
    ]
    if not fresh:
        return []

    base = base_url.rstrip("/")
    # Only hubs that were actually built are live URLs; the rest 404.
    brands = _brand_index(deals)
    cats = _category_index(deals)
    paths = ["", *(_deal_path(d) for d in fresh)]
    touched_brands = {_brand_slug(d.get("brand")) for d in fresh} & set(brands)
    touched_cats = {_brand_slug(d.get("category")) for d in fresh} & set(cats)
    paths += [f"brands/{s}.html" for s in sorted(touched_brands)]
    paths += [f"cat/{s}.html" for s in sorted(touched_cats)]

    seen: set[str] = set()
    urls: list[str] = []
    for path in paths:
        url = f"{base}/{path}" if path else f"{base}/"
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls[:MAX_URLS]


def submit(urls: list[str], base_url: str) -> bool:
    """POST the batch. Returns whether it was accepted; never raises.

    Indexing is a bonus surface. A dead endpoint, a rate limit or a DNS blip must
    not fail a run that already posted deals and deployed a site — same contract
    as the Facebook poster.
    """
    if not KEY or not urls:
        return False
    host = urlsplit(base_url).netloc
    if not host:
        print(f"IndexNow: no host in base URL {base_url!r}")
        return False
    payload = {
        "host": host,
        "key": KEY,
        # Required whenever the site is not at the domain root — on a
        # `user.github.io/repo` Pages URL the key file lives under /repo/, and
        # without this the engine looks for it at the domain root and 403s.
        "keyLocation": f"{base_url.rstrip('/')}/{key_file()}",
        "urlList": urls[:MAX_URLS],
    }
    try:
        response = requests.post(
            ENDPOINT, json=payload, timeout=TIMEOUT,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
    except requests.RequestException as exc:
        print(f"IndexNow submit failed: {exc}")
        return False
    # 200 = accepted, 202 = accepted but the key is still being verified (which is
    # the normal answer for the first ping after a key changes).
    if response.status_code in (200, 202):
        print(f"IndexNow: submitted {len(payload['urlList'])} URLs ({response.status_code})")
        return True
    print(f"IndexNow rejected the batch: HTTP {response.status_code} {response.text[:200]}")
    return False


def ping_recent(archive: dict, base_url: str, now: datetime | None = None) -> bool:
    urls = changed_urls(archive, base_url, now)
    if not urls:
        print("IndexNow: nothing new to announce")
        return False
    return submit(urls, base_url)


if __name__ == "__main__":
    from archive import ARCHIVE_FILE, load_archive
    from site_builder import SITE_BASE_URL

    ping_recent(load_archive(ARCHIVE_FILE), SITE_BASE_URL)
