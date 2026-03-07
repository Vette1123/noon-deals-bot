import responses
import requests
import pytest
from unittest.mock import patch
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
    responses.add(
        responses.POST,
        "https://affiliates.noon.partners/_svc/affiliate/affiliate/campaign/custom_link",
        json={"error": "unauthorized"},
        status=401
    )
    with patch("affiliate.re_authenticate", return_value="_npsid=fresh99"):
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


@responses.activate
def test_retries_after_401_with_new_cookie():
    """On 401, calls re_authenticate() then retries once and succeeds."""
    responses.add(
        responses.POST,
        "https://affiliates.noon.partners/_svc/affiliate/affiliate/campaign/custom_link",
        json={"error": "UnAuthenticated"},
        status=401,
    )
    responses.add(
        responses.POST,
        "https://affiliates.noon.partners/_svc/affiliate/affiliate/campaign/custom_link",
        json={"url": "https://s.noon.com/refreshed"},
        status=200,
    )

    with patch("affiliate.re_authenticate", return_value="_npsid=fresh99") as mock_reauth:
        result = build_affiliate_link(
            product_url="https://www.noon.com/egypt-en/product/p/SKU/",
            product_name="Test",
            session_cookie="expired_cookie",
        )

    assert result == "https://s.noon.com/refreshed"
    mock_reauth.assert_called_once()


@responses.activate
def test_raises_if_retry_also_fails():
    """If the retried call also 401s, raises AffiliateError without looping."""
    responses.add(
        responses.POST,
        "https://affiliates.noon.partners/_svc/affiliate/affiliate/campaign/custom_link",
        json={"error": "UnAuthenticated"},
        status=401,
    )
    responses.add(
        responses.POST,
        "https://affiliates.noon.partners/_svc/affiliate/affiliate/campaign/custom_link",
        json={"error": "UnAuthenticated"},
        status=401,
    )

    with patch("affiliate.re_authenticate", return_value="_npsid=fresh99"):
        with pytest.raises(AffiliateError):
            build_affiliate_link(
                product_url="https://www.noon.com/egypt-en/product/p/SKU/",
                product_name="Test",
                session_cookie="expired_cookie",
            )
