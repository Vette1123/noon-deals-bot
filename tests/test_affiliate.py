import responses
import requests
import pytest
from affiliate import build_affiliate_link, AffiliateError

@responses.activate
def test_returns_short_url_on_success():
    responses.add(
        responses.POST,
        "https://affiliates.noon.partners/_svc/affiliate/affiliate/campaign/custom_link",
        json={"url": "https://s.noon.com/AbCdEfGhI"},
        status=200
    )
    result = build_affiliate_link(
        product_url="https://www.noon.com/egypt-en/some-product/p/N12345678A/",
        product_name="Test Product",
        session_cookie="fake_cookie"
    )
    assert result == "https://s.noon.com/AbCdEfGhI"

@responses.activate
def test_raises_on_api_failure():
    responses.add(
        responses.POST,
        "https://affiliates.noon.partners/_svc/affiliate/affiliate/campaign/custom_link",
        json={"error": "unauthorized"},
        status=401
    )
    with pytest.raises(AffiliateError):
        build_affiliate_link(
            product_url="https://www.noon.com/egypt-en/product/p/SKU/",
            product_name="Test",
            session_cookie="bad_cookie"
        )

def test_raises_on_missing_cookie():
    with pytest.raises(AffiliateError, match="session cookie"):
        build_affiliate_link(
            product_url="https://www.noon.com/egypt-en/product/p/SKU/",
            product_name="Test",
            session_cookie=""
        )
