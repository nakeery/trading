"""
Options-P&L overlay (S32) — does the framework's UNDERLYING edge survive as long-CALL P&L?
============================================================================================
The walk-forward backtest measures the underlying stock's forward return. But the framework
trades long call options. Three things the underlying backtest ignores can erase the edge:

  1. THETA  — time decay; a flat/slow underlying still bleeds the option.
  2. IV CRUSH — these signals fire AFTER drops (elevated IV); a calm recovery collapses IV and
               the option loses value even if the stock rises.
  3. SPREAD — bid-ask + commission round-trip cost.

This script re-prices each existing STRONG ENTRY signal as an ATM call via Black-Scholes,
holds it the signal horizon, exits, and reports NET option P&L vs two baselines:
  - naive dip rule (buy after a 20d drop)         — is the ML timing better than a one-liner?
  - all-days (buy a call every day)               — is there ANY timing edge over random?

HONEST CAVEATS (this is a MODEL, not real option prices — a backfill is disallowed):
  - IV is proxied by realized HV-20. Real IV is HIGHER, especially right after a drop, so this
    is GENEROUS to the strategy. If the edge dies here, it dies for real. `iv_mult` stresses this.
  - Dividend yield q=0 (≈ cancels in the entry/exit price ratio); adjusted-close basis; one ATM
    strike; hold-to-horizon (no early exit — triple-barrier exits are a later step).

Run:  python options_pnl.py            (defaults QQQ, JPM)
      python options_pnl.py QQQ F JPM
"""

import os
import sys
import numpy as np
import pandas as pd

from modules.bs_invert import black_scholes_call

DATA_DIR = "data"
R = 0.04          # risk-free rate (annual)
TRADING_DAYS = 252

# Sweep grid: (option DTE in calendar days, hold horizon in TRADING days)
HORIZONS = [(180, 15), (365, 126)]   # 6mo call held 15d ; 12mo call held ~6mo (the LEAPS use case)
SPREADS  = [0.02, 0.05, 0.10]        # round-trip bid-ask as fraction of premium
IV_MULTS = [1.0, 1.2]                # HV→IV multiplier (1.0 = generous; 1.2 = realistic post-dip premium)


def option_pnl(close, hv, entries, dte_cal, hold_td, spread, iv_mult, r=R):
    """Net long-ATM-call return for a set of entry positions. Returns (net_array, und_array)."""
    n = len(close)
    hold_cal = hold_td * 365.0 / TRADING_DAYS
    t_entry = dte_cal / 365.0
    t_exit  = (dte_cal - hold_cal) / 365.0
    if t_exit <= 0:
        return np.array([]), np.array([])
    nets, unds = [], []
    for i in entries:
        j = i + hold_td
        if j >= n:
            continue
        s0, s1 = close[i], close[j]
        ive, ivx = hv[i] * iv_mult, hv[j] * iv_mult
        if not (np.isfinite(s0) and np.isfinite(s1) and np.isfinite(ive) and np.isfinite(ivx)):
            continue
        if ive <= 0 or ivx <= 0 or s0 <= 0:
            continue
        p0 = black_scholes_call(s0, s0, r, t_entry, ive)   # ATM: K = S0
        p1 = black_scholes_call(s1, s0, r, t_exit, ivx)
        if p0 <= 1e-6:
            continue
        buy  = p0 * (1 + spread / 2)   # pay the ask
        sell = p1 * (1 - spread / 2)   # hit the bid
        nets.append(sell / buy - 1)
        unds.append(s1 / s0 - 1)
    return np.array(nets), np.array(unds)


def summarize(label, nets):
    if len(nets) == 0:
        return f"  {label:<26} (no valid trades)"
    return (f"  {label:<26} n={len(nets):>5}  mean {nets.mean():>+7.1%}  "
            f"median {np.median(nets):>+7.1%}  win {(nets > 0).mean():>4.0%}")


def run_ticker(ticker):
    ind_path = os.path.join(DATA_DIR, f"{ticker.lower()}_indicators.csv")
    res_path = os.path.join(DATA_DIR, f"{ticker.lower()}_backtest_results.csv")
    if not (os.path.exists(ind_path) and os.path.exists(res_path)):
        print(f"\n{ticker}: missing indicators or backtest_results CSV — skipping")
        return
    ind = pd.read_csv(ind_path, index_col=0, parse_dates=True)
    res = pd.read_csv(res_path, index_col=0, parse_dates=True)
    close = ind["Close"].values
    # HV-20 (annualized realized vol) as the IV proxy — computed here because indicators.py
    # does not write HV_20 (it's added downstream by modules/features.py:compute_hv_features).
    log_ret = np.log(ind["Close"] / ind["Close"].shift(1))
    hv = (log_ret.rolling(20).std() * np.sqrt(TRADING_DAYS)).values
    pos = {d: k for k, d in enumerate(ind.index)}

    # entry position sets (restricted to backtest test window for fairness)
    test_dates = [d for d in res.index if d in pos]
    strong = [pos[d] for d in res.index[res["signal"] == "STRONG ENTRY"] if d in pos]
    trail20 = ind["Close"] / ind["Close"].shift(20) - 1
    dip = [pos[d] for d in test_dates if np.isfinite(trail20.iloc[pos[d]]) and trail20.iloc[pos[d]] <= -0.03]
    alld = [pos[d] for d in test_dates]

    print(f"\n{'='*78}\n  {ticker} — modeled long-ATM-call P&L  (STRONG={len(strong)} signals)\n{'='*78}")
    for dte, hold in HORIZONS:
        print(f"\n  ── {dte}d call held {hold} trading days "
              f"({'~6mo LEAPS use case' if hold > 60 else 'short hold'}) ──")
        for ivm in IV_MULTS:
            for s in SPREADS:
                ns, _ = option_pnl(close, hv, strong, dte, hold, s, ivm)
                nd, _ = option_pnl(close, hv, dip,    dte, hold, s, ivm)
                na, _ = option_pnl(close, hv, alld,   dte, hold, s, ivm)
                tag = f"iv×{ivm} spread {s:.0%}"
                edge_dip = (ns.mean() - nd.mean()) if len(ns) and len(nd) else float("nan")
                edge_all = (ns.mean() - na.mean()) if len(ns) and len(na) else float("nan")
                print(f"\n  [{tag}]")
                print(summarize("STRONG ENTRY", ns))
                print(summarize("naive dip (-3%/20d)", nd))
                print(summarize("all days (random call)", na))
                print(f"  -> STRONG edge vs all-days {edge_all:+.1%} | vs naive dip {edge_dip:+.1%}")


if __name__ == "__main__":
    tickers = [t.upper() for t in sys.argv[1:]] or ["QQQ", "JPM"]
    print("Modeled option P&L — HV-as-IV proxy is GENEROUS (real post-dip IV is higher).")
    print("Decision: STRONG must beat the all-days option baseline AND stay positive at "
          "spread~5%, iv×1.0+ to count as tradeable edge.")
    for t in tickers:
        run_ticker(t)
    print()
