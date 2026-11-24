"""News from several providers merged into one feed, de-duplicated and scored for tone.

Providers:
- Finnhub (free key): company news, and general market news. Links go through finnhub.io redirects.
- Yahoo Finance via yfinance: no key; links point at Yahoo or the original publisher.
- SEC EDGAR (company feeds only, needs SEC_USER_AGENT): the company's own Form 8-K filings, shown
  as "SEC filing" items. They are not scored for tone and do not count in the tone summary.

Every article becomes the same dict:
    {id, headline, summary, url, source, provider, published_at (ISO-8601 UTC), tickers, image, sentiment}
"""
from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import finnhub
import yfinance as yf
from django.conf import settings

from . import sec
from .sentiment import get_model, model_card

logger = logging.getLogger(__name__)

# Symbols whose Yahoo news makes a decent "whole market" feed.
MARKET_NEWS_SYMBOLS = ["^GSPC", "^DJI", "^IXIC", "SPY", "QQQ", "AAPL", "MSFT", "AMZN", "GOOGL", "META",
                       "TSLA", "NVDA", "JPM", "BAC", "XOM", "WMT", "UNH", "LLY"]
TONE_WINDOW_DAYS = 7            # tone summary: the recent mood
NEWS_WINDOWS_DAYS = (30, 90)    # article list: 30 days, widened to 90 for quiet stocks
MIN_ARTICLES = 20
YAHOO_COMPANY_COUNT = 50        # yfinance returns 10 by default
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


# ---------- normalisation ----------

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _headline_key(headline: str) -> str:
    """Case/punctuation-insensitive key: the same story from two feeds collapses to one."""
    return _NON_ALNUM.sub(" ", headline.lower()).strip()


def _article(headline, summary, url, source, provider, published: datetime, tickers, image) -> dict:
    return {
        "id": hashlib.sha1(_headline_key(headline).encode()).hexdigest()[:16],
        "headline": headline.strip(),
        "summary": (summary or "").strip(),
        "url": url,
        "source": source or provider,
        "provider": provider,
        "published_at": _iso(published),
        "tickers": sorted({t.strip().upper() for t in tickers if t and t.strip()}),
        "image": image or None,
        "sentiment": None,
    }


def from_finnhub(item: dict) -> dict | None:
    headline, url, ts = item.get("headline"), item.get("url"), item.get("datetime")
    if not headline or not url or not ts:
        return None
    return _article(headline, item.get("summary"), url, item.get("source"), "finnhub",
                    datetime.fromtimestamp(ts, tz=timezone.utc),
                    (item.get("related") or "").split(","), item.get("image"))


def from_yahoo(item: dict) -> dict | None:
    c = item.get("content") or {}
    headline = c.get("title")
    # Prefer the publisher's own URL; fall back to Yahoo's page.
    url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
    pub = c.get("pubDate") or c.get("displayTime")
    if not headline or not url or not pub:
        return None
    try:
        published = datetime.fromisoformat(pub.replace("Z", "+00:00"))
    except ValueError:
        return None
    tickers = [t.get("symbol") for t in ((c.get("finance") or {}).get("stockTickers") or [])]
    image = ((c.get("thumbnail") or {}).get("originalUrl"))
    return _article(headline, c.get("summary") or c.get("description"), url,
                    (c.get("provider") or {}).get("displayName"), "yahoo", published, tickers, image)


def merge(articles: list[dict]) -> list[dict]:
    """Drop duplicates (same normalised headline), newest first. Of two copies keep the one with a
    direct publisher link (Finnhub's are redirects) and the longer summary; union their tickers."""
    best: dict[str, dict] = {}
    for a in articles:
        # Two filings can share a headline ("files 8-K: Director or officer change"); never merge them.
        key = a["url"] if a["provider"] == "sec" else _headline_key(a["headline"])
        cur = best.get(key)
        if cur is None:
            best[key] = a
            continue
        rank = lambda x: ("finnhub.io/" not in x["url"], len(x["summary"]))  # noqa: E731
        keep, other = (a, cur) if rank(a) > rank(cur) else (cur, a)
        keep["tickers"] = sorted(set(keep["tickers"]) | set(other["tickers"]))
        best[key] = keep
    return sorted(best.values(), key=lambda x: x["published_at"], reverse=True)


def add_sentiment(articles: list[dict]) -> list[dict]:
    """Score headlines only: the models were evaluated on single sentences, not article summaries.
    SEC filings are skipped: "files 8-K: Results of operations" is a label, not a news sentence."""
    model = get_model()
    news = [a for a in articles if a["provider"] != "sec"]
    if model is None or not news:
        return articles
    for a, s in zip(news, model.score_many([a["headline"] for a in news])):
        a["sentiment"] = s.as_dict()
    return articles


def tone_summary(articles: list[dict], now: datetime | None = None, days: int = TONE_WINDOW_DAYS) -> dict:
    """Counts of bullish/neutral/bearish headlines in the last `days`, and a net score in [-1, 1]
    = (bullish - bearish) / (bullish + bearish), None when there are no opinionated headlines."""
    cutoff = _iso((now or datetime.now(timezone.utc)) - timedelta(days=days))
    counts = {"bullish": 0, "neutral": 0, "bearish": 0}
    model = None
    for a in articles:
        s = a.get("sentiment")
        if s and a["published_at"] >= cutoff:
            counts[s["label"]] += 1
            model = s["model"]
    opinionated = counts["bullish"] + counts["bearish"]
    return {**counts, "days": days, "total": sum(counts.values()), "model": model, "model_card": model_card(model),
            "net": round((counts["bullish"] - counts["bearish"]) / opinionated, 3) if opinionated else None}


# ---------- providers ----------

def _finnhub_client():
    return finnhub.Client(api_key=settings.FINNHUB_API_KEY) if settings.FINNHUB_API_KEY else None


def _finnhub_company(symbol: str, days: int) -> list[dict]:
    client = _finnhub_client()
    if client is None:
        return []
    today = date.today()
    try:
        raw = client.company_news(symbol, _from=(today - timedelta(days=days)).isoformat(), to=today.isoformat())
    except Exception as exc:  # finnhub raises its own exception types plus requests errors
        logger.warning("finnhub company_news failed symbol=%s err=%s", symbol, exc)
        return []
    return [a for a in map(from_finnhub, raw or []) if a]


def _finnhub_general() -> list[dict]:
    client = _finnhub_client()
    if client is None:
        return []
    try:
        raw = client.general_news("general", min_id=0)
    except Exception as exc:
        logger.warning("finnhub general_news failed err=%s", exc)
        return []
    return [a for a in map(from_finnhub, raw or []) if a]


def _yahoo(symbol: str, count: int = 10) -> list[dict]:
    try:
        raw = yf.Ticker(symbol).get_news(count=count) or []
    except Exception as exc:  # one bad symbol must not break the feed
        logger.warning("yfinance news failed symbol=%s err=%s", symbol, exc)
        return []
    return [a for a in map(from_yahoo, raw) if a]


# ---------- public ----------

def _within(articles: list[dict], days: int) -> list[dict]:
    cutoff = _iso(datetime.now(timezone.utc) - timedelta(days=days))
    return [a for a in articles if a["published_at"] >= cutoff]


def company_news(symbol: str, limit: int = 60) -> dict:
    """Up to `limit` recent headlines about one company from all providers, plus its SEC filings
    in the same window, newest first. Filings don't count toward `limit`: for a busy stock the
    newest 60 headlines can all be from today and would push every filing off the list.

    The list covers NEWS_WINDOWS_DAYS[0] days, widened to the next window only when a quiet stock
    has fewer than MIN_ARTICLES. The tone summary always covers the last TONE_WINDOW_DAYS, so
    "recent mood" means the same thing for every stock however long the list is."""
    symbol = symbol.upper()
    with ThreadPoolExecutor(max_workers=3) as pool:
        fin = pool.submit(_finnhub_company, symbol, NEWS_WINDOWS_DAYS[0])
        yah = pool.submit(_yahoo, symbol, YAHOO_COMPANY_COUNT)
        # Fetched once for the widest window; _within() trims it with everything else.
        fil = pool.submit(sec.company_filings, symbol, NEWS_WINDOWS_DAYS[-1])
        finnhub_items, yahoo_items, filings = fin.result(), yah.result(), fil.result()

    days = NEWS_WINDOWS_DAYS[0]
    articles = _within(merge(finnhub_items + yahoo_items + filings), days)
    for wider in NEWS_WINDOWS_DAYS[1:]:
        if len(articles) >= MIN_ARTICLES:
            break
        days = wider
        articles = _within(merge(_finnhub_company(symbol, wider) + yahoo_items + filings), days)

    headlines = [a for a in articles if a["provider"] != "sec"][:limit]
    filings_kept = [a for a in articles if a["provider"] == "sec"]
    articles = add_sentiment(sorted(headlines + filings_kept, key=lambda a: a["published_at"], reverse=True))
    logger.info("company_news symbol=%s articles=%d window_days=%d", symbol, len(articles), days)
    return {"symbol": symbol, "articles": articles, "window_days": days,
            "tone": tone_summary(articles, days=TONE_WINDOW_DAYS),
            "sources": sorted({a["source"] for a in articles})}


def market_news(limit: int = 80) -> dict:
    """General market news: Finnhub's general feed plus Yahoo news for major indices and stocks."""
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_finnhub_general)] + [pool.submit(_yahoo, s) for s in MARKET_NEWS_SYMBOLS]
        articles = [a for f in futures for a in f.result()]
    articles = add_sentiment(merge(articles)[:limit])
    logger.info("market_news articles=%d", len(articles))
    return {"articles": articles, "tone": tone_summary(articles),
            "sources": sorted({a["source"] for a in articles})}
