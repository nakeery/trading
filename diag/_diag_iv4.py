"""
Focused debug: inspect raw v, n, price, and IV for every QQQ contract
on 2025-10-01 that returns price data. Shows exactly what passes/fails
the MIN_OPTION_VOLUME / MIN_OPTION_TRADES / max_iv filters.
"""
import datetime
import os
import requests
import yfinance as yf
from modules.massive import (
    _fetch_historical_contracts, BACK_MONTH_MIN_DTE,
    MIN_OPTION_VOLUME, MIN_OPTION_TRADES, MASSIVE_API_KEY, MASSIVE_URL,
)
from modules.bs_invert import implied_vol

TICKER     = "QQQ"
DATE       = datetime.date(2025, 10, 1)
TARGET_DTE = 30
R          = 0.0385

print(f"Fetching actual QQQ close for {DATE}...")
raw = yf.download("QQQ", start="2025-09-29", end="2025-10-02", progress=False, auto_adjust=True)
raw.columns = raw.columns.get_level_values(0)
SPOT = float(raw["Close"].dropna().iloc[-1])
print(f"  spot = {SPOT:.2f}\n")

print("Fetching front-month call contracts from reference endpoint...")
contracts = _fetch_historical_contracts(
    TICKER, DATE,
    max(1, TARGET_DTE - 7), TARGET_DTE + 7,
    SPOT * 0.90, SPOT * 1.10,
    contract_type="call",
)
print(f"  {len(contracts)} contracts returned\n")

def parse_meta(c):
    opt_ticker = c.get("ticker")
    strike_raw = c.get("strike_price")
    expiry_str = c.get("expiration_date")
    if not (opt_ticker and strike_raw and expiry_str):
        return None
    try:
        expiry = datetime.date.fromisoformat(expiry_str)
    except ValueError:
        return None
    dte = (expiry - DATE).days
    if dte <= 0:
        return None
    return (opt_ticker, float(strike_raw), expiry, dte)

parsed = sorted(
    [p for p in (parse_meta(c) for c in contracts) if p],
    key=lambda p: abs(p[3] - TARGET_DTE) * 10 + abs(p[1] - SPOT) / SPOT * 100,
)

print(f"{'Ticker':<38} {'K':>6} {'DTE':>4}  {'v':>6} {'n':>6}  {'price':>8}  {'IV':>8}  Status")
print("-" * 100)
found = 0
for opt_ticker, strike, expiry, dte in parsed[:30]:
    T = dte / 252.0
    date_str = DATE.isoformat()
    url = f"{MASSIVE_URL}/v2/aggs/ticker/{opt_ticker}/range/1/day/{date_str}/{date_str}"
    try:
        resp = requests.get(url, params={"apiKey": MASSIVE_API_KEY}, timeout=15)
        results = (resp.json().get("results") or []) if resp.ok else []
    except Exception:
        results = []

    if not results:
        continue

    agg = results[0]
    v   = agg.get("v") or 0
    n   = agg.get("n") or 0
    raw_price = agg.get("c") or agg.get("vw")
    price = float(raw_price) if raw_price else None

    if price is None or price <= 0:
        continue

    try:
        iv = implied_vol(price, SPOT, strike, R, T)
        iv_str = f"{iv:.1%}"
    except Exception as e:
        iv_str = f"ERR"
        iv = None

    pass_v  = v >= MIN_OPTION_VOLUME
    pass_n  = n >= MIN_OPTION_TRADES
    pass_iv = iv is not None and 0.01 <= iv <= 2.0
    if pass_v and pass_n and pass_iv:
        status = "PASS"
    else:
        reasons = []
        if not pass_v:  reasons.append(f"v={v:.0f}<{MIN_OPTION_VOLUME}")
        if not pass_n:  reasons.append(f"n={n:.0f}<{MIN_OPTION_TRADES}")
        if not pass_iv: reasons.append(f"iv={iv_str}")
        status = "REJECT(" + ",".join(reasons) + ")"

    print(f"{opt_ticker:<38} {strike:>6.0f} {dte:>4}  {v:>6.0f} {n:>6.0f}  {price:>8.2f}  {iv_str:>8}  {status}")
    found += 1

if found == 0:
    print("  No contracts returned any price data.")
else:
    print(f"\n{found} contracts had price data out of {len(parsed)} candidates.")
