"""
Options Trading — Phase 4: Exit Signal (Drawdown Forecast)
==========================================================
Predicts whether the underlying will experience a vol-adjusted drawdown
within the next N trading days. Complements Phase 2/2B (entry direction)
and Phase 3 (IV regime) with a thesis-break warning for held positions.

Target: max adverse excursion (peak-to-trough drawdown) over the next N
days <= -(P4_VOL_MULTIPLE × median_HV × sqrt(N/252)).

Trains three candidate windows (5d tactical / 15d symmetric / 63d
strategic) on the same feature set and reports which produces the
cleanest precision tail per ticker — per the project's cross-ticker
validation rule, ship the winner per-ticker, not framework-wide, unless
QQQ + NVDA agree.

Features (in addition to the standard Phase 2/3 set):
  - Trend-vulnerability features from modules.features.add_trend_break_features
    (above_ma20/50, dist_above_ma20/50_pct, ma20/50_slope_5d,
     days_above_ma20/50). All backward-looking — no lookahead.

Requirements:
    pip install yfinance pandas scikit-learn matplotlib
"""

import argparse
import os
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, precision_score

from modules.benchmarks import (
    detect_benchmarks, detect_macro_features, add_macro_features, add_catalyst_proximity,
)
from modules.econ_calendar import add_macro_event_proximity
from modules.massive import IV_COLS
from modules.features import (
    HV_WINDOW, IV_RANK_WINDOW,
    P4_FORWARD_DAYS_LIST, P4_VOL_MULTIPLE,
    compute_hv_features, add_trend_break_features,
    compute_p4_drawdown_threshold, add_p4_drawdown_target,
    add_vix, add_benchmarks, add_earnings_proximity, normalize_features,
)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
TICKER         = ""
START_DATE     = "1792-05-17"
END_DATE       = ""  # set automatically from CSV
DATA_DIR       = "data"
MODULE_DIR     = "modules"

TEST_SIZE          = 0.20
DECISION_THRESHOLD = 0.55
RANDOM_STATE       = 42
ECON_FEATURES      = False  # set by --econ-features CLI arg; when True, Days_to_FOMC/CPI/... added


# ─────────────────────────────────────────
# 1. LOAD BASE INDICATORS
# ─────────────────────────────────────────
def load_indicators(path):
    global TICKER, START_DATE, END_DATE
    print(f"Loading indicators from {path}...")
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    except FileNotFoundError:
        print(f"  ERROR: File not found -> {path}")
        sys.exit(1)
    df = df.sort_index()
    if "Adj Close" in df.columns:
        df.drop(columns=["Adj Close"], inplace=True)
    if "Ticker" in df.columns:
        TICKER = df["Ticker"].iloc[0]
        df.drop(columns=["Ticker"], inplace=True)
    START_DATE = df.index.min().strftime("%Y-%m-%d")
    END_DATE   = df.index.max().strftime("%Y-%m-%d")
    print(f"  → Ticker: {TICKER} | {START_DATE} to {END_DATE}")
    print(f"  → {len(df)} rows, {len(df.columns)} columns\n")
    return df


# Target construction lives in modules.features:
#   compute_p4_drawdown_threshold(df, forward_days) — vol-adjusted threshold
#   add_p4_drawdown_target(df, forward_days, threshold, target_col="target") — apply + truncate


# ─────────────────────────────────────────
# 3. TRAIN / EVALUATE
# ─────────────────────────────────────────
def train(df, forward_days):
    exclude = {"Open", "High", "Low", "Close", "Volume", "target", *IV_COLS}
    feature_cols = [c for c in df.columns if c not in exclude and pd.api.types.is_numeric_dtype(df[c])]

    df_model = df[feature_cols + ["target"]].dropna()
    if df_model.empty:
        print(f"  ✗ No usable rows after dropna for {forward_days}d window — skipping")
        return None

    X = df_model[feature_cols]
    y = df_model["target"]

    split_idx = int(len(X) * (1 - TEST_SIZE))
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    print(f"  Train: {len(X_train)} rows ({X_train.index[0].date()} → {X_train.index[-1].date()})")
    print(f"  Test:  {len(X_test)} rows ({X_test.index[0].date()} → {X_test.index[-1].date()})")

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    clf = LogisticRegression(
        C=0.1, class_weight="balanced", max_iter=1000, random_state=RANDOM_STATE,
    )
    clf.fit(X_train_s, y_train)

    y_prob = clf.predict_proba(X_test_s)[:, 1]
    y_pred = (y_prob >= DECISION_THRESHOLD).astype(int)

    test_base = y_test.mean()
    test_prec = precision_score(y_test, y_pred, zero_division=0)

    print(f"\n  Classification report ({forward_days}d window, threshold={DECISION_THRESHOLD}):")
    print(classification_report(
        y_test, y_pred, target_names=["NoExit", "Exit"], zero_division=0,
    ))

    # Threshold sweep — same heuristic as Phase 2/3: max (prec - base) × log(signals)
    print(f"  Threshold sweep (test base = {test_base:.1%})")
    print(f"  {'Conf':>6}  {'Prec':>7}  {'Recall':>8}  {'F1':>6}  {'Signals':>8}  {'Edge':>7}")
    print("  " + "─" * 50)
    rows = []
    for t in [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        yp = (y_prob >= t).astype(int)
        tp = ((yp == 1) & (y_test == 1)).sum()
        fp = ((yp == 1) & (y_test == 0)).sum()
        fn = ((yp == 0) & (y_test == 1)).sum()
        prec   = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1     = 2 * prec * recall / (prec + recall) if (prec + recall) > 0 else 0
        signals = int(yp.sum())
        rows.append((t, prec, recall, f1, signals))

    best = max(rows, key=lambda r: (r[1] - test_base) * np.log(r[4] + 1) if r[1] > test_base else 0)
    for t, prec, recall, f1, signals in rows:
        marker = " ◄ optimal" if t == best[0] else ""
        print(f"  {t:>6.2f}  {prec:>7.1%}  {recall:>8.1%}  {f1:>6.3f}  {signals:>8}  {prec - test_base:>+6.1%}{marker}")

    # Top coefficients
    coefs = pd.Series(clf.coef_[0], index=feature_cols).sort_values(key=abs, ascending=False)
    print(f"\n  Top 10 coefficients ({forward_days}d):")
    for feat, val in coefs.head(10).items():
        direction = "exit ↑" if val > 0 else "no-exit ↓"
        print(f"    {feat:<30} {val:>+8.4f}  {direction}")

    edge = test_prec - test_base
    return {
        "forward_days":  forward_days,
        "base_rate":     test_base,
        "precision":     test_prec,
        "edge":          edge,
        "signal_count":  int(y_pred.sum()),
        "test_size":     len(y_test),
        "sweep_rows":    rows,
        "best_threshold": best[0],
        "best_precision": best[1],
        "best_signals":   best[4],
        "feature_cols":  feature_cols,
        "clf":           clf,
        "scaler":        scaler,
    }


# ─────────────────────────────────────────
# 4. PLOT — 3-panel comparison
# ─────────────────────────────────────────
def plot_results(results, df_full):
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), facecolor="#0d1117")
    fig.suptitle(f"{TICKER} Phase 4 — Exit Signal (Drawdown Forecast)",
                 color="white", fontsize=13)

    for ax, res in zip(axes, results):
        ax.set_facecolor("#0d1117")
        if res is None:
            ax.set_title("(skipped)", color="white")
            continue

        # Coefficient bar chart, top 12 by abs magnitude
        coefs = pd.Series(res["clf"].coef_[0], index=res["feature_cols"])
        top = coefs.abs().sort_values().tail(12).index
        coefs_top = coefs[top]
        colors = ["#f85149" if v > 0 else "#3fb950" for v in coefs_top]
        coefs_top.plot(kind="barh", ax=ax, color=colors)
        ax.axvline(0, color="#8b949e", lw=0.8)
        ax.set_title(
            f"{res['forward_days']}d window\n"
            f"base {res['base_rate']:.1%}  prec {res['precision']:.1%}  edge {res['edge']:+.1f}pp",
            color="white", pad=8, fontsize=10,
        )
        ax.tick_params(colors="#8b949e", labelsize=7)
        ax.spines[:].set_color("#30363d")

    plt.tight_layout()
    out = os.path.join(DATA_DIR, f"{TICKER.lower()}_exit_results.png")
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor="#0d1117")
    print(f"\nResults chart saved -> {out}")
    plt.show()


# ─────────────────────────────────────────
# 5. SUMMARY TABLE
# ─────────────────────────────────────────
def print_summary(results):
    print()
    print("═" * 72)
    print(f"  Phase 4 SUMMARY — {TICKER}  (DECISION_THRESHOLD={DECISION_THRESHOLD})")
    print("═" * 72)
    print(f"  {'Window':>8}  {'Base':>7}  {'Prec':>7}  {'Edge':>7}  {'Signals':>8}  {'Best τ':>7}  {'Best Prec':>10}")
    print("  " + "─" * 68)
    best_overall = None
    for res in results:
        if res is None:
            continue
        edge_pp = (res["edge"]) * 100
        line = (f"  {res['forward_days']:>6}d   {res['base_rate']:>7.1%}  {res['precision']:>7.1%}  "
                f"{res['edge']:>+6.1%}  {res['signal_count']:>8}  {res['best_threshold']:>7.2f}  {res['best_precision']:>10.1%}")
        print(line)
        if best_overall is None or res["edge"] > best_overall["edge"]:
            best_overall = res
    print("═" * 72)
    if best_overall is not None:
        print(f"  Winner: {best_overall['forward_days']}d window — edge {best_overall['edge']:+.1%}, "
              f"{best_overall['signal_count']} signals on {best_overall['test_size']}-day test set")
        print(f"  Per project rule: validate on QQQ + NVDA before adopting as production default.")
    print()


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 4 exit signal — drawdown forecast across 3 forward windows.")
    parser.add_argument(
        "--econ-features", action=argparse.BooleanOptionalAction, default=False,
        dest="econ_features",
        help="Include macro-release proximity features (Days_to_FOMC, Days_to_CPI, ...) "
             "from data/econ_calendar.csv. Default OFF. "
             "Requires `python -m modules.econ_calendar --refresh` to have been run.",
    )
    args = parser.parse_args()
    ECON_FEATURES = args.econ_features

    print("═" * 64)
    print(f"  Phase 4 — Exit Signal (Drawdown Forecast)")
    print(f"  Forward windows: {P4_FORWARD_DAYS_LIST}  |  P4_VOL_MULTIPLE = {P4_VOL_MULTIPLE}")
    print("═" * 64)
    print()

    while True:
        try:
            ticker_in = input("  Ticker [XYZ]: ").strip().upper()
            if ticker_in:
                TICKER         = ticker_in
                INDICATORS_CSV = os.path.join(DATA_DIR, f"{TICKER.lower()}_indicators.csv")
                break
        except KeyboardInterrupt:
            print()
            sys.exit(0)

    df = load_indicators(INDICATORS_CSV)

    print(f"  Detecting benchmarks for {TICKER}...")
    benchmarks = detect_benchmarks(TICKER)
    for bt, bn in benchmarks:
        print(f"    {bn} ({bt})")
    default_str = ",".join(bt for bt, bn in benchmarks)
    override = input(f"  Benchmarks [{default_str}]: ").strip().upper()
    if override:
        benchmarks = [(t.strip(), t.strip().lstrip("^")) for t in override.split(",")]
    print()

    print("Building features...")
    df = compute_hv_features(df)
    print("  ✓ HV_20, IV_rank, IV_pct, HV_chg_5d, HV_chg_10d, HV_vs_ma20")
    df = add_trend_break_features(df)
    df = add_vix(df, START_DATE, END_DATE)
    df = add_benchmarks(df, benchmarks, START_DATE, END_DATE)
    macro = detect_macro_features(TICKER)
    if macro:
        print("  Macro features:")
        df = add_macro_features(df, macro, START_DATE, END_DATE)
    df = add_earnings_proximity(df, TICKER)
    df = add_catalyst_proximity(df, TICKER, MODULE_DIR, for_direction=True)
    if ECON_FEATURES:
        df = add_macro_event_proximity(df, DATA_DIR)
    df = normalize_features(df)

    # Save feature dataset (pre-target-truncation) — single CSV shared across windows.
    out_csv = os.path.join(DATA_DIR, f"{TICKER.lower()}_exit_features.csv")
    df.to_csv(out_csv)
    print(f"\nFeature dataset saved -> {out_csv}")

    # Loop over candidate windows: 5d / 15d / 63d
    results = []
    for n in P4_FORWARD_DAYS_LIST:
        drawdown_threshold = compute_p4_drawdown_threshold(df, n)
        df_target = add_p4_drawdown_target(df, n, drawdown_threshold, target_col="target")
        print(f"\nPhase 4 target ({n}d window)")
        print(f"  Drawdown threshold:  {drawdown_threshold:.2%}")
        print(f"  Base rate:           {df_target['target'].mean():.1%}  ({int(df_target['target'].sum())} hits / {len(df_target)} samples)")
        print()
        print("─" * 64)
        print(f"  TRAINING — {n}-day forward window")
        print("─" * 64)
        res = train(df_target, n)
        results.append(res)

    print_summary(results)
    plot_results(results, df)
