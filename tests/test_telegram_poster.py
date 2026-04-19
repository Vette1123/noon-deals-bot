from telegram_poster import _build_markup, format_message


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
