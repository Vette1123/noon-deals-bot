import os
import requests
from noon_auth import re_authenticate, AuthError

AFFILIATE_API_URL = "https://affiliates.noon.partners/_svc/affiliate/affiliate/campaign/custom_link"
CAMPAIGN_CODE = "CMPa5461f39a36enoon"
AFFILIATE_CODE = "AFFccacc092d97d"
PROJECT_CODE = "PRJ496018"


class AffiliateError(Exception):
    pass


def build_affiliate_link(product_url: str, product_name: str, session_cookie: str = None, _retried: bool = False) -> str:
    """
    Call noon.partners API to generate an s.noon.com affiliate tracking short link.

    Args:
        product_url: Full noon.com Egypt product URL
        product_name: Product name (used as link title)
        session_cookie: Noon session cookie string (from NOON_SESSION_COOKIE env var if not provided)

    Returns:
        Short affiliate URL like https://s.noon.com/XXXXXXXXX

    Raises:
        AffiliateError: If cookie is missing or API call fails
    """
    if session_cookie is None:
        session_cookie = os.environ.get("NOON_SESSION_COOKIE", "")

    if not session_cookie:
        raise AffiliateError("Noon session cookie is required — set NOON_SESSION_COOKIE env var")

    headers = {
        "content-type": "application/json",
        "x-platform": "web",
        "x-project": PROJECT_CODE,
        "Cookie": session_cookie,
    }

    payload = {
        "campaignCode": CAMPAIGN_CODE,
        "linkTitle": product_name[:100],  # API may have length limit
        "linkTemplate": product_url,
        "affiliateCode": AFFILIATE_CODE,
        "locale": {"countryCode": "EG", "languageCode": "en"},
    }

    try:
        response = requests.post(AFFILIATE_API_URL, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.HTTPError as e:
        if response.status_code == 401 and not _retried:
            print("  Affiliate API 401 — attempting session refresh")
            try:
                new_cookie = re_authenticate()
                return build_affiliate_link(product_url, product_name, session_cookie=new_cookie, _retried=True)
            except (AuthError, AffiliateError) as reauth_err:
                raise AffiliateError(f"Re-auth failed: {reauth_err}") from reauth_err
        raise AffiliateError(f"Affiliate API error {response.status_code}: {response.text}") from e
    except requests.RequestException as e:
        raise AffiliateError(f"Affiliate API request failed: {e}") from e

    data = response.json()
    print(f"  Affiliate API response: {data}")

    short_url = (
        data.get("url") or data.get("shortUrl") or data.get("short_url")
        or data.get("link") or data.get("trackingLink") or data.get("customLink")
        or data.get("tracking_url") or data.get("redirect_url")
    )

    # Try nested data wrapper (some APIs wrap response)
    if not short_url and isinstance(data.get("data"), dict):
        short_url = data["data"].get("url") or data["data"].get("shortUrl")

    # linkCode exists but shortUrl is always null from this API — use linkTemplate
    # (the correct product URL that the API echoes back, with proper /{sku}/p/ format)
    if not short_url:
        short_url = data.get("linkTemplate")
        link_code = data.get("linkCode", "")
        if short_url:
            print(f"  Using linkTemplate (linkCode={link_code})")

    if not short_url:
        raise AffiliateError(f"Affiliate API returned unexpected response: {data}")

    return short_url
