
import json
import requests , re
import pandas as pd

BINANCE_24H_URL = "https://api4.binance.com/api/v3/ticker/24hr"

r = requests.get(BINANCE_24H_URL)

results = json.loads(r.text)

df = pd.DataFrame(results)



def get_coins_list():

    return sorted(df["symbol"].dropna().unique().tolist())

def get_coin_price(symbol: str):
    s = symbol.strip().upper()
    ser = df.loc[df["symbol"].str.upper() == s, "lastPrice"]
    if ser.empty:
        return None
    try:
        return float(ser.iloc[0])
    except (ValueError, TypeError):
        return None


def get_crypto_table(query: str | None , limit: int | None = 50 ):

    c = ["symbol", "lastPrice" , "priceChangePercent"]
    sub = df.loc[:, c].copy()

    if query:
        q = query.strip().lower()
        sub = sub[sub["symbol"].str.lower().str.contains(q)]

    if limit: sub = sub.head(limit)

    # cast numeric cols safely, without mutating df4
    sub["lastPrice"] = pd.to_numeric(sub["lastPrice"], errors="coerce")
    sub["priceChangePercent"] = pd.to_numeric(sub["priceChangePercent"], errors="coerce")


    sub = sub.rename(columns={"lastPrice": "price", "priceChangePercent": "change_percent"})
    sub["name"] = sub["symbol"]

    return sub[["symbol", "name", "price", "change_percent"]].to_dict(orient="records")


def _reload_df():
    r2 = requests.get(BINANCE_24H_URL, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
    r2.raise_for_status()
    return pd.DataFrame(r2.json())







