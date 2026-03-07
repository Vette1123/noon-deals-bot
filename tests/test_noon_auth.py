from noon_auth import AuthError, re_authenticate
import responses as rsps
import pytest
from noon_auth import _noon_login, AuthError, _LOGIN_URL


@rsps.activate
def test_noon_login_returns_token():
    rsps.add(rsps.POST, _LOGIN_URL, json={"token": "tok_abc123"}, status=200)
    token = _noon_login("user@example.com", "s3cr3t")
    assert token == "tok_abc123"


@rsps.activate
def test_noon_login_raises_on_failure():
    rsps.add(rsps.POST, _LOGIN_URL, json={"error": "invalid"}, status=401)
    with pytest.raises(AuthError, match="Login failed"):
        _noon_login("user@example.com", "wrong")
