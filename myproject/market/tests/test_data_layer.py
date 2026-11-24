"""Unit tests for the data layer. Every network call is mocked: tests are fast, deterministic
and run in CI without API keys."""
from datetime import date
from unittest import mock

import numpy as np
import pandas as pd
import pytest
import requests

from market.providers import Nexchange
from market.stocks import IPO, stocks_home_page, stocksOverview


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache
    cache.clear()


# ---------- world indices: no look-ahead ----------

def _close_frame(index, columns):
    return pd.concat({"Close": pd.DataFrame(columns, index=index)}, axis=1)


def test_indices_do_not_backfill_future_prices(monkeypatch):
    """An index with no data a year ago must report y1=None, not a later price copied back.
    With the old .bfill() this returned a made-up 1Y change."""
    idx = pd.bdate_range(end="2026-11-20", periods=400)
    full = np.linspace(100, 200, len(idx))
    late = full.copy()
    late[:300] = np.nan  # this index only has data for the last 100 business days
    df = _close_frame(idx, {"^GSPC": full, "^DJI": late})
    monkeypatch.setattr(stocks_home_page.yf, "download", lambda *a, **k: df)

    rows = {r["symbol"]: r for r in stocks_home_page.get_world_indices_tables()["americas"]}

    assert rows["^GSPC"]["y1"] is not None
    assert rows["^DJI"]["y1"] is None
    assert rows["^DJI"]["value"] == pytest.approx(200.0)


def test_rows_for_group_percent_changes():
    idx = pd.to_datetime(["2026-11-18", "2026-11-19", "2026-11-20"])
    close = pd.DataFrame({"^FTSE": [100.0, 100.0, 110.0]}, index=idx)
    (row,) = stocks_home_page._rows_for_group(close, [{"symbol": "^FTSE", "name": "FTSE"}, {"symbol": "^MISSING", "name": "x"}])
    assert row["value"] == 110.0
    assert row["change"] == 10.0
    assert row["pct_change"] == 10.0
    assert row["as_of"] == "2026-11-20"


def test_closed_market_uses_its_own_last_session():
    """Nikkei closed on 2026-11-20 (holiday): its day change is its last real session
    (11-18 -> 11-19), dated 11-19, not a flat 0.00 against itself."""
    idx = pd.to_datetime(["2026-11-18", "2026-11-19", "2026-11-20"])
    close = pd.DataFrame({"^N225": [100.0, 105.0, np.nan], "^GSPC": [1.0, 1.0, 1.0]}, index=idx)
    (row,) = stocks_home_page._rows_for_group(close, [{"symbol": "^N225", "name": "Nikkei"}])
    assert row["as_of"] == "2026-11-19"
    assert row["change"] == 5.0 and row["pct_change"] == 5.0


def _resp(payload, status=200):
    r = mock.Mock(status_code=status)
    r.json.return_value = payload
    r.raise_for_status.side_effect = None if status < 400 else requests.HTTPError(str(status))
    return r


# ---------- analyst ratings ----------

def test_analyst_ratings_newest_first_mapped_and_windowed(monkeypatch):
    """Grades come from Yahoo, newest first, action codes mapped to words, 365-day window applied
    (2025-01-02 is outside it)."""
    df = pd.DataFrame(
        {"Firm": ["Old Co", "RBC", "TD"], "ToGrade": ["Hold", "Buy", "Buy"],
         "FromGrade": ["", "Hold", "Buy"], "Action": ["main", "up", "reit"]},
        index=pd.DatetimeIndex(["2025-01-02", "2026-11-20 14:58", "2026-11-18"], name="GradeDate"),
    )
    monkeypatch.setattr(stocksOverview.yf, "Ticker", lambda s: mock.Mock(upgrades_downgrades=df))
    rows = stocksOverview.get_analyst_ratings("MSFT", today=date(2026, 11, 21))
    assert [(r["date"], r["firm"], r["action"]) for r in rows] == [
        ("2026-11-20", "RBC", "upgrade"), ("2026-11-18", "TD", "reiterate")]
    assert rows[0]["previous_grade"] == "Hold" and rows[1]["new_grade"] == "Buy"


def test_analyst_ratings_carry_price_target_changes(monkeypatch):
    """Yahoo's price-target columns come through; its 0 means 'no target' and becomes None."""
    df = pd.DataFrame(
        {"Firm": ["Jefferies", "UBS", "Old Co", "New Co"], "ToGrade": ["Hold", "Buy", "Buy", "Buy"],
         "FromGrade": ["Hold", "Buy", "Buy", ""], "Action": ["main", "main", "main", "init"],
         "priceTargetAction": ["Raises", "Maintains", "", "Announces"],
         "currentPriceTarget": [175.0, 180.0, 0.0, 150.0], "priorPriceTarget": [145.0, 180.0, 0.0, 0.0]},
        index=pd.DatetimeIndex(["2026-11-09", "2026-11-08", "2026-11-07", "2026-11-06"], name="GradeDate"),
    )
    monkeypatch.setattr(stocksOverview.yf, "Ticker", lambda s: mock.Mock(upgrades_downgrades=df))
    rows = stocksOverview.get_analyst_ratings("DUOL", today=date(2026, 11, 24))
    got = [(r["firm"], r["price_target_action"], r["prior_price_target"], r["price_target"]) for r in rows]
    assert got == [("Jefferies", "raise", 145.0, 175.0), ("UBS", "maintain", 180.0, 180.0),
                   ("Old Co", None, None, None), ("New Co", "new", None, 150.0)]


def test_analyst_ratings_without_target_columns(monkeypatch):
    """Older yfinance versions have no price-target columns: the fields are just None."""
    df = pd.DataFrame({"Firm": ["RBC"], "ToGrade": ["Buy"], "FromGrade": ["Hold"], "Action": ["up"]},
                      index=pd.DatetimeIndex(["2026-11-20"], name="GradeDate"))
    monkeypatch.setattr(stocksOverview.yf, "Ticker", lambda s: mock.Mock(upgrades_downgrades=df))
    (row,) = stocksOverview.get_analyst_ratings("MSFT", today=date(2026, 11, 21))
    assert (row["price_target"], row["prior_price_target"], row["price_target_action"]) == (None, None, None)


# ---------- price history ----------

def test_history_rejects_unknown_period():
    with pytest.raises(ValueError):
        stocksOverview.get_stock_history("AAPL", "15y")


def test_history_5y_uses_a_valid_yahoo_interval(monkeypatch):
    calls = {}

    class FakeTicker:
        def __init__(self, sym):
            pass

        def history(self, period, interval):
            calls.update(period=period, interval=interval)
            return pd.DataFrame({"Close": [1.234]}, index=pd.to_datetime(["2026-01-05"]))

    monkeypatch.setattr(stocksOverview.yf, "Ticker", FakeTicker)
    assert stocksOverview.get_stock_history("AAPL", "5y") == [{"date": "2026-01-05", "price": 1.23}]
    assert calls == {"period": "5y", "interval": "1wk"}  # was "15d", which Yahoo rejects


# ---------- IPO calendar ----------

def test_ipo_without_key_returns_empty(settings):
    settings.FINNHUB_API_KEY = ""
    assert IPO.show_ipo() == []


def test_ipo_window_is_computed_per_call(monkeypatch):
    seen = []
    monkeypatch.setattr(IPO, "ipo", lambda a, b: seen.append((a, b)) or {"ipoCalendar": [{"symbol": "NEW", "price": "", "date": "2026-12-01"}]})
    rows = IPO.show_ipo(today=date(2026, 11, 20))
    assert seen == [(date(2026, 10, 21), date(2027, 11, 20))]  # 30 days back, 365 ahead
    assert rows[0]["symbol"] == "NEW" and rows[0]["price"] is None and rows[0]["name"] is None


def test_ipo_upcoming_first_then_recent_newest_first(monkeypatch):
    cal = {"ipoCalendar": [
        {"symbol": "OLD", "date": "2026-11-01"},
        {"symbol": "SOON", "date": "2026-11-25"},
        {"symbol": "LATER", "date": "2027-01-10"},
        {"symbol": "TODAY", "date": "2026-11-20"},
        {"symbol": "NEWER", "date": "2026-11-15"},
    ]}
    monkeypatch.setattr(IPO, "ipo", lambda a, b: cal)
    rows = IPO.show_ipo(today=date(2026, 11, 20))
    assert [r["symbol"] for r in rows] == ["TODAY", "SOON", "LATER", "NEWER", "OLD"]
    assert [r["upcoming"] for r in rows] == [True, True, True, False, False]


# ---------- crypto ----------

def test_crypto_failure_is_not_cached(monkeypatch):
    ok = [{c: 1 for c in Nexchange.CRYPTO_COLUMNS}]
    responses = iter([requests.ConnectionError("down"), _resp(ok)])

    def fake_get(*a, **k):
        r = next(responses)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(Nexchange.requests, "get", fake_get)
    assert Nexchange.get_crypto_table() == []   # outage
    assert Nexchange.get_crypto_table() == ok   # next call retries instead of serving a cached []


def test_crypto_schema_change_returns_empty(monkeypatch):
    monkeypatch.setattr(Nexchange.requests, "get", lambda *a, **k: _resp([{"symbol": "btc"}]))
    assert Nexchange.get_crypto_table() == []


# ---------- analyst recommendation trend ----------

def test_trend_from_finnhub_oldest_first(settings, monkeypatch):
    settings.FINNHUB_API_KEY = "k"
    raw = [{"period": "2026-11-01", "strongBuy": 10, "buy": 12, "hold": 2, "sell": 0, "strongSell": 0},
           {"period": "2026-10-01", "strongBuy": 9, "buy": 12, "hold": 2, "sell": 1, "strongSell": 0}]
    import finnhub
    monkeypatch.setattr(finnhub, "Client", lambda api_key: mock.Mock(recommendation_trends=lambda s: raw))
    out = stocksOverview.get_recommendation_trend("pony")
    assert out["source"] == "finnhub"
    assert [m["period"] for m in out["months"]] == ["2026-10", "2026-11"]
    assert out["months"][0] == {"period": "2026-10", "strong_buy": 9, "buy": 12, "hold": 2, "sell": 1, "strong_sell": 0}


def test_trend_falls_back_to_yahoo_relative_months(settings, monkeypatch):
    settings.FINNHUB_API_KEY = ""
    df = pd.DataFrame({"period": ["0m", "-1m", "-2m"], "strongBuy": [4, 3, 3], "buy": [13, 13, 14],
                       "hold": [1, 1, 1], "sell": [0, 0, 0], "strongSell": [0, 0, 0]})
    monkeypatch.setattr(stocksOverview.yf, "Ticker", lambda s: mock.Mock(recommendations=df))
    out = stocksOverview.get_recommendation_trend("PONY", today=date(2026, 1, 15))
    assert out["source"] == "yahoo"
    assert [m["period"] for m in out["months"]] == ["2025-11", "2025-12", "2026-01"]  # crosses the year boundary
    assert out["months"][-1]["strong_buy"] == 4


def test_overview_includes_key_statistics_and_profile(monkeypatch):
    info = {"currentPrice": 100.0, "longName": "Acme", "marketCap": 3.5e12, "trailingPE": 30.1, "forwardPE": 25.0,
            "trailingEps": 3.3, "beta": 1.1, "dividendYield": 0.44, "averageDailyVolume3Month": 5_000_000,
            "regularMarketDayLow": 98.0, "regularMarketDayHigh": 101.0, "longBusinessSummary": "Makes things.",
            "website": "https://acme.example"}
    t = mock.MagicMock(info=info, analyst_price_targets={"low": 80, "high": 150, "mean": 120, "median": 118},
                       recommendations=None, ticker="ACME")
    monkeypatch.setattr(stocksOverview.yf, "Ticker", lambda s: t)
    o = stocksOverview.get_stock_overview("acme")
    assert (o["market_cap"], o["pe_ttm"], o["pe_forward"], o["eps_ttm"], o["beta"]) == (3.5e12, 30.1, 25.0, 3.3, 1.1)
    assert o["dividend_yield_pct"] == 0.44 and o["avg_volume"] == 5_000_000
    assert (o["day_low"], o["day_high"]) == (98.0, 101.0)
    assert o["summary"] == "Makes things." and o["website"] == "https://acme.example"
    assert (o["target_low"], o["target_median"], o["target_high"]) == (80, 118, 150)
