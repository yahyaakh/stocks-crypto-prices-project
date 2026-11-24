"""Nasdaq Trader symbol directory: parsing, search order and failure handling. No network."""
import requests

from market import symbols
from market.tests.conftest import load_listings

NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N
ZXZZT|NASDAQ TEST STOCK|G|Y|N|100|N|N
File Creation Time: 1124202612:11|||||||
"""
OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire Hathaway Inc. New Common Stock|N|BRK.B|N|100|N|BRK.B
ABR$D|Arbor Realty Trust 6.375% Series D Preferred|N|ABRpD|N|100|N|ABR-D
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
XYZQ|Some Fund|Q|XYZQ|N|100|N|XYZQ
File Creation Time: 1124202612:11||||||
"""


def test_parse_keeps_stocks_and_etfs_in_yahoo_form():
    rows = {r["symbol"]: r for r in symbols.parse(NASDAQ, OTHER)}
    assert sorted(rows) == ["AAPL", "BRK-B", "QQQ", "SPY", "XYZQ"]   # no test issue, no preferred
    assert rows["AAPL"] == {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "Nasdaq", "etf": False,
                            "main_board": True}
    assert rows["QQQ"]["main_board"] is False and rows["BRK-B"]["main_board"] is True
    assert rows["BRK-B"]["name"] == "Berkshire Hathaway Inc. New" and rows["BRK-B"]["exchange"] == "NYSE"
    assert rows["SPY"]["exchange"] == "NYSE Arca" and rows["SPY"]["etf"] is True
    assert rows["XYZQ"]["exchange"] == "Other"     # an exchange code we have no name for


def test_search_order_exact_then_prefix_then_name():
    assert [r["symbol"] for r in symbols.search("aapl")] == ["AAPL"]
    # a symbol starting with the query beats names starting with it; names: shortest first
    assert [r["symbol"] for r in symbols.search("ap")][:3] == ["APLE", "AAPL", "AMAT"]
    assert symbols.search("SPY")[0]["symbol"] == "SPY"
    assert [r["symbol"] for r in symbols.search("apple")] == ["AAPL", "APLE"]
    assert [r["symbol"] for r in symbols.search("appl")] == ["AAPL", "AMAT", "APLE"]
    assert symbols.search("brk.b")[0]["symbol"] == "BRK-B"
    assert [r["symbol"] for r in symbols.search("brk")] == ["BRK-B", "BRKC"]      # base symbol BRK is shortest
    assert [r["symbol"] for r in symbols.search("micro")] == ["MSFT", "MLGO"]     # main board first
    assert symbols.search("") == [] and symbols.search("zzzz") == []
    assert symbols.get("brk.b")["symbol"] == "BRK-B" and symbols.get("NOPE") is None


def test_failed_download_keeps_the_old_list_and_waits_before_retrying(monkeypatch):
    load_listings(monkeypatch, [{"symbol": "AAPL", "name": "Apple Inc.", "exchange": "Nasdaq", "etf": False}])
    monkeypatch.setattr(symbols, "_loaded_at", -1e9)          # a day old: due for a refresh
    calls = []

    def down(url, timeout):
        calls.append(url)
        raise requests.ConnectionError("down")

    monkeypatch.setattr(symbols.requests, "get", down)
    assert symbols.get("AAPL") is not None                    # old list kept
    assert symbols.get("AAPL") is not None
    assert len(calls) == 1                                    # second call inside RETRY_S: no request


def test_truncated_file_is_rejected(monkeypatch):
    load_listings(monkeypatch, [])
    monkeypatch.setattr(symbols, "_loaded_at", 0.0)

    class Resp:
        text = NASDAQ

        def raise_for_status(self):
            pass

    monkeypatch.setattr(symbols.requests, "get", lambda url, timeout: Resp())
    assert symbols.available() is False                       # 5 rows parsed, fewer than 1,000
