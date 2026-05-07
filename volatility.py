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

import os
import sys
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report
from modules.benchmarks import detect_macro_features, add_macro_features, add_catalyst_proximity

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
# TICKER         = "AMD"
START_DATE     = "1792-05-17"
END_DATE       = ""  # set automatically from CSV
DATA_DIR       = "data"
MODULE_DIR     = "modules"
# INDICATORS_CSV = os.path.join(DATA_DIR, f"{TICKER.lower()}_indicators.csv")

HV_WINDOW           = 20    # Days for realized vol calculation
IV_RANK_WINDOW      = 252   # 1 trading year lookback for IV rank/percentile
FORWARD_DAYS        = 10    # Days ahead to evaluate expansion
EXPANSION_THRESHOLD = 0.10  # Default (AMD). Overridden at runtime by compute_vol_thresholds()
P3_VOL_MULTIPLE     = 0.20  # Sets expansion bar at 20% of median HV — practical range: 0.10 to 0.40
TEST_SIZE           = 0.20
DECISION_THRESHOLD  = 0.50
RANDOM_STATE        = 42


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
    log_ret = np.log(df["Close"] / df["Close"].shift(1))
    df["HV_20"] = log_ret.rolling(HV_WINDOW).std() * np.sqrt(252)

    # IV rank: where current HV sits in its 1-year range (0 = cheapest, 1 = most expensive)
    hv_high = df["HV_20"].rolling(IV_RANK_WINDOW).max()
    hv_low  = df["HV_20"].rolling(IV_RANK_WINDOW).min()
    df["IV_rank"] = (df["HV_20"] - hv_low) / (hv_high - hv_low)

    # IV percentile: % of past year where HV was below current level
    df["IV_pct"] = df["HV_20"].rolling(IV_RANK_WINDOW).apply(
        lambda x: (x[:-1] < x[-1]).mean(), raw=True
    )

    # HV trend: is vol rising or falling?
    df["HV_chg_5d"]  = df["HV_20"].pct_change(5)
    df["HV_chg_10d"] = df["HV_20"].pct_change(10)
    df["HV_vs_ma20"] = df["HV_20"] / df["HV_20"].rolling(20).mean() - 1

    print("  ✓ HV_20, IV_rank, IV_pct, HV_chg_5d, HV_chg_10d, HV_vs_ma20")
    return df


# ─────────────────────────────────────────
# 3. VIX FEATURES
# ─────────────────────────────────────────
def add_vix(df):
    raw = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False)
    raw.columns = raw.columns.get_level_values(0)
    vix = raw[["Close"]].rename(columns={"Close": "VIX"})
    vix["VIX_chg_5d"]  = vix["VIX"].pct_change(5)
    vix["VIX_vs_ma20"] = vix["VIX"] / vix["VIX"].rolling(20).mean() - 1
    df = df.join(vix, how="left")
    df[["VIX", "VIX_chg_5d", "VIX_vs_ma20"]] = df[["VIX", "VIX_chg_5d", "VIX_vs_ma20"]].ffill()
    print("  ✓ VIX, VIX_chg_5d, VIX_vs_ma20")
    return df


# ─────────────────────────────────────────
# 4. EARNINGS PROXIMITY
# ─────────────────────────────────────────
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
        df["Days_to_earnings"] = 45
        return df

    if not ed:
        print("  ✗ Earnings dates empty — filling with 45")
        df["Days_to_earnings"] = 45
        return df

    def _days_to_next(date):
        future = [e for e in ed if e >= date]
        return (future[0] - date).days if future else 90

    df["Days_to_earnings"] = [_days_to_next(d) for d in df.index]
    print("  ✓ Days_to_earnings")
    return df


# ─────────────────────────────────────────
# 5. NORMALIZE PRICE-LEVEL FEATURES
# ─────────────────────────────────────────
def normalize_features(df):
    close = df["Close"]

    # Universal momentum / positioning features (generic for any ticker)
    df["price_vs_52w_high"] = close / close.rolling(252).max() - 1
    df["price_vs_52w_low"]  = close / close.rolling(252).min() - 1
    df["vol_ratio"]         = df["Volume"] / df["Volume"].rolling(20).mean()

    for period in [20, 50, 200]:
        col = f"MA_{period}"
        if col in df.columns:
            df[f"price_vs_ma{period}"] = close / df[col] - 1
    df.drop(columns=[c for c in df.columns if c.startswith("MA_")], inplace=True)

    for period in [8, 21, 89]:
        col = f"EMA_{period}"
        if col in df.columns:
            df[f"price_vs_ema{period}"] = close / df[col] - 1
    df.drop(columns=[c for c in df.columns if c.startswith("EMA_")], inplace=True)

    for band, label in [("KC_upper", "kc_upper"), ("KC_middle", "kc_mid"), ("KC_lower", "kc_lower")]:
        if band in df.columns:
            df[f"price_vs_{label}"] = close / df[band] - 1
            df.drop(columns=[band], inplace=True)

    for col in ["MACD", "MACD_signal", "MACD_hist"]:
        if col in df.columns:
            df[f"{col}_norm"] = df[col] / close
            df.drop(columns=[col], inplace=True)

    if "OBV" in df.columns:
        df["OBV_chg_5d"] = df["OBV"].pct_change(5)
        df.drop(columns=["OBV"], inplace=True)

    print("Features normalized:")
    print("  ✓ MA/EMA → price_vs ratios")
    print("  ✓ KC bands → price_vs ratios")
    print("  ✓ MACD → normalized by Close")
    print("  ✓ OBV → OBV_chg_5d\n")
    return df


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


# ─────────────────────────────────────────
# VOL-ADJUSTED THRESHOLD
# ─────────────────────────────────────────
def compute_vol_thresholds(df):
    global EXPANSION_THRESHOLD
    log_ret   = np.log(df["Close"] / df["Close"].shift(1))
    hv_series = log_ret.rolling(HV_WINDOW).std() * np.sqrt(252)
    hv_valid  = hv_series.dropna()

    print("\nVol-Adjusted Threshold Calibration")
    print("─" * 42)
    if len(hv_valid) < 20 or hv_valid.median() < 0.05:
        print("  WARNING: Insufficient/invalid HV data — using AMD default.")
        print("─" * 42)
        return

    median_hv     = hv_valid.median()
    new_expansion = P3_VOL_MULTIPLE * median_hv
    print(f"  Ticker median HV (20-day, annualized): {median_hv:.1%}")
    print(f"  EXPANSION_THRESHOLD:  0.10 (AMD default)  ->  {new_expansion:.1%}  [computed]")
    print("─" * 42)
    EXPANSION_THRESHOLD = new_expansion


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

    print("Building features...")
    df = add_iv_features(df)
    df = add_vix(df)
    macro = detect_macro_features(TICKER)
    if macro:
        print("  Macro features:")
        df = add_macro_features(df, macro, START_DATE, END_DATE)
    df = add_earnings_proximity(df)
    df = add_catalyst_proximity(df, TICKER, MODULE_DIR)
    df = normalize_features(df)

    # Save full df before target truncation for signal summary and HV plot
    df_full = df.copy()

    df = add_target(df)

    clf, scaler, X_test, y_test, y_pred, y_prob, feature_cols = train_model(df)
    print_signal_summary(df_full, clf, scaler, feature_cols)
    plot_results(df_full, clf, feature_cols)

    df.to_csv(os.path.join(DATA_DIR, f"{TICKER.lower()}_phase3_features.csv"))
    print(f"Feature dataset saved -> {os.path.join(DATA_DIR, f'{TICKER.lower()}_phase3_features.csv')}")
