
from django.shortcuts import render

from .providers.api_providers import get_crypto_table
from .stocks.stock_prices import get_magnificent7_prices, get_biggest_etf_stock_prices, get_stock_information, \
    get_target_price, get_stock_news

from .providers.Nexchange import get_crypto_table
from .stocks.stocks_home_page import get_world_indices_tables , get_general_stock_news_yf

from .stocks.IPO import show_ipo

from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_http_methods

import logging


from django.http import JsonResponse
import yfinance as yf


import math


# def biggest_movers_list(request):
#     crypto_movers = biggest_crypto_movers(limit=10)
#     return render(request, "biggest_movers.html", {"movers": movers})


# @cache_page Decorator stores the entire Render page in the cache for a specific period of time
# it improves performance :
# for pages that d'ont change often
# high traffic pages with static content
# API end points with stable DATA

""" @cache_page(60 * 5) means the page will be cached for 5 minutes before it needs to be regenerated."""
# 60 = 1 minutes
@cache_page(60 * 5)

@cache_page(60 * 5)
def home(request):
    # Return empty shell instantly — data loads via JS
    return render(request, "homepage.html", {
        "americas": [],
        "emea": [],
        "apac": [],
    })


def sanitize_floats(obj):
    """Replace NaN/Infinity with None so JsonResponse doesn't break."""
    if isinstance(obj, list):
        return [sanitize_floats(i) for i in obj]
    if isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj

@cache_page(60 * 5)
@require_http_methods(["GET"])
def api_world_indices(request):
    try:
        data = get_world_indices_tables()
        return JsonResponse(sanitize_floats(data), safe=False)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)




@cache_page(60 * 5)

@require_http_methods(["GET"]) # Security best practice. It ensures no one can try to POST or DELETE data at this URL.
def api_crypto(request):
    """Return crypto data as JSON"""
    try:
        crypto_rows = get_crypto_table()
        print(f" Crypto API: Returning {len(crypto_rows) if crypto_rows else 0} rows")
        return JsonResponse(crypto_rows if crypto_rows else [], safe=False)
    except Exception as e:
        print(f" Error in api_crypto: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


@cache_page(60 * 5)

@require_http_methods(["GET"])
def api_news(request):
    """Return news data as JSON"""
    try:
        news = get_general_stock_news_yf()
        print(f"News API: Returning {len(news) if news else 0} items")
        return JsonResponse(news if news else [], safe=False)
    except Exception as e:
        print(f" Error in api_news: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)

logger = logging.getLogger(__name__)

@cache_page(60 * 5)
def magnificent7_view(request):
    """Display Magnificent 7 stocks"""
    mag7 = get_magnificent7_prices()


    return render(request, 'magnificent7.html', {"mag7": mag7})


@cache_page(60 * 5)

def etf (request):
    etfs  = get_biggest_etf_stock_prices()
    return render(request, "etfs.html", {"etfs": etfs})

@cache_page(60 * 5)

def stocks_page(request):
    return render(request, "stocks.html")

@cache_page(60 * 5)

def stock_detail(request):
    symbol = (request.GET.get("symbol") or "MSFT").upper()
    info = get_stock_information(symbol)
    return render(request, "stock_detail.html", {"symbol": symbol, "info": info})

@cache_page(60 * 5)

def price_target(request):
    symbol = (request.GET.get("symbol") or "MSFT").upper()
    targets = get_target_price(symbol)
    return render(request, "price_target.html", {"symbol": symbol, "targets": targets})

@cache_page(60 * 5)

def stock_news(request):
    symbol = (request.GET.get("symbol") or "MSFT").upper()
    news = get_stock_news(symbol)
    return render(request, "stock_news.html", {"symbol": symbol, "news": news})


@cache_page(60 * 5)

def stocks_ipo(request):
    ipo = show_ipo()
    return render(request, "ipo.html", {"ipo": ipo})




def api_get_stock_price(request):
    symbol = request.GET.get('symbol', '').upper()

    if not symbol:
        return JsonResponse({'error': 'No symbol provided'}, status=400)


        # Fetch data using yfinance
    ticker = yf.Ticker(symbol)

    # We use 'fast_info' for speed, or 'history' for reliability
    # This is faster than downloading the whole history
    price = ticker.fast_info['last_price']
    prev_close = ticker.fast_info['previous_close']

    if price is None:
        return JsonResponse({'error': 'Symbol not found'}, status=404)

        # Calculate change
    change = price - prev_close
    change_pct = (change / prev_close) * 100

    data = {
        'symbol': symbol,
        'price': round(price, 2),
        'change': round(change, 2),
        'change_pct': round(change_pct, 2),
    }
    return JsonResponse(data)


# VIEW: React Integration Point (Hybrid Architecture)
# This view does not return raw data. Instead, it serves the 'container' HTML page
# that loads our compiled React application (Single Page Application).
#
# ARCHITECTURE NOTE:
# By serving the React app through Django, we maintain a "Monolithic" deployment structure.
# This simplifies our Azure Container App because we only need to manage ONE container
# that serves both the API and the Frontend, rather than orchestrating two separate microservices.

def live_watch_view(request):
    return render(request, 'live_watch.html')















