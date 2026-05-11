"""
Validation: confirms S12 data quality fixes work correctly.
  - 2025-11-03: previously returned 237% IV (v=1 artifact). Should now return None
    or a plausible value after MIN_OPTION_VOLUME filter + max_iv=2.0 cap.
  - 2025-10-01: clean trading day. Should return ~15-22% IV.
"""
import datetime
import yfinance as yf
from modules.massive import get_historical_iv_snapshot

def get_r(irx, d):
    avail = irx[irx.index <= str(d)]
    return float(avail.iloc[-1]) if not avail.empty else 0.05

print("Fetching ^IRX for risk-free rates...")
raw = yf.download("^IRX", period="5y", progress=False, auto_adjust=True)
raw.columns = raw.columns.get_level_values(0)
irx = raw["Close"].dropna() / 100.0

tests = [
    ("QQQ", datetime.date(2025, 11, 3),  "BAD  — was 237% IV (v=1 artifact)"),
    ("QQQ", datetime.date(2025, 10, 1),  "GOOD — expect ~15-22% IV"),
]

# Fetch actual QQQ closing prices for test dates
print("Fetching QQQ spot prices...")
qqq_raw = yf.download("QQQ", start="2025-09-29", end="2025-11-05", progress=False, auto_adjust=True)
qqq_raw.columns = qqq_raw.columns.get_level_values(0)
qqq_close = qqq_raw["Close"].dropna()

def get_spot(d):
    avail = qqq_close[qqq_close.index <= str(d)]
    if avail.empty:
        return None
    return float(avail.iloc[-1])

for ticker, date, label in tests:
    r    = get_r(irx, date)
    spot = get_spot(date)
    if spot is None:
        print(f"\n--- {date}  SKIP: no spot price ---")
        continue
    print(f"\n--- {date}  {label}  spot={spot:.2f}  r={r:.4f} ---")
    result = get_historical_iv_snapshot(ticker, date, spot, r)
    if result is None:
        print("  -> None (volume filter or IV cap rejected all candidates — fix working)")
    else:
        for k, v in result.items():
            print(f"  {k}: {v}")
        atm_iv = result.get("atm_iv_30d")
        if atm_iv is not None:
            if atm_iv > 2.0:
                print(f"  !! FAIL: atm_iv_30d={atm_iv:.1%} exceeds max_iv=2.0")
            elif atm_iv < 0.05 or atm_iv > 0.50:
                print(f"  ?? WARN: atm_iv_30d={atm_iv:.1%} outside plausible 5-50% range")
            else:
                print(f"  OK: atm_iv_30d={atm_iv:.1%} looks plausible")
