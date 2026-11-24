"""Top-upside list: parsing Yahoo's answers, the universe filter, ranking, the shared snapshot file
and the page. No network: the screener and quoteSummary calls are replaced."""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from market import upside

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def _ts(days_ago: float) -> int:
    return int((NOW - timedelta(days=days_ago)).timestamp())


def summary(mean=150.0, median=148.0, low=100.0, high=200.0, analysts=12, key="buy", history=()):
    return {"quoteSummary": {"result": [{
        "financialData": {"currentPrice": 100.0, "targetMeanPrice": mean, "targetMedianPrice": median,
                          "targetLowPrice": low, "targetHighPrice": high, "numberOfAnalystOpinions": analysts,
                          "recommendationKey": key},
        "upgradeDowngradeHistory": {"history": list(history)},
    }]}}


def row(symbol, price, mean, analysts=10, cap=50e9, **extra):
    return {"symbol": symbol, "name": symbol + " Inc.", "exchange": "NYSE", "price": price, "market_cap": cap,
            "target_mean": mean, "target_median": mean, "target_low": mean and mean * 0.8,
            "target_high": mean and mean * 1.2,
            "analysts": analysts, "consensus": "Buy", "recent_count": 3, "last_target_date": "2026-11-20", **extra}


@pytest.fixture(autouse=True)
def _data_dir(settings, tmp_path, monkeypatch):
    settings.UPSIDE_DATA_DIR = str(tmp_path)
    monkeypatch.setattr(upside, "_cache", (0.0, None))


# ---------- parsing ----------

def test_summary_gives_consensus_and_freshness():
    history = [
        {"firm": "A", "epochGradeDate": _ts(10), "currentPriceTarget": 160.0},
        {"firm": "A", "epochGradeDate": _ts(200), "currentPriceTarget": 90.0},     # older row of the same firm
        {"firm": "B", "epochGradeDate": _ts(5), "currentPriceTarget": 0},          # rating change only
        {"firm": "B", "epochGradeDate": _ts(120), "currentPriceTarget": 140.0},    # B's target is stale
        {"firm": "C", "epochGradeDate": _ts(89), "currentPriceTarget": 1450.0},    # value not used, only the date
    ]
    got = upside.parse_summary(summary(key="strong_buy", history=history), NOW)
    assert got == {"analysts": 12, "target_mean": 150.0, "target_median": 148.0, "target_low": 100.0,
                   "target_high": 200.0, "consensus": "Strong buy", "recent_count": 2,
                   "last_target_date": "2026-11-14"}


def test_summary_without_coverage():
    got = upside.parse_summary(summary(mean=None, median=None, low=None, high=None, analysts=None, key="none"), NOW)
    assert got["analysts"] == 0 and got["target_mean"] is None and got["consensus"] is None
    assert got["recent_count"] == 0 and got["last_target_date"] is None
    assert upside.parse_summary({}, NOW)["analysts"] == 0


# ---------- universe ----------

def quote(symbol, cap, price=50.0):
    return {"symbol": symbol, "longName": symbol + " Corp", "fullExchangeName": "NYSE", "marketCap": cap,
            "regularMarketPrice": price}


def test_universe_keeps_listed_common_shares_only(monkeypatch):
    page = [quote("AAPL", 5e12), quote("SPY", 6e11), quote("RF-PC", 3e10), quote("PINKY", 2e10),
            quote("BRK-B", 1e12), quote("MSFT", 4e12, price=None), quote("AAPL", 5e12), quote("NVDA", 4e12)]
    monkeypatch.setattr(upside, "_screen_page", lambda offset, size: {"quotes": page if offset == 0 else [],
                                                                      "total": len(page)})
    got = [r["symbol"] for r in upside.screen_universe(10)]
    # SPY is an ETF, RF-PC a preferred, PINKY not in the directory, MSFT has no price, AAPL twice.
    assert got == ["AAPL", "BRK-B", "NVDA"]
    assert [r["symbol"] for r in upside.screen_universe(2)] == ["AAPL", "BRK-B"]


def test_universe_reads_several_pages(monkeypatch):
    calls = []

    def fake(offset, size):
        calls.append(offset)
        return {"quotes": [quote("AAPL", 1)] * size if offset == 0 else [quote("NVDA", 1)], "total": size + 1}

    monkeypatch.setattr(upside, "_screen_page", fake)
    assert [r["symbol"] for r in upside.screen_universe(5)] == ["AAPL", "NVDA"]
    assert calls == [0, upside.SCREEN_PAGE]


# ---------- build ----------

def test_build_merges_and_skips_failed_stocks(monkeypatch):
    universe = [{"symbol": s, "name": s, "exchange": "NYSE", "market_cap": 1e10, "price": 100.0}
                for s in ["S%d" % i for i in range(10)]]
    monkeypatch.setattr(upside, "screen_universe", lambda size: universe)
    monkeypatch.setattr(upside, "_fetch_targets", lambda s, now: None if s == "S3" else upside.parse_summary(summary(), now))
    snap = upside.build(size=10, workers=2, now=NOW)
    assert snap["universe"] == 10 and snap["failed"] == 1 and len(snap["rows"]) == 9
    assert snap["targets_at"] == snap["prices_at"] == "2026-11-24T12:00:00+00:00"
    assert snap["rows"][0]["target_mean"] == 150.0 and snap["rows"][0]["price"] == 100.0


def test_build_refuses_when_most_requests_fail(monkeypatch):
    universe = [{"symbol": s, "name": s, "exchange": "NYSE", "market_cap": 1, "price": 1.0} for s in "ABCDE"]
    monkeypatch.setattr(upside, "screen_universe", lambda size: universe)
    monkeypatch.setattr(upside, "_fetch_targets", lambda s, now: None if s in "AB" else {})
    with pytest.raises(upside.BuildError):
        upside.build(size=5, now=NOW)


def test_one_retry_after_an_error(monkeypatch):
    answers = [RuntimeError("429"), summary()]

    def flaky(symbol):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr(upside, "_quote_summary", flaky)
    monkeypatch.setattr(upside.time, "sleep", lambda s: None)
    assert upside._fetch_targets("AAPL", NOW)["target_mean"] == 150.0


# ---------- ranking ----------

SNAP = {"rows": [row("BIG", 100, 300, analysts=20), row("ONE", 10, 100, analysts=1), row("MID", 50, 75),
                 row("DOWN", 100, 70), row("SMALL", 20, 40, cap=1e9), row("NONE", 30, None)]}


def test_rank_by_upside_with_filters():
    rows, eligible = upside.rank(SNAP, n=10, basis="mean", direction="up", min_analysts=5, cap="all")
    assert [r["symbol"] for r in rows] == ["BIG", "SMALL", "MID", "DOWN"]      # ONE: 1 analyst; NONE: no target
    assert eligible == 4 and rows[0]["upside_pct"] == pytest.approx(200.0)
    rows, _ = upside.rank(SNAP, n=10, basis="mean", direction="up", min_analysts=1, cap="all")
    assert rows[0]["symbol"] == "ONE"                                         # 900% on one opinion
    rows, eligible = upside.rank(SNAP, n=2, basis="mean", direction="up", min_analysts=5, cap="10b")
    assert [r["symbol"] for r in rows] == ["BIG", "MID"] and eligible == 3


def test_rank_by_downside_and_median():
    snap = {"rows": [row("A", 100, 120, target_median=90), row("B", 100, 110)]}
    rows, _ = upside.rank(snap, n=5, basis="median", direction="down", min_analysts=1, cap="all")
    assert [(r["symbol"], round(r["upside_pct"])) for r in rows] == [("A", -10), ("B", 10)]


def test_range_bar_fits_the_price():
    assert upside._range_bar(100, 200, 50, 150) == {"low": 33.3, "high": 100.0, "price": 0.0, "target": 66.7}
    assert upside._range_bar(None, 200, 50, 150) is None


def test_bad_params_fall_back_to_defaults():
    assert upside.parse_params({"n": "7", "basis": "x", "direction": "sideways", "min_analysts": "a", "cap": "1t"}) \
        == upside.DEFAULTS
    assert upside.parse_params({"n": "50", "basis": "median", "direction": "down", "min_analysts": "10", "cap": "200b"}) \
        == {"n": 50, "basis": "median", "direction": "down", "min_analysts": 10, "cap": "200b"}


# ---------- storage and the refresh job ----------

def snapshot(targets_at=NOW, prices_at=NOW):
    return {"version": 1, "targets_at": targets_at.isoformat(timespec="seconds"),
            "prices_at": prices_at.isoformat(timespec="seconds"), "universe": 2, "rows": [row("BIG", 100, 300)]}


def test_save_and_load_keep_one_file_per_day(tmp_path):
    assert upside.load() is None
    first = snapshot()
    upside.save(first)
    upside.save({**first, "universe": 99})                  # same day: history keeps the first build
    assert upside.load()["universe"] == 99
    assert json.loads((tmp_path / "targets-2026-11-24.json").read_text())["universe"] == 2


def test_due_work(monkeypatch):
    built, priced = [], []
    monkeypatch.setattr(upside, "build", lambda now: built.append(now) or snapshot(now, now))
    monkeypatch.setattr(upside, "refresh_prices", lambda snap, now: priced.append(now) or {**snap, "prices_at": now.isoformat()})
    assert upside.run_due_work(NOW) == "built"
    assert upside.run_due_work(NOW + timedelta(minutes=5)) == "fresh"
    assert upside.run_due_work(NOW + timedelta(minutes=20)) == "prices"
    assert upside.run_due_work(NOW + timedelta(hours=21)) == "built"
    assert len(built) == 2 and len(priced) == 1


def test_only_one_process_fetches(tmp_path):
    with upside._job_lock() as first:
        with upside._job_lock() as second:
            assert first is True and second is False
    with upside._job_lock() as again:
        assert again is True                                  # released after use


def test_a_dead_process_lock_is_taken_over(tmp_path):
    lock = tmp_path / "job.lock"
    lock.write_text("12345")
    old = time.time() - upside.LOCK_STALE_S - 10
    os.utime(lock, (old, old))
    with upside._job_lock() as mine:
        assert mine is True


def test_refresh_prices_keeps_targets(monkeypatch):
    monkeypatch.setattr(upside, "screen_universe", lambda size: [
        {"symbol": "BIG", "name": "Big", "exchange": "NYSE", "market_cap": 9e10, "price": 150.0}])
    snap = upside.refresh_prices({**snapshot(), "rows": [row("BIG", 100, 300), row("GONE", 10, 20)]},
                                 NOW + timedelta(minutes=16))
    assert [(r["symbol"], r["price"], r["target_mean"]) for r in snap["rows"]] == [("BIG", 150.0, 300), ("GONE", 10, 20)]
    assert snap["prices_at"] == "2026-11-24T12:16:00+00:00" and snap["targets_at"] == "2026-11-24T12:00:00+00:00"


# ---------- page and API ----------

def test_page_before_the_first_build(client):
    html = client.get("/upside/").content.decode()
    assert "Building the list" in html and 'http-equiv="refresh"' in html


def test_page_lists_the_top_stocks(client):
    upside.save({**snapshot(), "rows": SNAP["rows"]})
    html = client.get("/upside/?n=10&min_analysts=5").content.decode()
    assert "Top 4 of 4 stocks" in html
    assert html.index('href="/live/stock/BIG"') < html.index('href="/live/stock/MID"')
    assert 'href="/live/stock/ONE"' not in html and 'data-watch="BIG"' in html
    assert "+200.00%" in html and '<option value="10" selected>' in html
    assert 'href="/upside/"' in client.get("/stocks/").content.decode()     # linked from Research


def test_stale_targets_are_flagged(client):
    upside.save({**snapshot(), "rows": [row("OLD", 10, 30, recent_count=0, last_target_date="2026-05-21")]})
    html = client.get("/upside/").content.decode()
    assert "the latest was on 2026-05-21" in html


def test_api(client):
    upside.save({**snapshot(), "rows": SNAP["rows"]})
    data = client.get("/api/upside/?n=10&direction=down&cap=10b").json()
    assert data["params"]["direction"] == "down" and data["eligible"] == 3
    assert [r["symbol"] for r in data["rows"]] == ["DOWN", "MID", "BIG"]
    assert set(data["rows"][0]) >= {"symbol", "price", "target", "upside_pct", "analysts", "recent_count"}
