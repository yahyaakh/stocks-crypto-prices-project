"""Single-stock data: overview, analyst ratings and price history from yfinance; the monthly
recommendation trend from Finnhub, with Yahoo as fallback."""

import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from django.conf import settings

logger = logging.getLogger(__name__)

# Chart period -> bar interval. Only combinations Yahoo accepts.
HISTORY_INTERVALS = {
    "1d": "5m",
    "5d": "1h",
    "1mo": "1d",
    "3mo": "1d",
    "6mo": "1d",
    "1y": "1d",
    "5y": "1wk",
}
INTRADAY_INTERVALS = {"5m", "1h"}


def _yf_recommendation_counts(ticker: yf.Ticker) -> dict:
    """Current-month analyst counts from yfinance (row with period == '0m')."""
    counts = {"strong_buy": 0, "buy": 0, "hold": 0, "sell": 0, "strong_sell": 0}
    try:
        rec = ticker.recommendations
        if rec is not None and not rec.empty:
            row = rec[rec["period"] == "0m"].iloc[0] if "period" in rec else rec.iloc[0]
            counts = {
                "strong_buy": int(row.get("strongBuy", 0)),
                "buy": int(row.get("buy", 0)),
                "hold": int(row.get("hold", 0)),
                "sell": int(row.get("sell", 0)),
                "strong_sell": int(row.get("strongSell", 0)),
            }
    except Exception as exc:  # yfinance raises many different types
        logger.warning("yfinance recommendations failed symbol=%s err=%s", ticker.ticker, exc)
    return counts


def get_stock_overview(symbol: str) -> dict:
    symbol = symbol.upper()
    t = yf.Ticker(symbol)
    info = t.info or {}
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if price is None:
        return {"error": f"Symbol '{symbol}' not found on any source"}

    targets = t.analyst_price_targets or {}
    return {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName"),
        "exchange": info.get("exchange"),
        "logo": info.get("logo_url", ""),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "price": price,
        "change": info.get("regularMarketChange"),
        "change_pct": info.get("regularMarketChangePercent"),
        "volume": info.get("regularMarketVolume"),
        "year_high": info.get("fiftyTwoWeekHigh"),
        "year_low": info.get("fiftyTwoWeekLow"),
        **_yf_recommendation_counts(t),
        "consensus": (info.get("recommendationKey") or "n/a").capitalize(),
        "target_high": targets.get("high"),
        "target_low": targets.get("low"),
        "target_mean": targets.get("mean"),
        "target_median": targets.get("median"),
        # Key statistics and profile (previously the separate /info/ page).
        "market_cap": info.get("marketCap"),
        "pe_ttm": info.get("trailingPE"),
        "pe_forward": info.get("forwardPE"),
        "eps_ttm": info.get("trailingEps"),
        "beta": info.get("beta"),
        "dividend_yield_pct": info.get("dividendYield"),  # yfinance >= 1.0: already in percent (0.44 = 0.44%)
        "avg_volume": info.get("averageDailyVolume3Month") or info.get("averageVolume"),
        "day_low": info.get("regularMarketDayLow"),
        "day_high": info.get("regularMarketDayHigh"),
        "summary": info.get("longBusinessSummary"),
        "website": info.get("website"),
        "source": "yfinance",
    }


# Yahoo's short action codes -> readable words for the frontend.
YF_ACTIONS = {"up": "upgrade", "down": "downgrade", "main": "maintain", "init": "initiate", "reit": "reiterate"}
# Yahoo's price-target actions. "Announces" is a firm's first target (no prior one).
YF_TARGET_ACTIONS = {"Raises": "raise", "Lowers": "lower", "Maintains": "maintain", "Announces": "new", "Adjusts": "adjust"}


def _target(value) -> float | None:
    """Yahoo writes 0 when a row has no price target (or no prior one): treat 0 and NaN as missing."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 and v == v else None


def get_analyst_ratings(symbol: str, lookback_days: int = 365, today: date | None = None) -> list[dict]:
    """Analyst grade changes from yfinance over the last `lookback_days` (rolling window, not a
    hard-coded year), newest first, with the firm's price-target change when Yahoo has one."""
    symbol = symbol.upper()
    # ISO dates (YYYY-MM-DD) compare correctly as strings.
    cutoff = ((today or date.today()) - timedelta(days=lookback_days)).isoformat()
    try:
        df = yf.Ticker(symbol).upgrades_downgrades
    except Exception as exc:  # yfinance raises a mix of its own and requests errors
        logger.warning("yfinance upgrades_downgrades failed symbol=%s err=%s", symbol, exc)
        return []
    if df is None or df.empty:
        return []
    out = []
    for ts, row in df.sort_index(ascending=False).iterrows():
        day = pd.Timestamp(ts).strftime("%Y-%m-%d")
        if day < cutoff:
            break  # sorted newest first: everything after this is older
        action = row.get("Action")
        target = _target(row.get("currentPriceTarget"))
        out.append({
            "firm": row.get("Firm") or None,
            "date": day,
            "previous_grade": row.get("FromGrade") or None,
            "new_grade": row.get("ToGrade") or None,
            "action": YF_ACTIONS.get(action, action or None),
            "price_target": target,
            "prior_price_target": _target(row.get("priorPriceTarget")) if target else None,
            "price_target_action": YF_TARGET_ACTIONS.get(row.get("priceTargetAction")) if target else None,
        })
    return out


def get_stock_history(symbol: str, period: str = "1y") -> list[dict]:
    if period not in HISTORY_INTERVALS:
        raise ValueError(f"unsupported period {period!r}; use one of {sorted(HISTORY_INTERVALS)}")
    interval = HISTORY_INTERVALS[period]
    hist = yf.Ticker(symbol).history(period=period, interval=interval)

    fmt = "%H:%M" if interval in INTRADAY_INTERVALS else "%Y-%m-%d"
    return [
        {"date": pd.Timestamp(ts).strftime(fmt), "price": round(float(row["Close"]), 2)}
        for ts, row in hist.iterrows()
    ]


# ---------- analyst recommendation trend ----------

TREND_FIELDS = (("strongBuy", "strong_buy"), ("buy", "buy"), ("hold", "hold"), ("sell", "sell"), ("strongSell", "strong_sell"))


def get_recommendation_trend(symbol: str, today: date | None = None) -> dict:
    """Monthly analyst rating counts, oldest month first. Finnhub (free tier) first, Yahoo as fallback.
    The two disagree on analyst counts (different broker panels), so the source is returned too."""
    symbol = symbol.upper()
    rows = _finnhub_trend(symbol) or _yahoo_trend(symbol, today or date.today())
    source = rows[0].pop("_source") if rows else None
    for r in rows:
        r.pop("_source", None)
    return {"symbol": symbol, "source": source, "months": rows}


def _finnhub_trend(symbol: str) -> list[dict]:
    if not settings.FINNHUB_API_KEY:
        return []
    try:
        import finnhub
        raw = finnhub.Client(api_key=settings.FINNHUB_API_KEY).recommendation_trends(symbol) or []
    except Exception as exc:  # finnhub raises its own exception types plus requests errors
        logger.warning("finnhub recommendation_trends failed symbol=%s err=%s", symbol, exc)
        return []
    rows = [{"period": r["period"][:7], **{ours: int(r.get(theirs) or 0) for theirs, ours in TREND_FIELDS},
             "_source": "finnhub"} for r in raw if r.get("period")]
    return sorted(rows, key=lambda r: r["period"])


def _yahoo_trend(symbol: str, today: date) -> list[dict]:
    try:
        df = yf.Ticker(symbol).recommendations
    except Exception as exc:
        logger.warning("yfinance recommendations failed symbol=%s err=%s", symbol, exc)
        return []
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        try:
            back = -int(str(r["period"]).rstrip("m"))  # "0m", "-1m", ... months before the current one
        except ValueError:
            continue
        y, m = divmod(today.year * 12 + today.month - 1 - back, 12)
        rows.append({"period": f"{y:04d}-{m + 1:02d}", **{ours: int(r.get(theirs) or 0) for theirs, ours in TREND_FIELDS},
                     "_source": "yahoo"})
    return sorted(rows, key=lambda r: r["period"])
