"""
AMD Options Trading — Phase 2: ML Feature Engineering & Classification
=======================================================================
Loads amd_indicators.csv (Phase 1 output) and builds an ML pipeline to
identify high-probability entry points for AMD 6-12 month call options.

New features added:
  - HV_20: 20-day historical (realized) volatility, annualized
  - VIX level, 5-day change, distance from 20-day MA
  - Sector/industry benchmark relative strength over 5 and 20 days
  - Days to next earnings

Target: Binary — AMD closes >= 5% higher 15 trading days from signal date

Requirements:
    pip install yfinance pandas scikit-learn matplotlib
"""

import argparse
import os
import sys
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import classification_report, confusion_matrix, ConfusionMatrixDisplay, brier_score_loss
from modules.benchmarks import detect_benchmarks, detect_macro_features, add_macro_features, add_catalyst_proximity
from modules.econ_calendar import add_macro_event_proximity
from modules.massive import IV_COLS
from modules.features import (
    HV_WINDOW, IV_RANK_WINDOW,
    P2_FORWARD_DAYS, P2B_FORWARD_DAYS, P2_VOL_MULTIPLE,
    compute_hv_features, compute_vix_features, add_vix, add_benchmarks,
    add_earnings_proximity, normalize_features, compute_vol_thresholds,
)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
# HV_WINDOW, P2_FORWARD_DAYS, P2B_FORWARD_DAYS, P2_VOL_MULTIPLE imported from modules.features
FORWARD_DAYS    = P2_FORWARD_DAYS   # 15-day direction window
FORWARD_DAYS_63 = P2B_FORWARD_DAYS  # 63-day direction window
START_DATE     = "1792-05-17"
END_DATE       = ""  # set automatically from CSV
DATA_DIR       = "data"
MODULE_DIR     = "modules"
# INDICATORS_CSV = os.path.join(DATA_DIR, f"{TICKER.lower()}_indicators.csv")

WIN_THRESHOLD    = 0.05  # Default (AMD). Set by compute_vol_thresholds() in __main__
WIN_THRESHOLD_63 = 0.10  # Default (AMD). Set by compute_vol_thresholds() in __main__
TEST_SIZE      = 0.20   # Fraction of data held out as test set (time-based)
DECISION_THRESHOLD = 0.55   # Probability cutoff for predicting Win (lower = more wins predicted)
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


# ─────────────────────────────────────────
# 2. FEATURE ENGINEERING
# ─────────────────────────────────────────
def add_hv(df):
    df = compute_hv_features(df)
    print("  \u2713 HV_20, IV_rank, IV_pct, HV_chg_5d, HV_chg_10d, HV_vs_ma20")
    return df



# add_earnings_proximity imported from modules.features (call: add_earnings_proximity(df, TICKER))
# normalize_features  imported from modules.features


# ─────────────────────────────────────────
# 4. TARGET VARIABLE
# ─────────────────────────────────────────
def add_target(df):
    future_close = df["Close"].shift(-FORWARD_DAYS)
    df["target"] = ((future_close / df["Close"] - 1) >= WIN_THRESHOLD).astype(int)
    df = df.iloc[:-FORWARD_DAYS]  # last N rows have no forward close to label
    win_rate = df["target"].mean()
    print(f"\nTarget: {FORWARD_DAYS}d forward ≥ {WIN_THRESHOLD*100:.0f}% gain = win")
    print(f"  → Win rate: {win_rate:.1%}  ({df['target'].sum()} wins / {len(df)} samples)\n")
    return df


# ─────────────────────────────────────────
# 5. TRAIN / EVALUATE
# ─────────────────────────────────────────
def print_calibration_diagnostic(y_true, y_prob, label):
    """Print Brier score, ECE, and reliability bins for predicted probabilities."""
    y_true = np.asarray(y_true)
    y_prob = np.asarray(y_prob)
    brier = brier_score_loss(y_true, y_prob)

    n_bins = 10
    edges = np.linspace(0, 1, n_bins + 1)
    bin_idx = np.clip(np.digitize(y_prob, edges) - 1, 0, n_bins - 1)

    ece = 0.0
    rows = []
    for i in range(n_bins):
        mask = bin_idx == i
        n = int(mask.sum())
        if n == 0:
            continue
        pred = y_prob[mask].mean()
        actual = y_true[mask].mean()
        gap = pred - actual
        ece += abs(gap) * n / len(y_prob)
        rows.append((edges[i], edges[i+1], n, pred, actual, gap))

    print(f"\n[{label}]")
    print(f"  Brier: {brier:.4f}  ECE: {ece:.4f}  (lower=better; 0=perfect)")
    print(f"  {'Bin':<11}  {'N':>5}  {'Pred':>7}  {'Actual':>7}  {'Gap':>8}")
    for lo, hi, n, pred, actual, gap in rows:
        marker = " over" if gap > 0.05 else " under" if gap < -0.05 else ""
        print(f"  {lo:.1f}-{hi:.1f}      {n:>5}  {pred:>7.1%}  {actual:>7.1%}  {gap:>+8.1%}{marker}")


def train_model(df, calibrate=False, decision_threshold=DECISION_THRESHOLD, forward_days=0):
    # forward_days: embargo width at the train/test boundary. Targets are built with
    # shift(-N) on the full frame, so the last N training rows have labels computed
    # from test-period prices — drop them so no label's forward window crosses the split.
    exclude = {"Open", "High", "Low", "Close", "Volume", "target", *IV_COLS}
    feature_cols = [c for c in df.columns if c not in exclude]

    df_model = df[feature_cols + ["target"]].dropna()
    X = df_model[feature_cols]
    y = df_model["target"]

    split_idx = int(len(X) * (1 - TEST_SIZE))
    embargo   = max(0, split_idx - forward_days)
    X_train, X_test = X.iloc[:embargo], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:embargo], y.iloc[split_idx:]

    print(f"Train: {len(X_train)} rows  |  Test: {len(X_test)} rows")
    print(f"Test period: {X_test.index[0].date()} → {X_test.index[-1].date()}\n")

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    raw_clf = LogisticRegression(
        C=0.1,                  # regularization strength (lower = more regularized)
        class_weight="balanced",
        max_iter=1000,
        random_state=RANDOM_STATE,
    )
    raw_clf.fit(X_train_s, y_train)

    if calibrate:
        clf = CalibratedClassifierCV(
            LogisticRegression(C=0.1, class_weight="balanced",
                               max_iter=1000, random_state=RANDOM_STATE),
            method="isotonic",
            cv=5,
        )
        clf.fit(X_train_s, y_train)
        # Average base-estimator coefs onto the wrapper so downstream code that
        # reads clf.coef_ (top-coefficients print, entry.py contributors) works unchanged.
        clf.coef_ = np.mean(
            [cc.estimator.coef_ for cc in clf.calibrated_classifiers_], axis=0
        )
    else:
        clf = raw_clf

    y_prob_train = clf.predict_proba(X_train_s)[:, 1]
    y_pred_train = (y_prob_train >= decision_threshold).astype(int)
    y_prob = clf.predict_proba(X_test_s)[:, 1]
    y_pred = (y_prob >= decision_threshold).astype(int)

    train_base = y_train.mean()
    test_base  = y_test.mean()
    from sklearn.metrics import precision_score
    train_prec = precision_score(y_train, y_pred_train, zero_division=0)
    test_prec  = precision_score(y_test,  y_pred,       zero_division=0)
    print(f"Base rate  — train: {train_base:.1%}  |  test: {test_base:.1%}")
    print(f"Accuracy   — train: {(y_pred_train == y_train).mean():.1%}  |  test: {(y_pred == y_test).mean():.1%}\n\n"
          f"Precision  — train: {train_prec:.1%}  |  test: {test_prec:.1%}  (when model says WIN, how often correct) ***\n")

    print("─" * 50)
    print(f"CLASSIFICATION REPORT (test set, threshold={decision_threshold})")
    print("─" * 50)
    print(classification_report(y_test, y_pred, target_names=["Loss", "Win"], zero_division=0))

    # Threshold sweep — shows precision/recall tradeoff across candidate cutoffs
    print("─" * 60)
    print(f"THRESHOLD SWEEP  (base win rate: {y_test.mean():.1%})")
    print(f"{'Confidence':>10}  {'Win Prec':>9}  {'Win Recall':>10}  {'Win F1':>7}  {'Signals':>8}")
    print("─" * 60)
    thresholds = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
    rows = []
    for t in thresholds:
        yp = (y_prob >= t).astype(int)
        tp = ((yp == 1) & (y_test == 1)).sum()
        fp = ((yp == 1) & (y_test == 0)).sum()
        fn = ((yp == 0) & (y_test == 1)).sum()
        prec   = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1     = 2 * prec * recall / (prec + recall) if (prec + recall) > 0 else 0
        rows.append((t, prec, recall, f1, int(yp.sum())))

    base_rate = y_test.mean()
    best_threshold = max(
        rows,
        key=lambda r: (r[1] - base_rate) * np.log(r[4] + 1) if r[1] > base_rate else 0
    )[0]
    for t, prec, recall, f1, signals in rows:
        marker = "  ◄ optimal" if t == best_threshold else ""
        print(f"{t:>10.2f}  {prec:>9.1%}  {recall:>10.1%}  {f1:>7.3f}  {signals:>8}{marker}")
    print("─" * 60)

    # Top coefficients
    coefs = pd.Series(clf.coef_[0], index=feature_cols).sort_values(key=abs, ascending=False)
    print(f"\nTOP 10 COEFFICIENTS")
    print(f"{'Feature':<25}  {'Coefficient':>12}  Direction")
    print("─" * 50)
    for feat, val in coefs.head(10).items():
        direction = "bullish ↑" if val > 0 else "bearish ↓"
        print(f"{feat:<25}  {val:>12.4f}  {direction}")
    print()

    # Calibration diagnostic — compare raw LR vs isotonic-calibrated wrapper.
    # When calibrate=True the calibrated path is the production model; the
    # diagnostic still prints both for ECE drift monitoring.
    print("─" * 60)
    print("CALIBRATION DIAGNOSTIC (test set)")
    print("─" * 60)
    raw_y_prob = raw_clf.predict_proba(X_test_s)[:, 1]
    print_calibration_diagnostic(y_test, raw_y_prob, "Raw Logistic Regression")
    if calibrate:
        calibrated = clf  # reuse the production calibrated model
    else:
        calibrated = CalibratedClassifierCV(
            LogisticRegression(C=0.1, class_weight="balanced", max_iter=1000, random_state=RANDOM_STATE),
            method="isotonic",
            cv=5,
        )
        calibrated.fit(X_train_s, y_train)
    y_prob_cal = calibrated.predict_proba(X_test_s)[:, 1]
    print_calibration_diagnostic(y_test, y_prob_cal, "Calibrated (Isotonic, 5-fold CV)")
    print("─" * 60)
    print()

    return clf, X_test, y_test, y_pred, y_prob, feature_cols


# ─────────────────────────────────────────
# 6. PLOT RESULTS
# ─────────────────────────────────────────
def plot_results(clf, X_test, y_test, y_pred, feature_cols):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), facecolor="#0d1117")
    fig.suptitle(f"{TICKER} ML Phase 2 — Logistic Regression Results", color="white", fontsize=13)

    # Confusion matrix
    ax1 = axes[0]
    ax1.set_facecolor("#161b22")
    cm = confusion_matrix(y_test, y_pred)
    disp = ConfusionMatrixDisplay(cm, display_labels=["Loss", "Win"])
    disp.plot(ax=ax1, colorbar=False, cmap="Blues")
    ax1.set_title("Confusion Matrix", color="white", pad=10)
    for label in ax1.get_xticklabels() + ax1.get_yticklabels():
        label.set_color("white")
    ax1.xaxis.label.set_color("white")
    ax1.yaxis.label.set_color("white")
    ax1.spines[:].set_color("#30363d")

    # Logistic regression coefficients — top 15 by absolute magnitude
    ax2 = axes[1]
    ax2.set_facecolor("#0d1117")
    coefs = pd.Series(clf.coef_[0], index=feature_cols)
    top15 = coefs.abs().sort_values().tail(15).index
    coefs_top = coefs[top15]
    colors = ["#3fb950" if v > 0 else "#f85149" for v in coefs_top]
    coefs_top.plot(kind="barh", ax=ax2, color=colors)
    ax2.axvline(0, color="#8b949e", lw=0.8)
    ax2.set_title("Feature Coefficients — green=bullish, red=bearish", color="white", pad=10)
    ax2.tick_params(colors="#8b949e")
    ax2.spines[:].set_color("#30363d")
    ax2.set_facecolor("#0d1117")
    ax2.xaxis.label.set_color("#8b949e")

    plt.tight_layout()
    plt.savefig(os.path.join(DATA_DIR, f"{TICKER.lower()}_ml_results.png"), dpi=150,
                bbox_inches="tight", facecolor="#0d1117")
    print(f"Results chart saved -> {os.path.join(DATA_DIR, f'{TICKER.lower()}_ml_results.png')}")
    plt.show()


# compute_vol_thresholds imported from modules.features


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 2 direction model — train + diagnose.")
    parser.add_argument(
        "--calibrate", action=argparse.BooleanOptionalAction, default=False,
        help="Use isotonic-calibrated Phase 2 (Decision 1, S11). Default OFF (NVDA regression: STRONG ENTRY 4.4% → -0.4%). Pass --calibrate to enable.",
    )
    parser.add_argument(
        "--econ-features", action=argparse.BooleanOptionalAction, default=False,
        dest="econ_features",
        help="Include macro-release proximity features (Days_to_FOMC, Days_to_CPI, ...) "
             "from data/econ_calendar.csv. Default OFF. "
             "Requires `python -m modules.econ_calendar --refresh` to have been run.",
    )
    args = parser.parse_args()
    P2_CALIBRATE  = args.calibrate
    ECON_FEATURES = args.econ_features
    P2_THRESHOLD  = 0.50 if P2_CALIBRATE else 0.55

    mode_label = "CALIBRATED  (Decision 1 — isotonic, 5-fold CV)" if P2_CALIBRATE else "RAW  (Decision 1 disabled — class_weight=balanced)"
    print("═" * 64)
    print(f"  Phase 2 mode: {mode_label}")
    print(f"  P2_THRESHOLD = {P2_THRESHOLD}")
    print("═" * 64)
    print()

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

    df = load_indicators(INDICATORS_CSV)
    WIN_THRESHOLD, WIN_THRESHOLD_63, _ = compute_vol_thresholds(df)

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
    df = add_hv(df)
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

    # Phase 2 — 15-day direction model (mode set via CLI flag — see banner)
    df_15 = add_target(df.copy())
    clf, X_test, y_test, y_pred, y_prob, feature_cols = train_model(
        df_15, calibrate=P2_CALIBRATE, decision_threshold=P2_THRESHOLD,
        forward_days=FORWARD_DAYS,
    )
    plot_results(clf, X_test, y_test, y_pred, feature_cols)

    # Phase 2B — 63-day direction model
    df_63 = df.copy()
    future_close_63 = df_63["Close"].shift(-FORWARD_DAYS_63)
    df_63["target"] = ((future_close_63 / df_63["Close"] - 1) >= WIN_THRESHOLD_63).astype(int)
    df_63 = df_63.iloc[:-FORWARD_DAYS_63]
    win_rate_63 = df_63["target"].mean()
    print(f"\nPhase 2B — 63-day direction model")
    print(f"  Target: {FORWARD_DAYS_63}d forward ≥ {WIN_THRESHOLD_63*100:.0f}% gain = win")
    print(f"  → Win rate: {win_rate_63:.1%}  ({df_63['target'].sum()} wins / {len(df_63)} samples)")
    clf63, X_test63, y_test63, y_pred63, y_prob63, fcols63 = train_model(df_63, forward_days=FORWARD_DAYS_63)

    df_15.to_csv(os.path.join(DATA_DIR, f"{TICKER.lower()}_ml_features.csv"))
    print(f"\nEnriched feature dataset saved -> {os.path.join(DATA_DIR, f'{TICKER.lower()}_ml_features.csv')}")

    print(f"\n[Phase 2: {'CALIBRATED' if P2_CALIBRATE else 'RAW'} — P2_THRESHOLD={P2_THRESHOLD}]")
