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

import os
import sys
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, confusion_matrix, ConfusionMatrixDisplay
from modules.benchmarks import detect_benchmarks, detect_macro_features, add_macro_features, add_catalyst_proximity

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
# TICKER         = "AMD"
START_DATE     = "1792-05-17"
END_DATE       = ""  # set automatically from CSV
DATA_DIR       = "data"
MODULE_DIR     = "modules"
# INDICATORS_CSV = os.path.join(DATA_DIR, f"{TICKER.lower()}_indicators.csv")

HV_WINDOW      = 20     # Rolling window for realized vol (trading days)
FORWARD_DAYS     = 15    # Days ahead to evaluate win/loss (entry timing)
FORWARD_DAYS_63  = 63    # Medium-term direction window (~1 quarter)
WIN_THRESHOLD    = 0.05  # Default (AMD). Overridden at runtime by compute_vol_thresholds()
WIN_THRESHOLD_63 = 0.10  # Default (AMD). Overridden at runtime by compute_vol_thresholds()
P2_VOL_MULTIPLE  = 0.41  # 0.41 sigma bar — practical range: 0.25 (aggressive) to 1.0 (conservative)
TEST_SIZE      = 0.20   # Fraction of data held out as test set (time-based)
N_ESTIMATORS       = 200    # Random forest trees
DECISION_THRESHOLD = 0.55   # Probability cutoff for predicting Win (lower = more wins predicted)
RANDOM_STATE       = 42


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
    log_ret = np.log(df["Close"] / df["Close"].shift(1))
    df["HV_20"] = log_ret.rolling(HV_WINDOW).std() * np.sqrt(252)
    print("  ✓ HV_20")
    return df


def add_vix(df):
    raw = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False)
    raw.columns = raw.columns.get_level_values(0)
    vix = raw[["Close"]].rename(columns={"Close": "VIX"})
    vix["VIX_chg_5d"]  = vix["VIX"].pct_change(5)
    vix["VIX_vs_ma20"] = vix["VIX"] / vix["VIX"].rolling(20).mean() - 1
    df = df.join(vix, how="left")
    df[["VIX", "VIX_chg_5d", "VIX_vs_ma20"]] = (
        df[["VIX", "VIX_chg_5d", "VIX_vs_ma20"]].ffill()
    )

    # VIX term structure: near-term vs spot vs 3-month
    # VIX9D available ~2013+; VIX3M available ~2011+ — neutral fill (1.0) for missing history
    for sym, col in [("^VIX9D", "VIX9D"), ("^VIX3M", "VIX3M")]:
        r = yf.download(sym, start=START_DATE, end=END_DATE, progress=False)
        r.columns = r.columns.get_level_values(0)
        df = df.join(r[["Close"]].rename(columns={"Close": col}), how="left")
        df[col] = df[col].ffill()
    df["VIX9D_VIX_ratio"] = (df["VIX9D"] / df["VIX"]).fillna(1.0)  # >1 = near-term fear
    df["VIX_VIX3M_ratio"] = (df["VIX"] / df["VIX3M"]).fillna(1.0)  # <1 = backwardation (stress)
    df.drop(columns=["VIX9D", "VIX3M"], inplace=True)

    print("  ✓ VIX, VIX_chg_5d, VIX_vs_ma20, VIX9D_VIX_ratio, VIX_VIX3M_ratio")
    return df


def add_benchmarks(df, benchmarks):
    for bench_ticker, bench_name in benchmarks:
        raw = yf.download(bench_ticker, start=START_DATE, end=END_DATE, progress=False)
        raw.columns = raw.columns.get_level_values(0)
        col = f"_BENCH_{bench_name}"
        bench = raw[["Close"]].rename(columns={"Close": col})
        df = df.join(bench, how="left")
        df[col] = df[col].ffill()
        for window in [5, 20]:
            df[f"{bench_name}_RS_{window}d"] = df["Close"].pct_change(window) - df[col].pct_change(window)
        df[f"{bench_name}_vs_ma200"] = df[col] / df[col].rolling(200).mean() - 1
        df.drop(columns=[col], inplace=True)
        print(f"  ✓ {bench_name}_RS_5d, {bench_name}_RS_20d, {bench_name}_vs_ma200")
    return df


def add_earnings_proximity(df):
    ticker = yf.Ticker(TICKER)
    ed = []
    try:
        dates = ticker.get_earnings_dates(limit=20)
        if dates is not None and len(dates) > 0:
            idx = pd.DatetimeIndex(dates.index)
            if idx.tz is not None:
                idx = idx.tz_convert(None)
            ed = sorted(idx.normalize().unique())
    except Exception as e:
        print(f"  ✗ Earnings dates unavailable ({e}) — filling with 45")
        df["Days_to_earnings"] = 45  # neutral fallback: mid-cycle
        return df

    if not ed:
        print("  ✗ Earnings dates empty — filling with 45")
        df["Days_to_earnings"] = 45
        return df

    def _days_to_next(date):
        future = [e for e in ed if e >= date]
        # Cap at 90 if no future date found (end of dataset edge case)
        return (future[0] - date).days if future else 90

    df["Days_to_earnings"] = [_days_to_next(d) for d in df.index]
    print("  ✓ Days_to_earnings")
    return df


# ─────────────────────────────────────────
# 3. NORMALIZE PRICE-LEVEL FEATURES
# ─────────────────────────────────────────
def normalize_features(df):
    """Replace absolute price-level indicators with scale-invariant ratios."""
    close = df["Close"]

    # Universal momentum / positioning features (generic for any ticker)
    df["price_vs_52w_high"] = close / close.rolling(252).max() - 1
    df["price_vs_52w_low"]  = close / close.rolling(252).min() - 1
    df["vol_ratio"]         = df["Volume"] / df["Volume"].rolling(20).mean()

    # MA → keep short (20), medium (50), long (200) — drop 100 (redundant between 50/200)
    for period in [20, 50, 200]:
        col = f"MA_{period}"
        if col in df.columns:
            df[f"price_vs_ma{period}"] = close / df[col] - 1
    ma_drop = [c for c in df.columns if c.startswith("MA_")]
    df.drop(columns=ma_drop, inplace=True)

    # EMA → keep short (8), medium (21), long (89) — drop 34/55 (redundant)
    for period in [8, 21, 89]:
        col = f"EMA_{period}"
        if col in df.columns:
            df[f"price_vs_ema{period}"] = close / df[col] - 1
    ema_drop = [c for c in df.columns if c.startswith("EMA_")]
    df.drop(columns=ema_drop, inplace=True)

    # Keltner Channels → price position relative to each band
    for band, label in [("KC_upper", "kc_upper"), ("KC_middle", "kc_mid"), ("KC_lower", "kc_lower")]:
        df[f"price_vs_{label}"] = close / df[band] - 1
        df.drop(columns=[band], inplace=True)

    # MACD values are in dollar terms — normalize by price
    for col in ["MACD", "MACD_signal", "MACD_hist"]:
        df[f"{col}_norm"] = df[col] / close
        df.drop(columns=[col], inplace=True)

    # OBV is cumulative and non-stationary — replace with 5-day rate of change
    df["OBV_chg_5d"] = df["OBV"].pct_change(5)
    df.drop(columns=["OBV"], inplace=True)

    print("Features normalized:")
    print("  ✓ MA/EMA → price_vs_ma/ema ratios")
    print("  ✓ KC bands → price_vs_kc ratios")
    print("  ✓ MACD/signal/hist → normalized by Close")
    print("  ✓ OBV → OBV_chg_5d\n")
    return df


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
def train_model(df):
    exclude = {"Open", "High", "Low", "Close", "Volume", "target"}
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
        C=0.1,                  # regularization strength (lower = more regularized)
        class_weight="balanced",
        max_iter=1000,
        random_state=RANDOM_STATE,
    )
    clf.fit(X_train_s, y_train)

    y_prob_train = clf.predict_proba(X_train_s)[:, 1]
    y_pred_train = (y_prob_train >= DECISION_THRESHOLD).astype(int)
    y_prob = clf.predict_proba(X_test_s)[:, 1]
    y_pred = (y_prob >= DECISION_THRESHOLD).astype(int)

    train_base = y_train.mean()
    test_base  = y_test.mean()
    from sklearn.metrics import precision_score
    train_prec = precision_score(y_train, y_pred_train, zero_division=0)
    test_prec  = precision_score(y_test,  y_pred,       zero_division=0)
    print(f"Base rate  — train: {train_base:.1%}  |  test: {test_base:.1%}")
    print(f"Accuracy   — train: {(y_pred_train == y_train).mean():.1%}  |  test: {(y_pred == y_test).mean():.1%}\n\n"
          f"Precision  — train: {train_prec:.1%}  |  test: {test_prec:.1%}  (when model says WIN, how often correct) ***\n")

    print("─" * 50)
    print(f"CLASSIFICATION REPORT (test set, threshold={DECISION_THRESHOLD})")
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


# ─────────────────────────────────────────
# VOL-ADJUSTED THRESHOLD
# ─────────────────────────────────────────
def compute_vol_thresholds(df):
    global WIN_THRESHOLD, WIN_THRESHOLD_63
    log_ret   = np.log(df["Close"] / df["Close"].shift(1))
    hv_series = log_ret.rolling(HV_WINDOW).std() * np.sqrt(252)
    hv_valid  = hv_series.dropna()

    print("\nVol-Adjusted Threshold Calibration")
    print("─" * 42)
    if len(hv_valid) < 20 or hv_valid.median() < 0.05:
        print("  WARNING: Insufficient/invalid HV data — using AMD default.")
        print("─" * 42)
        return

    median_hv    = hv_valid.median()
    new_win      = P2_VOL_MULTIPLE * median_hv * np.sqrt(FORWARD_DAYS / 252)
    new_win_63   = P2_VOL_MULTIPLE * median_hv * np.sqrt(FORWARD_DAYS_63 / 252)
    print(f"  Ticker median HV (20-day, annualized): {median_hv:.1%}")
    print(f"  WIN_THRESHOLD:    0.05 (AMD default)  ->  {new_win:.1%}  [computed]")
    print(f"  WIN_THRESHOLD_63: 0.10 (AMD default)  ->  {new_win_63:.1%}  [computed]")
    print("─" * 42)
    WIN_THRESHOLD    = new_win
    WIN_THRESHOLD_63 = new_win_63


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
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
    compute_vol_thresholds(df)

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
    df = add_vix(df)
    df = add_benchmarks(df, benchmarks)
    macro = detect_macro_features(TICKER)
    if macro:
        print("  Macro features:")
        df = add_macro_features(df, macro, START_DATE, END_DATE)
    df = add_earnings_proximity(df)
    df = add_catalyst_proximity(df, TICKER, MODULE_DIR, for_direction=True)
    df = normalize_features(df)

    # Phase 2 — 15-day direction model
    df_15 = add_target(df.copy())
    clf, X_test, y_test, y_pred, y_prob, feature_cols = train_model(df_15)
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
    clf63, X_test63, y_test63, y_pred63, y_prob63, fcols63 = train_model(df_63)

    df_15.to_csv(os.path.join(DATA_DIR, f"{TICKER.lower()}_ml_features.csv"))
    print(f"\nEnriched feature dataset saved -> {os.path.join(DATA_DIR, f'{TICKER.lower()}_ml_features.csv')}")
