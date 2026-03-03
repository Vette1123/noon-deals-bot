from telegram_poster import format_message

def test_format_contains_key_info():
    p = {"name": "Samsung A15", "sale_price": 2999.0, "original_price": 4000.0,
         "discount_pct": 25, "affiliate_url": "https://s.noon.com/AbCdEf"}
    msg = format_message(p)
    assert "Samsung" in msg
    assert "25" in msg
    assert "s.noon.com" in msg

def test_format_has_emojis():
    p = {"name": "Test", "sale_price": 100.0, "original_price": 200.0,
         "discount_pct": 50, "affiliate_url": "https://s.noon.com/test"}
    msg = format_message(p)
    assert any(e in msg for e in ["🔥", "💰", "📉", "🛒"])
