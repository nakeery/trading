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

import argparse
import os
import sys
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from modules.benchmarks import detect_benchmarks, detect_macro_features, add_catalyst_proximity
from modules.econ_calendar import add_macro_event_proximity
from modules.massive import IV_COLS, IV_META_COLS, IV_FEATURE_COLS, IV_INDICATOR_COLS
from modules.regime import classify_regime, apply_regime_gate
from modules.features import (
    HV_WINDOW, IV_RANK_WINDOW,
    P2_FORWARD_DAYS, P2B_FORWARD_DAYS, P3_FORWARD_DAYS,
    P2_VOL_MULTIPLE, P2B_VOL_MULTIPLE, P3_VOL_MULTIPLE, P4_VOL_MULTIPLE,
    compute_hv_features, compute_vix_features, add_trend_break_features,
    add_bear_duration_features,
    compute_p4_drawdown_threshold, add_p4_drawdown_target,
    add_earnings_proximity, normalize_features, compute_vol_thresholds,
    impute_iv_features,
)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
# TICKER         = ""
START_DATE     = "2018-01-01"
END_DATE       = ""  # set automatically from CSV
DATA_DIR       = "data"
MODULE_DIR     = "modules"
# INDICATORS_CSV = os.path.join(DATA_DIR, f"{TICKER.lower()}_indicators.csv")

# HV_WINDOW, IV_RANK_WINDOW, P2_FORWARD_DAYS, P2B_FORWARD_DAYS, P3_FORWARD_DAYS
# imported from modules.features
WIN_THRESHOLD       = 0.05  # Default (AMD). Set by compute_vol_thresholds() in __main__
WIN_THRESHOLD_63    = 0.10  # Default (AMD). Set by compute_vol_thresholds() in __main__
EXPANSION_THRESHOLD = 0.10  # Default (AMD). Set by compute_vol_thresholds() in __main__
# P2_VOL_MULTIPLE, P2B_VOL_MULTIPLE, P3_VOL_MULTIPLE imported from modules.features
P2_CALIBRATE        = False  # Decision 1 (S11) reverted as default after NVDA regression (STRONG ENTRY 4.4% → -0.4%). Pass --calibrate to enable.
P2_THRESHOLD        = 0.55   # Phase 2 (15d) cutoff. Set from P2_CALIBRATE in __main__: 0.50 calibrated / 0.55 raw.
P2B_THRESHOLD       = 0.55  # Phase 2B (63d) raw cutoff — calibration deferred to Decision 2
P3_THRESHOLD        = 0.60
BAND_CAP            = 0.70  # Phase 2 confidence band (S31): dir_prob >= this is the "inverted tail"
BAND_MIN_TAIL       = 30    # min training-window tail signals before the band can activate
BAND_RATIO          = 0.50  # activate band iff tail_avg < BAND_RATIO × mid_avg (training outcomes)
P4_FORWARD_DAYS     = 15   # Phase 4 exit window — aligned to entry.py/exit.py 15d production default.
                           # NOTE: was 5 from S18 (commit 6fb8131) until 2026-06-12 — all P4-gate
                           # A/B numbers before then, incl. the S18 rejection, were 5d-gate results.
P4_THRESHOLD        = 0.55  # Phase 4 drawdown cutoff
RANDOM_STATE        = 42

IV_FEATURES   = False  # set by --iv-features CLI arg; when True, Phase 3 uses IV_FEATURE_COLS as features
ECON_FEATURES = False  # set by --econ-features CLI arg; when True, Days_to_FOMC/CPI/... added
BEAR_DURATION = False  # set by --bear-duration CLI arg (S31); when True, adds days_below_ma200 + days_since_52w_high

# Walk-forward parameters
# MIN_TRAIN_DAYS = 504   # ~2 years minimum training window
MIN_TRAIN_DAYS = 252   # ~1 year minimum training window
STEP_DAYS      = 126   # ~6 months between retrains

# Multiplier sweep — list of (P2_VOL_MULTIPLE, P2B_VOL_MULTIPLE, P3_VOL_MULTIPLE) tuples.
# Empty list = single run with the production constants from modules.features (default behavior).
# When non-empty, runs the full walk-forward backtest for each combination,
# then prints a comparison table identifying the best by STRONG ENTRY avg return.
# Features are built once and reused; only target labels and model fits vary per run.
MULTIPLIER_SWEEP = []
# NVDA P2B sweep — uncomment to re-run (production validated at P2B=0.55):
# MULTIPLIER_SWEEP = [
#     (0.41, 0.25, 0.20),
#     (0.41, 0.35, 0.20),
#     (0.41, 0.45, 0.20),
#     (0.41, 0.55, 0.20),  # production
#     (0.41, 0.65, 0.20),
#     (0.41, 0.75, 0.20),
#     (0.41, 0.85, 0.20),
#     (0.41, 0.95, 0.20),
#     (0.41, 1.05, 0.20),
#     (0.41, 1.15, 0.20),
#     (0.41, 1.25, 0.20),
#     (0.41, 1.35, 0.20),
#     (0.41, 1.45, 0.20),
# ]


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
    df = compute_hv_features(df)

    # VIX (uses local cache for performance across walk-forward windows)
    df = compute_vix_features(
        df,
        _fetch_cached("^VIX",   "vix_cache.csv"),
        _fetch_cached("^VIX9D", "vix9d_cache.csv"),
        _fetch_cached("^VIX3M", "vix3m_cache.csv"),
    )

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
        macro_cols = []
        for symbol, name in macro_features:
            rate_raw = _fetch_cached(symbol, f"{name.lower()}_cache.csv")
            series = rate_raw[["Close"]].rename(columns={"Close": name})
            series[f"{name}_chg_5d"]  = series[name].pct_change(5)
            series[f"{name}_vs_ma20"] = series[name] / series[name].rolling(20).mean() - 1
            df = df.join(series, how="left")
            ff_cols = [name, f"{name}_chg_5d", f"{name}_vs_ma20"]
            df[ff_cols] = df[ff_cols].ffill()
            macro_cols += ff_cols
            fetched[name] = True
        if "UST10Y" in fetched and "UST3M" in fetched:
            df["yield_curve"]        = df["UST10Y"] - df["UST3M"]
            # diff(5), not pct_change(5): the 10Y-3M spread crosses zero at curve
            # inversions (e.g. 2007-08-10), so a percentage change divides by ~0 and
            # explodes to +inf (crashes StandardScaler). An absolute 5-day change in the
            # spread (percentage points) is well-defined through the zero crossing.
            df["yield_curve_chg_5d"] = df["yield_curve"].diff(5)
            macro_cols += ["yield_curve", "yield_curve_chg_5d"]
        # Defensive: near-zero / negative short rates (^IRX during ZIRP and the 2008
        # panic) can still make a pct_change/ratio feature non-finite; convert any inf
        # to NaN so the affected row drops out cleanly rather than crashing the model.
        if macro_cols:
            df[macro_cols] = df[macro_cols].replace([np.inf, -np.inf], np.nan)

    df = add_earnings_proximity(df, TICKER)
    df = add_catalyst_proximity(df, TICKER, MODULE_DIR, for_direction=True)
    if ECON_FEATURES:
        df = add_macro_event_proximity(df, DATA_DIR)
    df = add_trend_break_features(df)  # must precede normalize_features (drops MA cols)
    if BEAR_DURATION:
        df = add_bear_duration_features(df)  # also pre-normalize (needs MA_200)
    df = normalize_features(df)

    # Overnight gap features — computed fresh (not read from CSV) for self-containment
    if "gap_pct" not in df.columns:
        df["gap_pct"]    = (df["Open"] - close.shift(1)) / close.shift(1)
        df["gap_ma_5d"]  = df["gap_pct"].rolling(5).mean()
        df["gap_vol_5d"] = df["gap_pct"].abs().rolling(5).mean()

    print("Features built.\n")
    return df


# ─────────────────────────────────────────
# 4. TRAIN A SINGLE MODEL
# ─────────────────────────────────────────
def train_model(df_train, target_col, calibrate=False, use_iv_features=False):
    # use_iv_features=True: include IV_FEATURE_COLS (+ iv_available/term_available indicators)
    #   as features (Phase 3 only when --iv-features); dropna() auto-limits training to the
    #   ~2yr backfilled window.
    # default (Phase 2/2B/4): exclude all IV_COLS *and* the impute indicator cols, so the
    #   full price history is used and --iv-features stays Phase-3-scoped (no Phase 2/2B leak).
    exclude = {"Open", "High", "Low", "Close", "Volume", target_col,
               "Days_to_earnings",  # S31: dropped from features framework-wide (leak source; display-only)
               *(IV_META_COLS if use_iv_features else IV_COLS + IV_INDICATOR_COLS)}
    feature_cols = [c for c in df_train.columns if c not in exclude]

    df_model = df_train[feature_cols + [target_col]].dropna()
    if len(df_model) < 50:
        return None, None, None

    X = df_model[feature_cols]
    y = df_model[target_col].values

    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)

    if calibrate:
        clf = CalibratedClassifierCV(
            LogisticRegression(C=0.1, class_weight="balanced",
                               max_iter=1000, random_state=RANDOM_STATE),
            method="isotonic",
            cv=5,
        )
        clf.fit(X_s, y)
    else:
        clf = LogisticRegression(C=0.1, class_weight="balanced",
                                 max_iter=1000, random_state=RANDOM_STATE)
        clf.fit(X_s, y)
    return clf, scaler, feature_cols


# ─────────────────────────────────────────
# 4B. PHASE 2 CONFIDENCE BAND — in-window self-test (S31)
# ─────────────────────────────────────────
def compute_band_active(clf2, scaler2, fcols2, df_p2, p2_ret,
                        band_cap=BAND_CAP, min_tail=BAND_MIN_TAIL, ratio=BAND_RATIO):
    """Decide — using ONLY training-window data — whether the high-confidence tail
    underperforms the mid band, i.e. whether the S25 NVDA inversion is present for
    THIS ticker/window. No lookahead: probabilities and realized 15d returns both
    come from the training slice.

    Returns True iff the band should activate: tail ([band_cap, 1]) has >= min_tail
    signals and its mean realized return is below ratio × the mid band's
    ([P2_THRESHOLD, band_cap)) mean. mid_avg must be positive (a broken-signal
    window where the mid band itself doesn't pay should not trigger a veto)."""
    if clf2 is None or fcols2 is None:
        return False
    sub = df_p2[fcols2].dropna()
    if len(sub) < 50:
        return False
    prob = clf2.predict_proba(scaler2.transform(sub))[:, 1]
    realized = p2_ret.reindex(sub.index).values
    mid_mask  = (prob >= P2_THRESHOLD) & (prob < band_cap)
    tail_mask = (prob >= band_cap)
    if tail_mask.sum() < min_tail or mid_mask.sum() < min_tail:
        return False
    mid_avg  = np.nanmean(realized[mid_mask])
    tail_avg = np.nanmean(realized[tail_mask])
    if not np.isfinite(mid_avg) or not np.isfinite(tail_avg) or mid_avg <= 0:
        return False
    return tail_avg < ratio * mid_avg


# ─────────────────────────────────────────
# 5. WALK-FORWARD BACKTEST
# ─────────────────────────────────────────
def run_backtest(df_full, p2_mult=None, p2b_mult=None, p3_mult=None, side="call"):
    global WIN_THRESHOLD, WIN_THRESHOLD_63, EXPANSION_THRESHOLD
    # Sweep mode passes per-iteration multipliers; default to production constants.
    if p2_mult  is None: p2_mult  = P2_VOL_MULTIPLE
    if p2b_mult is None: p2b_mult = P2B_VOL_MULTIPLE
    if p3_mult  is None: p3_mult  = P3_VOL_MULTIPLE
    close = df_full["Close"]
    n     = len(df_full)
    results = []
    window_num = 0

    # Regime classification is data-only (VIX/VIX3M ratio), no model — precompute once
    # across the full df.  Gated against ungated signal independently of P4 gate.
    regime_series = classify_regime(df_full)

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
        WIN_THRESHOLD, WIN_THRESHOLD_63, EXPANSION_THRESHOLD = compute_vol_thresholds(
            df_train, verbose=False,
            p2_vol_multiple=p2_mult, p2b_vol_multiple=p2b_mult, p3_vol_multiple=p3_mult,
        )

        # Phase 2 — 15-day direction target (mode set via CLI flag — see banner)
        df_p2 = df_train.copy()
        fc2 = df_p2["Close"].shift(-P2_FORWARD_DAYS)
        p2_ret = fc2 / df_p2["Close"] - 1
        df_p2["_target"] = ((p2_ret <= -WIN_THRESHOLD) if side == "put"
                            else (p2_ret >= WIN_THRESHOLD)).astype(int)
        df_p2 = df_p2.iloc[:-P2_FORWARD_DAYS]
        clf2, scaler2, fcols2 = train_model(df_p2, "_target", calibrate=P2_CALIBRATE)

        # Phase 2B — 63-day direction target
        df_p2b = df_train.copy()
        fc2b = df_p2b["Close"].shift(-P2B_FORWARD_DAYS)
        p2b_ret = fc2b / df_p2b["Close"] - 1
        df_p2b["_target"] = ((p2b_ret <= -WIN_THRESHOLD_63) if side == "put"
                             else (p2b_ret >= WIN_THRESHOLD_63)).astype(int)
        df_p2b = df_p2b.iloc[:-P2B_FORWARD_DAYS]
        clf2b, scaler2b, fcols2b = train_model(df_p2b, "_target")

        # Phase 3 — IV expansion target
        df_p3 = df_train.copy()
        fh3 = df_p3["HV_20"].shift(-P3_FORWARD_DAYS)
        df_p3["_target"] = ((fh3 / df_p3["HV_20"] - 1) >= EXPANSION_THRESHOLD).astype(int)
        df_p3 = df_p3.iloc[:-P3_FORWARD_DAYS]
        clf3, scaler3, fcols3 = train_model(df_p3, "_target", use_iv_features=IV_FEATURES)

        # Phase 4 — exit risk target (15d max drawdown). Per-window threshold avoids lookahead.
        p4_threshold_window = compute_p4_drawdown_threshold(df_train, P4_FORWARD_DAYS)
        df_p4 = add_p4_drawdown_target(df_train, P4_FORWARD_DAYS, p4_threshold_window, target_col="_target")
        clf4, scaler4, fcols4 = train_model(df_p4, "_target")

        if clf2 is None or clf2b is None or clf3 is None or clf4 is None:
            train_end += STEP_DAYS
            continue

        # Phase 2 confidence band (S31): in-window self-test decides band ON/OFF for
        # this window (call side only — the S25 inversion evidence is call/long).
        band_active = (side == "call") and compute_band_active(
            clf2, scaler2, fcols2, df_p2, p2_ret)

        # Generate signals on test period
        for i in range(test_start, test_end):
            date = df_full.index[i]

            row2  = df_full[fcols2].iloc[i]
            row2b = df_full[fcols2b].iloc[i]
            row3  = df_full[fcols3].iloc[i]
            row4  = df_full[fcols4].iloc[i]
            if row2.isna().any() or row2b.isna().any() or row3.isna().any() or row4.isna().any():
                continue

            X2  = pd.DataFrame([row2],  columns=fcols2)
            X2b = pd.DataFrame([row2b], columns=fcols2b)
            X3  = pd.DataFrame([row3],  columns=fcols3)
            X4  = pd.DataFrame([row4],  columns=fcols4)
            dir_prob    = clf2.predict_proba(scaler2.transform(X2))[0, 1]
            dir_prob_63 = clf2b.predict_proba(scaler2b.transform(X2b))[0, 1]
            exp_prob    = clf3.predict_proba(scaler3.transform(X3))[0, 1]
            exit_prob   = clf4.predict_proba(scaler4.transform(X4))[0, 1]

            dir_signal    = dir_prob    >= P2_THRESHOLD
            dir_signal_63 = dir_prob_63 >= P2B_THRESHOLD
            exp_signal    = exp_prob    >= P3_THRESHOLD
            exit_signal   = exit_prob   >= P4_THRESHOLD

            if dir_signal and dir_signal_63 and exp_signal:
                signal = "STRONG ENTRY"
            elif dir_signal and dir_signal_63 and not exp_signal:
                signal = "CAUTION"
            elif dir_signal and not dir_signal_63:
                signal = "SHORT-TERM ONLY"
            elif not dir_signal and dir_signal_63:
                signal = "LEAPS ONLY"
            else:
                signal = "STAY OUT"

            # Option B (S18): P4 gate — one-tier-down downgrade when exit_signal fires.
            # STRONG ENTRY → CAUTION; CAUTION / SHORT-TERM ONLY → STAY OUT; LEAPS ONLY unchanged.
            if exit_signal and signal == "STRONG ENTRY":
                signal_gated = "CAUTION"
            elif exit_signal and signal in ("CAUTION", "SHORT-TERM ONLY"):
                signal_gated = "STAY OUT"
            else:
                signal_gated = signal

            # VIX regime gate (S21): independent A/B vs ungated signal.  Mirror of entry.py's
            # post-hoc gate — STRONG ENTRY → CAUTION, CAUTION → STAY OUT in stress regime.
            regime = regime_series.loc[date]
            signal_regime_gated, _, _ = apply_regime_gate(signal, "", regime)

            # Phase 2 confidence band (S31): when active for this window, a dir_prob in
            # the inverted tail (>= BAND_CAP) is treated as NO 15d signal, so STRONG/
            # CAUTION/SHORT-TERM fall through to LEAPS ONLY / STAY OUT.
            dir_signal_banded = dir_signal and not (band_active and dir_prob >= BAND_CAP)
            if dir_signal_banded and dir_signal_63 and exp_signal:
                signal_banded = "STRONG ENTRY"
            elif dir_signal_banded and dir_signal_63 and not exp_signal:
                signal_banded = "CAUTION"
            elif dir_signal_banded and not dir_signal_63:
                signal_banded = "SHORT-TERM ONLY"
            elif not dir_signal_banded and dir_signal_63:
                signal_banded = "LEAPS ONLY"
            else:
                signal_banded = "STAY OUT"

            fwd_return = close.iloc[i + P2_FORWARD_DAYS] / close.iloc[i] - 1
            fwd_126 = i + 126
            fwd_return_126d = (
                close.iloc[fwd_126] / close.iloc[i] - 1
                if fwd_126 < len(close) else float("nan")
            )

            results.append({
                "date":                 date,
                "signal":               signal,
                "signal_gated":         signal_gated,
                "signal_regime_gated":  signal_regime_gated,
                "signal_banded":        signal_banded,
                "band_active":          band_active,
                "regime":               regime,
                "dir_prob":             dir_prob,
                "dir_prob_63":          dir_prob_63,
                "exp_prob":             exp_prob,
                "exit_prob":            exit_prob,
                "fwd_return":           fwd_return,
                "fwd_return_126d":      fwd_return_126d,
                "window":               window_num,
            })

        train_end += STEP_DAYS

    return pd.DataFrame(results).set_index("date")


# ─────────────────────────────────────────
# 6. SUMMARIZE RESULTS
# ─────────────────────────────────────────
def summarize(results, signal_col="signal", label="UNGATED", side="call"):
    order  = ["STRONG ENTRY", "CAUTION", "SHORT-TERM ONLY", "LEAPS ONLY", "STAY OUT", "ALL DAYS"]
    colors = {"STRONG ENTRY": "#3fb950", "CAUTION": "#ffa657",
              "SHORT-TERM ONLY": "#d2a8ff", "LEAPS ONLY": "#a5d6ff", "STAY OUT": "#f85149", "ALL DAYS": "#58a6ff"}

    side_tag = f"[{label}]" if side == "call" else f"[PUT / {label}]"
    all_row = results.copy()
    all_row[signal_col] = "ALL DAYS"
    combined = pd.concat([results, all_row])

    stats = []
    for sig in order:
        subset = combined[combined[signal_col] == sig]["fwd_return"].dropna()
        if side == "put":
            subset = -subset          # put gross P&L = -underlying return
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
    print(f"  WALK-FORWARD BACKTEST RESULTS — {TICKER}  {side_tag}  "
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

    # ── 6-month forward return table ──────────────────────────────────────────
    combined_126 = pd.concat([results.copy(), results.copy().assign(**{signal_col: "ALL DAYS"})])
    stats_126 = []
    for sig in order:
        subset = combined_126[combined_126[signal_col] == sig]["fwd_return_126d"].dropna()
        if side == "put":
            subset = -subset
        if len(subset) == 0:
            continue
        stats_126.append({
            "Signal":        sig,
            "Count":         len(subset),
            "Avg Return":    subset.mean(),
            "Median Return": subset.median(),
            "Win Rate":      (subset > 0).mean(),
            "Avg Win":       subset[subset > 0].mean() if (subset > 0).any() else 0,
            "Avg Loss":      subset[subset <= 0].mean() if (subset <= 0).any() else 0,
        })
    df_stats_126 = pd.DataFrame(stats_126).set_index("Signal")

    n_nan = results["fwd_return_126d"].isna().sum()
    print(f"{'─'*80}")
    print(f"  6-MONTH FORWARD RETURNS — {TICKER}  {side_tag}  "
          f"(excl. last 126 trading days; {n_nan} rows NaN)")
    print(f"{'─'*80}")
    print(f"  {'Signal':<16} {'Count':>6} {'Avg Ret':>9} {'Median':>8} "
          f"{'Win%':>7} {'AvgWin':>7} {'AvgLoss':>9}")
    best_126 = df_stats_126.loc[
        [s for s in order if s in df_stats_126.index and s != "ALL DAYS"],
        "Avg Return",
    ].idxmax()
    print(f"{'─'*80}")
    for sig in order:
        if sig not in df_stats_126.index:
            continue
        r = df_stats_126.loc[sig]
        marker = "  <- best avg return" if sig == best_126 else ""
        print(f"  {sig:<16} {int(r['Count']):>6} {r['Avg Return']:>8.1%} "
              f"{r['Median Return']:>8.1%} {r['Win Rate']:>7.1%} "
              f"{r['Avg Win']:>7.1%} {r['Avg Loss']:>8.1%}{marker}")
    print(f"{'─'*80}\n")

    return df_stats, order, colors


def summarize_p4_gate_ab(results):
    """A/B comparison of ungated vs P4-gated STRONG ENTRY metrics.

    Accept criterion: gated STRONG ENTRY avg return strictly > ungated
    AND signal count doesn't collapse below 300 (sample-size floor).
    """
    print(f"\n{'═'*80}")
    print(f"  PHASE 4 GATE — A/B COMPARISON (15d forward returns)")
    print(f"{'═'*80}")
    print(f"  {'Signal':<18} {'Count U':>8} {'Count G':>8} {'Avg U':>8} {'Avg G':>8} {'Δ Avg':>8} {'Win U':>7} {'Win G':>7}")
    print(f"  {'─'*78}")
    for sig in ["STRONG ENTRY", "CAUTION", "SHORT-TERM ONLY", "LEAPS ONLY", "STAY OUT"]:
        u = results[results["signal"] == sig]["fwd_return"].dropna()
        g = results[results["signal_gated"] == sig]["fwd_return"].dropna()
        if len(u) == 0 and len(g) == 0:
            continue
        u_avg  = u.mean() if len(u) > 0 else 0
        g_avg  = g.mean() if len(g) > 0 else 0
        u_win  = (u > 0).mean() if len(u) > 0 else 0
        g_win  = (g > 0).mean() if len(g) > 0 else 0
        delta  = g_avg - u_avg
        print(f"  {sig:<18} {len(u):>8} {len(g):>8} {u_avg:>7.1%} {g_avg:>7.1%} "
              f"{delta:>+7.2%} {u_win:>7.1%} {g_win:>7.1%}")

    # Verdict on STRONG ENTRY (the primary signal)
    u_strong = results[results["signal"] == "STRONG ENTRY"]["fwd_return"].dropna()
    g_strong = results[results["signal_gated"] == "STRONG ENTRY"]["fwd_return"].dropna()
    u_avg = u_strong.mean() if len(u_strong) > 0 else 0
    g_avg = g_strong.mean() if len(g_strong) > 0 else 0
    print(f"  {'─'*78}")
    print(f"  STRONG ENTRY verdict:")
    if len(g_strong) < 300:
        print(f"    ✗ REJECT — gated count {len(g_strong)} below sample-size floor (300)")
    elif g_avg > u_avg:
        print(f"    ✓ ACCEPT — gated avg {g_avg:.2%} > ungated {u_avg:.2%}  (Δ {g_avg - u_avg:+.2%})")
    else:
        print(f"    ✗ REJECT — gated avg {g_avg:.2%} not strictly above ungated {u_avg:.2%}  (Δ {g_avg - u_avg:+.2%})")
    print(f"{'═'*80}\n")


def summarize_band_ab(results):
    """A/B of ungated vs Phase-2-confidence-band signals (S31).

    The band is per-ticker by construction: the in-window self-test only activates
    where the high-confidence tail underperforms (NVDA-like). Accept criteria:
      1. STRONG ENTRY banded 6mo avg >= ungated (the tail it removes should be dead
         weight at the LEAPS horizon on a band-ON ticker; flat-or-better on band-OFF)
      2. STRONG ENTRY banded 15d avg >= ungated − 0.2pp (no 15d compression)
      3. Hierarchy STRONG > CAUTION on the banded arm (15d)
      4. STRONG ENTRY banded count >= 300 (sample-size floor)
    """
    if "band_active" in results.columns:
        frac = results["band_active"].mean()
        print(f"\n  Band-active window fraction: {frac:.1%} of test rows "
              f"(per-window self-test; 0% = ticker never triggers the band)")

    print(f"\n{'═'*80}")
    print(f"  PHASE 2 CONFIDENCE BAND — A/B COMPARISON (S31)")
    print(f"{'═'*80}")
    print(f"  {'Signal':<18} {'Cnt U':>7} {'Cnt B':>7} {'15d U':>7} {'15d B':>7} "
          f"{'6mo U':>7} {'6mo B':>7} {'Δ6mo':>7}")
    print(f"  {'─'*78}")
    for sig in ["STRONG ENTRY", "CAUTION", "SHORT-TERM ONLY", "LEAPS ONLY", "STAY OUT"]:
        u   = results[results["signal"] == sig]
        b   = results[results["signal_banded"] == sig]
        u15 = u["fwd_return"].mean() if len(u) else 0
        b15 = b["fwd_return"].mean() if len(b) else 0
        u126 = u["fwd_return_126d"].dropna().mean() if len(u) else 0
        b126 = b["fwd_return_126d"].dropna().mean() if len(b) else 0
        d126 = (b126 - u126) if (len(u) and len(b)) else float("nan")
        print(f"  {sig:<18} {len(u):>7} {len(b):>7} {u15:>7.1%} {b15:>7.1%} "
              f"{u126:>7.1%} {b126:>7.1%} {d126:>+7.2%}")

    us = results[results["signal"] == "STRONG ENTRY"]
    bs = results[results["signal_banded"] == "STRONG ENTRY"]
    u15, b15 = us["fwd_return"].mean(), bs["fwd_return"].mean()
    u126 = us["fwd_return_126d"].dropna().mean()
    b126 = bs["fwd_return_126d"].dropna().mean()
    bc = results[results["signal_banded"] == "CAUTION"]["fwd_return"].mean()
    c1 = b126 >= u126
    c2 = b15 >= u15 - 0.002
    c3 = b15 > bc
    c4 = len(bs) >= 300
    print(f"  {'─'*78}")
    print(f"  ACCEPT criteria:")
    print(f"    [{'✓' if c1 else '✗'}] STRONG 6mo no worse:   banded {b126:.1%} vs ungated {u126:.1%} (Δ {b126-u126:+.2%})")
    print(f"    [{'✓' if c2 else '✗'}] STRONG 15d no compress: banded {b15:.2%} vs ungated {u15:.2%} (Δ {b15-u15:+.2%}, need ≥ −0.2pp)")
    print(f"    [{'✓' if c3 else '✗'}] Hierarchy STRONG>CAUTION (15d, banded): {b15:.2%} > {bc:.2%}")
    print(f"    [{'✓' if c4 else '✗'}] STRONG sample floor:    banded count {len(bs)} (need ≥ 300)")
    if c1 and c2 and c3 and c4:
        print(f"  ✓ ACCEPT — band is non-harmful here; on a band-OFF ticker this means dormant.")
    else:
        print(f"  ✗ REJECT / band harmful for this ticker (expected on band-OFF tickers like QQQ).")
    print(f"{'═'*80}\n")


def summarize_regime_gate_ab(results):
    """A/B comparison of ungated vs VIX-regime-gated signals.

    Same A/B layout as summarize_p4_gate_ab.  Accept criteria (all must pass):
      1. STRONG ENTRY gated avg >= ungated − 0.2pp     (no compression on best signal)
      2. CAUTION gated avg      >= ungated + 0.5pp     (load-bearing improvement —
         stress-driven CAUTIONs moved to STAY OUT, residual CAUTION bucket cleaner)
      3. Hierarchy STRONG > CAUTION > STAY OUT intact on signal_regime_gated
      4. STRONG ENTRY gated count >= 300                (sample-size floor)
    """
    # Stress-regime frequency for the run (useful diagnostic)
    if "regime" in results.columns:
        stress_pct = (results["regime"] == "stress").mean()
        print(f"\n  Stress-regime frequency over backtest window: {stress_pct:.1%}")

    print(f"\n{'═'*80}")
    print(f"  VIX REGIME GATE — A/B COMPARISON (15d forward returns)")
    print(f"{'═'*80}")
    print(f"  {'Signal':<18} {'Count U':>8} {'Count G':>8} {'Avg U':>8} {'Avg G':>8} {'Δ Avg':>8} {'Win U':>7} {'Win G':>7}")
    print(f"  {'─'*78}")
    bucket_stats = {}
    for sig in ["STRONG ENTRY", "CAUTION", "SHORT-TERM ONLY", "LEAPS ONLY", "STAY OUT"]:
        u = results[results["signal"] == sig]["fwd_return"].dropna()
        g = results[results["signal_regime_gated"] == sig]["fwd_return"].dropna()
        if len(u) == 0 and len(g) == 0:
            continue
        u_avg = u.mean() if len(u) > 0 else 0
        g_avg = g.mean() if len(g) > 0 else 0
        u_win = (u > 0).mean() if len(u) > 0 else 0
        g_win = (g > 0).mean() if len(g) > 0 else 0
        bucket_stats[sig] = {"u_avg": u_avg, "g_avg": g_avg, "g_count": len(g)}
        delta = g_avg - u_avg
        print(f"  {sig:<18} {len(u):>8} {len(g):>8} {u_avg:>7.1%} {g_avg:>7.1%} "
              f"{delta:>+7.2%} {u_win:>7.1%} {g_win:>7.1%}")

    print(f"  {'─'*78}")
    print(f"  ACCEPT criteria:")

    strong = bucket_stats.get("STRONG ENTRY", {"u_avg": 0, "g_avg": 0, "g_count": 0})
    caution = bucket_stats.get("CAUTION", {"u_avg": 0, "g_avg": 0, "g_count": 0})

    c1_pass = strong["g_avg"] >= strong["u_avg"] - 0.002  # within −0.2pp
    c2_pass = caution["g_avg"] >= caution["u_avg"] + 0.005  # +0.5pp improvement
    c4_pass = strong["g_count"] >= 300

    # Hierarchy check
    gated_avgs = {k: v["g_avg"] for k, v in bucket_stats.items()}
    h_strong  = gated_avgs.get("STRONG ENTRY", 0)
    h_caution = gated_avgs.get("CAUTION", 0)
    h_stayout = gated_avgs.get("STAY OUT", 0)
    c3_pass = (h_strong > h_caution) and (h_caution > h_stayout)

    print(f"    [{'✓' if c1_pass else '✗'}] STRONG ENTRY no compression:  "
          f"gated {strong['g_avg']:.2%} vs ungated {strong['u_avg']:.2%} "
          f"(Δ {strong['g_avg'] - strong['u_avg']:+.2%}, need ≥ −0.2pp)")
    print(f"    [{'✓' if c2_pass else '✗'}] CAUTION improvement:          "
          f"gated {caution['g_avg']:.2%} vs ungated {caution['u_avg']:.2%} "
          f"(Δ {caution['g_avg'] - caution['u_avg']:+.2%}, need ≥ +0.5pp)")
    print(f"    [{'✓' if c3_pass else '✗'}] Hierarchy intact:             "
          f"STRONG {h_strong:.2%} > CAUTION {h_caution:.2%} > STAY OUT {h_stayout:.2%}")
    print(f"    [{'✓' if c4_pass else '✗'}] STRONG ENTRY sample floor:    "
          f"gated count {strong['g_count']} (need ≥ 300)")

    all_pass = c1_pass and c2_pass and c3_pass and c4_pass
    if all_pass:
        print(f"  ✓ ACCEPT — all four criteria pass")
    else:
        print(f"  ✗ REJECT — one or more criteria failed (see above)")
    print(f"{'═'*80}\n")


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
    try:
        _show = input("Show chart? [y/N]: ").strip().lower() == "y"
    except EOFError:
        _show = False  # piped / exhausted stdin — skip the chart, don't crash before the CSV save
    if _show:
        plt.show()


# compute_vol_thresholds imported from modules.features


def collect_signal_stats(results, side="call"):
    """Returns a dict of per-signal stats for sweep comparison (15d + 6mo)."""
    stats = {}
    for sig in ["STRONG ENTRY", "CAUTION", "SHORT-TERM ONLY", "LEAPS ONLY", "STAY OUT"]:
        rows = results[results["signal"] == sig]
        s15  = rows["fwd_return"].dropna()
        s126 = rows["fwd_return_126d"].dropna()
        if side == "put":
            s15, s126 = -s15, -s126
        stats[sig] = {
            "count":           len(s15),
            "avg_return":      s15.mean()  if len(s15)  > 0 else float("nan"),
            "win_rate":        (s15 > 0).mean()  if len(s15)  > 0 else float("nan"),
            "avg_return_126d": s126.mean() if len(s126) > 0 else float("nan"),
            "win_rate_126d":   (s126 > 0).mean() if len(s126) > 0 else float("nan"),
        }
    return stats


def print_sweep_summary(sweep_results, ticker):
    """Compare multiplier combinations side-by-side; flag the best by STRONG ENTRY avg return."""
    print()
    print("=" * 98)
    print(f"  MULTIPLIER SWEEP SUMMARY — {ticker}  ({len(sweep_results)} combinations)")
    print("=" * 98)
    print(f"  {'P2':>5} {'P2B':>5} {'P3':>5}  {'STRONG':<22}  {'CAUTION':<19}  "
          f"{'SHORT':<19}  {'STAY':<13}  {'Hierarchy':>10}")
    print(f"  {'mult':>5} {'mult':>5} {'mult':>5}  {'cnt   avg     win%':<22}  "
          f"{'cnt   avg':<19}  {'cnt   avg':<19}  {'cnt   avg':<13}  {'monotonic?':>10}")
    print("-" * 98)

    rows = []
    for r in sweep_results:
        s = r["stats"]
        strong, caution, short, stay = (
            s["STRONG ENTRY"], s["CAUTION"], s["SHORT-TERM ONLY"], s["STAY OUT"]
        )
        leaps = s.get("LEAPS ONLY", {"avg_return": float("nan"), "count": 0, "win_rate": float("nan")})
        # Clean hierarchy: STRONG > CAUTION > SHORT-TERM > LEAPS > STAY OUT (by avg return)
        avgs = [strong["avg_return"], caution["avg_return"],
                short["avg_return"], leaps["avg_return"], stay["avg_return"]]
        valid = [a for a in avgs if not np.isnan(a)]
        hierarchy_clean = (len(valid) >= 4 and all(
            avgs[j] > avgs[j + 1]
            for j in range(len(avgs) - 1)
            if not (np.isnan(avgs[j]) or np.isnan(avgs[j + 1]))
        ))
        rows.append({
            "p2": r["p2"], "p2b": r["p2b"], "p3": r["p3"],
            "strong_avg":  strong["avg_return"],
            "strong_cnt":  strong["count"],
            "hierarchy":   hierarchy_clean,
            "stats":       s,
        })

    # Sort by STRONG ENTRY avg return descending
    rows.sort(key=lambda x: x["strong_avg"] if not np.isnan(x["strong_avg"]) else -1,
              reverse=True)
    best = (rows[0]["p2"], rows[0]["p2b"], rows[0]["p3"])

    for r in rows:
        s = r["stats"]
        marker = "  <-- best" if (r["p2"], r["p2b"], r["p3"]) == best else ""
        hier   = "Y" if r["hierarchy"] else "N"
        line = (
            f"  {r['p2']:>5.2f} {r['p2b']:>5.2f} {r['p3']:>5.2f}  "
            f"{s['STRONG ENTRY']['count']:>4} {s['STRONG ENTRY']['avg_return']:>+6.1%} "
            f"{s['STRONG ENTRY']['win_rate']:>6.0%}  "
            f"{s['CAUTION']['count']:>4} {s['CAUTION']['avg_return']:>+6.1%}      "
            f"{s['SHORT-TERM ONLY']['count']:>4} {s['SHORT-TERM ONLY']['avg_return']:>+6.1%}      "
            f"{s['STAY OUT']['count']:>4} {s['STAY OUT']['avg_return']:>+6.1%}   "
            f"{hier:>10}{marker}"
        )
        print(line)
    print("=" * 98)
    print(f"\n  Best by STRONG ENTRY avg return: P2={best[0]}, P2B={best[1]}, P3={best[2]}")
    print(f"  Hierarchy column flags whether STRONG > CAUTION > SHORT-TERM > STAY OUT (Y/N).")
    print(f"  Production values: P2={P2_VOL_MULTIPLE}, P2B={P2B_VOL_MULTIPLE}, P3={P3_VOL_MULTIPLE}.")


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Walk-forward backtest of combined Phase 2/2B/3 signal.")
    parser.add_argument(
        "--calibrate", action=argparse.BooleanOptionalAction, default=False,
        help="Use isotonic-calibrated Phase 2 (Decision 1, S11). Default OFF (NVDA regression: STRONG ENTRY 4.4% → -0.4%). Pass --calibrate to enable.",
    )
    parser.add_argument(
        "--iv-features", action=argparse.BooleanOptionalAction, default=False,
        dest="iv_features",
        help="Use real IV features (atm_iv_30d, iv_skew_25d, term_structure) for Phase 3. "
             "Default OFF — HV proxy, full history. Requires backfill_iv.py to have been run.",
    )
    parser.add_argument(
        "--econ-features", action=argparse.BooleanOptionalAction, default=False,
        dest="econ_features",
        help="Include macro-release proximity features (Days_to_FOMC, Days_to_CPI, ...) "
             "from data/econ_calendar.csv. Default OFF. "
             "Requires `python -m modules.econ_calendar --refresh` to have been run.",
    )
    parser.add_argument(
        "--bear-duration", action=argparse.BooleanOptionalAction, default=False,
        dest="bear_duration",
        help="Add bear-market DURATION features (days_below_ma200, days_since_52w_high). "
             "S31 experiment, default OFF — targets the grind-bear vs V-dip distinction "
             "behind the NVDA high-confidence-tail misfire. Validate cross-ticker before use.",
    )
    parser.add_argument(
        "--side", choices=["call", "put"], default="call",
        help="Direction to scan. 'call' (default, production) = bullish upside target. "
             "'put' = bearish PoC (S28): flips the Phase 2/2B target to a downside move "
             "(<= -WIN_THRESHOLD) and reports gross put P&L (= -underlying return). Phase 3 "
             "unchanged. Writes *_backtest_results_put.csv; skips call-oriented gate A/Bs + chart.",
    )
    args = parser.parse_args()
    P2_CALIBRATE  = args.calibrate
    IV_FEATURES   = args.iv_features
    ECON_FEATURES = args.econ_features
    BEAR_DURATION = args.bear_duration
    SIDE          = args.side
    P2_THRESHOLD  = 0.50 if P2_CALIBRATE else 0.55

    mode_label = "CALIBRATED  (Decision 1 — isotonic, 5-fold CV)" if P2_CALIBRATE else "RAW  (Decision 1 disabled — class_weight=balanced)"
    print("═" * 64)
    print(f"  Phase 2 mode: {mode_label}")
    print(f"  P2_THRESHOLD = {P2_THRESHOLD}  |  P2B_THRESHOLD = {P2B_THRESHOLD}  |  P3_THRESHOLD = {P3_THRESHOLD}")
    if SIDE == "put":
        print(f"  SIDE: PUT  (bearish PoC — downside target; Avg Ret = gross put P&L = -underlying return)")
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
    WIN_THRESHOLD, WIN_THRESHOLD_63, EXPANSION_THRESHOLD = compute_vol_thresholds(
        df, p2_vol_multiple=P2_VOL_MULTIPLE, p2b_vol_multiple=P2B_VOL_MULTIPLE, p3_vol_multiple=P3_VOL_MULTIPLE,
    )

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
    if IV_FEATURES:
        df_full = impute_iv_features(df_full)

    print("Running walk-forward backtest...")
    print(f"  Min training window: {MIN_TRAIN_DAYS} days (~1 years)")
    print(f"  Step / test window:  {STEP_DAYS} days (~6 months)")
    print()

    if MULTIPLIER_SWEEP:
        # Sweep mode: rerun walk-forward for each (p2, p3) combo, compare summaries.
        print(f"\n*** MULTIPLIER SWEEP MODE — {len(MULTIPLIER_SWEEP)} combinations ***\n")
        sweep_results = []
        for i, (p2_mult, p2b_mult, p3_mult) in enumerate(MULTIPLIER_SWEEP, 1):
            print(f"\n[{i}/{len(MULTIPLIER_SWEEP)}] P2={p2_mult}, P2B={p2b_mult}, P3={p3_mult}")
            print("─" * 60)
            WIN_THRESHOLD, WIN_THRESHOLD_63, EXPANSION_THRESHOLD = compute_vol_thresholds(
                df, verbose=True,
                p2_vol_multiple=p2_mult, p2b_vol_multiple=p2b_mult, p3_vol_multiple=p3_mult,
            )
            results = run_backtest(df_full, p2_mult=p2_mult, p2b_mult=p2b_mult, p3_mult=p3_mult, side=SIDE)
            stats   = collect_signal_stats(results, side=SIDE)
            sweep_results.append({"p2": p2_mult, "p2b": p2b_mult, "p3": p3_mult,
                                  "stats": stats, "results": results})
            print(f"  STRONG ENTRY: {stats['STRONG ENTRY']['count']} signals, "
                  f"avg {stats['STRONG ENTRY']['avg_return']:+.1%}, "
                  f"win% {stats['STRONG ENTRY']['win_rate']:.0%}")

        print_sweep_summary(sweep_results, TICKER)

        # Persist the sweep summary as CSV for later inspection.
        sweep_rows = []
        for r in sweep_results:
            for sig, s in r["stats"].items():
                sweep_rows.append({
                    "p2_mult":         r["p2"],
                    "p2b_mult":        r["p2b"],
                    "p3_mult":         r["p3"],
                    "signal":          sig,
                    "count":           s["count"],
                    "avg_return":      s["avg_return"],
                    "win_rate":        s["win_rate"],
                    "avg_return_126d": s["avg_return_126d"],
                    "win_rate_126d":   s["win_rate_126d"],
                })
        out = os.path.join(DATA_DIR, f"{TICKER.lower()}_multiplier_backtest_sweep{'_put' if SIDE == 'put' else ''}.csv")
        pd.DataFrame(sweep_rows).to_csv(out, index=False)
        print(f"\nSweep summary saved -> {out}")
    else:
        results = run_backtest(df_full, side=SIDE)

        # Ungated (baseline) — current production hierarchy
        df_stats, order, colors = summarize(results, signal_col="signal", label="UNGATED", side=SIDE)

        # The P4 / VIX gate A/Bs + chart are call-oriented (Phase 4 is an EXIT signal for calls;
        # for puts a drawdown is entry-confirmation, so the gates would be inverted). PoC keeps
        # puts to the ungated table — re-enable if the put side is productionized.
        if SIDE == "call":
            # Gated (Option B candidate) — P4 downgrades STRONG ENTRY → CAUTION, CAUTION/SHORT-TERM → STAY OUT
            summarize(results, signal_col="signal_gated", label="GATED (Phase 4)")

            # A/B comparison + accept/reject verdict on STRONG ENTRY
            summarize_p4_gate_ab(results)

            # VIX regime gate — STRONG ENTRY → CAUTION, CAUTION → STAY OUT in stress regime
            summarize(results, signal_col="signal_regime_gated", label="GATED (VIX regime)")
            summarize_regime_gate_ab(results)

            # Phase 2 confidence band (S31) — per-ticker in-window self-test
            summarize(results, signal_col="signal_banded", label="BANDED (P2 confidence)")
            summarize_band_ab(results)

            plot_results(df_stats, order, colors, results)

        out = os.path.join(DATA_DIR, f"{TICKER.lower()}_backtest_results{'_put' if SIDE == 'put' else ''}.csv")
        results.to_csv(out)
        print(f"Full results saved -> {out}")

    print(f"\n[Phase 2: {'CALIBRATED' if P2_CALIBRATE else 'RAW'} — P2_THRESHOLD={P2_THRESHOLD} | Phase 3 IV: {'REAL' if IV_FEATURES else 'HV proxy'}]")
