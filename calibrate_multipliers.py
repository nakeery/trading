"""
Multiplier Calibration Sweep — Phase 2 / Phase 3
=================================================
Sweeps P2_VOL_MULTIPLE and P3_VOL_MULTIPLE over their practical ranges and
measures model edge for each value, on one or more tickers.

Production multipliers (0.41 / 0.20) were chosen using AMD as reference and
empirically validated on QQQ. This script tests whether a longer, lower-noise
calibration source (e.g. ^GSPC back to 1950s) would produce a meaningfully
different optimum.

Usage:
    cmd /c "(echo ^GSPC,QQQ && echo.) | python -X utf8 calibrate_multipliers.py" 2>&1

Prereq: each ticker must have data/{ticker_lower}_indicators.csv generated first
(via `python indicators.py`).

Output:
    data/{ticker}_multiplier_sweep.csv
    data/multiplier_calibration.png
"""

import os
import sys
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import precision_score
from modules.benchmarks import (
    detect_benchmarks, detect_macro_features, add_macro_features,
    add_catalyst_proximity,
)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
DATA_DIR   = "data"
MODULE_DIR = "modules"

HV_WINDOW       = 20
IV_RANK_WINDOW  = 252
P2_FORWARD_DAYS = 15
P3_FORWARD_DAYS = 10
TEST_SIZE       = 0.20
P2_DECISION     = 0.55
P3_DECISION     = 0.60
RANDOM_STATE    = 42

# Sweep ranges
P2_MULT_GRID = np.round(np.arange(0.20, 1.81, 0.05), 3)
P3_MULT_GRID = np.round(np.arange(0.10, 0.41, 0.025), 4)

# Production values (for marking on plots)
PROD_P2_MULT = 0.41
PROD_P3_MULT = 0.20


# ─────────────────────────────────────────
# LOAD + FEATURE ENGINEERING
# (mirrors direction.py / volatility.py)
# ─────────────────────────────────────────
def load_indicators(ticker):
    path = os.path.join(DATA_DIR, f"{ticker.lower()}_indicators.csv")
    if not os.path.exists(path):
        print(f"  ERROR: {path} not found. Run indicators.py for {ticker} first.")
        sys.exit(1)
    df = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    if "Adj Close" in df.columns:
        df.drop(columns=["Adj Close"], inplace=True)
    if "Ticker" in df.columns:
        df.drop(columns=["Ticker"], inplace=True)
    return df


def add_hv_block(df):
    log_ret = np.log(df["Close"] / df["Close"].shift(1))
    df["HV_20"] = log_ret.rolling(HV_WINDOW).std() * np.sqrt(252)
    hv_high = df["HV_20"].rolling(IV_RANK_WINDOW).max()
    hv_low  = df["HV_20"].rolling(IV_RANK_WINDOW).min()
    df["IV_rank"] = (df["HV_20"] - hv_low) / (hv_high - hv_low)
    df["IV_pct"]  = df["HV_20"].rolling(IV_RANK_WINDOW).apply(
        lambda x: (x[:-1] < x[-1]).mean(), raw=True
    )
    df["HV_chg_5d"]  = df["HV_20"].pct_change(5)
    df["HV_chg_10d"] = df["HV_20"].pct_change(10)
    df["HV_vs_ma20"] = df["HV_20"] / df["HV_20"].rolling(20).mean() - 1
    return df


def add_vix_block(df, start, end):
    raw = yf.download("^VIX", start=start, end=end, progress=False)
    raw.columns = raw.columns.get_level_values(0)
    vix = raw[["Close"]].rename(columns={"Close": "VIX"})
    vix["VIX_chg_5d"]  = vix["VIX"].pct_change(5)
    vix["VIX_vs_ma20"] = vix["VIX"] / vix["VIX"].rolling(20).mean() - 1
    df = df.join(vix, how="left")
    df[["VIX", "VIX_chg_5d", "VIX_vs_ma20"]] = df[["VIX", "VIX_chg_5d", "VIX_vs_ma20"]].ffill()
    return df


def add_benchmarks_block(df, ticker, start, end):
    benchmarks = detect_benchmarks(ticker)
    # Filter self-references (e.g. ^GSPC vs SPX fallback which is itself)
    benchmarks = [(bt, bn) for bt, bn in benchmarks if bt.upper() != ticker.upper()]
    if not benchmarks:
        print(f"  (no cross-benchmark available for {ticker} — skipping RS features)")
        return df
    for bt, bn in benchmarks:
        raw = yf.download(bt, start=start, end=end, progress=False)
        raw.columns = raw.columns.get_level_values(0)
        col = f"_BENCH_{bn}"
        bench = raw[["Close"]].rename(columns={"Close": col})
        df = df.join(bench, how="left")
        df[col] = df[col].ffill()
        for w in [5, 20]:
            df[f"{bn}_RS_{w}d"] = df["Close"].pct_change(w) - df[col].pct_change(w)
        df[f"{bn}_vs_ma200"] = df[col] / df[col].rolling(200).mean() - 1
        df.drop(columns=[col], inplace=True)
    return df


def add_earnings_block(df, ticker):
    try:
        dates = yf.Ticker(ticker).get_earnings_dates(limit=20)
        if dates is not None and len(dates) > 0:
            idx = pd.DatetimeIndex(dates.index)
            if idx.tz is not None:
                idx = idx.tz_convert(None)
            ed = sorted(idx.normalize().unique())
        else:
            ed = []
    except Exception:
        ed = []

    if not ed:
        df["Days_to_earnings"] = 45
        return df

    def _days_to_next(d):
        fut = [e for e in ed if e >= d]
        return (fut[0] - d).days if fut else 90

    df["Days_to_earnings"] = [_days_to_next(d) for d in df.index]
    return df


def normalize_features(df):
    close = df["Close"]
    df["price_vs_52w_high"] = close / close.rolling(252).max() - 1
    df["price_vs_52w_low"]  = close / close.rolling(252).min() - 1
    df["vol_ratio"]         = df["Volume"] / df["Volume"].rolling(20).mean()

    for p in [20, 50, 200]:
        col = f"MA_{p}"
        if col in df.columns:
            df[f"price_vs_ma{p}"] = close / df[col] - 1
    df.drop(columns=[c for c in df.columns if c.startswith("MA_")], inplace=True)

    for p in [8, 21, 89]:
        col = f"EMA_{p}"
        if col in df.columns:
            df[f"price_vs_ema{p}"] = close / df[col] - 1
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
    return df


def build_p2_features(ticker):
    """Mirror direction.py feature set: HV_20 only, with VIX/benchmarks/earnings/catalyst."""
    df = load_indicators(ticker)
    start = df.index.min().strftime("%Y-%m-%d")
    end   = df.index.max().strftime("%Y-%m-%d")

    log_ret = np.log(df["Close"] / df["Close"].shift(1))
    df["HV_20"] = log_ret.rolling(HV_WINDOW).std() * np.sqrt(252)

    df = add_vix_block(df, start, end)
    df = add_benchmarks_block(df, ticker, start, end)
    macro = detect_macro_features(ticker)
    if macro:
        df = add_macro_features(df, macro, start, end)
    df = add_earnings_block(df, ticker)
    df = add_catalyst_proximity(df, ticker, MODULE_DIR, for_direction=True)
    df = normalize_features(df)
    return df


def build_p3_features(ticker):
    """Mirror volatility.py feature set: full IV block, VIX, macro, earnings, catalyst (no benchmarks)."""
    df = load_indicators(ticker)
    start = df.index.min().strftime("%Y-%m-%d")
    end   = df.index.max().strftime("%Y-%m-%d")

    df = add_hv_block(df)
    df = add_vix_block(df, start, end)
    macro = detect_macro_features(ticker)
    if macro:
        df = add_macro_features(df, macro, start, end)
    df = add_earnings_block(df, ticker)
    df = add_catalyst_proximity(df, ticker, MODULE_DIR, for_direction=False)
    df = normalize_features(df)
    return df


# ─────────────────────────────────────────
# SWEEP CORE
# ─────────────────────────────────────────
def fit_and_score(X, y, decision_threshold):
    """Time-based 80/20 split, fit logistic regression, return precision/base_rate/signals at threshold."""
    if y.sum() < 5 or (len(y) - y.sum()) < 5:
        return None  # degenerate target distribution

    split_idx = int(len(X) * (1 - TEST_SIZE))
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    if y_train.sum() < 3 or y_test.sum() < 3:
        return None

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    clf = LogisticRegression(C=0.1, class_weight="balanced", max_iter=1000,
                             random_state=RANDOM_STATE)
    clf.fit(X_train_s, y_train)
    y_prob = clf.predict_proba(X_test_s)[:, 1]
    y_pred = (y_prob >= decision_threshold).astype(int)

    base_rate = y_test.mean()
    prec      = precision_score(y_test, y_pred, zero_division=0)
    signals   = int(y_pred.sum())
    return {
        "base_rate": base_rate,
        "precision": prec,
        "signals":   signals,
        "edge":      prec - base_rate,
        "test_size": len(y_test),
    }


def sweep_p2(df, median_hv):
    """Phase 2 (15-day direction) sweep across P2_VOL_MULTIPLE."""
    rows = []
    exclude = {"Open", "High", "Low", "Close", "Volume", "target"}
    feature_cols_base = [c for c in df.columns if c not in exclude]

    future_close = df["Close"].shift(-P2_FORWARD_DAYS)
    fwd_ret = future_close / df["Close"] - 1
    df_trim = df.iloc[:-P2_FORWARD_DAYS].copy()
    fwd_ret = fwd_ret.iloc[:-P2_FORWARD_DAYS]

    for mult in P2_MULT_GRID:
        win_thresh = mult * median_hv * np.sqrt(P2_FORWARD_DAYS / 252)
        target = (fwd_ret >= win_thresh).astype(int)

        df_model = df_trim[feature_cols_base].copy()
        df_model["target"] = target
        df_model = df_model.dropna()
        X = df_model[feature_cols_base]
        y = df_model["target"]

        result = fit_and_score(X, y, P2_DECISION)
        if result is None:
            rows.append({"multiplier": mult, "win_threshold": win_thresh,
                         "precision": np.nan, "base_rate": np.nan,
                         "signals": 0, "edge": np.nan, "score": np.nan})
            continue

        score = result["edge"] * np.log(result["signals"] + 1) if result["edge"] > 0 else 0.0
        rows.append({
            "multiplier":    float(mult),
            "win_threshold": float(win_thresh),
            "precision":     float(result["precision"]),
            "base_rate":     float(result["base_rate"]),
            "signals":       int(result["signals"]),
            "edge":          float(result["edge"]),
            "score":         float(score),
        })
    return pd.DataFrame(rows)


def sweep_p3(df, median_hv):
    """Phase 3 (IV expansion) sweep across P3_VOL_MULTIPLE."""
    rows = []
    exclude = {"Open", "High", "Low", "Close", "Volume", "target"}
    feature_cols_base = [c for c in df.columns if c not in exclude]

    future_hv = df["HV_20"].shift(-P3_FORWARD_DAYS)
    fwd_chg = future_hv / df["HV_20"] - 1
    df_trim = df.iloc[:-P3_FORWARD_DAYS].copy()
    fwd_chg = fwd_chg.iloc[:-P3_FORWARD_DAYS]

    for mult in P3_MULT_GRID:
        exp_thresh = mult * median_hv
        target = (fwd_chg >= exp_thresh).astype(int)

        df_model = df_trim[feature_cols_base].copy()
        df_model["target"] = target
        df_model = df_model.dropna()
        X = df_model[feature_cols_base]
        y = df_model["target"]

        result = fit_and_score(X, y, P3_DECISION)
        if result is None:
            rows.append({"multiplier": mult, "expansion_threshold": exp_thresh,
                         "precision": np.nan, "base_rate": np.nan,
                         "signals": 0, "edge": np.nan, "score": np.nan})
            continue

        score = result["edge"] * np.log(result["signals"] + 1) if result["edge"] > 0 else 0.0
        rows.append({
            "multiplier":          float(mult),
            "expansion_threshold": float(exp_thresh),
            "precision":           float(result["precision"]),
            "base_rate":           float(result["base_rate"]),
            "signals":             int(result["signals"]),
            "edge":                float(result["edge"]),
            "score":               float(score),
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────
# PLOT
# ─────────────────────────────────────────
def plot_sweeps(results_by_ticker):
    n = len(results_by_ticker)
    fig, axes = plt.subplots(n, 2, figsize=(13, 4.2 * n), facecolor="#0d1117", squeeze=False)
    fig.suptitle("Multiplier Calibration Sweep — Edge vs Multiplier",
                 color="white", fontsize=13)

    for i, (ticker, (p2_df, p3_df)) in enumerate(results_by_ticker.items()):
        ax_p2 = axes[i, 0]; ax_p3 = axes[i, 1]
        for ax in (ax_p2, ax_p3):
            ax.set_facecolor("#161b22")
            ax.tick_params(colors="#8b949e")
            ax.spines[:].set_color("#30363d")
            ax.grid(True, color="#30363d", lw=0.4, alpha=0.5)

        # P2
        ax_p2.plot(p2_df["multiplier"], p2_df["edge"] * 100,
                   marker="o", color="#58a6ff", lw=1.2, label="edge (precision − base)")
        ax_p2.axhline(0, color="#8b949e", lw=0.6)
        ax_p2.axvline(PROD_P2_MULT, color="#ffa657", lw=1, ls="--",
                      label=f"prod = {PROD_P2_MULT}")
        valid = p2_df.dropna(subset=["score"])
        if not valid.empty and valid["score"].max() > 0:
            best = valid.loc[valid["score"].idxmax()]
            ax_p2.axvline(best["multiplier"], color="#3fb950", lw=1, ls=":",
                          label=f"optimal = {best['multiplier']:.2f}")
        ax_p2.set_title(f"{ticker} — Phase 2 (15d direction)",
                        color="white", fontsize=10, pad=8)
        ax_p2.set_xlabel("P2_VOL_MULTIPLE", color="#8b949e", fontsize=8)
        ax_p2.set_ylabel("edge (pp)", color="#e6edf3", fontsize=8)
        ax_p2.legend(fontsize=7, facecolor="#161b22", labelcolor="white")

        # P3
        ax_p3.plot(p3_df["multiplier"], p3_df["edge"] * 100,
                   marker="o", color="#a5a5ff", lw=1.2, label="edge (precision − base)")
        ax_p3.axhline(0, color="#8b949e", lw=0.6)
        ax_p3.axvline(PROD_P3_MULT, color="#ffa657", lw=1, ls="--",
                      label=f"prod = {PROD_P3_MULT}")
        valid = p3_df.dropna(subset=["score"])
        if not valid.empty and valid["score"].max() > 0:
            best = valid.loc[valid["score"].idxmax()]
            ax_p3.axvline(best["multiplier"], color="#3fb950", lw=1, ls=":",
                          label=f"optimal = {best['multiplier']:.3f}")
        ax_p3.set_title(f"{ticker} — Phase 3 (IV expansion)",
                        color="white", fontsize=10, pad=8)
        ax_p3.set_xlabel("P3_VOL_MULTIPLE", color="#8b949e", fontsize=8)
        ax_p3.set_ylabel("edge (pp)", color="#e6edf3", fontsize=8)
        ax_p3.legend(fontsize=7, facecolor="#161b22", labelcolor="white")

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    out = os.path.join(DATA_DIR, "multiplier_calibration.png")
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor="#0d1117")
    print(f"\nChart saved -> {out}")


# ─────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────
def print_summary(results_by_ticker):
    print()
    print("=" * 78)
    print(f"  CALIBRATION SUMMARY  (production: P2_VOL_MULTIPLE={PROD_P2_MULT}, "
          f"P3_VOL_MULTIPLE={PROD_P3_MULT})")
    print("=" * 78)
    print(f"  {'Ticker':<8} {'Phase':<10} {'Optimal':>9} {'Edge@opt':>10} "
          f"{'Edge@prod':>11} {'Δ vs prod':>11}")
    print("-" * 78)
    for ticker, (p2_df, p3_df) in results_by_ticker.items():
        for label, df, prod in [("P2 (15d)", p2_df, PROD_P2_MULT),
                                 ("P3 (IV)", p3_df, PROD_P3_MULT)]:
            valid = df.dropna(subset=["score"])
            if valid.empty or valid["score"].max() <= 0:
                print(f"  {ticker:<8} {label:<10} {'-':>9} {'-':>10} {'-':>11} {'-':>11}")
                continue
            best = valid.loc[valid["score"].idxmax()]
            opt_mult  = best["multiplier"]
            opt_edge  = best["edge"] * 100
            prod_row  = df.iloc[(df["multiplier"] - prod).abs().argmin()]
            prod_edge = prod_row["edge"] * 100
            delta     = opt_mult - prod
            print(f"  {ticker:<8} {label:<10} {opt_mult:>9.3f} "
                  f"{opt_edge:>9.1f}pp {prod_edge:>10.1f}pp {delta:>+11.3f}")
    print("=" * 78)
    print("\nDecision rule:")
    print("  P2: |Δ| ≤ 0.10 → no change to 0.41")
    print("  P3: |Δ| ≤ 0.05 → no change to 0.20")
    print("  Otherwise: check whether SPX-optimal and QQQ-optimal agree before updating constants.")


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    while True:
        try:
            raw = input("  Tickers (comma-separated) [^GSPC,QQQ]: ").strip().upper()
            tickers = [t.strip() for t in raw.split(",") if t.strip()] if raw else ["^GSPC", "QQQ"]
            break
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)

    print(f"\nCalibrating multipliers for: {', '.join(tickers)}")
    print(f"P2 grid: {len(P2_MULT_GRID)} values  [{P2_MULT_GRID[0]:.2f} → {P2_MULT_GRID[-1]:.2f}]")
    print(f"P3 grid: {len(P3_MULT_GRID)} values  [{P3_MULT_GRID[0]:.3f} → {P3_MULT_GRID[-1]:.3f}]")

    results = {}
    for ticker in tickers:
        print(f"\n--- {ticker} ---")
        print(f"  building Phase 2 features (direction.py parity)...")
        df_p2 = build_p2_features(ticker)
        print(f"  building Phase 3 features (volatility.py parity)...")
        df_p3 = build_p3_features(ticker)

        log_ret   = np.log(df_p2["Close"] / df_p2["Close"].shift(1))
        hv_full   = (log_ret.rolling(HV_WINDOW).std() * np.sqrt(252)).dropna()
        median_hv = hv_full.median()
        print(f"  {ticker}: {len(df_p2)} rows  |  median HV: {median_hv:.1%}")

        print(f"  sweeping P2 ({len(P2_MULT_GRID)} values)...")
        p2_df = sweep_p2(df_p2, median_hv)
        print(f"  sweeping P3 ({len(P3_MULT_GRID)} values)...")
        p3_df = sweep_p3(df_p3, median_hv)

        # Persist per-ticker
        out_path = os.path.join(DATA_DIR, f"{ticker.lower()}_multiplier_sweep.csv")
        combined = pd.concat([
            p2_df.assign(phase="P2"),
            p3_df.rename(columns={"expansion_threshold": "win_threshold"}).assign(phase="P3"),
        ], ignore_index=True)
        combined.to_csv(out_path, index=False)
        print(f"  saved -> {out_path}")

        results[ticker] = (p2_df, p3_df)

    plot_sweeps(results)
    print_summary(results)
