"""Upcoming IPO calendar from Finnhub."""

import logging
from datetime import date, timedelta

import finnhub
from django.conf import settings

logger = logging.getLogger(__name__)

IPO_FIELDS = ("date", "exchange", "name", "numberOfShares", "price", "symbol", "totalSharesValue", "status")
LOOKBACK_DAYS = 30    # recent IPOs: the upcoming calendar is often empty on the free tier
LOOKAHEAD_DAYS = 365


def ipo(from_date: date, to_date: date) -> dict:
    if not settings.FINNHUB_API_KEY:
        logger.warning("FINNHUB_API_KEY not set; IPO calendar disabled")
        return {}
    client = finnhub.Client(api_key=settings.FINNHUB_API_KEY)
    try:
        return client.ipo_calendar(_from=from_date.isoformat(), to=to_date.isoformat()) or {}
    except Exception as exc:  # finnhub raises its own exception types plus requests errors
        logger.warning("finnhub ipo_calendar failed err=%s", exc)
        return {}


def show_ipo(today: date | None = None) -> list[dict]:
    """IPOs from 30 days ago to +365 days, upcoming first (soonest first), then recent (newest first).
    Dates are computed per call, not at import time, so a long-running server never serves a
    stale window."""
    today = today or date.today()
    results = ipo(today - timedelta(days=LOOKBACK_DAYS), today + timedelta(days=LOOKAHEAD_DAYS))
    # Normalise: every row has every field; missing/empty values become None.
    rows = [{f: row.get(f) or None for f in IPO_FIELDS} for row in results.get("ipoCalendar", [])]
    iso_today = today.isoformat()
    for r in rows:
        r["upcoming"] = (r["date"] or "") >= iso_today
    upcoming = sorted((r for r in rows if r["upcoming"]), key=lambda r: r["date"] or "")
    recent = sorted((r for r in rows if not r["upcoming"]), key=lambda r: r["date"] or "", reverse=True)
    return upcoming + recent
