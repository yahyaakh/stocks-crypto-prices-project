import requests
import pandas as pd
from django.core.cache import cache

CRYPTO_COLUMNS = [
    "symbol", "name", "image", "current_price",
    "market_cap", "market_cap_rank", "price_change_percentage_24h"
]

COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
)

def get_crypto_table():
    # 1. Try cache first — avoids hitting CoinGecko on every request
    cached = cache.get('crypto_table')
    if cached is not None:
        return cached

    # 2. Fetch fresh data
    try:
        r = requests.get(COINGECKO_URL, timeout=10)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.Timeout:
        print("[Crypto] CoinGecko request timed out")
        return []
    except requests.exceptions.HTTPError as e:
        print(f"[Crypto] CoinGecko HTTP error: {e}")
        return []
    except Exception as e:
        print(f"[Crypto] Unexpected error: {e}")
        return []

    # 3. Shape the data
    try:
        df = pd.DataFrame(data)
        missing = [c for c in CRYPTO_COLUMNS if c not in df.columns]
        if missing:
            print(f"[Crypto] Missing columns: {missing}")
            return []

        result = df[CRYPTO_COLUMNS].to_dict('records')
    except Exception as e:
        print(f"[Crypto] Data processing error: {e}")
        return []

    # 4. Store in cache for 5 minutes
    cache.set('crypto_table', result, 60 * 5)

    return result