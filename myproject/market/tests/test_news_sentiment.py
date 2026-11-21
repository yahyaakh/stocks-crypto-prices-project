"""News merging and headline sentiment. A tiny hand-made word list stands in for the real
Loughran-McDonald one, so these tests need no downloads and run in CI."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from market import news, sentiment
from market.sentiment import lexicon
from market.sentiment.lexicon import LexiconModel

WORDS = {"positive": ["gain", "strong", "improve"], "negative": ["loss", "decline", "weak"]}


@pytest.fixture
def lm(tmp_path, settings):
    path = tmp_path / "lm.json"
    path.write_text(json.dumps(WORDS))
    settings.SENTIMENT_LEXICON_PATH = str(path)
    settings.SENTIMENT_MODEL = "lexicon"
    sentiment.get_model.cache_clear()
    lexicon.default_model.cache_clear()
    yield LexiconModel.from_file(path)
    sentiment.get_model.cache_clear()
    lexicon.default_model.cache_clear()


# ---------- lexicon ----------

@pytest.mark.parametrize("text, label, score", [
    ("Strong quarter as margins improve", "bullish", 1.0),
    ("Weak demand drives decline", "bearish", -1.0),
    ("Strong sales but a wider loss", "neutral", 0.0),     # one each: tie -> neutral
    ("Company holds annual meeting", "neutral", None),     # no sentiment words -> no score
    ("", "neutral", None),
])
def test_lexicon_labels(lm, text, label, score):
    s = lm.score(text)
    assert (s.label, s.score) == (label, score)


def test_negation_flips_positive_words_within_three_words(lm):
    # Loughran & McDonald (2011): "not" etc. up to 3 words before a positive word makes it negative.
    assert lm.score("Results did not show any gain").label == "bearish"
    assert lm.score("Margins will never improve").label == "bearish"
    # 4 words away: outside the window, stays positive.
    assert lm.score("Not that anyone expected the gain").label == "bullish"


def test_negation_does_not_apply_to_negative_words(lm):
    assert lm.score("Not a loss").label == "bearish"  # LM only negate positive words


def test_known_weakness_is_documented(lm):
    # "narrows loss" is good news, but a word list sees only "loss". The test pins the known
    # behaviour so a change to it is deliberate.
    assert lm.score("Company narrows its loss").label == "bearish"


def test_missing_lexicon_means_no_sentiment(tmp_path, settings):
    settings.SENTIMENT_LEXICON_PATH = str(tmp_path / "missing.json")
    settings.SENTIMENT_MODEL = "lexicon"
    sentiment.get_model.cache_clear()
    lexicon.default_model.cache_clear()
    arts = [news._article("Strong gain", "", "https://a.com/1", "A", "yahoo", datetime.now(timezone.utc), [], None)]
    assert news.add_sentiment(arts)[0]["sentiment"] is None
    lexicon.default_model.cache_clear()
    sentiment.get_model.cache_clear()


def test_finbert_setting_falls_back_to_lexicon_without_torch(lm, settings, monkeypatch):
    import sys
    settings.SENTIMENT_MODEL = "finbert"
    sentiment.get_model.cache_clear()
    monkeypatch.setitem(sys.modules, "market.sentiment.finbert", None)  # import fails like a missing dependency
    assert sentiment.get_model().name == "lexicon-lm"


# ---------- normalisation & merging ----------

FINNHUB_ITEM = {"category": "company", "datetime": 1795268773, "headline": "Microsoft Posts Strong Gain",
                "id": 1, "image": "", "related": "MSFT", "source": "Yahoo", "summary": "short",
                "url": "https://finnhub.io/api/news?id=abc"}
YAHOO_ITEM = {"id": "x", "content": {
    "title": "Microsoft posts strong gain!", "summary": "a much longer summary from the publisher",
    "pubDate": "2026-11-21T15:59:18Z", "provider": {"displayName": "24/7 Wall St."},
    "canonicalUrl": {"url": "https://247wallst.com/a"}, "clickThroughUrl": {"url": "https://finance.yahoo.com/a"},
    "finance": {"stockTickers": [{"symbol": "MSFT"}, {"symbol": "ICE"}]}}}


def test_from_finnhub():
    a = news.from_finnhub(FINNHUB_ITEM)
    assert a["provider"] == "finnhub" and a["source"] == "Yahoo" and a["tickers"] == ["MSFT"]
    assert a["published_at"] == datetime.fromtimestamp(1795268773, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert a["image"] is None


def test_from_yahoo_prefers_publisher_url():
    a = news.from_yahoo(YAHOO_ITEM)
    assert a["url"] == "https://247wallst.com/a"
    assert a["source"] == "24/7 Wall St." and a["tickers"] == ["ICE", "MSFT"]
    assert a["published_at"] == "2026-11-21T15:59:18Z"


@pytest.mark.parametrize("bad", [{}, {"content": {"title": "x"}}, {"content": {"title": "x", "pubDate": "nope",
                                                                               "canonicalUrl": {"url": "u"}}}])
def test_from_yahoo_skips_incomplete_items(bad):
    assert news.from_yahoo(bad) is None


def test_merge_collapses_same_story_and_keeps_direct_link():
    fin, yah = news.from_finnhub(FINNHUB_ITEM), news.from_yahoo(YAHOO_ITEM)
    merged = news.merge([fin, yah])
    assert len(merged) == 1
    assert merged[0]["url"] == "https://247wallst.com/a"          # direct link beats the finnhub redirect
    assert merged[0]["tickers"] == ["ICE", "MSFT"]


def test_merge_sorts_newest_first():
    t = lambda h: datetime(2026, 11, 20, h, tzinfo=timezone.utc)  # noqa: E731
    arts = [news._article(f"story {h}", "", f"https://a.com/{h}", "A", "yahoo", t(h), [], None) for h in (9, 15, 12)]
    assert [a["headline"] for a in news.merge(arts)] == ["story 15", "story 12", "story 9"]


def test_tone_summary_window_and_net(lm):
    now = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
    mk = lambda h, d: news._article(h, "", f"https://a.com/{h}", "A", "yahoo",  # noqa: E731
                                     datetime(2026, 11, d, 12, tzinfo=timezone.utc), [], None)
    arts = news.add_sentiment([mk("Strong gain", 20), mk("Margins improve", 19), mk("Weak demand", 18),
                               mk("Annual meeting", 17), mk("Strong gain again", 1)])  # last is outside 7 days
    t = news.tone_summary(arts, now=now)
    assert (t["bullish"], t["neutral"], t["bearish"], t["total"]) == (2, 1, 1, 4)
    assert t["net"] == pytest.approx(1 / 3, abs=1e-3)


def test_company_news_merges_providers(lm, monkeypatch):
    now = datetime.now(timezone.utc)
    recent = int(now.timestamp()) - 3600
    monkeypatch.setattr(news, "_finnhub_company", lambda s, d: [news.from_finnhub({**FINNHUB_ITEM, "datetime": recent})])
    yitem = {"content": {**YAHOO_ITEM["content"], "pubDate": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "title": "Weak outlook for cloud unit"}}
    monkeypatch.setattr(news, "_yahoo", lambda s, count=10: [news.from_yahoo(yitem)])
    out = news.company_news("msft")
    assert out["symbol"] == "MSFT"
    assert [a["sentiment"]["label"] for a in out["articles"]] == ["bearish", "bullish"]  # newest first
    assert out["tone"]["bullish"] == 1 and out["tone"]["bearish"] == 1
    assert out["sources"] == ["24/7 Wall St.", "Yahoo"]


def _aged(n, days_ago):
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return news._article(f"story {n}", "", f"https://a.com/{n}", "A", "finnhub", ts, [], None)


def test_quiet_stock_widens_to_90_days_but_tone_stays_7(lm, monkeypatch):
    calls = []

    def finnhub(symbol, days):
        calls.append(days)
        # 5 stories in the last 30 days, 30 more between 30 and 90 days old
        return [_aged(i, 2 + i) for i in range(5)] + ([_aged(100 + i, 40 + i) for i in range(30)] if days >= 90 else [])

    monkeypatch.setattr(news, "_finnhub_company", finnhub)
    monkeypatch.setattr(news, "_yahoo", lambda s, count=10: [])
    out = news.company_news("DUOL")
    assert calls == [30, 90]
    assert out["window_days"] == 90 and len(out["articles"]) == 35
    assert out["tone"]["days"] == 7 and out["tone"]["total"] == 5   # stories 0-4 are 2-6 days old


def test_busy_stock_stays_at_30_days(lm, monkeypatch):
    calls = []
    monkeypatch.setattr(news, "_finnhub_company", lambda s, d: calls.append(d) or [_aged(i, 1) for i in range(25)])
    monkeypatch.setattr(news, "_yahoo", lambda s, count=10: [])
    out = news.company_news("MSFT")
    assert calls == [30] and out["window_days"] == 30 and len(out["articles"]) == 25


def test_finnhub_without_key_is_empty(settings):
    settings.FINNHUB_API_KEY = ""
    assert news._finnhub_company("MSFT", 7) == [] and news._finnhub_general() == []
