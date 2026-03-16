from yahooquery import Ticker

tsla = Ticker("TSLA")

detail = tsla.summary_detail
profile = tsla.asset_profile
price = tsla.price

print("summary_detail type:", type(detail))
if isinstance(detail, dict):
    print("keys:", detail.keys())
    if "tsla" in detail:
        print("marketCap:", detail["tsla"].get("marketCap"))

print("\nprice type:", type(price))
if isinstance(price, dict):
    print("keys:", price.keys())
    if "tsla" in price:
        print("regularMarketPrice:", price["tsla"].get("regularMarketPrice"))
        print("shortName:", price["tsla"].get("shortName"))
