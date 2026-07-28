import json

import pytest

import main


def _product(sku, **overrides):
    p = {
        "sku": sku,
        "name": f"Product {sku}",
        "url": f"https://www.noon.com/egypt-en/p/{sku}/p/",
        "image_url": None,
        "sale_price": 500.0,
        "original_price": 1000.0,
        "discount_pct": 50,
        "store_name": f"Store {sku}",
    }
    p.update(overrides)
    return p


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """Run main against throwaway state files."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, "POSTED_FILE", str(tmp_path / "posted.json"))
    monkeypatch.setattr(main, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    return tmp_path


def _read(path):
    with open(path) as f:
        return json.load(f)


def test_zero_products_fails_the_run_instead_of_exiting_clean(workdir, monkeypatch):
    monkeypatch.setattr(main, "fetch_products", lambda start_page=1: [])
    with pytest.raises(SystemExit):
        main.run()
    # Cursor still resets so the next attempt starts from the top.
    assert _read(workdir / "state.json") == {"next_page": 1}


def test_cursor_advances_even_when_nothing_qualifies(workdir, monkeypatch):
    # Regression: the old code returned early on an empty deal list, so the bot
    # re-scraped the same two pages forever instead of moving through the catalogue.
    monkeypatch.setattr(main, "fetch_products", lambda start_page=1: [_product("A", discount_pct=1)])
    monkeypatch.setattr(main, "post_deal", lambda *a, **k: pytest.fail("should not post"))
    main.run()
    assert _read(workdir / "state.json")["next_page"] == 1 + main.PAGES_PER_RUN


def test_posted_state_survives_a_crash_mid_run(workdir, monkeypatch):
    products = [_product("A"), _product("B"), _product("C")]
    monkeypatch.setattr(main, "fetch_products", lambda start_page=1: products)
    monkeypatch.setattr(main, "DELAY_BETWEEN_POSTS", 0)

    sent = []

    def flaky_post(product, *a, **k):
        if len(sent) == 2:
            raise RuntimeError("telegram exploded")
        sent.append(product["sku"])
        return True

    monkeypatch.setattr(main, "post_deal", flaky_post)
    with pytest.raises(RuntimeError):
        main.run()

    # The two deals that did go out are recorded, so they are not sent twice.
    assert set(_read(workdir / "posted.json")) == set(sent)


def test_already_posted_deals_are_not_repeated(workdir, monkeypatch):
    monkeypatch.setattr(main, "fetch_products", lambda start_page=1: [_product("A"), _product("B")])
    monkeypatch.setattr(main, "DELAY_BETWEEN_POSTS", 0)
    monkeypatch.setattr(main, "post_deal", lambda *a, **k: True)

    main.run()
    first = set(_read(workdir / "posted.json"))
    assert first == {"A", "B"}

    posted_second_time = []
    monkeypatch.setattr(
        main, "post_deal",
        lambda product, *a, **k: posted_second_time.append(product["sku"]) or True,
    )
    main.run()
    assert posted_second_time == []


def test_post_cap_is_respected(workdir, monkeypatch):
    products = [_product(f"S{i}", store_name=f"Store {i}") for i in range(30)]
    monkeypatch.setattr(main, "fetch_products", lambda start_page=1: products)
    monkeypatch.setattr(main, "MAX_POSTS_PER_RUN", 5)
    monkeypatch.setattr(main, "DELAY_BETWEEN_POSTS", 0)
    monkeypatch.setattr(main, "post_deal", lambda *a, **k: True)
    main.run()
    assert len(_read(workdir / "posted.json")) == 5


def test_cursor_wraps_at_the_end_of_the_catalogue():
    assert main._next_page(main.MAX_PAGES - main.PAGES_PER_RUN + 1) == 1
    assert main._next_page(1) == 1 + main.PAGES_PER_RUN
