import logging
import math
import re

import yfinance as yf
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import cache_control, cache_page, never_cache
from django.views.decorators.http import require_GET

from .providers.Nexchange import get_crypto_table
from .stocks.IPO import show_ipo
from .stocks.stock_prices import (
    get_biggest_etf_stock_prices,
    get_magnificent7_prices,
)
from .news import company_news, market_news
from .stocks.stocks_home_page import get_world_indices_tables
from .stocks.stocksOverview import (
    get_analyst_ratings,
    get_recommendation_trend,
    get_stock_history,
    get_stock_overview,
)

logger = logging.getLogger(__name__)

# Whole-response caching (django cache_page). Market pages tolerate a few minutes of staleness;
# analyst data changes at most daily.
PAGE_TTL_S = 5 * 60
ANALYST_TTL_S = 60 * 60
# Browsers may reuse a response for at most this long. Without it cache_page would send
# max-age=TTL, and a browser could keep an empty/failed response for a full hour.
BROWSER_TTL_S = 60


def cached(ttl_s: int):
    """Server-side cache for `ttl_s`, browser cache for at most BROWSER_TTL_S.
    (cache_page keeps the smaller of the two max-age values.)"""
    def decorator(view):
        return cache_page(ttl_s)(cache_control(max_age=BROWSER_TTL_S)(view))
    return decorator


def sanitize_floats(obj):
    """Replace NaN/Infinity with None: they are not valid JSON."""
    if isinstance(obj, list):
        return [sanitize_floats(i) for i in obj]
    if isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _json_error(view: str, exc: Exception, status: int = 500) -> JsonResponse:
    logger.exception("view failed view=%s", view)
    return JsonResponse({"error": str(exc)}, status=status)


@never_cache
@require_GET
def healthz(request):
    """Liveness probe: the process is up and serving. Does not call upstream APIs."""
    return JsonResponse({"status": "ok"})


# ---------- HTML pages ----------

@cached(PAGE_TTL_S)
def home(request):
    # Empty shell; tables are filled by JS from the /api/ endpoints.
    return render(request, "homepage.html", {"americas": [], "emea": [], "apac": []})


@cached(PAGE_TTL_S)
def magnificent7_view(request):
    return render(request, "magnificent7.html", {"mag7": get_magnificent7_prices()})


@cached(PAGE_TTL_S)
def etf(request):
    return render(request, "etfs.html", {"etfs": get_biggest_etf_stock_prices()})


POPULAR_SYMBOLS = [("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "NVIDIA"), ("GOOGL", "Alphabet"),
                   ("AMZN", "Amazon"), ("TSLA", "Tesla")]


@cached(PAGE_TTL_S)
def stocks_page(request):
    return render(request, "stocks.html", {"popular": POPULAR_SYMBOLS})


def _symbol(request, default: str = "MSFT") -> str:
    return (request.GET.get("symbol") or default).strip().upper()


# Tickers look like AAPL, BRK-B, BRK.B, ^GSPC, EURUSD=X. Anything else is not a symbol.
_SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^]{0,14}$")


def stock_lookup(request, symbol: str = ""):
    """One stock page: the React overview. The header search (?symbol=), /stock/AAPL and the
    retired /info/ and /target/ pages all land here and redirect to /live/stock/<SYMBOL>.
    Not permanent (302): the retired URLs may be reused later without stale browser redirects."""
    s = (symbol or request.GET.get("symbol") or "").strip().upper()
    if not _SYMBOL_RE.match(s):
        return redirect("stocks")
    return redirect(f"/live/stock/{s}")


@cached(PAGE_TTL_S)
def stock_news(request):
    symbol = _symbol(request)
    return render(request, "stock_news.html", {"symbol": symbol, **company_news(symbol)})


@cached(PAGE_TTL_S)
def stocks_ipo(request):
    return render(request, "ipo.html", {"ipo": show_ipo()})


def live_watch_view(request, rest=""):
    """Serves the page that mounts the compiled React watchlist (static/react-watchlist.js)."""
    return render(request, "live_watch.html")


# ---------- JSON API ----------

@cached(PAGE_TTL_S)
@require_GET
def api_world_indices(request):
    try:
        return JsonResponse(sanitize_floats(get_world_indices_tables()), safe=False)
    except Exception as exc:
        return _json_error("api_world_indices", exc)


@cached(PAGE_TTL_S)
@require_GET
def api_crypto(request):
    try:
        rows = get_crypto_table()
        logger.info("api_crypto rows=%d", len(rows))
        return JsonResponse(sanitize_floats(rows), safe=False)
    except Exception as exc:
        return _json_error("api_crypto", exc)


@cached(PAGE_TTL_S)
@require_GET
def api_news(request):
    try:
        return JsonResponse(market_news())
    except Exception as exc:
        return _json_error("api_news", exc)


@cached(PAGE_TTL_S)
@require_GET
def api_company_news(request, symbol):
    try:
        return JsonResponse(company_news(symbol))
    except Exception as exc:
        return _json_error("api_company_news", exc)


@cached(ANALYST_TTL_S)
@require_GET
def api_recommendation_trend(request, symbol):
    try:
        return JsonResponse(get_recommendation_trend(symbol))
    except Exception as exc:
        return _json_error("api_recommendation_trend", exc)


@require_GET
def api_get_stock_price(request):
    symbol = _symbol(request, default="")
    if not symbol:
        return JsonResponse({"error": "No symbol provided"}, status=400)

    try:
        fast = yf.Ticker(symbol).fast_info
        price, prev_close = fast["last_price"], fast["previous_close"]
    except Exception:
        # yfinance raises (KeyError/HTTPError/...) for unknown tickers instead of returning None.
        logger.info("api_get_stock_price unknown symbol=%s", symbol)
        return JsonResponse({"error": f"Symbol '{symbol}' not found"}, status=404)

    if price is None or not math.isfinite(price):
        return JsonResponse({"error": f"Symbol '{symbol}' not found"}, status=404)

    change = change_pct = None
    if prev_close:  # None or 0 -> no change figures, never a ZeroDivisionError
        change = round(price - prev_close, 2)
        change_pct = round((price - prev_close) / prev_close * 100, 2)

    return JsonResponse({"symbol": symbol, "price": round(price, 2), "change": change, "change_pct": change_pct})


@cached(ANALYST_TTL_S)
@require_GET
def stock_overview_api(request, symbol):
    try:
        data = get_stock_overview(symbol)
    except Exception as exc:
        return _json_error("stock_overview_api", exc)
    # An unknown symbol is a 404, not a 200 that the client has to inspect.
    return JsonResponse(sanitize_floats(data), status=404 if "error" in data else 200)


@cached(ANALYST_TTL_S)
@require_GET
def analyst_ratings_api(request, symbol):
    try:
        return JsonResponse(sanitize_floats(get_analyst_ratings(symbol)), safe=False)
    except Exception as exc:
        return _json_error("analyst_ratings_api", exc)


@cached(PAGE_TTL_S)
@require_GET
def stock_price_history_api(request, symbol):
    try:
        data = get_stock_history(symbol, request.GET.get("period", "1y"))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        return _json_error("stock_price_history_api", exc)
    return JsonResponse(sanitize_floats(data), safe=False)
