"""Stocks with the biggest gap between the analysts' price target and today's price.

Yahoo has no bulk endpoint for price targets (its screener and batch quote return the rating but
not the target, checked 2026-11-24), so the list is built in the background and saved:

  1. Universe: Yahoo's screener, US-listed equities by market cap, 250 rows per call. OTC listings,
     preferred shares and anything not in Nasdaq's symbol directory are dropped.
  2. Targets: one quoteSummary request per stock (financialData + upgradeDowngradeHistory), once a
     day. financialData has the consensus (mean, median, low, high, analyst count); the per-firm
     history only says how fresh it is: how many firms changed their target in the last 90 days.
     The history's target values are not used: after splits, spin-offs and for ADRs they are on a
     different basis from the consensus (2026-11-24: RDY history mean 1,450 vs consensus 14.88,
     SNDK 1,749 vs 247).
  3. Prices: refreshed from the screener every 15 minutes (exchange data is delayed ~15 minutes).

The result is a JSON file in UPSIDE_DATA_DIR that every worker process reads. A lock file makes sure
only one process does the fetching. The first build of each UTC day is also kept as
targets-YYYY-MM-DD.json, so the list's history can be studied later.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings

from . import symbols

logger = logging.getLogger(__name__)

UNIVERSE_SIZE = 2000
SCREEN_PAGE = 250                 # the most Yahoo's screener returns per call
WORKERS = 4                       # parallel target requests
TARGETS_TTL_S = 20 * 3600         # targets change at most daily
PRICES_TTL_S = 15 * 60
CHECK_EVERY_S = 5 * 60            # how often the background thread looks for due work
LOCK_STALE_S = 60 * 60            # a lock older than this belongs to a process that died
FRESH_DAYS = 90                   # a firm's target counts as recent if set within this many days
MAX_FAILED_SHARE = 0.2            # more failed requests than this: keep the previous list
QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/"
# Yahoo exchange codes: Nasdaq Global Select / Global / Capital, NYSE, NYSE American, NYSE Arca, Cboe BZX.
EXCHANGES = ("NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS")
# Common shares and share classes (BRK-B); preferreds like RF-PC are left out.
_COMMON = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")

# Choices offered on the page.
COUNTS = (10, 15, 20, 50, 100)
BASES = {"mean": "target_mean", "median": "target_median"}
CAPS = {"all": 0, "10b": 10e9, "50b": 50e9, "200b": 200e9}
ANALYST_MINIMUMS = (1, 3, 5, 10, 20)
DEFAULTS = {"n": 20, "basis": "mean", "direction": "up", "min_analysts": 5, "cap": "all"}


class BuildError(Exception):
    pass


# ---------- fetching ----------

def _screen_page(offset: int, size: int) -> dict:
    import yfinance as yf
    from yfinance import EquityQuery

    query = EquityQuery("and", [EquityQuery("eq", ["region", "us"]),
                                EquityQuery("is-in", ["exchange", *EXCHANGES])])
    return yf.screen(query, size=size, offset=offset, sortField="intradaymarketcap", sortAsc=False)


def _is_listed_common(symbol: str) -> bool:
    if not _COMMON.match(symbol):
        return False
    if not symbols.available():      # Nasdaq unreachable: the pattern and exchange filter still apply
        return True
    listing = symbols.get(symbol)
    return bool(listing) and not listing["etf"]


def screen_universe(size: int = UNIVERSE_SIZE) -> list[dict]:
    """The `size` largest US-listed common stocks: [{symbol, name, exchange, market_cap, price}]."""
    out, seen, offset = [], set(), 0
    max_pages = size // SCREEN_PAGE + 4      # room for the rows that get filtered out
    for _ in range(max_pages):
        page = _screen_page(offset, SCREEN_PAGE)
        quotes = page.get("quotes") or []
        for q in quotes:
            sym, price = q.get("symbol"), q.get("regularMarketPrice")
            if not sym or sym in seen or not price or not _is_listed_common(sym):
                continue
            seen.add(sym)
            out.append({"symbol": sym, "name": q.get("longName") or q.get("shortName") or sym,
                        "exchange": q.get("fullExchangeName") or q.get("exchange"),
                        "market_cap": q.get("marketCap"), "price": float(price)})
            if len(out) >= size:
                return out
        offset += SCREEN_PAGE
        if len(quotes) < SCREEN_PAGE or offset >= (page.get("total") or 0):
            break
    return out


def _quote_summary(symbol: str) -> dict:
    """The one request per stock. yfinance's public properties would take two (analyst_price_targets
    also drops the analyst count), so this calls the same endpoint through yfinance's session."""
    from yfinance.data import YfData

    return YfData().get_raw_json(QUOTE_SUMMARY_URL + symbol, params={
        "modules": "financialData,upgradeDowngradeHistory", "formatted": "false",
        "corsDomain": "finance.yahoo.com", "symbol": symbol})


def _positive(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 and v == v else None


def parse_summary(summary: dict, now: datetime) -> dict:
    """quoteSummary JSON -> the consensus targets plus how many firms changed theirs recently."""
    result = ((summary or {}).get("quoteSummary") or {}).get("result") or [{}]
    fd = result[0].get("financialData") or {}
    history = (result[0].get("upgradeDowngradeHistory") or {}).get("history") or []

    # Each firm's latest target (Yahoo writes 0 on rows that only change the rating).
    latest: dict[str, tuple[int, float]] = {}
    for row in history:
        firm, ts, target = row.get("firm"), row.get("epochGradeDate"), _positive(row.get("currentPriceTarget"))
        if not firm or not ts or target is None:
            continue
        if firm not in latest or ts > latest[firm][0]:
            latest[firm] = (int(ts), target)
    cutoff = (now - timedelta(days=FRESH_DAYS)).timestamp()
    recent = sum(ts >= cutoff for ts, _ in latest.values())
    newest = max((ts for ts, _ in latest.values()), default=None)

    key = fd.get("recommendationKey")
    return {
        "analysts": int(fd.get("numberOfAnalystOpinions") or 0),
        "target_mean": _positive(fd.get("targetMeanPrice")),
        "target_median": _positive(fd.get("targetMedianPrice")),
        "target_low": _positive(fd.get("targetLowPrice")),
        "target_high": _positive(fd.get("targetHighPrice")),
        "consensus": key.replace("_", " ").capitalize() if key and key != "none" else None,
        "recent_count": recent,
        "last_target_date": datetime.fromtimestamp(newest, timezone.utc).date().isoformat() if newest else None,
    }


def _fetch_targets(symbol: str, now: datetime) -> dict | None:
    """Targets for one stock, or None when the request failed (twice: one retry after a pause)."""
    for attempt in (1, 2):
        try:
            return parse_summary(_quote_summary(symbol), now)
        except Exception as exc:  # yfinance raises its own, requests' and JSON errors
            if attempt == 2:
                logger.warning("upside targets failed symbol=%s err=%s", symbol, exc)
                return None
            time.sleep(3)
    return None


def build(size: int = UNIVERSE_SIZE, workers: int = WORKERS, now: datetime | None = None) -> dict:
    """A full snapshot: universe, prices and targets. Raises BuildError if Yahoo mostly failed."""
    now = now or datetime.now(timezone.utc)
    t0 = time.perf_counter()
    universe = screen_universe(size)
    if not universe:
        raise BuildError("the screener returned no stocks")
    t_screen = time.perf_counter() - t0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        targets = list(pool.map(lambda r: _fetch_targets(r["symbol"], now), universe))
    failed = sum(t is None for t in targets)
    if failed > MAX_FAILED_SHARE * len(universe):
        raise BuildError(f"{failed} of {len(universe)} target requests failed")
    rows = [{**u, **t} for u, t in zip(universe, targets) if t is not None]
    stamp = now.isoformat(timespec="seconds")
    snap = {"version": 1, "targets_at": stamp, "prices_at": stamp, "universe": len(universe), "failed": failed,
            "screen_seconds": round(t_screen, 1), "build_seconds": round(time.perf_counter() - t0, 1),
            "workers": workers, "rows": rows}
    logger.info("upside build done stocks=%d failed=%d seconds=%.1f", len(rows), failed, snap["build_seconds"])
    return snap


def refresh_prices(snap: dict, now: datetime | None = None) -> dict:
    """New prices and market caps from the screener; targets unchanged."""
    now = now or datetime.now(timezone.utc)
    fresh = {r["symbol"]: r for r in screen_universe(len(snap["rows"]))}
    if not fresh:
        raise BuildError("the screener returned no stocks")
    rows = [{**r, "price": fresh[r["symbol"]]["price"], "market_cap": fresh[r["symbol"]]["market_cap"]}
            if r["symbol"] in fresh else r for r in snap["rows"]]
    return {**snap, "rows": rows, "prices_at": now.isoformat(timespec="seconds")}


# ---------- storage (shared by all worker processes) ----------

def data_dir() -> Path:
    path = Path(settings.UPSIDE_DATA_DIR or Path(tempfile.gettempdir()) / "marketwatch-upside")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)      # atomic: a reader sees the old file or the new one, never half of one


def save(snap: dict) -> None:
    folder = data_dir()
    _write_json(folder / "current.json", snap)
    day = folder / f"targets-{snap['targets_at'][:10]}.json"
    if not day.exists():
        _write_json(day, snap)


_cache_lock = threading.Lock()
_cache: tuple[float, dict | None] = (0.0, None)


def load() -> dict | None:
    """The saved snapshot, or None before the first build. Re-read only when the file changes."""
    global _cache
    path = data_dir() / "current.json"
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None
    with _cache_lock:
        if _cache[0] != mtime:
            try:
                _cache = (mtime, json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                logger.warning("upside snapshot unreadable err=%s", exc)
                return _cache[1]
        return _cache[1]


def _age_s(stamp: str | None, now: datetime) -> float:
    if not stamp:
        return float("inf")
    return (now - datetime.fromisoformat(stamp)).total_seconds()


@contextmanager
def _job_lock():
    """True for the one process allowed to fetch right now, False for everyone else."""
    path = data_dir() / "job.lock"
    for _ in (1, 2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > LOCK_STALE_S:
                    path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            yield False
            return
    else:
        yield False
        return
    try:
        os.write(fd, str(os.getpid()).encode())
        yield True
    finally:
        os.close(fd)
        path.unlink(missing_ok=True)


def run_due_work(now: datetime | None = None) -> str:
    """Rebuild the targets if they are a day old, else refresh prices if they are 15 minutes old."""
    now = now or datetime.now(timezone.utc)
    with _job_lock() as mine:
        if not mine:
            return "busy"
        snap = load()
        if not snap or _age_s(snap.get("targets_at"), now) > TARGETS_TTL_S:
            save(build(now=now))
            return "built"
        if _age_s(snap.get("prices_at"), now) > PRICES_TTL_S:
            save(refresh_prices(snap, now))
            return "prices"
        return "fresh"


_started = False
_start_lock = threading.Lock()


def start_background() -> None:
    """Start this process's refresh thread (once). Off in tests (UPSIDE_BACKGROUND=False)."""
    global _started
    if not settings.UPSIDE_BACKGROUND:
        return
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, daemon=True, name="upside-refresh").start()


def _loop() -> None:
    while True:
        try:
            run_due_work()
        except Exception:
            logger.exception("upside refresh failed")
        time.sleep(CHECK_EVERY_S)


# ---------- ranking ----------

def _choice(raw, allowed, default):
    return raw if raw in allowed else default


def parse_params(get) -> dict:
    """Query string -> validated choices; anything unexpected falls back to the default."""
    def as_int(name, allowed):
        try:
            return _choice(int(get.get(name, "")), allowed, DEFAULTS[name])
        except ValueError:
            return DEFAULTS[name]

    return {"n": as_int("n", COUNTS),
            "basis": _choice(get.get("basis"), BASES, DEFAULTS["basis"]),
            "direction": _choice(get.get("direction"), ("up", "down"), DEFAULTS["direction"]),
            "min_analysts": as_int("min_analysts", ANALYST_MINIMUMS),
            "cap": _choice(get.get("cap"), CAPS, DEFAULTS["cap"])}


def _range_bar(low, high, price, target) -> dict | None:
    """Positions (0-100) of the price and the target on a low-high bar that also fits the price."""
    if low is None or high is None or high < low:
        return None
    lo, hi = min(low, price), max(high, price)
    span = hi - lo or 1.0
    pos = lambda v: round((v - lo) / span * 100, 1)
    return {"low": pos(low), "high": pos(high), "price": pos(price), "target": pos(target)}


def rank(snap: dict, n: int, basis: str, direction: str, min_analysts: int, cap: str) -> tuple[list[dict], int]:
    """The top `n` rows by upside (or downside) and how many stocks passed the filters."""
    key, min_cap = BASES[basis], CAPS[cap]
    eligible = []
    for r in snap.get("rows", []):
        target, price = r.get(key), r.get("price")
        if not target or not price or price <= 0 or r.get("analysts", 0) < min_analysts:
            continue
        if min_cap and (r.get("market_cap") or 0) < min_cap:
            continue
        eligible.append({**r, "target": target, "upside_pct": (target / price - 1) * 100,
                         "bar": _range_bar(r.get("target_low"), r.get("target_high"), price, target)})
    eligible.sort(key=lambda r: r["upside_pct"], reverse=direction == "up")
    return eligible[:n], len(eligible)
