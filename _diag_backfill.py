"""
Backfill diagnostic — samples ~1 date per month across the 2-year window.
Uses real spot prices from the indicators CSV (same as backfill_iv.py will).
Goal: confirm coverage rate and IV plausibility before committing to the full run.
"""
import os
import sys
import time
import datetime
import pandas as pd
import yfinance as yf
from modules.massive import get_historical_iv_snapshot, IV_FEATURE_COLS

TICKER       = "QQQ"
DATA_DIR     = "data"
BACKFILL_YEARS = 2
SLEEP        = 0.1   # polite between calls

csv_path = os.path.join(DATA_DIR, f"{TICKER.lower()}_indicators.csv")
if not os.path.exists(csv_path):
    print(f"ERROR: {csv_path} not found. Run indicators.py for {TICKER} first.")
    sys.exit(1)

print(f"Loading {csv_path}...")
df = pd.read_csv(csv_path, index_col=0, parse_dates=True).sort_index()

cutoff = pd.Timestamp.today() - pd.DateOffset(years=BACKFILL_YEARS)
# atm_iv_30d may not exist yet if indicators.py hasn't harvested it — treat all as NaN
if "atm_iv_30d" in df.columns:
    mask = (df.index >= cutoff) & df["atm_iv_30d"].isna()
else:
    mask = df.index >= cutoff
target = df[mask].copy()
print(f"  {len(target)} NaN rows in {BACKFILL_YEARS}-year window\n")

# Sample one row per calendar month
target["_ym"] = target.index.to_period("M")
sample = (
    target.groupby("_ym", group_keys=False)
          .apply(lambda g: g.iloc[len(g) // 2])   # mid-month row
)
print(f"Sampling {len(sample)} dates (1 per month)...\n")

# Fetch ^IRX for risk-free rates
print("Fetching ^IRX...")
try:
    irx_raw = yf.download("^IRX", period="5y", progress=False, auto_adjust=True)
    irx_raw.columns = irx_raw.columns.get_level_values(0)
    irx = irx_raw["Close"].dropna() / 100.0
except Exception as e:
    print(f"  WARNING: ^IRX failed ({e}), using flat 4%")
    irx = None

def get_r(d):
    if irx is None:
        return 0.04
    avail = irx[irx.index <= str(d)]
    return float(avail.iloc[-1]) if not avail.empty else 0.04

# ── Header ────────────────────────────────────────────────────────────────
print(f"{'Date':<12} {'Spot':>7}  {'ATM IV':>7}  {'Skew':>7}  {'Term':>6}  Status")
print("─" * 65)

passed = 0
failed = 0
warned = 0

for ts, row in sample.iterrows():
    date = ts.to_timestamp().date() if hasattr(ts, "to_timestamp") else ts.date()
    spot = row.get("Close")
    if pd.isna(spot) or spot <= 0:
        print(f"{str(date):<12} {'N/A':>7}  — SKIP (no Close price)")
        failed += 1
        continue

    r = get_r(date)
    result = get_historical_iv_snapshot(TICKER, date, float(spot), r, _debug=True)
    time.sleep(SLEEP)

    if result is None:
        print(f"{str(date):<12} {spot:>7.2f}  — None (no liquid contracts found)")
        failed += 1
        continue

    iv   = result["atm_iv_30d"]
    skew = result.get("iv_skew_25d")
    term = result.get("term_structure")

    iv_str   = f"{iv:.1%}" if iv is not None else "  N/A"
    skew_str = f"{skew:+.3f}" if skew is not None else "   N/A"
    term_str = f"{term:.3f}" if term is not None else "  N/A"

    if iv is None:
        status = "WARN: iv=None"
        warned += 1
    elif iv < 0.05 or iv > 0.60:
        status = f"WARN: iv={iv:.1%} outside 5-60%"
        warned += 1
    else:
        status = "OK"
        passed += 1

    print(f"{str(date):<12} {spot:>7.2f}  {iv_str:>7}  {skew_str:>7}  {term_str:>6}  {status}")

# ── Summary ───────────────────────────────────────────────────────────────
total = passed + failed + warned
print("─" * 65)
print(f"PASS: {passed}/{total}   WARN: {warned}/{total}   FAIL(None): {failed}/{total}")
coverage = (passed + warned) / total * 100 if total else 0
print(f"Coverage: {coverage:.0f}%  (dates where any IV was returned)")
if coverage >= 70:
    print("\n-> Coverage looks good. Safe to run full backfill.")
else:
    print("\n-> Low coverage. Investigate before running full backfill.")
