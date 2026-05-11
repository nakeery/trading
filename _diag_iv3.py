"""End-to-end test of get_historical_iv_snapshot after fixes."""
import datetime
from modules.massive import get_historical_iv_snapshot

ticker = "QQQ"
date   = datetime.date(2025, 11, 3)
spot   = 490.0
r      = 0.045

print(f"get_historical_iv_snapshot: {ticker} on {date} (spot={spot})")
result = get_historical_iv_snapshot(ticker, date, spot, r)
if result:
    for k, v in result.items():
        print(f"  {k}: {v}")
else:
    print("  Result: None — no valid inversion found")


# --- fetch contracts ---
contracts = _fetch_historical_contracts(
    ticker, date, target_dte - 7, target_dte + 7,
    spot * 0.90, spot * 1.10, contract_type="call"
)
print(f"Reference returned {len(contracts)} contracts")

def parse_meta(c):
    import datetime as dt
    opt_ticker = c.get("ticker")
    strike_raw = c.get("strike_price")
    expiry_str = c.get("expiration_date")
    if not (opt_ticker and strike_raw and expiry_str):
        return None
    expiry = dt.date.fromisoformat(expiry_str)
    dte = (expiry - date).days
    if dte <= 0:
        return None
    return (opt_ticker, float(strike_raw), expiry, dte)

parsed = [p for p in (parse_meta(c) for c in contracts) if p]
parsed.sort(key=lambda p: abs(p[3] - target_dte) * 10 + abs(p[1] - spot))
cands = parsed[:MAX_INVERT_PER_CATEGORY]

print(f"\nTop {len(cands)} candidates by ATM score:")
for p in cands:
    print(f"  {p[0]}  K={p[1]}  dte={p[3]}")

print(f"\nFetching agg prices and inverting:")
for p in cands:
    opt_ticker, strike, expiry, dte = p
    T = dte / 252.0
    price = _fetch_agg_price(opt_ticker, date)
    if price is None:
        print(f"  {opt_ticker}  K={strike}  -> NO PRICE")
        continue
    try:
        iv = implied_vol(price, spot, strike, r, T)
    except Exception as e:
        print(f"  {opt_ticker}  K={strike}  price={price:.4f}  -> INVERSION ERROR: {e}")
        continue
    ok = "OK" if 0.01 <= iv <= 5.0 else f"REJECTED (iv={iv:.4f} out of bounds)"
    print(f"  {opt_ticker}  K={strike}  dte={dte}  price={price:.4f}  iv={iv:.4f}  -> {ok}")
