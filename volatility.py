"""
Options Trading — Phase 3: IV Expansion/Contraction Forecasting
================================================================
Predicts whether historical volatility (HV, used as IV proxy) is likely
to expand or contract over the next 10 trading days.

Helps time options entries by identifying:
  - Expansion signal → buy options while IV is low and rising (cheap premium)
  - Contraction signal → wait, IV crush risk is elevated

Best entries combine Phase 2 and Phase 3:
  Phase 2: direction signal favorable (stock likely up 5%+ in 15 days)
  Phase 3: IV expansion likely (options cheap and getting more expensive)

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
from sklearn.metrics import classification_report, brier_score_loss
from modules.benchmarks import detect_macro_features, add_macro_features, add_catalyst_proximity
from modules.massive import IV_COLS, IV_META_COLS, IV_FEATURE_COLS
from modules.features import (
    HV_WINDOW, IV_RANK_WINDOW, P3_FORWARD_DAYS, P3_VOL_MULTIPLE,
    compute_hv_features, compute_vix_features, add_earnings_proximity,
    normalize_features, compute_vol_thresholds,
)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
# TICKER         = "AMD"
START_DATE     = "1792-05-17"
END_DATE       = ""  # set automatically from CSV
DATA_DIR       = "data"
MODULE_DIR     = "modules"
# INDICATORS_CSV = os.path.join(DATA_DIR, f"{TICKER.lower()}_indicators.csv")

FORWARD_DAYS        = P3_FORWARD_DAYS  # 10 — imported from modules.features
EXPANSION_THRESHOLD = 0.10  # Default (AMD). Overridden at runtime by compute_vol_thresholds()
TEST_SIZE           = 0.20
DECISION_THRESHOLD  = 0.50
RANDOM_STATE        = 42

IV_FEATURES = False  # set by --iv-features CLI arg; when True, IV_FEATURE_COLS used as features


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
# 2. IV FEATURES
# ─────────────────────────────────────────
def add_iv_features(df):
    df = compute_hv_features(df)
    print("  ✓ HV_20, IV_rank, IV_pct, HV_chg_5d, HV_chg_10d, HV_vs_ma20")
    return df


# ─────────────────────────────────────────
# 3. VIX FEATURES
# ─────────────────────────────────────────
def add_vix(df):
    vix_raw   = yf.download("^VIX",   start=START_DATE, end=END_DATE, progress=False)
    vix9d_raw = yf.download("^VIX9D", start=START_DATE, end=END_DATE, progress=False)
    vix3m_raw = yf.download("^VIX3M", start=START_DATE, end=END_DATE, progress=False)
    df = compute_vix_features(df, vix_raw, vix9d_raw, vix3m_raw)
    print("  ✓ VIX, VIX_chg_5d, VIX_vs_ma20, VIX9D_VIX_ratio, VIX_VIX3M_ratio")
    return df


# add_earnings_proximity imported from modules.features (call: add_earnings_proximity(df, TICKER))
# normalize_features  imported from modules.features

# ─────────────────────────────────────────
# 6. TARGET VARIABLE
# ─────────────────────────────────────────
def add_target(df):
    future_hv = df["HV_20"].shift(-FORWARD_DAYS)
    df["target"] = ((future_hv / df["HV_20"] - 1) >= EXPANSION_THRESHOLD).astype(int)
    df = df.iloc[:-FORWARD_DAYS]
    expansion_rate = df["target"].mean()
    print(f"Target: HV ≥ {EXPANSION_THRESHOLD*100:.0f}% higher in {FORWARD_DAYS} trading days")
    print(f"  → Expansion rate: {expansion_rate:.1%}  ({df['target'].sum()} expansions / {len(df)} samples)\n")
    return df


# ─────────────────────────────────────────
# 7. TRAIN / EVALUATE
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


def impute_iv_features(df):
    """When --iv-features is active: add binary missing-indicator columns and
    impute NaN IV values so the full training history is preserved.

      iv_available   = 1 where atm_iv_30d was measured, 0 where imputed
      term_available = 1 where term_structure was measured, 0 where imputed

    Imputation: atm_iv_30d -> HV_20,  iv_skew_25d -> 0.0,  term_structure -> 1.0
    """
    df["iv_available"]   = df["atm_iv_30d"].notna().astype(int)
    df["term_available"] = df["term_structure"].notna().astype(int)
    df["atm_iv_30d"]     = df["atm_iv_30d"].fillna(df["HV_20"])
    df["iv_skew_25d"]    = df["iv_skew_25d"].fillna(0.0)
    df["term_structure"] = df["term_structure"].fillna(1.0)
    n_iv   = int(df["iv_available"].sum())
    n_term = int(df["term_available"].sum())
    print(f"  ✓ IV imputation: {n_iv} real atm_iv_30d rows, {n_term} real term_structure rows"
          f" (remainder filled with HV_20/0.0/1.0 + binary indicators)")
    return df


def train_model(df):
    # --iv-features: include IV_FEATURE_COLS + binary missing indicators as features;
    #   impute_iv_features() called before this ensures no NaN in IV cols so
    #   dropna() uses the full training history.
    # default (HV proxy): exclude all IV_COLS so full price history is used.
    exclude = {"Open", "High", "Low", "Close", "Volume", "target",
               *(IV_META_COLS if IV_FEATURES else IV_COLS)}
    feature_cols = [c for c in df.columns if c not in exclude]

    df_model = df[feature_cols + ["target"]].dropna()
    X = df_model[feature_cols]
    y = df_model["target"]

    split_idx = int(len(X) * (1 - TEST_SIZE))
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    print(f"Train: {len(X_train)} rows  |  Test: {len(X_test)} rows")
    print(f"Test period: {X_test.index[0].date()} → {X_test.index[-1].date()}\n")

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    clf = LogisticRegression(
        C=0.1,
        class_weight="balanced",
        max_iter=1000,
        random_state=RANDOM_STATE,
    )
    clf.fit(X_train_s, y_train)

    y_prob_train = clf.predict_proba(X_train_s)[:, 1]
    y_pred_train = (y_prob_train >= DECISION_THRESHOLD).astype(int)
    y_prob       = clf.predict_proba(X_test_s)[:, 1]
    y_pred       = (y_prob >= DECISION_THRESHOLD).astype(int)

    train_base = y_train.mean()
    test_base  = y_test.mean()
    from sklearn.metrics import precision_score
    train_prec = precision_score(y_train, y_pred_train, zero_division=0)
    test_prec  = precision_score(y_test,  y_pred,       zero_division=0)
    print(f"Base rate  — train: {train_base:.1%}  |  test: {test_base:.1%}")
    print(f"Accuracy   — train: {(y_pred_train == y_train).mean():.1%}  |  test: {(y_pred == y_test).mean():.1%}\n\n"
          f"Precision  — train: {train_prec:.1%}  |  test: {test_prec:.1%}  (when model says EXPANSION, how often correct) ***\n")

    print("─" * 50)
    print(f"CLASSIFICATION REPORT (test set, threshold={DECISION_THRESHOLD})")
    print("─" * 50)
    print(classification_report(y_test, y_pred, target_names=["Contraction", "Expansion"], zero_division=0))

    # Threshold sweep
    print("─" * 65)
    print(f"THRESHOLD SWEEP  (base expansion rate: {test_base:.1%})")
    print(f"{'Confidence':>10}  {'Exp Prec':>9}  {'Exp Recall':>10}  {'Exp F1':>7}  {'Signals':>8}")
    print("─" * 65)
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
    print("─" * 65)

    # Top coefficients
    coefs = pd.Series(clf.coef_[0], index=feature_cols).sort_values(key=abs, ascending=False)
    print(f"\nTOP 10 COEFFICIENTS")
    print(f"{'Feature':<25}  {'Coefficient':>12}  Direction")
    print("─" * 55)
    for feat, val in coefs.head(10).items():
        direction = "expansion ↑" if val > 0 else "contraction ↓"
        print(f"{feat:<25}  {val:>12.4f}  {direction}")
    print()

    # Calibration diagnostic — compare raw LR vs isotonic-calibrated wrapper.
    # Diagnostic only; does not affect the production model returned below.
    print("─" * 60)
    print("CALIBRATION DIAGNOSTIC (test set)")
    print("─" * 60)
    print_calibration_diagnostic(y_test, y_prob, "Raw Logistic Regression")
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

    return clf, scaler, X_test, y_test, y_pred, y_prob, feature_cols


# ─────────────────────────────────────────
# 8. SIGNAL SUMMARY (current bar)
# ─────────────────────────────────────────
def print_signal_summary(df_full, clf, scaler, feature_cols):
    latest_row  = df_full[feature_cols].dropna().iloc[-1]
    latest_date = df_full[feature_cols].dropna().index[-1].strftime("%Y-%m-%d")

    X_latest = scaler.transform(pd.DataFrame([latest_row], columns=feature_cols))
    exp_prob  = clf.predict_proba(X_latest)[0, 1]

    iv_rank = latest_row["IV_rank"]
    iv_pct  = latest_row["IV_pct"]
    hv_20   = latest_row["HV_20"]

    regime = "Low IV" if iv_rank < 0.33 else "High IV" if iv_rank > 0.67 else "Mid IV"
    signal = "EXPANSION" if exp_prob >= DECISION_THRESHOLD else "CONTRACTION"

    print(f"{'═'*50}")
    print(f"  IV SIGNAL SUMMARY — {TICKER} as of {latest_date}")
    print(f"{'═'*50}")
    print(f"  HV (20-day):      {hv_20:.1%}")
    print(f"  IV Rank:          {iv_rank:.2f}  ({regime})")
    print(f"  IV Percentile:    {iv_pct:.1%}")
    print(f"  Expansion Prob:   {exp_prob:.1%}")
    print(f"  Signal:           {signal}")
    _dtc = int(latest_row.get("Days_to_catalyst", 90))
    days_to_cat = "N/A" if _dtc >= 90 else f"{_dtc}d"
    print(f"  Days to Earnings: {int(latest_row['Days_to_earnings'])}d")
    print(f"  Days to Catalyst: {days_to_cat}")
    print()
    if iv_rank < 0.33 and signal == "EXPANSION":
        print("  → Options cheap and vol likely rising — favorable entry")
    elif iv_rank < 0.33 and signal == "CONTRACTION":
        print("  → Options cheap but vol likely falling — wait for a catalyst")
    elif iv_rank <= 0.67 and signal == "EXPANSION":
        print("  → Mid-range IV with vol likely rising — acceptable entry, monitor premium")
    elif iv_rank <= 0.67 and signal == "CONTRACTION":
        print("  → Mid-range IV with vol likely falling — avoid, IV crush risk")
    elif iv_rank > 0.67 and signal == "EXPANSION":
        print("  → Options expensive and vol still rising — high risk entry, premium inflated")
    else:
        print("  → Options expensive and vol likely falling — IV crush risk, wait")
    print(f"{'═'*50}\n")


# ─────────────────────────────────────────
# 9. PLOT RESULTS
# ─────────────────────────────────────────
def plot_results(df_full, clf, feature_cols):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), facecolor="#0d1117")
    fig.suptitle(f"{TICKER} Phase 3 — IV Expansion Forecasting", color="white", fontsize=13)

    # HV over time, shaded by IV rank regime
    ax1 = axes[0]
    ax1.set_facecolor("#0d1117")
    plot_df = df_full[["HV_20", "IV_rank"]].dropna()
    x = range(len(plot_df))
    ax1.plot(x, plot_df["HV_20"].values, color="#58a6ff", lw=0.9, label="HV 20-day")
    for i in range(len(plot_df) - 1):
        rank  = plot_df["IV_rank"].iloc[i]
        color = "#3fb950" if rank < 0.33 else "#f85149" if rank > 0.67 else "#ffa657"
        ax1.axvspan(i, i + 1, alpha=0.15, color=color)
    tick_spacing = max(1, len(plot_df) // 8)
    ax1.set_xticks(range(0, len(plot_df), tick_spacing))
    ax1.set_xticklabels(
        [plot_df.index[i].strftime("%b '%y") for i in range(0, len(plot_df), tick_spacing)],
        rotation=30, ha="right", color="#8b949e", fontsize=7
    )
    ax1.set_title("HV Over Time  (green=low IV, amber=mid, red=high)", color="white", pad=10)
    ax1.set_ylabel("HV (annualized)", color="#e6edf3")
    ax1.tick_params(colors="#8b949e")
    ax1.spines[:].set_color("#30363d")
    ax1.legend(fontsize=7, facecolor="#161b22", labelcolor="white")

    # Feature coefficients
    ax2 = axes[1]
    ax2.set_facecolor("#0d1117")
    coefs = pd.Series(clf.coef_[0], index=feature_cols)
    top15 = coefs.abs().sort_values().tail(15).index
    coefs_top = coefs[top15]
    bar_colors = ["#3fb950" if v > 0 else "#f85149" for v in coefs_top]
    coefs_top.plot(kind="barh", ax=ax2, color=bar_colors)
    ax2.axvline(0, color="#8b949e", lw=0.8)
    ax2.set_title("Feature Coefficients — green=expansion, red=contraction", color="white", pad=10)
    ax2.tick_params(colors="#8b949e")
    ax2.spines[:].set_color("#30363d")
    ax2.xaxis.label.set_color("#8b949e")

    plt.tight_layout()
    plt.savefig(os.path.join(DATA_DIR, f"{TICKER.lower()}_phase3_results.png"), dpi=150,
                bbox_inches="tight", facecolor="#0d1117")
    print(f"Results chart saved -> {os.path.join(DATA_DIR, f'{TICKER.lower()}_phase3_results.png')}")
    plt.show()


# compute_vol_thresholds imported from modules.features

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 3: IV expansion forecasting.")
    parser.add_argument(
        "--iv-features", action=argparse.BooleanOptionalAction, default=False,
        dest="iv_features",
        help="Include real IV features (atm_iv_30d, iv_skew_25d, term_structure) from "
             "backfilled indicators CSV. Default OFF — uses HV proxy (full history). "
             "Requires backfill_iv.py to have been run first.",
    )
    args = parser.parse_args()
    IV_FEATURES = args.iv_features

    iv_mode = ("REAL IV FEATURES  (imputed missing → full history)"
               if IV_FEATURES else "HV PROXY  (full history)")
    print("\u2550" * 64)
    print(f"  Phase 3 IV features: {iv_mode}")
    print("\u2550" * 64)
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
    _, _, EXPANSION_THRESHOLD = compute_vol_thresholds(df)

    print("Building features...")
    df = add_iv_features(df)
    df = add_vix(df)
    macro = detect_macro_features(TICKER)
    if macro:
        print("  Macro features:")
        df = add_macro_features(df, macro, START_DATE, END_DATE)
    df = add_earnings_proximity(df, TICKER)
    df = add_catalyst_proximity(df, TICKER, MODULE_DIR)
    df = normalize_features(df)
    if IV_FEATURES:
        df = impute_iv_features(df)

    # Save full df before target truncation for signal summary and HV plot
    df_full = df.copy()

    df = add_target(df)

    clf, scaler, X_test, y_test, y_pred, y_prob, feature_cols = train_model(df)
    print_signal_summary(df_full, clf, scaler, feature_cols)
    plot_results(df_full, clf, feature_cols)

    df.to_csv(os.path.join(DATA_DIR, f"{TICKER.lower()}_phase3_features.csv"))
    print(f"Feature dataset saved -> {os.path.join(DATA_DIR, f'{TICKER.lower()}_phase3_features.csv')}")
