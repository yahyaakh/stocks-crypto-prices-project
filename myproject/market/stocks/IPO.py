import finnhub
from datetime import datetime, timedelta
from django.conf import settings

import os
import sys
import django

today = datetime.now()
one_year_later = today + timedelta(days=365)

# ipo

def ipo(fromDate: datetime | None, toDate: datetime | None):
    # 1. Connect to API
    finnhub_client = finnhub.Client(api_key=settings.FINNHUB_API_KEY)

    # 2. Format Dates (API requires YYYY-MM-DD strings)
    # Convert datetime objects to string format "YYYY-MM-DD"
    from_str = fromDate.strftime("%Y-%m-%d") if fromDate else None
    to_str = toDate.strftime("%Y-%m-%d") if toDate else None
    
    # 3. Fetch Data
    results = finnhub_client.ipo_calendar(_from=from_str, to=to_str)

    return results if results else {}


def show_ipo():

    # 4. Define Range (Today -> +365 Days)
    results = ipo(today, one_year_later)
    rows = []
    ipo_list = results.get('ipoCalendar', [])
    for row in ipo_list:
        # We use .get() OR None to prevent crashes if a field is missing
        date = row.get("date") or None
        exchange = row.get("exchange") or None
        name = row.get("name") or None
        numberOfShares = row.get("numberOfShares") or None
        price = row.get("price") or None
        symbol = row.get("symbol") or None
        totalSharesValue = row.get("totalSharesValue") or None
        rows.append({"date": date, "exchange": exchange, "name": name, "numberOfShares": numberOfShares , "price": price, "symbol": symbol, "totalSharesValue": totalSharesValue})

    return rows


# Data Normalization: "External APIs are often messy.
# Some companies might not have a set price or share count yet. 
# My show_ipo function acts as a cleaning layer. 
# It standardizes the data structure so my frontend receives a consistent list of dictionaries, 
# replacing missing values with None."