
import json
import requests as r

api_Key = "REDACTED"

# # 1. Rating (the gauge)
# url = "https://financialmodelingprep.com/stable/ratings-snapshot?symbol=AAPL&apikey=" + api_Key
#
# # 2. Price target
# url2 = "https://financialmodelingprep.com/stable/price-target-consensus?symbol=AAPL&apikey=" + api_Key
#
# # 3. Stock quote (price, change %)
# url3 = "https://financialmodelingprep.com/stable/quote?symbol=AAPL&apikey=" + api_Key
#
# # 4. Company profile (name, exchange, logo)
# url4 = "https://financialmodelingprep.com/stable/profile?symbol=AAPL&apikey=" + api_Key
#
# # 5. Analyst grades summary (buy/sell/hold count)
# url5 = "https://financialmodelingprep.com/stable/grades-consensus?symbol=AAPL&apikey=" + api_Key

# data1 = json.loads(r.request("GET", url).text)
# data2 = json.loads(r.request("GET", url2).text)
# data3 = json.loads(r.request("GET", url3).text)
# data4 = json.loads(r.request("GET", url4).text)
# data5 = json.loads(r.request("GET", url5).text)

#
# print(data1)
#
# print(data2)
# print(data3)
# print(data4)
# print(data5)



def get_stock_overview(symbol: str):
    symbol = symbol.upper()

    try:
        rating   = json.loads(r.request("GET", f"https://financialmodelingprep.com/stable/ratings-snapshot?symbol={symbol}&apikey={api_Key}").text)
        grades   = json.loads(r.request("GET", f"https://financialmodelingprep.com/stable/grades-consensus?symbol={symbol}&apikey={api_Key}").text)
        quote    = json.loads(r.request("GET", f"https://financialmodelingprep.com/stable/quote?symbol={symbol}&apikey={api_Key}").text)
        profile  = json.loads(r.request("GET", f"https://financialmodelingprep.com/stable/profile?symbol={symbol}&apikey={api_Key}").text)
        target   = json.loads(r.request("GET", f"https://financialmodelingprep.com/stable/price-target-consensus?symbol={symbol}&apikey={api_Key}").text)

    except json.JSONDecodeError:
        return {"error": f"Symbol '{symbol}' not found"}

    if not quote:
        return {"error": f"Symbol '{symbol}' not found"}
    return {
        # Company info
        "symbol":        symbol,
        "name":          profile[0].get("companyName"),
        "exchange":      profile[0].get("exchangeShortName"),
        "logo":          profile[0].get("image"),
        "sector":        profile[0].get("sector"),

        # Price
        "price":         quote[0].get("price"),
        "change":        quote[0].get("change"),
        "change_pct":    quote[0].get("changesPercentage"),

        # Rating gauge
        "rating":        rating[0].get("ratingRecommendation"),  # e.g. "Strong Buy"
        "rating_score":  rating[0].get("ratingScore"),

        # Analyst grades
        "strong_buy":    grades[0].get("strongBuy"),
        "buy":           grades[0].get("buy"),
        "hold":          grades[0].get("hold"),
        "sell":          grades[0].get("sell"),
        "strong_sell":   grades[0].get("strongSell"),
        "consensus":     grades[0].get("consensus"),

        # Price target
        "target_high":   target[0].get("targetHigh"),
        "target_low":    target[0].get("targetLow"),
        "target_mean":   target[0].get("targetMean"),
        "target_median": target[0].get("targetMedian"),
    }


# print (get_stock_overview("msft") )

