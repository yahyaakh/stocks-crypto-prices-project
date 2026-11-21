import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


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
    """One row per index. Each index is measured against its OWN last two closes, so a market
    that was closed today (holiday, different time zone) shows its last real session instead of
    a 0.00 change against itself. `as_of` is the date of that last close."""
    rows = []
    if close_df.empty:
        return rows

    for item in group:
        sym, name = item["symbol"], item["name"]
        if sym not in close_df.columns:
            continue

        series = close_df[sym].dropna()
        if series.empty:
            continue

        last_ts = series.index[-1]
        last = float(series.iloc[-1])
        prev = float(series.iloc[-2]) if len(series) >= 2 else None
        m1 = _nearest_past_value(series, last_ts - pd.Timedelta(days=30))
        y1 = _nearest_past_value(series, last_ts - pd.Timedelta(days=365))

        change = (last - prev) if prev is not None else None
        pct_change = _pct(last, prev)
        pct_m1 = _pct(last, m1)
        pct_y1 = _pct(last, y1)

        rows.append({
            "symbol": sym,
            "name": name,
            "value": round(last, 2),
            "change": round(change, 2) if change is not None else None,
            "pct_change": round(pct_change, 2) if pct_change is not None else None,
            "m1": round(pct_m1, 2) if pct_m1 is not None else None,
            "y1": round(pct_y1, 2) if pct_y1 is not None else None,
            "as_of": last_ts.date().isoformat(),
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

    # ffill only: carry the last known close forward over holidays. bfill would copy a
    # *later* price backwards in time (look-ahead), which silently corrupts 1M/1Y changes.
    close = df["Close"].ffill()

    return {
        "americas": _rows_for_group(close, WORLD_INDICES["americas"]),
        "emea":     _rows_for_group(close, WORLD_INDICES["emea"]),
        "apac":     _rows_for_group(close, WORLD_INDICES["apac"]),
    }
