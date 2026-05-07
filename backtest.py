"""
Options Trading — Walk-Forward Backtest
========================================
Validates the combined Phase 2 + Phase 3 signal using walk-forward
validation to avoid in-sample contamination.

Method (expanding window):
  - Train from 2018 up to window cutoff, test on the next 6 months
  - Retrain every 6 months with all available history
  - ~12 windows covering 2020-2025 across multiple market regimes

For each test day, records the signal (STRONG ENTRY / CAUTION / STAY OUT)
and the actual 15-day forward return. Aggregates results by signal category
vs an all-days benchmark.

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
from modules.benchmarks import detect_benchmarks, detect_macro_features, add_catalyst_proximity

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
TICKER         = "AMD"
START_DATE     = "2018-01-01"
END_DATE       = ""  # set automatically from CSV
DATA_DIR       = "data"
MODULE_DIR     = "modules"
INDICATORS_CSV = os.path.join(DATA_DIR, f"{TICKER.lower()}_indicators.csv")

HV_WINDOW           = 20
IV_RANK_WINDOW      = 252
P2_FORWARD_DAYS     = 15
P2B_FORWARD_DAYS    = 63    # Medium-term direction window (~1 quarter)
P3_FORWARD_DAYS     = 10
WIN_THRESHOLD       = 0.05  # Default (AMD). Overridden at runtime by compute_vol_thresholds()
WIN_THRESHOLD_63    = 0.10  # Default (AMD). Overridden at runtime by compute_vol_thresholds()
P2_VOL_MULTIPLE     = 0.41  # 0.41 sigma bar — practical range: 0.25 (aggressive) to 1.0 (conservative)
EXPANSION_THRESHOLD = 0.10  # Default (AMD). Overridden at runtime by compute_vol_thresholds()
P3_VOL_MULTIPLE     = 0.20  # Sets expansion bar at 20% of median HV — practical range: 0.10 to 0.40
P2_THRESHOLD        = 0.55
P3_THRESHOLD        = 0.60
RANDOM_STATE        = 42

# Walk-forward parameters
# MIN_TRAIN_DAYS = 504   # ~2 years minimum training window
MIN_TRAIN_DAYS = 252   # ~1 year minimum training window
STEP_DAYS      = 126   # ~6 months between retrains


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
    print(f"  -> Ticker: {TICKER} | {START_DATE} to {END_DATE}")
    print(f"  -> {len(df)} rows, {len(df.columns)} columns\n")
    return df


# ─────────────────────────────────────────
# 2. CACHED DOWNLOADS
# ─────────────────────────────────────────
def _fetch_cached(symbol, filename):
    """Fetch symbol from yfinance, using a local cache tied to END_DATE.
    Re-fetches automatically when the indicators CSV has been updated."""
    cache_path = os.path.join(DATA_DIR, filename)
    if os.path.exists(cache_path):
        cached = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        cached_end = cached.index.max().strftime("%Y-%m-%d")
        if cached_end >= END_DATE:
            return cached
    raw = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
    raw.columns = raw.columns.get_level_values(0)
    raw.to_csv(cache_path)
    return raw


# ─────────────────────────────────────────
# 3. FEATURE ENGINEERING
# ─────────────────────────────────────────
def build_features(df, benchmarks):
    close = df["Close"]

    # HV and IV features
    log_ret = np.log(close / close.shift(1))
    df["HV_20"]      = log_ret.rolling(HV_WINDOW).std() * np.sqrt(252)
    hv_high          = df["HV_20"].rolling(IV_RANK_WINDOW).max()
    hv_low           = df["HV_20"].rolling(IV_RANK_WINDOW).min()
    df["IV_rank"]    = (df["HV_20"] - hv_low) / (hv_high - hv_low)
    df["IV_pct"]     = df["HV_20"].rolling(IV_RANK_WINDOW).apply(
        lambda x: (x[:-1] < x[-1]).mean(), raw=True
    )
    df["HV_chg_5d"]  = df["HV_20"].pct_change(5)
    df["HV_chg_10d"] = df["HV_20"].pct_change(10)
    df["HV_vs_ma20"] = df["HV_20"] / df["HV_20"].rolling(20).mean() - 1

    # VIX
    vix_raw = _fetch_cached("^VIX", "vix_cache.csv")
    vix = vix_raw[["Close"]].rename(columns={"Close": "VIX"})
    vix["VIX_chg_5d"]  = vix["VIX"].pct_change(5)
    vix["VIX_vs_ma20"] = vix["VIX"] / vix["VIX"].rolling(20).mean() - 1
    df = df.join(vix, how="left")
    df[["VIX", "VIX_chg_5d", "VIX_vs_ma20"]] = df[["VIX", "VIX_chg_5d", "VIX_vs_ma20"]].ffill()

    # Sector/industry benchmark relative strength + sector trend
    for bench_ticker, bench_name in benchmarks:
        bench_raw = _fetch_cached(bench_ticker, f"{bench_name.lower()}_cache.csv")
        col = f"_BENCH_{bench_name}"
        bench = bench_raw[["Close"]].rename(columns={"Close": col})
        df = df.join(bench, how="left")
        df[col] = df[col].ffill()
        for window in [5, 20]:
            df[f"{bench_name}_RS_{window}d"] = close.pct_change(window) - df[col].pct_change(window)
        df[f"{bench_name}_vs_ma200"] = df[col] / df[col].rolling(200).mean() - 1
        df.drop(columns=[col], inplace=True)

    # Macro features (cached, rate-sensitive tickers, etc.)
    macro_features = detect_macro_features(TICKER)
    if macro_features:
        fetched = {}
        for symbol, name in macro_features:
            rate_raw = _fetch_cached(symbol, f"{name.lower()}_cache.csv")
            series = rate_raw[["Close"]].rename(columns={"Close": name})
            series[f"{name}_chg_5d"]  = series[name].pct_change(5)
            series[f"{name}_vs_ma20"] = series[name] / series[name].rolling(20).mean() - 1
            df = df.join(series, how="left")
            ff_cols = [name, f"{name}_chg_5d", f"{name}_vs_ma20"]
            df[ff_cols] = df[ff_cols].ffill()
            fetched[name] = True
        if "UST10Y" in fetched and "UST3M" in fetched:
            df["yield_curve"]        = df["UST10Y"] - df["UST3M"]
            df["yield_curve_chg_5d"] = df["yield_curve"].pct_change(5)

    # Earnings proximity
    ticker = yf.Ticker(TICKER)
    ed = []
    try:
        dates = ticker.get_earnings_dates(limit=20)
        if dates is not None and len(dates) > 0:
            idx = pd.DatetimeIndex(dates.index)
            if idx.tz is not None:
                idx = idx.tz_convert(None)
            ed = sorted(idx.normalize().unique())
    except Exception:
        pass
    if ed:
        def _days_to_next(date):
            future = [e for e in ed if e >= date]
            return (future[0] - date).days if future else 90
        df["Days_to_earnings"] = [_days_to_next(d) for d in df.index]
    else:
        df["Days_to_earnings"] = 45

    df = add_catalyst_proximity(df, TICKER, MODULE_DIR)

    # Normalize price-level features
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

    # Universal momentum / positioning features (generic for any ticker)
    df["price_vs_52w_high"] = close / close.rolling(252).max() - 1
    df["price_vs_52w_low"]  = close / close.rolling(252).min() - 1
    df["vol_ratio"]         = df["Volume"] / df["Volume"].rolling(20).mean()

    print("Features built.\n")
    return df


# ─────────────────────────────────────────
# 4. TRAIN A SINGLE MODEL
# ─────────────────────────────────────────
def train_model(df_train, target_col):
    exclude = {"Open", "High", "Low", "Close", "Volume", target_col}
    feature_cols = [c for c in df_train.columns if c not in exclude]

    df_model = df_train[feature_cols + [target_col]].dropna()
    if len(df_model) < 50:
        return None, None, None

    X = df_model[feature_cols]
    y = df_model[target_col].values

    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)

    clf = LogisticRegression(C=0.1, class_weight="balanced",
                             max_iter=1000, random_state=RANDOM_STATE)
    clf.fit(X_s, y)
    return clf, scaler, feature_cols


# ─────────────────────────────────────────
# 5. WALK-FORWARD BACKTEST
# ─────────────────────────────────────────
def run_backtest(df_full):
    close = df_full["Close"]
    n     = len(df_full)
    results = []
    window_num = 0

    train_end = MIN_TRAIN_DAYS
    while train_end < n - P2_FORWARD_DAYS:
        test_start = train_end
        test_end   = min(train_end + STEP_DAYS, n - P2_FORWARD_DAYS)
        window_num += 1

        train_date = df_full.index[train_end - 1].strftime("%Y-%m")
        test_s_date = df_full.index[test_start].strftime("%Y-%m")
        test_e_date = df_full.index[test_end - 1].strftime("%Y-%m")
        print(f"  Window {window_num:2d}: train through {train_date} | test {test_s_date} to {test_e_date}")

        df_train = df_full.iloc[:train_end].copy()

        # Phase 2 — 15-day direction target
        df_p2 = df_train.copy()
        fc2 = df_p2["Close"].shift(-P2_FORWARD_DAYS)
        df_p2["_target"] = ((fc2 / df_p2["Close"] - 1) >= WIN_THRESHOLD).astype(int)
        df_p2 = df_p2.iloc[:-P2_FORWARD_DAYS]
        clf2, scaler2, fcols2 = train_model(df_p2, "_target")

        # Phase 2B — 63-day direction target
        df_p2b = df_train.copy()
        fc2b = df_p2b["Close"].shift(-P2B_FORWARD_DAYS)
        df_p2b["_target"] = ((fc2b / df_p2b["Close"] - 1) >= WIN_THRESHOLD_63).astype(int)
        df_p2b = df_p2b.iloc[:-P2B_FORWARD_DAYS]
        clf2b, scaler2b, fcols2b = train_model(df_p2b, "_target")

        # Phase 3 — IV expansion target
        df_p3 = df_train.copy()
        fh3 = df_p3["HV_20"].shift(-P3_FORWARD_DAYS)
        df_p3["_target"] = ((fh3 / df_p3["HV_20"] - 1) >= EXPANSION_THRESHOLD).astype(int)
        df_p3 = df_p3.iloc[:-P3_FORWARD_DAYS]
        clf3, scaler3, fcols3 = train_model(df_p3, "_target")

        if clf2 is None or clf2b is None or clf3 is None:
            train_end += STEP_DAYS
            continue

        # Generate signals on test period
        for i in range(test_start, test_end):
            date = df_full.index[i]

            row2  = df_full[fcols2].iloc[i]
            row2b = df_full[fcols2b].iloc[i]
            row3  = df_full[fcols3].iloc[i]
            if row2.isna().any() or row2b.isna().any() or row3.isna().any():
                continue

            X2  = pd.DataFrame([row2],  columns=fcols2)
            X2b = pd.DataFrame([row2b], columns=fcols2b)
            X3  = pd.DataFrame([row3],  columns=fcols3)
            dir_prob    = clf2.predict_proba(scaler2.transform(X2))[0, 1]
            dir_prob_63 = clf2b.predict_proba(scaler2b.transform(X2b))[0, 1]
            exp_prob    = clf3.predict_proba(scaler3.transform(X3))[0, 1]

            dir_signal    = dir_prob    >= P2_THRESHOLD
            dir_signal_63 = dir_prob_63 >= P2_THRESHOLD
            exp_signal    = exp_prob    >= P3_THRESHOLD

            if dir_signal and dir_signal_63 and exp_signal:
                signal = "STRONG ENTRY"
            elif dir_signal and dir_signal_63 and not exp_signal:
                signal = "CAUTION"
            elif dir_signal and not dir_signal_63:
                signal = "SHORT-TERM ONLY"
            else:
                signal = "STAY OUT"

            fwd_return = close.iloc[i + P2_FORWARD_DAYS] / close.iloc[i] - 1

            results.append({
                "date":       date,
                "signal":     signal,
                "dir_prob":   dir_prob,
                "dir_prob_63": dir_prob_63,
                "exp_prob":   exp_prob,
                "fwd_return": fwd_return,
                "window":     window_num,
            })

        train_end += STEP_DAYS

    return pd.DataFrame(results).set_index("date")


# ─────────────────────────────────────────
# 6. SUMMARIZE RESULTS
# ─────────────────────────────────────────
def summarize(results):
    order  = ["STRONG ENTRY", "CAUTION", "SHORT-TERM ONLY", "STAY OUT", "ALL DAYS"]
    colors = {"STRONG ENTRY": "#3fb950", "CAUTION": "#ffa657",
              "SHORT-TERM ONLY": "#d2a8ff", "STAY OUT": "#f85149", "ALL DAYS": "#58a6ff"}

    all_row = results.copy()
    all_row["signal"] = "ALL DAYS"
    combined = pd.concat([results, all_row])

    stats = []
    for sig in order:
        subset = combined[combined["signal"] == sig]["fwd_return"].dropna()
        if len(subset) == 0:
            continue
        stats.append({
            "Signal":        sig,
            "Count":         len(subset),
            "Avg Return":    subset.mean(),
            "Median Return": subset.median(),
            "Win Rate":      (subset > 0).mean(),
            "Strong Win":    (subset >= WIN_THRESHOLD).mean(),
            "Avg Win":       subset[subset > 0].mean() if (subset > 0).any() else 0,
            "Avg Loss":      subset[subset <= 0].mean() if (subset <= 0).any() else 0,
        })

    df_stats = pd.DataFrame(stats).set_index("Signal")

    print(f"\n{'─'*80}")
    print(f"  WALK-FORWARD BACKTEST RESULTS — {TICKER}  "
          f"({results.index[0].date()} to {results.index[-1].date()})")
    print(f"{'─'*80}")
    print(f"  {'Signal':<16} {'Count':>6} {'Avg Ret':>9} {'Median':>8} "
          f"{'Win%':>5} {'Strong%':>8} {'AvgWin':>7} {'AvgLoss':>9}")
    best_sig = df_stats.loc[[s for s in order if s in df_stats.index and s != "ALL DAYS"], "Avg Return"].idxmax()
    print(f"{'─'*80}")
    for sig in order:
        if sig not in df_stats.index:
            continue
        r = df_stats.loc[sig]
        marker = "  <- best avg return" if sig == best_sig else ""
        print(f"  {sig:<16} {int(r['Count']):>6} {r['Avg Return']:>8.1%} "
              f"{r['Median Return']:>8.1%} {r['Win Rate']:>7.1%} "
              f"{r['Strong Win']:>7.1%} {r['Avg Win']:>7.1%} "
              f"{r['Avg Loss']:>8.1%}{marker}")
    print(f"{'─'*80}\n")

    return df_stats, order, colors


# ─────────────────────────────────────────
# 7. PLOT RESULTS
# ─────────────────────────────────────────
def plot_results(df_stats, order, colors, results):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), facecolor="#0d1117")
    fig.suptitle(f"{TICKER} Walk-Forward Backtest — {P2_FORWARD_DAYS}d Forward Returns by Signal",
                 color="white", fontsize=13)

    present = [s for s in order if s in df_stats.index]
    bar_colors = [colors[s] for s in present]

    # Avg return by signal
    ax1 = axes[0]
    ax1.set_facecolor("#0d1117")
    avg_returns = [df_stats.loc[s, "Avg Return"] * 100 for s in present]
    bars = ax1.bar(present, avg_returns, color=bar_colors, width=0.5, alpha=0.85)
    ax1.axhline(0, color="#8b949e", lw=0.8)
    for bar, val in zip(bars, avg_returns):
        ax1.text(bar.get_x() + bar.get_width() / 2, val + (0.2 if val >= 0 else -0.4),
                 f"{val:.1f}%", ha="center", va="bottom" if val >= 0 else "top",
                 color="white", fontsize=9)
    ax1.set_title("Average 15d Return by Signal", color="white", pad=10)
    ax1.set_ylabel("Return (%)", color="#e6edf3")
    ax1.tick_params(colors="#8b949e")
    ax1.spines[:].set_color("#30363d")

    # Strong win rate by signal (>=5%)
    ax2 = axes[1]
    ax2.set_facecolor("#0d1117")
    strong_wins = [df_stats.loc[s, "Strong Win"] * 100 for s in present]
    bars2 = ax2.bar(present, strong_wins, color=bar_colors, width=0.5, alpha=0.85)
    for bar, val in zip(bars2, strong_wins):
        ax2.text(bar.get_x() + bar.get_width() / 2, val + 0.3,
                 f"{val:.1f}%", ha="center", va="bottom",
                 color="white", fontsize=9)
    ax2.set_title(f"Strong Win Rate (>={WIN_THRESHOLD*100:.0f}% gain) by Signal",
                  color="white", pad=10)
    ax2.set_ylabel("Win Rate (%)", color="#e6edf3")
    ax2.tick_params(colors="#8b949e")
    ax2.spines[:].set_color("#30363d")

    plt.tight_layout()
    out = os.path.join(DATA_DIR, f"{TICKER.lower()}_backtest.png")
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor="#0d1117")
    print(f"Chart saved -> {out}")
    if input("Show chart? [y/N]: ").strip().lower() == "y":
        plt.show()


# ─────────────────────────────────────────
# VOL-ADJUSTED THRESHOLDS
# ─────────────────────────────────────────
def compute_vol_thresholds(df):
    global WIN_THRESHOLD, WIN_THRESHOLD_63, EXPANSION_THRESHOLD
    log_ret   = np.log(df["Close"] / df["Close"].shift(1))
    hv_series = log_ret.rolling(HV_WINDOW).std() * np.sqrt(252)
    hv_valid  = hv_series.dropna()

    print("\nVol-Adjusted Threshold Calibration")
    print("─" * 42)
    if len(hv_valid) < 20 or hv_valid.median() < 0.05:
        print("  WARNING: Insufficient/invalid HV data — using AMD defaults.")
        print("─" * 42)
        return

    median_hv     = hv_valid.median()
    new_win       = P2_VOL_MULTIPLE * median_hv * np.sqrt(P2_FORWARD_DAYS / 252)
    new_win_63    = P2_VOL_MULTIPLE * median_hv * np.sqrt(P2B_FORWARD_DAYS / 252)
    new_expansion = P3_VOL_MULTIPLE * median_hv
    print(f"  Ticker median HV (20-day, annualized): {median_hv:.1%}")
    print(f"  WIN_THRESHOLD:       0.05 (AMD default)  ->  {new_win:.1%}  [computed]")
    print(f"  WIN_THRESHOLD_63:    0.10 (AMD default)  ->  {new_win_63:.1%}  [computed]")
    print(f"  EXPANSION_THRESHOLD: 0.10 (AMD default)  ->  {new_expansion:.1%}  [computed]")
    print("─" * 42)
    WIN_THRESHOLD       = new_win
    WIN_THRESHOLD_63    = new_win_63
    EXPANSION_THRESHOLD = new_expansion


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    ticker_in = input(f"  Ticker [{TICKER}]: ").strip().upper()
    if ticker_in:
        TICKER         = ticker_in
        INDICATORS_CSV = os.path.join(DATA_DIR, f"{TICKER.lower()}_indicators.csv")

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

    df_full = build_features(df, benchmarks)

    print("Running walk-forward backtest...")
    print(f"  Min training window: {MIN_TRAIN_DAYS} days (~2 years)")
    print(f"  Step / test window:  {STEP_DAYS} days (~6 months)")
    print()

    results = run_backtest(df_full)

    df_stats, order, colors = summarize(results)
    plot_results(df_stats, order, colors, results)

    out = os.path.join(DATA_DIR, f"{TICKER.lower()}_backtest_results.csv")
    results.to_csv(out)
    print(f"Full results saved -> {out}")
