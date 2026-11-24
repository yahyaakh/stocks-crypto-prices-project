"""SEC EDGAR: a company's recent Form 8-K filings, as items for the news feed.

An 8-K is the filing a US-listed company must make within four business days of a material event
(earnings release, executive change, acquisition, ...). Unlike news, it comes from the company
itself, so the feed shows it with an "SEC filing" label and no tone score.

Sources (free, no key, but SEC's fair-access policy requires a User-Agent with a name and a contact
email, from the SEC_USER_AGENT setting; without it this module returns nothing):
  https://www.sec.gov/files/company_tickers.json          ticker -> CIK, cached for a day
  https://data.sec.gov/submissions/CIK##########.json     the company's recent filings
SEC allows 10 requests a second; a stock page makes at most two, and pages are cached.

Idea and the item-number approach adapted from github.com/Jakeschincariol/day-trader-skill (MIT).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
HTTP_TIMEOUT_S = 10
CIK_TTL_S = 24 * 3600
FORMS = ("8-K", "8-K/A")

# Form 8-K item numbers -> short names (from the form's own item list). 9.01 "Financial Statements
# and Exhibits" accompanies most filings and says nothing on its own, so it is left out of headlines.
ITEMS = {
    "1.01": "Material agreement",
    "1.02": "Material agreement terminated",
    "1.03": "Bankruptcy or receivership",
    "1.04": "Mine safety",
    "1.05": "Material cybersecurity incident",
    "2.01": "Acquisition or disposition completed",
    "2.02": "Results of operations (earnings)",
    "2.03": "New financial obligation",
    "2.04": "Financial obligation accelerated",
    "2.05": "Exit or disposal costs",
    "2.06": "Material impairment",
    "3.01": "Delisting notice or listing transfer",
    "3.02": "Unregistered sale of equity",
    "3.03": "Change to shareholder rights",
    "4.01": "Change of auditor",
    "4.02": "Earlier financial statements no longer reliable",
    "5.01": "Change in control",
    "5.02": "Director or officer change",
    "5.03": "Bylaws or fiscal year changed",
    "5.04": "Benefit plan trading suspended",
    "5.05": "Code of ethics changed or waived",
    "5.06": "Shell company status changed",
    "5.07": "Shareholder vote results",
    "5.08": "Shareholder director nominations",
    "7.01": "Regulation FD disclosure",
    "8.01": "Other events",
}

_cik_lock = threading.Lock()
_cik_map: dict[str, int] = {}
_cik_loaded_at = 0.0


def _get(url: str):
    resp = requests.get(url, timeout=HTTP_TIMEOUT_S,
                        headers={"User-Agent": settings.SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"})
    resp.raise_for_status()
    return resp.json()


def ticker_ciks() -> dict[str, int]:
    """{TICKER: CIK}, refreshed once a day per worker process. A failed refresh keeps the old map."""
    global _cik_map, _cik_loaded_at
    with _cik_lock:
        if _cik_map and time.monotonic() - _cik_loaded_at < CIK_TTL_S:
            return _cik_map
        try:
            raw = _get(TICKERS_URL)
            fresh = {str(r["ticker"]).upper(): int(r["cik_str"]) for r in raw.values()}
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.warning("sec company_tickers failed err=%s", exc)
            return _cik_map
        _cik_map, _cik_loaded_at = fresh, time.monotonic()
        return _cik_map


def describe_items(items: str) -> str:
    """'2.02,9.01' -> 'Results of operations (earnings)'. Unknown numbers stay as 'Item N'."""
    names = [ITEMS.get(i.strip(), "Item " + i.strip()) for i in (items or "").split(",")
             if i.strip() and i.strip() != "9.01"]
    return "; ".join(names) or "Financial statements and exhibits"


def filings_to_articles(symbol: str, cik: int, submissions: dict, since: datetime) -> list[dict]:
    """The submissions JSON's recent 8-Ks since `since`, as news-article dicts (see news._article)."""
    from .news import _article  # local import: news imports this module

    recent = ((submissions or {}).get("filings") or {}).get("recent") or {}
    cols = ("form", "accessionNumber", "primaryDocument", "acceptanceDateTime", "items")
    if not all(isinstance(recent.get(c), list) for c in cols):
        return []
    out = []
    for form, acc, doc, accepted, items in zip(*(recent[c] for c in cols)):
        if form not in FORMS or not acc or not doc or not accepted:
            continue
        try:  # e.g. "2026-07-31T00:30:28.000Z", UTC
            published = datetime.fromisoformat(accepted.replace("Z", "+00:00"))
        except ValueError:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if published < since:
            continue
        what = describe_items(items)
        url = ARCHIVE_URL.format(cik=cik, acc=acc.replace("-", ""), doc=doc)
        numbers = ", ".join(i.strip() for i in (items or "").split(",") if i.strip())
        a = _article(f"{symbol} files {form}: {what}",
                     f"Form {form} filed with the SEC" + (f", items {numbers}." if numbers else "."),
                     url, "SEC EDGAR", "sec", published, [symbol], None)
        a["id"] = "sec-" + acc  # two filings can share a headline; the accession number is unique
        a["form"] = form
        out.append(a)
    return out


def company_filings(symbol: str, days: int, now: datetime | None = None) -> list[dict]:
    """Recent 8-K filings for one ticker; [] when SEC_USER_AGENT is unset, the ticker has no CIK
    (ETFs, indices, foreign listings) or SEC is unreachable."""
    if not settings.SEC_USER_AGENT:
        return []
    symbol = symbol.upper()
    cik = ticker_ciks().get(symbol.replace(".", "-"))
    if cik is None:
        return []
    try:
        submissions = _get(SUBMISSIONS_URL.format(cik=cik))
    except (requests.RequestException, ValueError) as exc:
        logger.warning("sec submissions failed symbol=%s cik=%s err=%s", symbol, cik, exc)
        return []
    since = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    return filings_to_articles(symbol, cik, submissions, since)
