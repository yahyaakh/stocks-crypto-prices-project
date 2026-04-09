from datetime import datetime

import pandas as pd
import json
import requests
import yfinance as yf
import datetime as dt
from datetime import datetime, timezone

from concurrent.futures import ThreadPoolExecutor, as_completed


def get_biggest_etf_stock_prices():
    start = dt.date.today() - dt.timedelta(days=7)  # buffer over weekends/holidays
    end = None

    tickers = ['SPY', 'VTI', 'QQQ', 'IWM', 'VT', 'VXUS', 'BND', 'TLT', 'LQD', 'HYG', 'GLD', 'VNQ']

    close_prices = pd.DataFrame()

    for ticker in tickers:
        data = yf.download(ticker, start, end)
        close_prices[ticker] = data['Close']

    if close_prices.empty:
        return []  # nothing fetched

    out = close_prices.tail(1).T.reset_index()

    out.columns = ["symbol", "price"]
    return out.to_dict(orient="records")



# Yahoo tickers for major indices
WORLD_INDICES = {
    "americas": [
        {"symbol": "^DJI",    "name": "DOW JONES INDUS. AVG"},
        {"symbol": "^GSPC",   "name": "S&P 500 INDEX"},
        {"symbol": "^IXIC",   "name": "NASDAQ COMPOSITE"},
        {"symbol": "^NYA",    "name": "NYSE COMPOSITE INDEX"},
        {"symbol": "^GSPTSE", "name": "S&P/TSX COMPOSITE INDEX"},
    ],
    "emea": [
        {"symbol": "^STOXX50E", "name": "Euro Stoxx 50 Pr"},  # sometimes ^STOXX50E; change if needed
        {"symbol": "^FTSE",     "name": "FTSE 100 INDEX"},
        {"symbol": "^GDAXI",    "name": "DAX INDEX"},
        {"symbol": "^FCHI",     "name": "CAC 40 INDEX"},
        {"symbol": "^IBEX",     "name": "IBEX 35 INDEX"},
    ],
    "apac": [
        {"symbol": "^N225",   "name": "NIKKEI 225"},
        {"symbol": "^HSI",    "name": "HANG SENG INDEX"},
        {"symbol": "000300.SS","name": "CSI 300 INDEX"},
        {"symbol": "^AXJO",   "name": "S&P/ASX 200 INDEX"},
    ],
}


def _pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b * 100.0

def _nearest_past_value(series: pd.Series, target_ts: pd.Timestamp):
    """value at or before target timestamp (series index is DatetimeIndex)"""
    if series.empty:
        return None
    # slice up to target & take last available
    s = series.loc[:target_ts]
    if s.empty:
        return None
    v = s.iloc[-1]
    try:
        return float(v)
    except Exception:
        return None

def _rows_for_group(close_df: pd.DataFrame, group):
    # close_df: columns are tickers; index are timestamps (daily)
    rows = []
    if close_df.empty:
        return rows
    last_ts = close_df.index[-1]
    prev_ts = close_df.index[-2] if len(close_df.index) >= 2 else last_ts

    one_month_ts = last_ts - pd.Timedelta(days=30)
    one_year_ts  = last_ts - pd.Timedelta(days=365)

    for item in group:
        sym, name = item["symbol"], item["name"]
        if sym not in close_df.columns:
            continue

        series = close_df[sym].dropna()
        if series.empty:
            continue

        last = _nearest_past_value(series, last_ts)
        prev = _nearest_past_value(series, prev_ts)
        m1   = _nearest_past_value(series, one_month_ts)
        y1   = _nearest_past_value(series, one_year_ts)

        change      = (last - prev) if (last is not None and prev is not None) else None
        pct_change  = _pct(last, prev)
        pct_m1      = _pct(last, m1)
        pct_y1      = _pct(last, y1)

        rows.append({
            "symbol": sym,
            "name": name,
            "value": round(last, 2) if last is not None else None,
            "change": round(change, 2) if change is not None else None,
            "pct_change": round(pct_change, 2) if pct_change is not None else None,
            "m1": round(pct_m1, 2) if pct_m1 is not None else None,
            "y1": round(pct_y1, 2) if pct_y1 is not None else None,
            # Daily data → treat as midnight EDT for display, like your sample
            "time_edt": "12:00 AM",
        })
    return rows


def get_world_indices_tables():

    # flatten all symbols to one list and download in one call
    all_syms = [it["symbol"] for grp in WORLD_INDICES.values() for it in grp]
    # 400d for a year+ buffer (holidays, etc.)
    df = yf.download(all_syms, period="400d", interval="1d", auto_adjust=False, progress=False, threads=True)

    # Normalize to MultiIndex shape if single ticker is ever passed
    if not isinstance(df.columns, pd.MultiIndex):
        df = pd.concat({all_syms[0]: df}, axis=1)

    if "Close" not in df.columns.levels[0]:
        return {"americas": [], "emea": [], "apac": []}

    close = df["Close"].ffill().bfill()

    return {
        "americas": _rows_for_group(close, WORLD_INDICES["americas"]),
        "emea":     _rows_for_group(close, WORLD_INDICES["emea"]),
        "apac":     _rows_for_group(close, WORLD_INDICES["apac"]),
    }



def get_general_stock_news_yf(limit_total=50):
    symbols = [
        "^GSPC", "^DJI", "^IXIC", "SPY", "QQQ",
        "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "NVDA",
        "JPM", "BAC", "XOM", "WMT", "UNH", "LLY",
    ]  # trim to 18 most newsworthy — less is faster

    def fetch_news(sym):
        try:
            return yf.Ticker(sym).news or []
        except Exception:
            return []

    items, seen = [], set()
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_news, s): s for s in symbols}
        for future in as_completed(futures):
            for it in future.result():
                content = it.get("content") or {}
                title = it.get("title") or content.get("title") or ""
                link = (it.get('link')
                        or (content.get('clickThroughUrl') or {}).get('url')
                        or (content.get('canonicalUrl') or {}).get('url')
                        or content.get('previewUrl'))
                summary = it.get("summary") or content.get("summary") or ""
                if link and link not in seen:
                    seen.add(link)
                    items.append({"title": title, "link": link, "summary": summary})

    return items[:limit_total]

