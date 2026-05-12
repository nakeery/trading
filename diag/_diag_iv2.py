import datetime
from modules.massive import get_historical_iv_snapshot

ticker = "QQQ"
date   = datetime.date(2025, 11, 3)
spot   = 490.0
r      = 0.045   # approx T-bill rate Nov 2025

print(f"Full get_historical_iv_snapshot for {ticker} on {date} (spot={spot})")
result = get_historical_iv_snapshot(ticker, date, spot, r)
print(f"Result: {result}")
params1 = {
    "underlying_ticker":   ticker,
    "as_of":               date.isoformat(),
    "expired":             "true",
    "expiration_date.gte": (date + datetime.timedelta(days=23)).isoformat(),
    "expiration_date.lte": (date + datetime.timedelta(days=37)).isoformat(),
    "contract_type":       "call",
    "limit":               5,
    "apiKey":              MASSIVE_API_KEY,
}
r1 = requests.get(f"{MASSIVE_URL}/v3/reference/options/contracts", params=params1, timeout=15)
d1 = r1.json()
print(f"Test 1 (as_of + expired=true): status={r1.status_code}  count={len(d1.get('results') or [])}  keys={list(d1.keys())}")
if d1.get("results"):
    print(f"  Sample: {d1['results'][0]}")

# Test 2: expired=true only (no as_of)
params2 = {
    "underlying_ticker":   ticker,
    "expired":             "true",
    "expiration_date.gte": (date + datetime.timedelta(days=23)).isoformat(),
    "expiration_date.lte": (date + datetime.timedelta(days=37)).isoformat(),
    "contract_type":       "call",
    "limit":               5,
    "apiKey":              MASSIVE_API_KEY,
}
r2 = requests.get(f"{MASSIVE_URL}/v3/reference/options/contracts", params=params2, timeout=15)
d2 = r2.json()
print(f"Test 2 (expired=true, no as_of): status={r2.status_code}  count={len(d2.get('results') or [])}  keys={list(d2.keys())}")
if d2.get("results"):
    print(f"  Sample ticker: {d2['results'][0].get('ticker')}")

# Test 3: no filters at all — just ticker
params3 = {
    "underlying_ticker": ticker,
    "limit":             3,
    "apiKey":            MASSIVE_API_KEY,
}
r3 = requests.get(f"{MASSIVE_URL}/v3/reference/options/contracts", params=params3, timeout=15)
d3 = r3.json()
print(f"Test 3 (no filters): status={r3.status_code}  count={len(d3.get('results') or [])}  keys={list(d3.keys())}")
if d3.get("results"):
    print(f"  Sample: {d3['results'][0].get('ticker')}  expiry={d3['results'][0].get('expiration_date')}")
