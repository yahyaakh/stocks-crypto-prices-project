"""SEC 8-K filings in the company news feed. No network: SEC responses are mocked."""
from datetime import datetime, timezone
from unittest import mock

import pytest

from market import news, sec

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
SUBMISSIONS = {"filings": {"recent": {
    "form":               ["10-Q", "8-K", "8-K/A", "8-K", "8-K"],
    "accessionNumber":    ["0000320193-26-000020", "0000320193-26-000018", "0001140361-26-035325",
                           "0000320193-26-000015", "0000320193-25-000099"],
    "primaryDocument":    ["aapl-20260627.htm", "aapl-20260730.htm", "ef20081427_8ka.htm", "a.htm", "old.htm"],
    "acceptanceDateTime": ["2026-07-31T20:00:00.000Z", "2026-11-20T21:30:28.000Z", "2026-11-02T00:30:35.000Z",
                           "2026-11-01T12:00:00.000Z", "2025-01-01T12:00:00.000Z"],
    "items":              ["", "2.02,9.01", "5.02", "5.02", "8.01"],
}}}


@pytest.fixture(autouse=True)
def _clear(settings):
    from django.core.cache import cache
    cache.clear()
    settings.SEC_USER_AGENT = "Test Runner test@example.org"


def test_items_are_named_and_901_is_left_out():
    assert sec.describe_items("2.02,9.01") == "Results of operations (earnings)"
    assert sec.describe_items("5.02, 7.01") == "Director or officer change; Regulation FD disclosure"
    assert sec.describe_items("9.01") == "Financial statements and exhibits"
    assert sec.describe_items("9.99") == "Item 9.99"


def test_recent_8ks_become_articles():
    since = datetime(2026, 10, 25, tzinfo=timezone.utc)
    arts = sec.filings_to_articles("AAPL", 320193, SUBMISSIONS, since)
    assert [a["form"] for a in arts] == ["8-K", "8-K/A", "8-K"]          # no 10-Q, nothing before `since`
    a = arts[0]
    assert a["headline"] == "AAPL files 8-K: Results of operations (earnings)"
    assert a["url"] == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/aapl-20260730.htm"
    assert a["published_at"] == "2026-11-20T21:30:28Z" and a["source"] == "SEC EDGAR" and a["provider"] == "sec"
    assert a["summary"] == "Form 8-K filed with the SEC, items 2.02, 9.01." and a["tickers"] == ["AAPL"]
    assert len({x["id"] for x in arts}) == 3                               # two "Director or officer change" filings


def test_two_filings_with_the_same_headline_are_not_merged():
    since = datetime(2026, 10, 25, tzinfo=timezone.utc)
    arts = sec.filings_to_articles("AAPL", 320193, SUBMISSIONS, since)
    merged = news.merge(arts)
    assert len(merged) == 3


def test_no_user_agent_means_no_request(settings, monkeypatch):
    settings.SEC_USER_AGENT = ""
    monkeypatch.setattr(sec.requests, "get", mock.Mock(side_effect=AssertionError("must not call SEC")))
    assert sec.company_filings("AAPL", 30) == []


def test_unknown_ticker_and_sec_outage_give_nothing(monkeypatch):
    monkeypatch.setattr(sec, "ticker_ciks", lambda: {"AAPL": 320193})
    assert sec.company_filings("SPY", 30) == []                            # ETFs have no 8-Ks
    monkeypatch.setattr(sec, "_get", mock.Mock(side_effect=sec.requests.ConnectionError("down")))
    assert sec.company_filings("AAPL", 30) == []


def test_user_agent_is_sent(monkeypatch):
    seen = {}

    def fake_get(url, timeout, headers):
        seen[url] = headers["User-Agent"]
        r = mock.Mock()
        r.json.return_value = SUBMISSIONS
        r.raise_for_status.return_value = None
        return r

    monkeypatch.setattr(sec, "ticker_ciks", lambda: {"BRK-B": 1067983})
    monkeypatch.setattr(sec.requests, "get", fake_get)
    sec.company_filings("BRK.B", 90, now=NOW)
    assert seen == {"https://data.sec.gov/submissions/CIK0001067983.json": "Test Runner test@example.org"}


def test_company_news_includes_filings_without_tone(monkeypatch):
    since_now = datetime.now(timezone.utc)
    yahoo = [news._article("Apple beats estimates", "", "https://example.com/a", "Reuters", "yahoo",
                           since_now, ["AAPL"], None)]
    filing = news._article("AAPL files 8-K: Results of operations (earnings)", "", "https://www.sec.gov/x",
                           "SEC EDGAR", "sec", since_now, ["AAPL"], None)
    filing["form"] = "8-K"
    monkeypatch.setattr(news, "_finnhub_company", lambda s, d: [])
    monkeypatch.setattr(news, "_yahoo", lambda s, c=10: list(yahoo))
    monkeypatch.setattr(news.sec, "company_filings", lambda s, d: [filing])
    out = news.company_news("AAPL")
    by_provider = {a["provider"]: a for a in out["articles"]}
    assert by_provider["sec"]["sentiment"] is None                         # a label, not a news sentence
    assert by_provider["yahoo"]["sentiment"] is not None
    assert out["tone"]["total"] == 1                                       # the filing is not in the tone
    assert "SEC EDGAR" in out["sources"]


def test_news_page_labels_filings(client, monkeypatch):
    filing = news._article("AAPL files 8-K: Director or officer change", "", "https://www.sec.gov/x",
                           "SEC EDGAR", "sec", datetime.now(timezone.utc), ["AAPL"], None)
    filing["form"] = "8-K"
    monkeypatch.setattr(news, "_finnhub_company", lambda s, d: [])
    monkeypatch.setattr(news, "_yahoo", lambda s, c=10: [])
    monkeypatch.setattr(news.sec, "company_filings", lambda s, d: [filing])
    html = client.get("/stocknews/?symbol=AAPL").content.decode()
    assert 'class="filing-chip"' in html and "SEC 8-K" in html
