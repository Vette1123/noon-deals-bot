from telegram_poster import (
    _build_markup,
    channel_share_url,
    format_message,
    with_affiliate_utms,
)


def _product(**overrides):
    p = {
        "name": "Samsung A15",
        "sale_price": 2999.0,
        "original_price": 4000.0,
        "discount_pct": 25,
        "url": "https://www.noon.com/egypt-en/samsung-a15/N12345678A/p/",
    }
    p.update(overrides)
    return p


def test_format_contains_key_info():
    msg = format_message(_product())
    assert "Samsung" in msg
    assert "25" in msg
    assert "noon.com" in msg


def test_format_has_emojis():
    msg = format_message(_product(name="Test", sale_price=100.0, original_price=200.0, discount_pct=50))
    assert any(e in msg for e in ["🔥", "💰", "📉", "🛒"])


def test_coupon_rendered_as_tap_to_copy_code_span():
    msg = format_message(_product(), coupon="gado1996")
    # code span (tap-to-copy on mobile Telegram) around the exact coupon value
    assert "`gado1996`" in msg
    assert "🎟️" in msg


def test_empty_coupon_omits_coupon_line():
    msg = format_message(_product(), coupon="")
    assert "🎟️" not in msg
    assert "`" not in msg


def test_unsafe_coupon_is_rejected():
    # Anything outside [A-Za-z0-9_-] is dropped so we never emit unescaped content inside a code span
    msg = format_message(_product(), coupon="bad code!")
    assert "🎟️" not in msg


def test_markup_has_copy_button_and_buy_button_when_coupon_present():
    markup = _build_markup("https://www.noon.com/foo", coupon="gado1996")
    rows = markup.inline_keyboard
    assert len(rows) == 2
    copy_btn = rows[0][0]
    assert copy_btn.copy_text is not None
    assert copy_btn.copy_text.text == "gado1996"
    assert "gado1996" in copy_btn.text
    assert "📋" in copy_btn.text
    buy_btn = rows[1][0]
    assert buy_btn.url == "https://www.noon.com/foo"
    assert buy_btn.copy_text is None


def test_markup_omits_copy_button_when_no_coupon():
    markup = _build_markup("https://www.noon.com/foo", coupon="")
    rows = markup.inline_keyboard
    assert len(rows) == 1
    assert rows[0][0].url == "https://www.noon.com/foo"


def test_markup_rejects_unsafe_coupon():
    markup = _build_markup("https://www.noon.com/foo", coupon="bad code!")
    rows = markup.inline_keyboard
    assert len(rows) == 1  # copy button dropped
    assert rows[0][0].copy_text is None


def test_utms_appended_with_question_mark_when_no_query_string():
    out = with_affiliate_utms("https://www.noon.com/egypt-en/foo/N1A/p/")
    assert "?utm_campaign=" in out
    assert "&utm_medium=AFFccacc092d97d" in out
    assert "&utm_source=" in out
    assert "&adjust_deeplink_js=1" in out


def test_utms_appended_with_ampersand_when_query_string_already_present():
    out = with_affiliate_utms("https://www.noon.com/egypt-en/foo?ref=email")
    assert "?ref=email&utm_campaign=" in out
    assert out.count("?") == 1  # no second '?'


def test_utms_idempotent_when_already_decorated():
    decorated = with_affiliate_utms("https://www.noon.com/egypt-en/foo/N1A/p/")
    twice = with_affiliate_utms(decorated)
    assert twice == decorated


def test_utms_preserve_url_fragment():
    out = with_affiliate_utms("https://www.noon.com/egypt-en/foo/N1A/p/#reviews")
    assert out.endswith("#reviews")
    assert "utm_medium=" in out


def test_utms_disabled_when_medium_env_var_is_empty(monkeypatch):
    monkeypatch.setenv("NOON_AFFILIATE_MEDIUM", "")
    url = "https://www.noon.com/egypt-en/foo/N1A/p/"
    assert with_affiliate_utms(url) == url


def test_utms_respect_env_var_overrides(monkeypatch):
    monkeypatch.setenv("NOON_AFFILIATE_CAMPAIGN", "CMP_TEST")
    monkeypatch.setenv("NOON_AFFILIATE_MEDIUM", "AFF_TEST")
    monkeypatch.setenv("NOON_AFFILIATE_SOURCE", "SRC_TEST")
    out = with_affiliate_utms("https://www.noon.com/egypt-en/foo/N1A/p/")
    assert "utm_campaign=CMP_TEST" in out
    assert "utm_medium=AFF_TEST" in out
    assert "utm_source=SRC_TEST" in out


def test_utms_handles_empty_url():
    assert with_affiliate_utms("") == ""


def test_format_message_decorates_url_with_utms():
    msg = format_message(_product())
    assert "utm_medium=AFFccacc092d97d" in msg
    assert "utm_campaign=CMP2ce0b63a6a1anoon" in msg


def test_trust_badges_rendered_when_flags_present():
    msg = format_message(_product(
        is_bestseller=True, fulfilled_by_noon=True, free_delivery=True,
    ))
    assert "الأكثر مبيعاً" in msg
    assert "شحن نون" in msg
    assert "توصيل مجاني" in msg


def test_trust_badge_line_omitted_when_no_flags():
    assert "شحن نون" not in format_message(_product())


def test_share_link_forwards_the_channel_not_the_product():
    # A forward that wins a subscriber beats one that wins a single click.
    share = channel_share_url("@noon_hot_deals", "Samsung A15")
    assert share.startswith("https://t.me/share/url?url=")
    assert "https%3A%2F%2Ft.me%2Fnoon_hot_deals" in share
    assert "Samsung" in share


def test_share_link_omitted_for_private_channels():
    # Numeric chat IDs have no public t.me URL, so a share button would 404.
    assert channel_share_url("-1001234567890") == ""
    assert channel_share_url("") == ""


def test_share_button_sits_next_to_buy_not_above_it():
    markup = _build_markup("https://www.noon.com/foo", share_url="https://t.me/share/url?url=x")
    rows = markup.inline_keyboard
    assert len(rows) == 1 and len(rows[0]) == 2
    assert rows[0][0].text == "🛒 اشتري دلوقتي"
    assert "شارك" in rows[0][1].text


def test_buy_button_stands_alone_without_a_share_link():
    rows = _build_markup("https://www.noon.com/foo").inline_keyboard
    assert len(rows) == 1 and len(rows[0]) == 1
