"""
Probability-Decile Analysis
===========================
Sorts STRONG ENTRY signals by Phase 2 (15d direction) probability and reports
return / win-rate within probability buckets. Tests whether edge concentrates in
the high-confidence tail (the framework's working hypothesis from S11/S20/S21).

Pure analysis on existing data/{ticker}_backtest_results.csv — no model change,
no re-train. Backtest must have been run for the ticker first.

Usage:
    python probability_deciles.py             # prompts for ticker
    python probability_deciles.py NVDA QQQ    # batch mode

Output:
    Console table per ticker showing count / 15d avg / 15d win% / 6mo avg / 6mo win%
    per probability bucket. Buckets: [0.55,0.60), [0.60,0.65), [0.65,0.70),
    [0.70,0.75), [0.75,1.00].
"""

import os
import sys
import pandas as pd

DATA_DIR = "data"
BUCKETS = [(0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.75), (0.75, 1.01)]


def analyze(ticker, signal_label="STRONG ENTRY"):
    path = os.path.join(DATA_DIR, f"{ticker.lower()}_backtest_results.csv")
    if not os.path.exists(path):
        print(f"  ERROR: {path} not found — run `python backtest.py` for {ticker} first")
        return

    df = pd.read_csv(path)
    rows = df[df["signal"] == signal_label].copy()
    if len(rows) == 0:
        print(f"  No {signal_label} signals in {path}")
        return

    has_126d = "fwd_return_126d" in rows.columns
    n_total  = len(rows)
    avg_15d  = rows["fwd_return"].dropna().mean()
    win_15d  = (rows["fwd_return"].dropna() > 0).mean()

    print()
    print("=" * 80)
    print(f"  {ticker} — {signal_label} by Phase 2 (15d direction) probability decile")
    print(f"  Total signals: {n_total}  |  Overall 15d avg {avg_15d:+.1%}  |  win {win_15d:.0%}")
    if has_126d:
        avg_126 = rows["fwd_return_126d"].dropna().mean()
        win_126 = (rows["fwd_return_126d"].dropna() > 0).mean()
        print(f"                                Overall 6mo avg {avg_126:+.1%}  |  win {win_126:.0%}")
    print("=" * 80)

    header = f"  {'Bucket':<14}{'Count':>7}  {'15d Avg':>8}  {'15d Win':>8}"
    if has_126d:
        header += f"  {'6mo Avg':>8}  {'6mo Win':>8}"
    print(header)
    print("-" * 80)

    for lo, hi in BUCKETS:
        bucket = rows[(rows["dir_prob"] >= lo) & (rows["dir_prob"] < hi)]
        n = len(bucket)
        if n == 0:
            label = f"  {lo:.2f}-{hi:.2f}    "
            print(f"{label}{n:>7}        --        --")
            continue
        s15  = bucket["fwd_return"].dropna()
        avg  = s15.mean()      if len(s15) else float("nan")
        win  = (s15 > 0).mean() if len(s15) else float("nan")
        line = f"  {lo:.2f}-{hi:.2f}    {n:>7}  {avg:>+8.1%}  {win:>8.0%}"
        if has_126d:
            s126 = bucket["fwd_return_126d"].dropna()
            avg6 = s126.mean()      if len(s126) else float("nan")
            win6 = (s126 > 0).mean() if len(s126) else float("nan")
            line += f"  {avg6:>+8.1%}  {win6:>8.0%}" if len(s126) else f"        --        --"
        print(line)

    print("=" * 80)

    # Tail-vs-base summary
    tail = rows[rows["dir_prob"] >= 0.70]
    base = rows[rows["dir_prob"] < 0.65]
    if len(tail) and len(base):
        t_avg = tail["fwd_return"].dropna().mean()
        b_avg = base["fwd_return"].dropna().mean()
        print(f"  Tail (prob ≥ 0.70) vs base (prob < 0.65): "
              f"{t_avg:+.1%} vs {b_avg:+.1%}  (Δ {t_avg - b_avg:+.1%} on 15d)")
        if has_126d:
            t6 = tail["fwd_return_126d"].dropna().mean()
            b6 = base["fwd_return_126d"].dropna().mean()
            print(f"                                              "
                  f"{t6:+.1%} vs {b6:+.1%}  (Δ {t6 - b6:+.1%} on 6mo)")


if __name__ == "__main__":
    tickers = [t.upper() for t in sys.argv[1:]]
    if not tickers:
        try:
            t = input("  Ticker [XYZ]: ").strip().upper()
            if t:
                tickers = [t]
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)
    for t in tickers:
        analyze(t)
