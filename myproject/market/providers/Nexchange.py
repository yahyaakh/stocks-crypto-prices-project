"""Top-100 crypto assets by market cap from CoinGecko's public API."""

import logging

import pandas as pd
import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

CRYPTO_COLUMNS = [
    "symbol", "name", "image", "current_price",
    "market_cap", "market_cap_rank", "price_change_percentage_24h",
]

COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
)
CACHE_KEY = "crypto_table"
CACHE_TTL_S = 5 * 60


def get_crypto_table() -> list[dict]:
    """Return the table, or [] if CoinGecko is unavailable. Failures are never cached,
    so the next request retries instead of serving an empty table for 5 minutes."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    try:
        r = requests.get(COINGECKO_URL, timeout=10)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("coingecko fetch failed err=%s", exc)
        return []

    df = pd.DataFrame(data)
    missing = [c for c in CRYPTO_COLUMNS if c not in df.columns]
    if missing:
        logger.warning("coingecko schema changed missing_columns=%s", missing)
        return []

    result = df[CRYPTO_COLUMNS].to_dict("records")
    cache.set(CACHE_KEY, result, CACHE_TTL_S)
    return result
