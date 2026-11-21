import logging

import pandas as pd
import yfinance as yf
import datetime as dt
from math import isfinite
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  Single-symbol helpers  (used by detail pages)
# ─────────────────────────────────────────────

def get_stock_information(symbol: str | None):
    t = yf.Ticker(symbol)
    return t.info


def get_target_price(symbol: str | None):
    s = yf.Ticker(symbol)
    return s.analyst_price_targets


# ─────────────────────────────────────────────
#  ETF prices  (21 ETFs → 1 batch download)
# ─────────────────────────────────────────────

ETF_MAP = {
    'SPY':  'SPDR S&P 500 ETF Trust',
    'VTI':  'Vanguard Total Stock Market ETF',
    'VOO':  'Vanguard S&P 500 ETF',
    'IVV':  'iShares Core S&P 500 ETF',
    'VT':   'Vanguard Total World Stock ETF',
    'QQQ':  'Invesco QQQ Trust (Nasdaq-100)',
    'XLK':  'Technology Select Sector SPDR Fund',
    'VGT':  'Vanguard Information Technology ETF',
    'XLF':  'Financial Select Sector SPDR Fund',
    'XLE':  'Energy Select Sector SPDR Fund',
    'XLV':  'Health Care Select Sector SPDR Fund',
    'XLI':  'Industrial Select Sector SPDR Fund',
    'XLRE': 'Real Estate Select Sector SPDR Fund',
    'BND':  'Vanguard Total Bond Market ETF',
    'AGG':  'iShares Core U.S. Aggregate Bond ETF',
    'TLT':  'iShares 20+ Year Treasury Bond ETF',
    'EFA':  'iShares MSCI EAFE ETF',
    'EEM':  'iShares MSCI Emerging Markets ETF',
    'GLD':  'SPDR Gold Shares',
    'SLV':  'iShares Silver Trust',
    'VYM':  'Vanguard High Dividend Yield ETF',
}

def _etf_category(symbol: str) -> str:
    if symbol in {'SPY', 'VTI', 'VOO', 'IVV', 'VT'}:    return 'Broad Market'
    if symbol in {'QQQ', 'XLK', 'VGT'}:                  return 'Technology'
    if symbol in {'XLF', 'XLE', 'XLV', 'XLI', 'XLRE'}:  return 'Sector'
    if symbol in {'BND', 'AGG', 'TLT'}:                   return 'Bonds'
    if symbol in {'EFA', 'EEM'}:                           return 'International'
    if symbol in {'GLD', 'SLV'}:                           return 'Commodities'
    if symbol == 'VYM':                                    return 'Dividend'
    return 'Other'

def _safe_pct(new, old):
    try:
        if old is None or old == 0:
            return None
        v = (new - old) / old * 100.0
        return round(v, 2) if isfinite(v) else None
    except Exception:
        return None

def _asof(series: pd.Series, ts: pd.Timestamp) -> float | None:
    """Last available close on or before ts."""
    s = series.loc[:ts]
    if s.empty:
        return None
    v = s.iloc[-1]
    return float(v) if pd.notna(v) else None


def get_biggest_etf_stock_prices():
    """
    Fetch all 21 ETFs in ONE batch yf.download call.
    Previously: 21 individual downloads + time.sleep(0.12) each = ~15 s minimum.
    Now: 1 batch download with threads=True = ~2 s.
    """
    start   = dt.date.today() - dt.timedelta(days=365)
    symbols = list(ETF_MAP.keys())
    today   = pd.Timestamp(dt.date.today())

    data = yf.download(
        symbols,
        start=start,
        progress=False,
        auto_adjust=True,
        threads=True,       # parallel downloads inside yfinance
    )

    if data.empty:
        return []

    close  = data['Close']
    volume = data['Volume'] if 'Volume' in data else None

    results = []

    for symbol, name in ETF_MAP.items():
        try:
            if symbol not in close.columns:
                continue

            series = close[symbol].dropna()
            if len(series) < 2:
                continue

            latest_price = float(series.iloc[-1])
            prev_close   = float(series.iloc[-2])
            day_change   = latest_price - prev_close

            vol = None
            if volume is not None and symbol in volume.columns:
                v = volume[symbol].iloc[-1]
                vol = int(v) if pd.notna(v) else None

            results.append({
                'symbol':           symbol,
                'name':             name,
                'category':         _etf_category(symbol),
                'price':            round(latest_price, 2),
                'change':           round(day_change, 4),
                'change_pct':       _safe_pct(latest_price, prev_close),
                'week_change_pct':  _safe_pct(latest_price, _asof(series, today - pd.Timedelta(days=7))),
                'month_change_pct': _safe_pct(latest_price, _asof(series, today - pd.Timedelta(days=30))),
                'year_change_pct':  _safe_pct(latest_price, _asof(series, today - pd.Timedelta(days=365))),
                'volume':           vol,
                'avg_volume':       None,   # skipping .info call saves 21 extra round-trips
            })

        except Exception as e:
            logger.warning("etf row failed symbol=%s err=%s", symbol, e)
            continue

    results.sort(key=lambda x: (x['category'], x['symbol']))
    return results


# ─────────────────────────────────────────────
#  Magnificent 7  (7 tickers → 1 batch download
#                 + 7 parallel .info calls)
# ─────────────────────────────────────────────

MAG7 = ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'TSLA', 'NVDA']


def _fetch_info(ticker: str) -> dict:
    """Fetch .info for one ticker — runs in a thread."""
    try:
        return ticker, yf.Ticker(ticker).info
    except Exception:
        return ticker, {}


def get_magnificent7_prices():
    """
    Previously: 7 individual downloads + 7 sequential .info calls.
    Now: 1 batch price download  +  7 parallel .info calls via ThreadPoolExecutor.
    """
    start = dt.date.today() - dt.timedelta(days=365)

    # ── 1. Batch price download ──────────────────────────────────────────
    data = yf.download(
        MAG7,
        start=start,
        progress=False,
        auto_adjust=True,
        threads=True,
    )

    if data.empty:
        return []

    close  = data['Close']
    volume = data['Volume'] if 'Volume' in data else None

    # ── 2. Parallel .info calls ──────────────────────────────────────────
    info_map: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = {executor.submit(_fetch_info, t): t for t in MAG7}
        for future in as_completed(futures):
            ticker, info = future.result()
            info_map[ticker] = info

    # ── 3. Assemble results ───────────────────────────────────────────────
    results = []

    for ticker in MAG7:
        try:
            if ticker not in close.columns:
                continue

            series = close[ticker].dropna()
            if len(series) < 2:
                continue

            latest = float(series.iloc[-1])
            prev   = float(series.iloc[-2])
            change = latest - prev
            change_pct = (change / prev * 100) if prev != 0 else 0.0

            vol = None
            if volume is not None and ticker in volume.columns:
                v = volume[ticker].iloc[-1]
                vol = int(v) if pd.notna(v) else None

            info = info_map.get(ticker, {})

            market_cap = int(info.get('marketCap', 0) or 0)
            pe_raw     = info.get('trailingPE')
            try:
                pe_ratio = round(float(pe_raw), 2) if pe_raw is not None else 'N/A'
            except (ValueError, TypeError):
                pe_ratio = 'N/A'

            results.append({
                'symbol':     ticker,
                'name':       info.get('shortName', ticker),
                'price':      round(latest, 2),
                'change':     round(change, 2),
                'change_pct': round(change_pct, 2),
                'volume':     vol,
                'market_cap': market_cap,
                'pe_ratio':   pe_ratio,
            })

        except Exception as e:
            logger.warning("mag7 row failed symbol=%s err=%s", ticker, e)
            continue

    return results