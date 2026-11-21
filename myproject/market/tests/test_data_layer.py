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


# ---------- FMP client ----------

@pytest.fixture
def fmp_key(settings):
    settings.FMP_API_KEY = "test-key"


def _resp(payload, status=200):
    r = mock.Mock(status_code=status)
    r.json.return_value = payload
    r.raise_for_status.side_effect = None if status < 400 else requests.HTTPError(str(status))
    return r


def test_fmp_get_without_key_makes_no_request(settings):
    settings.FMP_API_KEY = ""
    with mock.patch.object(stocksOverview.requests, "get") as get:
        assert stocksOverview._fmp_get("quote", "AAPL") is None
    get.assert_not_called()


def test_fmp_get_treats_error_object_as_failure(fmp_key):
    # FMP reports errors as HTTP 200 + a JSON object; the old code then crashed on profile[0].
    with mock.patch.object(stocksOverview.requests, "get", return_value=_resp({"Error Message": "Limit reached"})):
        assert stocksOverview._fmp_get("quote", "AAPL") is None


def test_fmp_get_timeout_returns_none(fmp_key):
    with mock.patch.object(stocksOverview.requests, "get", side_effect=requests.Timeout()):
        assert stocksOverview._fmp_get("quote", "AAPL") is None


def test_fmp_get_passes_timeout_and_key_as_params(fmp_key):
    with mock.patch.object(stocksOverview.requests, "get", return_value=_resp([{"price": 1}])) as get:
        assert stocksOverview._fmp_get("quote", "AAPL") == [{"price": 1}]
    _, kwargs = get.call_args
    assert kwargs["timeout"] == stocksOverview.HTTP_TIMEOUT_S
    assert kwargs["params"] == {"symbol": "AAPL", "apikey": "test-key"}


def test_overview_falls_back_to_yfinance_when_fmp_unavailable(monkeypatch):
    monkeypatch.setattr(stocksOverview, "_fmp_get", lambda *a: None)
    monkeypatch.setattr(stocksOverview, "get_stock_overview_yf", lambda s: {"symbol": s, "source": "yfinance"})
    assert stocksOverview.get_stock_overview("aapl") == {"symbol": "AAPL", "source": "yfinance"}


def test_analyst_ratings_use_rolling_window(monkeypatch):
    grades = [
        {"date": "2026-11-01", "gradingCompany": "A"},
        {"date": "2025-11-21", "gradingCompany": "B"},  # inside 365 days of 2026-11-20
        {"date": "2025-11-19", "gradingCompany": "C"},  # outside
        {"gradingCompany": "D"},                          # no date
    ]
    monkeypatch.setattr(stocksOverview, "_fmp_get", lambda *a: grades)
    firms = [g["firm"] for g in stocksOverview.get_analyst_ratings("AAPL", today=date(2026, 11, 20))]
    assert firms == ["A", "B"]


def test_analyst_ratings_fall_back_to_yfinance(monkeypatch):
    """No FMP key -> grades come from Yahoo, newest first, action codes mapped, window applied."""
    monkeypatch.setattr(stocksOverview, "_fmp_get", lambda *a: None)
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
