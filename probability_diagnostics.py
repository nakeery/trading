"""
Probability-Decile Diagnostic
=============================
For STRONG ENTRY signals on a given ticker, investigate WHY high-confidence
signals (dir_prob >= 0.70) underperform mid-confidence ones (0.60-0.65).

Tests four hypotheses against existing backtest_results.csv + indicators.csv:

  H1 — Time clustering   (year histogram of 0.75+ vs 0.60-0.65 signals)
  H2 — Walk-forward      (which retraining windows produce 0.75+ signals)
  H3 — Filter degradation (P2B and P3 prob distributions per P2 bucket)
  H4 — Mean reversion    (preceding 20d return per P2 bucket)

Usage:
    python probability_diagnostics.py NVDA
"""

import os
import sys
import pandas as pd
import numpy as np

DATA_DIR = "data"
BUCKETS = [(0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.75), (0.75, 1.01)]


def load(ticker):
    bt_path  = os.path.join(DATA_DIR, f"{ticker.lower()}_backtest_results.csv")
    ind_path = os.path.join(DATA_DIR, f"{ticker.lower()}_indicators.csv")
    if not os.path.exists(bt_path):
        print(f"  ERROR: {bt_path} not found"); sys.exit(1)
    bt  = pd.read_csv(bt_path, parse_dates=["date"]).set_index("date")
    ind = pd.read_csv(ind_path, index_col=0, parse_dates=True)
    # 20d trailing return at signal date (price action preceding the signal)
    ind["ret_20d_back"] = ind["Close"].pct_change(20)
    return bt, ind


def bucket_label(lo, hi):
    return f"{lo:.2f}-{hi:.2f}" if hi < 1.0 else f"{lo:.2f}+"


def bucketize(strong):
    """Return list of (label, subset) tuples."""
    out = []
    for lo, hi in BUCKETS:
        sub = strong[(strong["dir_prob"] >= lo) & (strong["dir_prob"] < hi)]
        out.append((bucket_label(lo, hi), sub))
    return out


def h1_time_clustering(buckets):
    print("\n" + "=" * 84)
    print("  H1 — TIME CLUSTERING: when do signals at each confidence level fire?")
    print("=" * 84)

    # Year histogram, normalized within each bucket so we can compare distributions
    years = sorted({d.year for _, sub in buckets for d in sub.index})
    print(f"  {'Year':<6}", end="")
    for label, sub in buckets:
        print(f"  {label:>10}", end="")
    print()
    print("-" * 84)
    for yr in years:
        print(f"  {yr:<6}", end="")
        for label, sub in buckets:
            n = (sub.index.year == yr).sum()
            pct = 100 * n / max(len(sub), 1)
            print(f"  {n:>4} ({pct:>3.0f}%)", end="")
        print()
    print("-" * 84)
    print(f"  {'Total':<6}", end="")
    for label, sub in buckets:
        print(f"  {len(sub):>4} (100%)", end="")
    print()


def h2_window_distribution(buckets):
    print("\n" + "=" * 84)
    print("  H2 — WALK-FORWARD WINDOW: do later windows produce more high-confidence signals?")
    print("=" * 84)
    print(f"  {'Bucket':<12}  {'mean window':>12}  {'min':>5}  {'max':>5}  {'late% (≥40)':>12}")
    print("-" * 84)
    for label, sub in buckets:
        if len(sub) == 0:
            print(f"  {label:<12}  (no signals)"); continue
        w = sub["window"]
        late_pct = 100 * (w >= 40).mean()
        print(f"  {label:<12}  {w.mean():>12.1f}  {int(w.min()):>5}  {int(w.max()):>5}  {late_pct:>11.0f}%")


def h3_filter_distributions(buckets):
    print("\n" + "=" * 84)
    print("  H3 — MULTI-PHASE FILTER: do P2B and P3 probabilities differ across P2 buckets?")
    print("  (If 0.75+ bucket has lower P2B/P3 prob means, the multi-phase AND is degrading)")
    print("=" * 84)
    print(f"  {'Bucket':<12}  {'P2B mean':>9}  {'P2B med':>9}  {'P3 mean':>9}  {'P3 med':>9}")
    print("-" * 84)
    for label, sub in buckets:
        if len(sub) == 0:
            print(f"  {label:<12}  (no signals)"); continue
        p2b_mean = sub["dir_prob_63"].mean()
        p2b_med  = sub["dir_prob_63"].median()
        p3_mean  = sub["exp_prob"].mean()
        p3_med   = sub["exp_prob"].median()
        print(f"  {label:<12}  {p2b_mean:>9.3f}  {p2b_med:>9.3f}  {p3_mean:>9.3f}  {p3_med:>9.3f}")


def h4_mean_reversion(buckets, ind):
    print("\n" + "=" * 84)
    print("  H4 — MEAN REVERSION: are high-confidence signals fired AFTER big rallies?")
    print("  (If 0.75+ has high preceding 20d returns, the model is catching peaks that revert)")
    print("=" * 84)
    print(f"  {'Bucket':<12}  {'20d-back mean':>14}  {'median':>9}  {'q25':>8}  {'q75':>8}  {'≥+10%':>7}")
    print("-" * 84)
    for label, sub in buckets:
        if len(sub) == 0:
            print(f"  {label:<12}  (no signals)"); continue
        # Join on date to get the 20d preceding return at each signal date
        joined = sub.join(ind[["ret_20d_back"]], how="left")
        r = joined["ret_20d_back"].dropna()
        if len(r) == 0:
            print(f"  {label:<12}  (no overlap with indicators data)"); continue
        big_rally_pct = 100 * (r >= 0.10).mean()
        print(f"  {label:<12}  {r.mean():>+14.1%}  {r.median():>+9.1%}  "
              f"{r.quantile(0.25):>+8.1%}  {r.quantile(0.75):>+8.1%}  {big_rally_pct:>6.0f}%")


def summary_diagnosis(buckets, ind):
    """Print a quick concluding read."""
    print("\n" + "=" * 84)
    print("  DIAGNOSTIC SUMMARY")
    print("=" * 84)

    base_label, base = "0.60-0.65", buckets[1][1]
    tail_label, tail = "0.75+",     buckets[4][1]
    if len(base) == 0 or len(tail) == 0:
        print("  Insufficient data"); return

    # H1
    base_years = base.index.year
    tail_years = tail.index.year
    drawdown_years = {2008, 2018, 2022}
    base_dd_pct = 100 * base_years.isin(drawdown_years).mean()
    tail_dd_pct = 100 * tail_years.isin(drawdown_years).mean()
    print(f"  H1 (time clustering): {tail_dd_pct:.0f}% of 0.75+ signals fired in 2008/2018/2022 vs "
          f"{base_dd_pct:.0f}% of 0.60-0.65 signals")

    # H2
    base_late_pct = 100 * (base["window"] >= 40).mean()
    tail_late_pct = 100 * (tail["window"] >= 40).mean()
    print(f"  H2 (walk-forward):    {tail_late_pct:.0f}% of 0.75+ signals from window ≥40 vs "
          f"{base_late_pct:.0f}% of 0.60-0.65 signals")

    # H3
    base_p2b = base["dir_prob_63"].mean()
    tail_p2b = tail["dir_prob_63"].mean()
    base_p3  = base["exp_prob"].mean()
    tail_p3  = tail["exp_prob"].mean()
    print(f"  H3 (filter degrade):  0.75+ mean P2B {tail_p2b:.3f} vs base {base_p2b:.3f}  "
          f"(Δ {tail_p2b - base_p2b:+.3f})")
    print(f"                         0.75+ mean P3  {tail_p3:.3f} vs base {base_p3:.3f}  "
          f"(Δ {tail_p3 - base_p3:+.3f})")

    # H4
    base_r = base.join(ind[["ret_20d_back"]], how="left")["ret_20d_back"].mean()
    tail_r = tail.join(ind[["ret_20d_back"]], how="left")["ret_20d_back"].mean()
    print(f"  H4 (mean reversion):  0.75+ mean 20d-back {tail_r:+.1%} vs base {base_r:+.1%}  "
          f"(Δ {tail_r - base_r:+.1%})")


def main(ticker):
    bt, ind = load(ticker)
    strong = bt[bt["signal"] == "STRONG ENTRY"].copy()
    print(f"\n{ticker} — {len(strong)} STRONG ENTRY signals from "
          f"{strong.index.min().date()} to {strong.index.max().date()}")

    buckets = bucketize(strong)

    h1_time_clustering(buckets)
    h2_window_distribution(buckets)
    h3_filter_distributions(buckets)
    h4_mean_reversion(buckets, ind)
    summary_diagnosis(buckets, ind)


if __name__ == "__main__":
    tickers = [t.upper() for t in sys.argv[1:]]
    if not tickers:
        try:
            t = input("  Ticker [XYZ]: ").strip().upper()
            if t: tickers = [t]
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)
    for t in tickers:
        main(t)
