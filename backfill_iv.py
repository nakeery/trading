"""
Historical IV Backfill
======================
Backfills atm_iv_30d, iv_skew_25d, and term_structure into the indicators
CSV using Black-Scholes inversion on Massive.com historical options data
(reference endpoint + aggregates endpoint).

Run once per ticker after backfill_iv.py prerequisites are met. Takes
roughly 10-20 minutes for 500 trading days at ~0.05s sleep between dates.
Resumable: already-populated dates are never overwritten.

Usage:
    python backfill_iv.py       # prompts for ticker

Prerequisites:
    - $env:MASSIVE_API_KEY set in current PowerShell session
    - data/{ticker}_indicators.csv must exist (run indicators.py first)
    - modules/bs_invert.py must exist (already created in this repo)

Output:
    Modifies data/{ticker}_indicators.csv in-place.
    Checkpoints to disk every 50 dates.
    Prints per-date progress and final summary.
"""

import os
import sys
import time
import datetime
import pandas as pd
import yfinance as yf

from modules.massive import get_historical_iv_snapshot, IV_COLS

DATA_DIR        = "data"
BACKFILL_YEARS  = 2      # Massive Options Starter historical limit
SLEEP_PER_DATE  = 0.05   # seconds between date processing (polite to API)
CHECKPOINT_EVERY = 50    # save CSV to disk every N dates


# ─────────────────────────────────────────
# RISK-FREE RATE HELPERS
# ─────────────────────────────────────────
def load_irx():
    """
    Fetch 3-month T-bill yield history from yfinance.

    Returns a pandas Series indexed by date (annualized decimal).
    Falls back to a flat 5% warning message if download fails.
    """
    print("  Fetching ^IRX (3-month T-bill) for per-date risk-free rates...")
    try:
        raw = yf.download("^IRX", period="5y", progress=False, auto_adjust=True)
        raw.columns = raw.columns.get_level_values(0)
        irx = raw["Close"].dropna() / 100.0   # percent -> decimal
        print(f"  -> ^IRX loaded: {irx.index[0].date()} to {irx.index[-1].date()} "
              f"({len(irx)} days)\n")
        return irx
    except Exception as e:
        print(f"  WARNING: Could not download ^IRX ({e}). Using flat 5% fallback.\n")
        return None


def get_rate(irx, date):
    """
    Look up the risk-free rate for a given date.

    Forward-fills gaps (weekends / holidays where T-bill data is missing).
    """
    if irx is None:
        return 0.05
    idx = pd.Timestamp(date)
    available = irx[irx.index <= idx]
    if available.empty:
        return 0.05
    return float(available.iloc[-1])


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    # Ticker prompt
    while True:
        try:
            ticker = input("  Ticker [XYZ]: ").strip().upper()
            if ticker:
                break
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)

    csv_path = os.path.join(DATA_DIR, f"{ticker.lower()}_indicators.csv")
    if not os.path.exists(csv_path):
        print(f"\nERROR: {csv_path} not found. Run indicators.py for {ticker} first.")
        sys.exit(1)

    # Load indicators CSV
    print(f"\nLoading {csv_path}...")
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True).sort_index()
    print(f"  -> {len(df)} rows, index {df.index[0].date()} to {df.index[-1].date()}")

    # Ensure all IV columns exist (initialise with NaN if absent)
    for col in IV_COLS:
        if col not in df.columns:
            df[col] = pd.NA

    # Determine which dates need backfilling
    cutoff = pd.Timestamp.today().normalize() - pd.DateOffset(years=2)
    mask   = (df.index >= cutoff) & (df["atm_iv_30d"].isna() | df["term_structure"].isna())
    dates  = df.index[mask].sort_values(ascending=False)   # newest -> oldest

    print(f"  -> Dates to backfill: {len(dates)}  "
          f"(cutoff: {cutoff.date()}, NaN atm_iv_30d or term_structure)\n")

    if len(dates) == 0:
        print("  Nothing to backfill — atm_iv_30d and term_structure are already populated for all dates in range.")
        sys.exit(0)

    # Load risk-free rates
    irx = load_irx()

    # Backfill loop
    print("Beginning backfill (newest -> oldest)...")
    print(f"  Checkpoint every {CHECKPOINT_EVERY} dates | sleep {SLEEP_PER_DATE}s per date\n")

    filled  = 0
    failed  = 0
    skipped = 0
    total   = len(dates)

    for i, ts in enumerate(dates):
        date = ts.date()

        # Spot price on that date
        spot_raw = df.loc[ts, "Close"] if "Close" in df.columns else None
        if spot_raw is None or pd.isna(spot_raw) or float(spot_raw) <= 0:
            skipped += 1
            print(f"  {date}  SKIP — no spot price  ({i+1}/{total})")
            continue

        spot = float(spot_raw)
        r    = get_rate(irx, date)

        result = get_historical_iv_snapshot(ticker, date, spot, r)

        if result is not None:
            for key, val in result.items():
                if key in df.columns and val is not None:
                    df.loc[ts, key] = val
            filled += 1
            atm_iv = result.get("atm_iv_30d")
            skew   = result.get("iv_skew_25d")
            term   = result.get("term_structure")
            skew_s = f"  skew={skew:+.3f}" if skew is not None else ""
            term_s = f"  term={term:.3f}"   if term is not None else ""
            print(f"  {date}  iv={atm_iv:.3f}{skew_s}{term_s}  ({i+1}/{total})")
        else:
            failed += 1
            print(f"  {date}  FAILED — no data or inversion error  ({i+1}/{total})")

        # Checkpoint: save to disk periodically and at the very end
        if (i + 1) % CHECKPOINT_EVERY == 0 or (i + 1) == total:
            df.to_csv(csv_path)
            print(f"\n  [checkpoint] {csv_path}  "
                  f"({filled} filled, {failed} failed, {skipped} skipped so far)\n")

        time.sleep(SLEEP_PER_DATE)

    # Final save (may already be done by last checkpoint, but safe to repeat)
    df.to_csv(csv_path)

    fill_rate = 100 * filled / max(total - skipped, 1)
    print(f"\n{'='*52}")
    print(f"  BACKFILL COMPLETE  —  {ticker}")
    print(f"{'='*52}")
    print(f"  Dates attempted : {total}")
    print(f"  Filled          : {filled}")
    print(f"  Failed          : {failed}  (no options data for that date)")
    print(f"  Skipped         : {skipped}  (no spot price in indicators CSV)")
    print(f"  Fill rate       : {fill_rate:.0f}%")
    print(f"  CSV updated     : {csv_path}")
    print(f"{'='*52}\n")
    print("Next steps:")
    print("  1. python volatility.py --iv-features   # retrain Phase 3 with real IV")
    print("  2. python backtest.py  --iv-features    # walk-forward validation")
    print("  3. python entry.py     --iv-features    # live signal with real IV features\n")


if __name__ == "__main__":
    main()
