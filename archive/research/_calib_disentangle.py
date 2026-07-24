"""
Disentangle the S11 calibration regression on NVDA (open question #1).

--calibrate flips TWO things at once (backtest.py:744):
    isotonic CalibratedClassifierCV  AND  P2_THRESHOLD 0.55 -> 0.50

This harness runs the 2x2 to decompose the documented regression:

                 threshold 0.55     threshold 0.50
    RAW (LogReg)   A (production)    D (pure threshold)
    CALIBRATED     C (pure calib)    B (documented regression)

    A->D  isolates the threshold drop
    A->C  isolates the isotonic map + 5-fold CV ensemble
    A->B  combined (the -4.8pp STRONG ENTRY regression)

Features are config-independent, so build once and reuse. run_backtest reads
P2_CALIBRATE / P2_THRESHOLD as module globals -> we set them per config.
Does NOT write nvda_backtest_results.csv (never calls plot/to_csv on prod path).
"""
import io
import os
import sys
from contextlib import redirect_stdout

import numpy as np

import backtest as bt

TICKER = sys.argv[1].upper() if len(sys.argv) > 1 else "NVDA"

bt.IV_FEATURES   = False   # HV proxy = production
bt.ECON_FEATURES = False

# 2x2 configs: (label, calibrate, threshold)
CONFIGS = [
    ("A RAW @0.55  (production)",        False, 0.55),
    ("D RAW @0.50  (pure threshold)",    False, 0.50),
    ("C CAL @0.55  (pure calibration)",  True,  0.55),
    ("B CAL @0.50  (documented regr.)",  True,  0.50),
]

HIER = ["STRONG ENTRY", "CAUTION", "SHORT-TERM ONLY", "LEAPS ONLY", "STAY OUT"]


def main():
    csv = os.path.join(bt.DATA_DIR, f"{TICKER.lower()}_indicators.csv")
    print(f"Loading {csv} + building features (once)...", flush=True)
    df = bt.load_indicators(csv)
    benchmarks = bt.detect_benchmarks(TICKER)
    print(f"  benchmarks: {[b for b, _ in benchmarks]}", flush=True)
    df_full = bt.build_features(df, benchmarks)
    print(f"  df_full: {len(df_full)} rows, {df_full.index[0].date()} -> {df_full.index[-1].date()}", flush=True)

    all_stats = {}
    all_results = {}
    for label, calib, thresh in CONFIGS:
        bt.P2_CALIBRATE = calib
        bt.P2_THRESHOLD = thresh
        print(f"\n>>> running {label}  (calibrate={calib}, P2_THRESHOLD={thresh}) ...", flush=True)
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                results = bt.run_backtest(df_full)
        except Exception:
            print(buf.getvalue()[-2000:])
            raise
        all_stats[label] = bt.collect_signal_stats(results)
        all_results[label] = results
        s = all_stats[label]["STRONG ENTRY"]
        print(f"    STRONG ENTRY: n={s['count']}  15d={s['avg_return']:+.2%}  "
              f"win={s['win_rate']:.1%}  6mo={s['avg_return_126d']:+.2%}  "
              f"win6mo={s['win_rate_126d']:.1%}", flush=True)

    # ---- STRONG ENTRY 2x2 table ----
    print("\n" + "=" * 84)
    print(f"  STRONG ENTRY across the 2x2  ({TICKER}, HV proxy)")
    print("=" * 84)
    print(f"  {'config':<34} {'n':>5} {'15d avg':>9} {'15d win':>9} {'6mo avg':>9} {'6mo win':>9}")
    print("  " + "-" * 80)
    for label, _, _ in CONFIGS:
        s = all_stats[label]["STRONG ENTRY"]
        print(f"  {label:<34} {s['count']:>5} {s['avg_return']:>+9.2%} "
              f"{s['win_rate']:>9.1%} {s['avg_return_126d']:>+9.2%} {s['win_rate_126d']:>9.1%}")

    # ---- decomposition (deltas vs A, on STRONG ENTRY) ----
    A = all_stats["A RAW @0.55  (production)"]["STRONG ENTRY"]
    D = all_stats["D RAW @0.50  (pure threshold)"]["STRONG ENTRY"]
    C = all_stats["C CAL @0.55  (pure calibration)"]["STRONG ENTRY"]
    B = all_stats["B CAL @0.50  (documented regr.)"]["STRONG ENTRY"]

    def deco(metric):
        a, d, c, b = A[metric], D[metric], C[metric], B[metric]
        thr = d - a            # pure threshold
        cal = c - a            # pure calibration
        comb = b - a           # combined (documented)
        inter = comb - thr - cal
        return a, thr, cal, comb, inter

    print("\n" + "=" * 84)
    print("  DECOMPOSITION of the regression (STRONG ENTRY, delta vs A in pp)")
    print("=" * 84)
    for metric, name in [("avg_return", "15d avg"), ("avg_return_126d", "6mo avg")]:
        a, thr, cal, comb, inter = deco(metric)
        print(f"\n  {name}:  baseline A = {a:+.2%}")
        print(f"    threshold effect   (A->D): {thr*100:+.2f} pp")
        print(f"    calibration effect (A->C): {cal*100:+.2f} pp")
        print(f"    combined           (A->B): {comb*100:+.2f} pp   <- the documented regression")
        print(f"    interaction        (resid): {inter*100:+.2f} pp")

    # ---- hierarchy check (15d AND 6mo, all 5 signals) ----
    def hierarchy(metric, horizon):
        print("\n" + "=" * 92)
        print(f"  HIERARCHY ({horizon} avg return by signal; STRONG should be top)")
        print("=" * 92)
        print(f"  {'config':<34} " + " ".join(f"{h.split()[0][:6]:>8}" for h in HIER) + f"  {'STRONG top?':>14}")
        for label, _, _ in CONFIGS:
            st = all_stats[label]
            vals = [st[h][metric] for h in HIER]
            strong_top = all((not np.isnan(vals[0])) and (np.isnan(v) or vals[0] >= v) for v in vals[1:])
            cells = " ".join(f"{v:>+8.1%}" if not np.isnan(v) else f"{'n/a':>8}" for v in vals)
            print(f"  {label:<34} {cells}  {('YES' if strong_top else 'NO -- inverted'):>14}")

    hierarchy("avg_return", "15d")
    hierarchy("avg_return_126d", "6mo")

    # ---- direct selector check: is calibration ~ a high-confidence selector? ----
    # If so, config A's top-N STRONG ENTRYs ranked by RAW dir_prob (N = C's surviving
    # count) should earn ~the same 6mo as config C, and the raw-prob buckets should
    # reproduce S23 (tail is the bad part).
    print("\n" + "=" * 92)
    print("  SELECTOR CHECK — does calibration just keep A's highest-raw-confidence signals?")
    print("=" * 92)
    rA = all_results["A RAW @0.55  (production)"]
    se = rA[rA["signal"] == "STRONG ENTRY"].dropna(subset=["dir_prob", "fwd_return_126d"]).copy()
    se = se.sort_values("dir_prob", ascending=False)
    nC   = all_stats["C CAL @0.55  (pure calibration)"]["STRONG ENTRY"]["count"]
    c6mo = all_stats["C CAL @0.55  (pure calibration)"]["STRONG ENTRY"]["avg_return_126d"]
    top = se.head(nC)
    print(f"  A STRONG ENTRY total: {len(se)}   |   C surviving count: {nC}")
    print(f"  A's top-{nC} by raw dir_prob:  mean 6mo = {top['fwd_return_126d'].mean():+.2%}"
          f"   (config C = {c6mo:+.2%})")
    print(f"  raw dir_prob range of that top set: {top['dir_prob'].min():.3f} - {top['dir_prob'].max():.3f}")
    print(f"\n  A STRONG ENTRY 6mo by RAW dir_prob bucket (reproduces S23):")
    for lo, hi in [(0.55, 0.60), (0.60, 0.70), (0.70, 0.75), (0.75, 1.01)]:
        b = se[(se["dir_prob"] >= lo) & (se["dir_prob"] < hi)]
        if len(b):
            print(f"    [{lo:.2f}, {hi:.2f}):  n={len(b):>3}   6mo={b['fwd_return_126d'].mean():+.2%}"
                  f"   15d={b['fwd_return'].mean():+.2%}")
        else:
            print(f"    [{lo:.2f}, {hi:.2f}):  n=  0")

    print()


if __name__ == "__main__":
    main()
