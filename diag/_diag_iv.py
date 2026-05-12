import datetime
from modules.massive import _fetch_historical_contracts, _fetch_agg_price

ticker = "QQQ"
date   = datetime.date(2026, 5, 6)
spot   = 711.23

# Step 1: with expired=true (current code)
print(f"=== WITH expired=true ===")
contracts = _fetch_historical_contracts(ticker, date, 23, 37, spot*0.90, spot*1.10, contract_type="call")
print(f"Returned {len(contracts)} contracts")

# Step 2: without expired=true — test if active contracts come back
print(f"\n=== WITHOUT expired=true ===")
params = {
    "underlying_ticker":   ticker,
    "as_of":               date.isoformat(),
    "expiration_date.gte": (date + datetime.timedelta(days=23)).isoformat(),
    "expiration_date.lte": (date + datetime.timedelta(days=37)).isoformat(),
    "strike_price.gte":    round(spot * 0.90, 2),
    "strike_price.lte":    round(spot * 1.10, 2),
    "contract_type":       "call",
    "limit":               10,
    "apiKey":              MASSIVE_API_KEY,
}
resp = _get(f"{MASSIVE_URL}/v3/reference/options/contracts", {k: v for k, v in params.items() if k != "apiKey"})
# oops, _get adds the key — just pass all params directly
r2 = requests.get(f"{MASSIVE_URL}/v3/reference/options/contracts", params=params, timeout=15)
data2 = r2.json()
results2 = data2.get("results") or []
print(f"Returned {len(results2)} contracts  (status={r2.status_code})")
if results2:
    pprint.pprint(results2[:2])
else:
    print(f"  status={r2.status_code}, keys={list(data2.keys())}")

# Step 3: try completely unfiltered (just ticker + as_of, no expiry/strike range, no expired flag)
print(f"\n=== No strike/expiry filters, no expired flag, limit=5 ===")
params3 = {
    "underlying_ticker": ticker,
    "as_of":             date.isoformat(),
    "limit":             5,
    "apiKey":            MASSIVE_API_KEY,
}
r3 = requests.get(f"{MASSIVE_URL}/v3/reference/options/contracts", params=params3, timeout=15)
data3 = r3.json()
results3 = data3.get("results") or []
print(f"Returned {len(results3)} contracts  (status={r3.status_code})")
if results3:
    pprint.pprint(results3[:2])
else:
    print(f"  status={r3.status_code}, response={data3}")
