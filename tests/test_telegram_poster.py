from telegram_poster import format_message


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
