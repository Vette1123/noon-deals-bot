import facebook_poster
from facebook_poster import facebook_enabled, format_plain_message, post_to_facebook


def _product(**overrides):
    p = {
        "name": "Samsung A15",
        "sale_price": 2999.0,
        "original_price": 4000.0,
        "discount_pct": 25,
        "store_name": "Mobile Zone",
    }
    p.update(overrides)
    return p


def test_disabled_without_both_credentials(monkeypatch):
    monkeypatch.delenv("FACEBOOK_PAGE_ID", raising=False)
    monkeypatch.delenv("FACEBOOK_PAGE_TOKEN", raising=False)
    assert facebook_enabled() is False
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "123")
    assert facebook_enabled() is False
    monkeypatch.setenv("FACEBOOK_PAGE_TOKEN", "tok")
    assert facebook_enabled() is True


def test_no_request_is_made_when_unconfigured(monkeypatch):
    monkeypatch.delenv("FACEBOOK_PAGE_ID", raising=False)
    monkeypatch.delenv("FACEBOOK_PAGE_TOKEN", raising=False)
    monkeypatch.setattr(facebook_poster.requests, "post", _explode)
    assert post_to_facebook(_product(), "https://noon.com/x") is False


def _explode(*a, **k):
    raise AssertionError("should not have called the Graph API")


def test_posts_a_link_post_so_the_url_stays_clickable(monkeypatch):
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "123")
    monkeypatch.setenv("FACEBOOK_PAGE_TOKEN", "tok")
    seen = {}

    class Resp:
        ok = True

    def fake_post(url, data=None, timeout=None):
        seen["url"] = url
        seen["data"] = data
        return Resp()

    monkeypatch.setattr(facebook_poster.requests, "post", fake_post)
    assert post_to_facebook(_product(), "https://noon.com/x?utm_medium=AFF1",
                            coupon="gado1996", channel_handle="@noon_hot_deals") is True
    assert seen["url"].endswith("/123/feed")
    assert seen["data"]["link"] == "https://noon.com/x?utm_medium=AFF1"
    assert seen["data"]["access_token"] == "tok"
    assert "gado1996" in seen["data"]["message"]
    assert "https://t.me/noon_hot_deals" in seen["data"]["message"]


def test_graph_errors_are_swallowed_so_the_run_survives(monkeypatch):
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "123")
    monkeypatch.setenv("FACEBOOK_PAGE_TOKEN", "tok")

    class Resp:
        ok = False
        status_code = 400
        text = '{"error":{"message":"expired token"}}'

    monkeypatch.setattr(facebook_poster.requests, "post", lambda *a, **k: Resp())
    assert post_to_facebook(_product(), "https://noon.com/x") is False

    def boom(*a, **k):
        raise ConnectionError("network down")

    monkeypatch.setattr(facebook_poster.requests, "post", boom)
    assert post_to_facebook(_product(), "https://noon.com/x") is False


def test_plain_message_has_no_markdown_escapes():
    msg = format_plain_message(_product(), coupon="gado1996")
    assert "\\" not in msg
    assert "`" not in msg
    assert "2,999" in msg and "25%" in msg
