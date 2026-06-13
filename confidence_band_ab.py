"""
Phase 2 Confidence-Band A/B — Candidate 1 Phase A (S31)
========================================================
Tests the band rule — Phase 2 WIN requires 0.55 <= dir_prob < 0.70 — against
the production baseline by recomputing the five-tier signal from probabilities
already stored in data/{ticker}_backtest_results.csv. Pure post-processing:
no model retraining, no production files touched.

Rationale (S23/S25): on NVDA the model's most-confident P2 signals
(dir_prob >= 0.70) carry inverted edge (over-applied "post-drop recovery"
prior); the mid-confidence range holds the real edge. QQQ is the opposite.

Pre-registered predictions (written BEFORE first run — S25 deciles):
  NVDA: STRONG ENTRY 6mo avg improves >= +2pp; hierarchy intact.
  QQQ:  STRONG ENTRY 6mo avg degrades (band removes its best bucket).
  AMD:  informational — 15d degrades (tail is AMD's best 15d bucket),
        6mo flat-to-better (horizon-split).

Run: python confidence_band_ab.py   (1 prompt: ticker)
"""

import os
import sys
import pandas as pd

from entry import determine_signal

DATA_DIR      = "data"
P2_THRESHOLD  = 0.55
P2B_THRESHOLD = 0.55
P3_THRESHOLD  = 0.60
BAND_CAP      = 0.70

PREDICTIONS = {
    "NVDA": "improvement role — STRONG ENTRY 6mo avg should improve >= +2pp, hierarchy intact",
    "QQQ":  "control role — STRONG ENTRY 6mo avg should DEGRADE (band removes QQQ's best bucket)",
    "AMD":  "informational — 15d degrades, 6mo flat-to-better (horizon-split)",
}


def recompute_signals(df):
    """Baseline + banded five-tier labels from stored probabilities."""
    base, band = [], []
    for _, r in df.iterrows():
        dir_win    = r["dir_prob"] >= P2_THRESHOLD
        dir_win_63 = r["dir_prob_63"] >= P2B_THRESHOLD
        expansion  = r["exp_prob"] >= P3_THRESHOLD
        base.append(determine_signal(dir_win, dir_win_63, expansion))
        band.append(determine_signal(dir_win and r["dir_prob"] < BAND_CAP, dir_win_63, expansion))
    df = df.copy()
    df["signal_base"] = base
    df["signal_band"] = band
    return df


def tier_stats(df, signal_col, tier, ret_col):
    s = df.loc[df[signal_col] == tier, ret_col].dropna()
    if len(s) == 0:
        return {"count": 0, "avg": float("nan"), "win": float("nan")}
    return {"count": len(s), "avg": s.mean(), "win": (s > 0).mean()}


def print_ab(df, ticker):
    tiers = ["STRONG ENTRY", "CAUTION", "SHORT-TERM ONLY", "LEAPS ONLY", "STAY OUT"]
    for ret_col, label in [("fwd_return", "15d"), ("fwd_return_126d", "6mo")]:
        print(f"\n{'─'*86}")
        print(f"  CONFIDENCE BAND A/B — {ticker}  ({label} forward returns; band: "
              f"{P2_THRESHOLD} <= p < {BAND_CAP})")
        print(f"{'─'*86}")
        print(f"  {'Signal':<16} {'Cnt base':>9} {'Cnt band':>9} {'Avg base':>9} "
              f"{'Avg band':>9} {'Δ Avg':>8} {'Win base':>9} {'Win band':>9}")
        print(f"  {'─'*84}")
        for tier in tiers:
            b = tier_stats(df, "signal_base", tier, ret_col)
            n = tier_stats(df, "signal_band", tier, ret_col)
            delta = (n["avg"] - b["avg"]) if (b["count"] and n["count"]) else float("nan")
            print(f"  {tier:<16} {b['count']:>9} {n['count']:>9} {b['avg']:>9.1%} "
                  f"{n['avg']:>9.1%} {delta:>+8.2%} {b['win']:>9.1%} {n['win']:>9.1%}")

    # The removed cohort: would-be STRONG ENTRY days vetoed by the band
    removed = df[(df["signal_base"] == "STRONG ENTRY") & (df["signal_band"] != "STRONG ENTRY")]
    print(f"\n  REMOVED COHORT (STRONG ENTRY days with dir_prob >= {BAND_CAP}): {len(removed)}")
    if len(removed):
        r15  = removed["fwd_return"].dropna()
        r126 = removed["fwd_return_126d"].dropna()
        print(f"    15d: avg {r15.mean():+.1%}  win {(r15 > 0).mean():.1%}  (n={len(r15)})")
        print(f"    6mo: avg {r126.mean():+.1%}  win {(r126 > 0).mean():.1%}  (n={len(r126)})")
        print(f"    -> banded into: {removed['signal_band'].value_counts().to_dict()}")

    # Hierarchy on the banded arm (15d): STRONG > CAUTION > STAY OUT
    s = tier_stats(df, "signal_band", "STRONG ENTRY", "fwd_return")["avg"]
    c = tier_stats(df, "signal_band", "CAUTION", "fwd_return")["avg"]
    o = tier_stats(df, "signal_band", "STAY OUT", "fwd_return")["avg"]
    ok = (s > c) and (c > o)
    print(f"\n  Banded hierarchy (15d): STRONG {s:.2%} > CAUTION {c:.2%} > STAY OUT {o:.2%}"
          f"  -> {'INTACT' if ok else 'BROKEN'}")

    b6 = tier_stats(df, "signal_base", "STRONG ENTRY", "fwd_return_126d")["avg"]
    n6 = tier_stats(df, "signal_band", "STRONG ENTRY", "fwd_return_126d")["avg"]
    print(f"  STRONG ENTRY 6mo: base {b6:.1%} -> band {n6:.1%}  (Δ {n6 - b6:+.2%})")
    print(f"  Pre-registered: {PREDICTIONS.get(ticker, 'no prediction registered')}")
    print(f"{'─'*86}\n")


if __name__ == "__main__":
    while True:
        try:
            ticker = input("  Ticker [XYZ]: ").strip().upper()
            if ticker:
                break
        except KeyboardInterrupt:
            print()
            sys.exit(0)

    path = os.path.join(DATA_DIR, f"{ticker.lower()}_backtest_results.csv")
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    except FileNotFoundError:
        print(f"  ERROR: {path} not found — run backtest.py for {ticker} first.")
        sys.exit(1)

    needed = {"dir_prob", "dir_prob_63", "exp_prob", "signal", "fwd_return", "fwd_return_126d"}
    missing = needed - set(df.columns)
    if missing:
        print(f"  ERROR: {path} missing columns {missing}")
        sys.exit(1)

    df = recompute_signals(df)

    # Sanity: recomputed baseline must reproduce the stored signal column —
    # guards against a CSV produced under different thresholds (e.g. --calibrate).
    mismatch = (df["signal_base"] != df["signal"]).sum()
    print(f"\n  Loaded {len(df)} rows from {path}")
    print(f"  Baseline reproduction check: {mismatch} mismatches vs stored 'signal' column")
    if mismatch > 0.01 * len(df):
        print("  ERROR: stored signals don't reproduce under RAW thresholds — "
              "CSV may be from a --calibrate run. Aborting.")
        sys.exit(1)

    print_ab(df, ticker)
