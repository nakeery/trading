"""
Options Trading — Position Sizing (Phase 4)
============================================
Pulls the live options chain from Tradier, and recommends position sizes
based on your budget.

Run after signal.py fires an ENTER signal to determine:
  - Which strikes and expiries are available within your range
  - How many contracts you can buy at your budget
  - Daily theta decay cost at that position size
  - Whether current IV is cheap or expensive vs recent HV

Setup:
  1. Open a free Tradier brokerage account at tradier.com
  2. Get your API token from Account > API Access (use brokerage token, not sandbox)
  3. Set $env:TRADIER_TOKEN = "..." or edit modules/tradier.py

Requirements:
    pip install pandas numpy requests
"""

import os
import sys
import numpy as np
import pandas as pd
import datetime

from modules.tradier import (
    TRADIER_TOKEN,
    get_current_price,
    get_expirations,
    get_chain,
)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
# TICKER               = "AMD"
DATA_DIR             = "data"
# INDICATORS_CSV       = os.path.join(DATA_DIR, f"{TICKER.lower()}_indicators.csv")
MIN_DTE              = 180   # ~6 months
MAX_DTE              = 365 * 2   # ~12 months
DEFAULT_STRIKE_RANGE = 10    # strikes above and below ATM
HV_WINDOW            = 20


# ─────────────────────────────────────────
# 2. LOAD HV FROM INDICATORS CSV
# ─────────────────────────────────────────
def load_hv(path):
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if "Ticker" in df.columns:
            df.drop(columns=["Ticker"], inplace=True)
        close   = df["Close"].dropna()
        log_ret = np.log(close / close.shift(1))
        return log_ret.rolling(HV_WINDOW).std().iloc[-1] * np.sqrt(252)
    except Exception:
        return None


# ─────────────────────────────────────────
# 3. FETCH AND FILTER OPTIONS CHAIN
# ─────────────────────────────────────────
def fetch_options(ticker, current_price, strike_range):
    today    = datetime.date.today()
    rows     = []

    print(f"  Fetching expiration dates...")
    expirations = get_expirations(ticker)

    in_range = [
        (e, (datetime.date.fromisoformat(e) - today).days)
        for e in expirations
        if MIN_DTE <= (datetime.date.fromisoformat(e) - today).days <= MAX_DTE
    ]
    print(f"  Expiries in {MIN_DTE}-{MAX_DTE} DTE window: {len(in_range)}")

    if not in_range:
        return pd.DataFrame()

    for exp_str, dte in in_range:
        print(f"  Fetching {exp_str} ({dte} DTE)...")
        try:
            chain = get_chain(ticker, exp_str)
        except Exception as e:
            print(f"  Skipping {exp_str}: {e}")
            continue

        if chain.empty:
            continue

        chain = chain[chain["option_type"] == "call"].copy()

        # Select N strikes above and below ATM
        all_strikes = sorted(chain["strike"].unique())
        if not all_strikes:
            continue
        atm_idx  = min(range(len(all_strikes)), key=lambda i: abs(all_strikes[i] - current_price))
        low_idx  = max(0, atm_idx - strike_range)
        high_idx = min(len(all_strikes) - 1, atm_idx + strike_range)
        selected = set(all_strikes[low_idx:high_idx + 1])
        chain    = chain[chain["strike"].isin(selected) & (chain["ask"] > 0)].copy()

        if chain.empty:
            continue

        for _, row in chain.iterrows():
            greeks = row.get("greeks") or {}
            if not isinstance(greeks, dict):
                continue
            delta  = greeks.get("delta")
            theta  = greeks.get("theta")   # per share per day
            mid_iv = greeks.get("smv_vol") or greeks.get("mid_iv")

            if delta is None or theta is None:
                continue

            strike       = float(row["strike"])
            ask          = float(row["ask"])
            pct_from_atm = (strike - current_price) / current_price
            moneyness    = ("ITM" if pct_from_atm < -0.02
                            else "OTM" if pct_from_atm > 0.02
                            else "ATM")

            rows.append({
                "expiry":      exp_str,
                "dte":         dte,
                "strike":      strike,
                "atm_strike":  float(all_strikes[atm_idx]),
                "type":        moneyness,
                "ask":         ask,
                "cost":        ask * 100,
                "delta":       float(delta),
                "theta_day":   float(theta),
                "iv":          float(mid_iv) if mid_iv else np.nan,
            })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────
# 4. SIZING
# ─────────────────────────────────────────
def add_sizing(df, budget):
    df["contracts"]   = (budget / df["cost"]).apply(np.floor).astype(int)
    df["decay_total"] = df["contracts"] * df["theta_day"] * 100
    df["affordable"]  = df["contracts"] > 0
    return df


# ─────────────────────────────────────────
# 5. PRINT RESULTS
# ─────────────────────────────────────────
def print_results(df, ticker, current_price, budget, hv, strike_range):
    w = 76
    print(f"\n{'═'*w}")
    print(f"  OPTIONS SIZING — {ticker}  |  Price: ${current_price:.2f}  |  "
          f"Strike range: ATM +/- {strike_range} strikes")
    print(f"  Budget: ${budget:,.0f}")
    if hv is not None:
        print(f"  HV (20-day): {hv:.1%}  — compare against each option's IV below")
    print(f"{'─'*w}")
    print(f"  Loss scenarios on full budget:")
    for pct in [0.10, 0.15, 0.20]:
        print(f"    {int(pct*100):>3}% loss  ->  -${budget * pct:,.0f}")
    print(f"    100% loss  ->  -${budget:,.0f}  (expires worthless)")
    print(f"{'═'*w}")

    for expiry, group in df.groupby("expiry"):
        dte = group["dte"].iloc[0]
        print(f"\n  Expiry: {expiry}  ({dte} DTE)")
        print(f"  {'─'*74}")
        print(f"  {'Strike':>7}  {'Type':>4}  {'Ask':>7}  {'Delta':>6}  "
              f"{'Theta/day':>10}  {'IV':>6}  {'Contracts':>10}  {'Decay/d':>8}")
        print(f"  {'─'*74}")

        for _, row in group.sort_values("strike").iterrows():
            iv_flag = ""
            if hv is not None and not np.isnan(row["iv"]):
                if row["iv"] > hv * 1.20:
                    iv_flag = "^"
                elif row["iv"] < hv * 0.80:
                    iv_flag = "v"

            iv_str = f"{row['iv']:.1%}" if not np.isnan(row["iv"]) else "  N/A"

            if row["affordable"]:
                cts_str   = f"{row['contracts']:>10}"
                decay_str = f"${row['decay_total']:>7.2f}"
            else:
                cts_str   = f"{'over budget':>10}"
                decay_str = f"{'—':>8}"

            atm_marker = " <-- ATM" if row["strike"] == row["atm_strike"] else ""
            print(f"  {row['strike']:>7.2f}  {row['type']:>4}  "
                  f"${row['ask']:>6.2f}  {row['delta']:>6.3f}  "
                  f"${row['theta_day']:>9.4f}  {iv_str:>5}{iv_flag:1}  "
                  f"{cts_str}  {decay_str}{atm_marker}")

    print(f"\n  {'─'*74}")
    print(f"  ^ = IV expensive vs HV (+20%)   v = IV cheap vs HV (-20%)")
    print(f"  over budget = contract cost exceeds your budget (increase budget to size this strike)")
    print(f"  Theta/day = per share per day.  Decay/d = total daily decay at sized position.")
    print(f"  Max loss assumes option expires worthless (full premium lost).")
    print(f"{'═'*w}\n")


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    if TRADIER_TOKEN == "YOUR_TOKEN_HERE":
        print("  Set TRADIER_TOKEN in sizing.py before running.")
        exit(1)

    while True:
        try:
            ticker_in = input("  Ticker [XYZ]: ").strip().upper()
            if ticker_in:
                TICKER         = ticker_in
                INDICATORS_CSV = os.path.join(DATA_DIR, f"{TICKER.lower()}_indicators.csv")
            break
        except (KeyboardInterrupt):
            print()
            sys.exit(0)

    budget_in = input(f"  Budget ($): ").strip()
    try:
        budget = float(budget_in.replace(",", ""))
    except ValueError:
        print("  Invalid amount.")
        exit(1)

    range_in = input(f"  Strikes above/below ATM [{DEFAULT_STRIKE_RANGE}]: ").strip()
    strike_range = int(range_in) if range_in else DEFAULT_STRIKE_RANGE

    print(f"\n  Fetching {TICKER} data from Tradier...")
    try:
        current_price = get_current_price(TICKER)
        print(f"  Current price: ${current_price:.2f}")
    except Exception as e:
        print(f"  Error fetching price: {e}")
        exit(1)

    hv = load_hv(INDICATORS_CSV)
    df = fetch_options(TICKER, current_price, strike_range)

    if df.empty:
        print(f"  No options found. Check your token or try a wider strike range.")
        exit(0)

    df = add_sizing(df, budget)
    print_results(df, TICKER, current_price, budget, hv, strike_range)
