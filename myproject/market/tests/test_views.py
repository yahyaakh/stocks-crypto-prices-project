"""HTTP-level tests through Django's test client, upstream providers mocked."""
import json
from unittest import mock

import pytest

from market import views


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache
    cache.clear()


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert "no-cache" in r["Cache-Control"]


def test_sanitize_floats_nested():
    out = views.sanitize_floats({"a": [1.0, float("nan")], "b": {"c": float("inf")}, "d": "x"})
    assert out == {"a": [1.0, None], "b": {"c": None}, "d": "x"}


def test_crypto_api_emits_valid_json_for_nan(client, monkeypatch):
    monkeypatch.setattr(views, "get_crypto_table", lambda: [{"symbol": "x", "price_change_percentage_24h": float("nan")}])
    r = client.get("/api/crypto/")
    assert r.status_code == 200
    # Python's json would happily emit NaN; strict parsers (browsers) reject it.
    assert json.loads(r.content, parse_constant=lambda c: pytest.fail(f"invalid JSON constant {c}")) == [
        {"symbol": "x", "price_change_percentage_24h": None}
    ]


def test_api_rejects_post(client):
    assert client.post("/api/crypto/").status_code == 405


class _FastInfo(dict):
    pass


def _ticker_with(fast_info=None, exc=None):
    t = mock.Mock()
    if exc is not None:
        type(t).fast_info = mock.PropertyMock(side_effect=exc)
    else:
        t.fast_info = _FastInfo(fast_info)
    return t


def test_get_price_requires_symbol(client):
    assert client.get("/api/get-price/").status_code == 400


def test_get_price_unknown_symbol_is_404_not_500(client, monkeypatch):
    monkeypatch.setattr(views.yf, "Ticker", lambda s: _ticker_with(exc=KeyError("last_price")))
    assert client.get("/api/get-price/?symbol=NOPE").status_code == 404


def test_get_price_zero_prev_close_does_not_divide_by_zero(client, monkeypatch):
    monkeypatch.setattr(views.yf, "Ticker", lambda s: _ticker_with({"last_price": 10.0, "previous_close": 0}))
    r = client.get("/api/get-price/?symbol=abc")
    assert r.status_code == 200
    assert r.json() == {"symbol": "ABC", "price": 10.0, "change": None, "change_pct": None}


def test_get_price_change(client, monkeypatch):
    monkeypatch.setattr(views.yf, "Ticker", lambda s: _ticker_with({"last_price": 110.0, "previous_close": 100.0}))
    assert client.get("/api/get-price/?symbol=abc").json()["change_pct"] == 10.0


def test_history_bad_period_is_400(client):
    assert client.get("/api/stocks/AAPL/history/?period=15d").status_code == 400


def test_ipo_page_renders_without_api_key(client):
    # Used to be a 500 (unhandled Finnhub 401) when FINNHUB_API_KEY was not set.
    assert client.get("/ipo/").status_code == 200


@pytest.mark.parametrize("path", ["/live/", "/live/stock/MSFT"])
def test_react_routes_are_served_by_django(client, path):
    # React Router (basename "/live") handles deep links; a refresh on /live/stock/MSFT must not 404.
    r = client.get(path)
    assert r.status_code == 200
    assert b"react-watchlist.js" in r.content


def test_overview_unknown_symbol_is_404(client, monkeypatch):
    monkeypatch.setattr(views, "get_stock_overview", lambda s: {"error": f"Symbol '{s}' not found on any source"})
    r = client.get("/api/stocks/ZZZZ/overview/")
    assert r.status_code == 404 and "error" in r.json()


def test_browser_cache_is_short_even_when_server_cache_is_long(client, monkeypatch):
    # Server keeps analyst data for an hour; the browser must not (it would pin an empty result).
    monkeypatch.setattr(views, "get_analyst_ratings", lambda s: [])
    r = client.get("/api/stocks/MSFT/ratings/")
    assert "max-age=60" in r["Cache-Control"]


# ---------- one page per stock ----------

@pytest.mark.parametrize("path, target", [
    ("/stock/?symbol=aapl", "/live/stock/AAPL"),          # header search box
    ("/stock/brk-b/", "/live/stock/BRK-B"),
    ("/stock/%5EGSPC/", "/live/stock/%5EGSPC"),          # Django percent-encodes ^; React Router decodes it
    ("/info/?symbol=nvda", "/live/stock/NVDA"),           # retired pages keep working
    ("/target/?symbol=MSFT", "/live/stock/MSFT"),
    ("/stock/?symbol=", "/stocks/"),                      # not a symbol: back to Research
    ("/stock/?symbol=%3Cscript%3E", "/stocks/"),
    ("/info/", "/stocks/"),
])
def test_stock_lookup_redirects(client, path, target):
    r = client.get(path)
    assert r.status_code == 302 and r["Location"] == target


def test_research_page_links_to_overview_and_not_retired_pages(client):
    html = client.get("/stocks/").content.decode()
    assert 'href="/live/stock/AAPL"' in html and 'action="/stock/"' in html
    assert "/info/" not in html and "/target/" not in html
