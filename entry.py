"""
Options Trading — Combined Entry Signal (Phase 2 + Phase 3)
============================================================
Trains both the direction model (Phase 2) and IV expansion model (Phase 3)
on historical data, then outputs a single combined entry recommendation.

Decision framework:
  Win + Expansion   → Strong entry: direction and IV both favorable
  Win + Contraction → Caution: direction good but IV crush risk
  Loss + Expansion  → Stay out: vol rising but no directional edge
  Loss + Contraction → Stay out: both signals unfavorable

Requirements:
    pip install yfinance pandas scikit-learn
"""

import argparse
import sys
import os
import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score
from sklearn.preprocessing import StandardScaler
from modules.benchmarks import detect_benchmarks, detect_macro_features, add_macro_features, add_catalyst_proximity
from modules.econ_calendar import add_macro_event_proximity
from modules.massive import IV_COLS, IV_META_COLS, IV_FEATURE_COLS
from modules.features import (
    HV_WINDOW, IV_RANK_WINDOW,
    P2_FORWARD_DAYS, P2B_FORWARD_DAYS, P3_FORWARD_DAYS,
    P2_VOL_MULTIPLE, P3_VOL_MULTIPLE, P4_VOL_MULTIPLE,
    compute_hv_features, compute_vix_features, add_trend_break_features,
    compute_p4_drawdown_threshold, add_p4_drawdown_target,
    add_earnings_proximity, normalize_features, compute_vol_thresholds,
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

# HV_WINDOW, IV_RANK_WINDOW, P2/P2B/P3 forward days, P2/P3 vol multiples imported from modules.features
WIN_THRESHOLD       = 0.05  # Default (AMD). Overridden at runtime by compute_vol_thresholds()
WIN_THRESHOLD_63    = 0.10  # Default (AMD). Overridden at runtime by compute_vol_thresholds()
EXPANSION_THRESHOLD = 0.10  # Default (AMD). Overridden at runtime by compute_vol_thresholds()
TEST_SIZE           = 0.20
P2_CALIBRATE        = False  # Decision 1 (S11) reverted as default after NVDA regression (STRONG ENTRY 4.4% → -0.4%). Pass --calibrate to enable.
P2_THRESHOLD        = 0.55   # Phase 2 (15d) cutoff. Set from P2_CALIBRATE in __main__: 0.50 calibrated / 0.55 raw.
P2B_THRESHOLD       = 0.55  # Phase 2B (63d) raw cutoff — calibration deferred to Decision 2
P3_THRESHOLD        = 0.60  # IV expansion cutoff (best precision from Phase 3)
P4_FORWARD_DAYS     = 15    # Phase 4 exit window — symmetric with P2 entry; 15d production default (S18)
P4_THRESHOLD        = 0.55  # Phase 4 drawdown cutoff
P4_GATE             = False # Default OFF — pass --p4-gate to enable. Pending backtest validation.
RANDOM_STATE        = 42

IV_FEATURES   = False  # set by --iv-features CLI arg; when True, Phase 3 uses IV_FEATURE_COLS as features
ECON_FEATURES = False  # set by --econ-features CLI arg; when True, Days_to_FOMC/CPI/... added

# IV/HV gate thresholds — ATM IV (30 DTE) divided by realized HV-20.
# IV_HV_GATE_RICH triggers a STRONG ENTRY -> CAUTION downgrade when premium is
# rich enough that the vol-expansion thesis is already priced in.
IV_HV_FAIR_LOW   = 0.85  # below this: premium is cheap vs realized — favorable for buyers
IV_HV_FAIR_HIGH  = 1.20  # above this: premium is rich
IV_HV_GATE_RICH  = 1.40  # above this: STRONG ENTRY downgrades to CAUTION
IV_TARGET_DTE    = 30    # ATM IV expiry tenor — 30d aligns with HV-20 timeframe


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
    print(f"  → {len(df)} rows, {len(df.columns)} columns")
    last_date = df.index.max()
    today = pd.Timestamp.today().normalize()
    days_old = np.busday_count(last_date.date(), today.date())
    if days_old > 1:
        print(f"  WARNING: CSV data is {days_old} trading day(s) old (last: {last_date.date()}). Re-run Phase 1 for a fresh signal.")
    print()
    return df


# ─────────────────────────────────────────
# 2. FEATURE ENGINEERING
# ─────────────────────────────────────────
def build_features(df, benchmarks):
    print("Building features...")
    df = compute_hv_features(df)

    vix_raw   = yf.download("^VIX",   start=START_DATE, end=END_DATE, progress=False)
    vix9d_raw = yf.download("^VIX9D", start=START_DATE, end=END_DATE, progress=False)
    vix3m_raw = yf.download("^VIX3M", start=START_DATE, end=END_DATE, progress=False)
    df = compute_vix_features(df, vix_raw, vix9d_raw, vix3m_raw)

    # Sector/industry benchmark relative strength + sector trend
    close = df["Close"]
    for bench_ticker, bench_name in benchmarks:
        raw = yf.download(bench_ticker, start=START_DATE, end=END_DATE, progress=False)
        raw.columns = raw.columns.get_level_values(0)
        col = f"_BENCH_{bench_name}"
        bench = raw[["Close"]].rename(columns={"Close": col})
        df = df.join(bench, how="left")
        df[col] = df[col].ffill()
        for window in [5, 20]:
            df[f"{bench_name}_RS_{window}d"] = close.pct_change(window) - df[col].pct_change(window)
        df[f"{bench_name}_vs_ma200"] = df[col] / df[col].rolling(200).mean() - 1
        df.drop(columns=[col], inplace=True)

    macro = detect_macro_features(TICKER)
    df = add_macro_features(df, macro, START_DATE, END_DATE)

    df = add_earnings_proximity(df, TICKER)
    df = add_catalyst_proximity(df, TICKER, MODULE_DIR, for_direction=True)
    if ECON_FEATURES:
        df = add_macro_event_proximity(df, MODULE_DIR)
    df = add_trend_break_features(df)  # must precede normalize_features (drops MA cols)
    df = normalize_features(df)

    return df


# ─────────────────────────────────────────
# 3. TRAIN MODELS
# ─────────────────────────────────────────
def train(df, target_col, calibrate=False, use_iv_features=False, decision_threshold=0.50):
    # use_iv_features=True: include IV_FEATURE_COLS as features (Phase 3 only when --iv-features
    # );
    #   dropna() auto-limits training to the ~2yr backfilled window.
    # default: exclude all IV_COLS so full price history is used.
    # decision_threshold: probability cutoff used for precision reporting — must match the
    # production threshold for the phase (P2/P2B/P3) so the printed precision reflects the
    # signal that will actually fire.
    exclude = {"Open", "High", "Low", "Close", "Volume", target_col,
               *(IV_META_COLS if use_iv_features else IV_COLS)}
    feature_cols = [c for c in df.columns if c not in exclude]

    df_model = df[feature_cols + [target_col]].dropna()
    X = df_model[feature_cols]
    y = df_model[target_col]

    split_idx  = int(len(X) * (1 - TEST_SIZE))
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    if calibrate:
        clf = CalibratedClassifierCV(
            LogisticRegression(C=0.1, class_weight="balanced",
                               max_iter=1000, random_state=RANDOM_STATE),
            method="isotonic",
            cv=5,
        )
        clf.fit(X_train_s, y_train)
        # Synthesize .coef_ as average of base-estimator coefs so get_top_contributors
        # (which reads clf.coef_[0]) keeps working unchanged.
        clf.coef_ = np.mean(
            [cc.estimator.coef_ for cc in clf.calibrated_classifiers_], axis=0
        )
    else:
        clf = LogisticRegression(C=0.1, class_weight="balanced",
                                 max_iter=1000, random_state=RANDOM_STATE)
        clf.fit(X_train_s, y_train)

    y_pred_train = (clf.predict_proba(X_train_s)[:, 1] >= decision_threshold).astype(int)
    y_pred_test  = (clf.predict_proba(X_test_s)[:, 1]  >= decision_threshold).astype(int)
    train_prec = precision_score(y_train, y_pred_train, zero_division=0)
    test_prec  = precision_score(y_test,  y_pred_test,  zero_division=0)
    base_rate  = y_train.mean()

    return clf, scaler, feature_cols, train_prec, test_prec, base_rate


def get_current_prob(df_full, clf, scaler, feature_cols):
    latest = df_full[feature_cols].dropna().iloc[-1]
    X = pd.DataFrame([latest], columns=feature_cols)
    return clf.predict_proba(scaler.transform(X))[0, 1]


def get_top_contributors(df_full, clf, scaler, feature_cols, n=3):
    latest = df_full[feature_cols].dropna().iloc[-1]
    X_scaled = scaler.transform(pd.DataFrame([latest], columns=feature_cols))[0]
    contributions = clf.coef_[0] * X_scaled
    top_idx = np.argsort(np.abs(contributions))[::-1][:n]
    return [(feature_cols[i], contributions[i]) for i in top_idx]


# ─────────────────────────────────────────
# 4. COMBINED SIGNAL OUTPUT
# ─────────────────────────────────────────
def read_iv_from_csv(df, hv_20):
    """
    Read today's IV snapshot from the indicators CSV (harvested by indicators.py).
    Returns dict {iv, atm_strike, expiry, dte, hv_20, ratio, label, skew_25d, term, pc_oi}
    or None if atm_iv_30d is NaN — in which case prints a warning to re-run indicators.py.
    """
    latest = df.iloc[-1]
    atm_iv = latest.get("atm_iv_30d")
    if atm_iv is None or pd.isna(atm_iv):
        print(f"  WARNING: atm_iv_30d is NaN for {df.index[-1].date()} — "
              f"re-run indicators.py to refresh the IV snapshot.")
        return None
    if hv_20 is None or hv_20 <= 0:
        return None

    atm_iv = float(atm_iv)
    ratio  = atm_iv / hv_20
    if ratio < IV_HV_FAIR_LOW:
        label = "cheap"
    elif ratio < IV_HV_FAIR_HIGH:
        label = "fair"
    elif ratio < IV_HV_GATE_RICH:
        label = "rich"
    else:
        label = "very rich"

    def _opt(col):
        v = latest.get(col)
        return None if v is None or pd.isna(v) else v

    return {
        "iv":         atm_iv,
        "atm_strike": float(_opt("atm_strike")) if _opt("atm_strike") is not None else None,
        "expiry":     str(_opt("atm_expiry")) if _opt("atm_expiry") is not None else None,
        "dte":        int(_opt("atm_dte")) if _opt("atm_dte") is not None else None,
        "hv_20":      hv_20,
        "ratio":      ratio,
        "label":      label,
        "skew_25d":   _opt("iv_skew_25d"),
        "term":       _opt("term_structure"),
        "pc_oi":      _opt("put_call_oi_ratio"),
    }


def determine_signal(dir_win: bool, dir_win_63: bool, expansion: bool) -> str:
    """Map Phase 2/2B/3 binary signals to the five-tier SIGNAL label."""
    if dir_win and dir_win_63:
        return "STRONG ENTRY" if expansion else "CAUTION"
    if dir_win:
        return "SHORT-TERM ONLY"
    if dir_win_63:
        return "LEAPS ONLY"
    return "STAY OUT"


def print_combined_signal(df_full, direction_prob, dir_prob_63, expansion_prob,
                          iv_rank, iv_pct, hv_20,
                          dir_base_rate, dir_base_rate_63, exp_base_rate,
                          dir_contributors, dir_contributors_63, exp_contributors,
                          iv_info=None,
                          exit_prob=None, exit_base_rate=None, exit_contributors=None,
                          exit_drawdown_threshold=None):
    df_clean      = df_full.drop(columns=IV_COLS, errors="ignore").dropna()
    latest_date   = df_clean.index[-1].strftime("%Y-%m-%d")
    days_to_earn  = int(df_clean.iloc[-1].get("Days_to_earnings", 45))
    _dtc          = int(df_clean.iloc[-1].get("Days_to_catalyst", 90))
    days_to_cat   = "N/A" if _dtc >= 90 else f"{_dtc}d"

    dir_signal    = direction_prob >= P2_THRESHOLD
    dir_signal_63 = dir_prob_63 >= P2B_THRESHOLD
    exp_signal    = expansion_prob >= P3_THRESHOLD
    contraction_prob = 1 - expansion_prob

    iv_regime = "Low IV" if iv_rank < 0.33 else "High IV" if iv_rank > 0.67 else "Mid IV"

    # Signal label matches backtest.py terminology
    signal = determine_signal(dir_signal, dir_signal_63, exp_signal)

    # Sizing: Phase 3 is primary sizing input; Phase 2B adds a REDUCED override
    if dir_signal:
        if exp_signal and dir_signal_63:
            sizing      = "FULL"
            sizing_note = f"IV {iv_regime.lower()} and vol likely rising — premium affordable and expanding."
        elif exp_signal and not dir_signal_63:
            sizing      = "REDUCED"
            sizing_note = "Vol expanding but medium-term model does not confirm — limit size."
        elif not exp_signal and dir_signal_63:
            sizing      = "REDUCED"
            sizing_note = f"IV {iv_regime.lower()} with {contraction_prob:.0%} contraction probability — limit exposure to premium decay."
        else:
            sizing      = "REDUCED"
            sizing_note = f"IV {iv_regime.lower()} with {contraction_prob:.0%} contraction probability and medium-term model does not confirm — limit size."
    else:
        if dir_signal_63:  # LEAPS ONLY
            sizing      = "LEAPS"
            sizing_note = (f"15d edge absent but 63d model confirms ({dir_prob_63:.0%}) — "
                           f"longer-dated options only (6\u20139 months).")
        else:
            sizing      = "N/A"
            sizing_note = "No directional edge — wait for Phase 2 signal before sizing."

    # ── Gates: P4 exit gate first (multi-tier), then IV/HV gate (STRONG ENTRY only) ──
    signal_pre_gate = signal
    gate_msgs = []

    # P4 exit gate (Option B, S18): one-tier downgrade when Phase 4 forecasts drawdown.
    # STRONG ENTRY → CAUTION, CAUTION → STAY OUT, SHORT-TERM ONLY → STAY OUT, LEAPS ONLY unchanged.
    if P4_GATE and exit_prob is not None and exit_prob >= P4_THRESHOLD:
        if signal == "STRONG ENTRY":
            signal, sizing = "CAUTION", "REDUCED"
            sizing_note = (f"Phase 4 forecasts {exit_prob:.0%} {P4_FORWARD_DAYS}d drawdown probability — "
                           f"downgraded from STRONG ENTRY.")
            gate_msgs.append(f"P4 gate: prob {exit_prob:.0%} >= {P4_THRESHOLD}")
        elif signal in ("CAUTION", "SHORT-TERM ONLY"):
            prev_signal = signal
            signal, sizing = "STAY OUT", "N/A"
            sizing_note = (f"Phase 4 forecasts {exit_prob:.0%} {P4_FORWARD_DAYS}d drawdown probability — "
                           f"downgraded from {prev_signal}.")
            gate_msgs.append(f"P4 gate: prob {exit_prob:.0%} >= {P4_THRESHOLD}")

    # IV/HV gate (existing): downgrade STRONG ENTRY if options-market premium is too rich
    if iv_info is not None and signal == "STRONG ENTRY" and iv_info["ratio"] >= IV_HV_GATE_RICH:
        signal      = "CAUTION"
        sizing      = "REDUCED"
        sizing_note = (f"IV/HV ratio {iv_info['ratio']:.2f} ({iv_info['label']}) — "
                       f"premium pricing the vol-expansion thesis already; downgraded from STRONG ENTRY.")
        gate_msgs.append(f"IV/HV gate: ratio {iv_info['ratio']:.2f} >= {IV_HV_GATE_RICH}")

    gate_msg = "; ".join(gate_msgs) if gate_msgs else None

    def fmt_contributors(contributors):
        parts = []
        for name, val in contributors:
            direction = "+" if val > 0 else "-"
            parts.append(f"{name} ({direction})")
        return ", ".join(parts)

    w = 58
    print(f"\n{'═'*w}")
    print(f"  COMBINED ENTRY SIGNAL — {TICKER} as of {latest_date}")
    print(f"{'═'*w}")
    p2_mode = "calibrated" if P2_CALIBRATE else "raw"
    print(f"\n  DIRECTION — 15d entry timing  [threshold: {P2_THRESHOLD} — {p2_mode}]")
    print(f"  Win Probability:    {direction_prob:.1%}  (base rate: {dir_base_rate:.1%})")
    print(f"  Signal:             {'WIN ✓' if dir_signal else 'NO SIGNAL ✗'}")
    print(f"  Drivers:            {fmt_contributors(dir_contributors)}")
    print(f"  Days to Earnings:   {days_to_earn}d")
    print(f"  Days to Catalyst:   {days_to_cat}")
    print(f"\n  DIRECTION — 63d thesis        [threshold: {P2B_THRESHOLD}]")
    print(f"  Win Probability:    {dir_prob_63:.1%}  (base rate: {dir_base_rate_63:.1%})")
    print(f"  Signal:             {'WIN ✓' if dir_signal_63 else 'NO SIGNAL ✗'}")
    print(f"  Drivers:            {fmt_contributors(dir_contributors_63)}")
    print(f"\n  IV TIMING (Phase 3)           [threshold: {P3_THRESHOLD}]")
    print(f"  HV (20-day):        {hv_20:.1%}")
    print(f"  IV Rank:            {iv_rank:.2f}  ({iv_regime})")
    print(f"  IV Percentile:      {iv_pct:.1%}")
    print(f"  Expansion Prob:     {expansion_prob:.1%}  (base rate: {exp_base_rate:.1%})")
    print(f"  Signal:             {'EXPANSION ✓' if exp_signal else 'CONTRACTION ✗'}")
    print(f"  Drivers:            {fmt_contributors(exp_contributors)}")

    # Phase 4 — exit risk (display-only; does not gate SIGNAL — S18)
    if exit_prob is not None:
        exit_signal = exit_prob >= P4_THRESHOLD
        print(f"\n  EXIT RISK (Phase 4 — {P4_FORWARD_DAYS}d drawdown)  [threshold: {P4_THRESHOLD}]")
        if exit_drawdown_threshold is not None:
            print(f"  Drawdown Bar:       {exit_drawdown_threshold:.2%}")
        print(f"  Drawdown Prob:      {exit_prob:.1%}  (base rate: {exit_base_rate:.1%})")
        print(f"  Signal:             {'EXIT ⚠' if exit_signal else 'NO EXIT ✓'}")
        if exit_contributors is not None:
            print(f"  Drivers:            {fmt_contributors(exit_contributors)}")

    if iv_info is not None:
        print(f"\n  OPTIONS-MARKET CHECK (Massive snapshot)")
        print(f"  ATM IV ({iv_info['dte']}d):        {iv_info['iv']:.1%}   "
              f"(expiry: {iv_info['expiry']}, strike: ${iv_info['atm_strike']:.2f})")
        print(f"  HV-20:              {iv_info['hv_20']:.1%}")
        print(f"  IV/HV ratio:        {iv_info['ratio']:.2f}    "
              f"({iv_info['label']})")
        if iv_info.get("skew_25d") is not None:
            print(f"  25Δ skew (P-C):     {iv_info['skew_25d']:+.3f}")
        if iv_info.get("term") is not None:
            term_label = "noise" if iv_info["term"] > 0.98 and iv_info["term"] < 1.02 else "slight backwardation" if iv_info["term"] >= 1.02 and iv_info["term"] < 1.05 else "backwardation" if iv_info["term"] >= 1.05 else "slight contango" if iv_info["term"] <= 0.98 and iv_info["term"] >= 0.95 else "contango"
            print(f"  Term structure:     {iv_info['term']:.2f}  ({term_label})")
        if iv_info.get("pc_oi") is not None:
            print(f"  Put/Call OI:        {iv_info['pc_oi']:.2f}")
    else:
        print(f"\n  OPTIONS-MARKET CHECK: skipped (IV not in indicators CSV)")

    # ── Market stress warning: Phase 3 CONTRACTION but options market signals near-term risk ──
    stress_tells = []
    if not exp_signal and iv_info is not None:
        if iv_info.get("term") is not None and iv_info["term"] >= 1.05:
            stress_tells.append(f"term structure {iv_info['term']:.2f} (backwardation)")
        if iv_info["ratio"] >= IV_HV_GATE_RICH:
            stress_tells.append(f"IV/HV {iv_info['ratio']:.2f} (very rich)")
    if stress_tells:
        print(f"\n  WARNING: Phase 3 CONTRACTION under market stress")
        print(f"  Tells:              {', '.join(stress_tells)}")
        print(f"  Options market may be pricing near-term risk not visible in price history.")
        print(f"  Treat contraction sizing with extra conservatism.")

    print(f"\n  {'─'*w}")
    if gate_msg:
        print(f"  SIGNAL:             {signal_pre_gate} -> {signal}  ({gate_msg})")
    else:
        print(f"  SIGNAL:             {signal}")
    print(f"  POSITION SIZING:    {sizing}")
    print(f"  {sizing_note}")
    print(f"{'═'*w}\n")

    return signal_pre_gate, signal


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Combined Phase 2/2B/3 entry signal.")
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
        "--p4-gate", action=argparse.BooleanOptionalAction, default=False,
        dest="p4_gate",
        help="Enable Phase 4 exit gate (Option B): one-tier-down downgrade when "
             "Phase 4 forecasts drawdown. STRONG ENTRY → CAUTION, CAUTION → STAY OUT, "
             "SHORT-TERM ONLY → STAY OUT, LEAPS ONLY unchanged. Default OFF until "
             "backtest validation completes.",
    )
    parser.add_argument(
        "--econ-features", action=argparse.BooleanOptionalAction, default=False,
        dest="econ_features",
        help="Include macro-release proximity features (Days_to_FOMC, Days_to_CPI, ...) "
             "from modules/econ_calendar.csv. Default OFF. "
             "Requires `python -m modules.econ_calendar --refresh` to have been run.",
    )
    args = parser.parse_args()
    P2_CALIBRATE  = args.calibrate
    IV_FEATURES   = args.iv_features
    P4_GATE       = args.p4_gate
    ECON_FEATURES = args.econ_features
    P2_THRESHOLD = 0.50 if P2_CALIBRATE else 0.55

    mode_label = "CALIBRATED  (Decision 1 — isotonic, 5-fold CV)" if P2_CALIBRATE else "RAW  (Decision 1 disabled — class_weight=balanced)"
    print("═" * 64)
    print(f"  Phase 2 mode: {mode_label}")
    print(f"  P2_THRESHOLD = {P2_THRESHOLD}  |  P2B_THRESHOLD = {P2B_THRESHOLD}  |  P3_THRESHOLD = {P3_THRESHOLD}  |  P4_THRESHOLD = {P4_THRESHOLD}")
    print(f"  P4 gate: {'ON' if P4_GATE else 'OFF (display-only)'}")
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
    WIN_THRESHOLD, WIN_THRESHOLD_63, EXPANSION_THRESHOLD = compute_vol_thresholds(df)

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

    # Phase 2 — 15-day direction target (mode set via CLI flag — see banner)
    df_p2 = df_full.copy()
    future_close = df_p2["Close"].shift(-P2_FORWARD_DAYS)
    df_p2["direction_target"] = ((future_close / df_p2["Close"] - 1) >= WIN_THRESHOLD).astype(int)
    df_p2 = df_p2.iloc[:-P2_FORWARD_DAYS]
    clf2, scaler2, fcols2, tr2, te2, base2 = train(df_p2, "direction_target", calibrate=P2_CALIBRATE, decision_threshold=P2_THRESHOLD)
    print(f"Phase 2  (15d direction, {'calibrated' if P2_CALIBRATE else 'raw'}) — train precision: {tr2:.1%}  test precision: {te2:.1%}  base rate: {base2:.1%}")

    # Phase 2B — 63-day direction target
    df_p2b = df_full.copy()
    future_close_63 = df_p2b["Close"].shift(-P2B_FORWARD_DAYS)
    df_p2b["direction_target_63"] = ((future_close_63 / df_p2b["Close"] - 1) >= WIN_THRESHOLD_63).astype(int)
    df_p2b = df_p2b.iloc[:-P2B_FORWARD_DAYS]
    clf2b, scaler2b, fcols2b, tr2b, te2b, base2b = train(df_p2b, "direction_target_63", decision_threshold=P2B_THRESHOLD)
    print(f"Phase 2B (63d direction) — train precision: {tr2b:.1%}  test precision: {te2b:.1%}  base rate: {base2b:.1%}")

    # Phase 3 — IV expansion target
    df_p3 = df_full.copy()
    future_hv = df_p3["HV_20"].shift(-P3_FORWARD_DAYS)
    df_p3["iv_target"] = ((future_hv / df_p3["HV_20"] - 1) >= EXPANSION_THRESHOLD).astype(int)
    df_p3 = df_p3.iloc[:-P3_FORWARD_DAYS]
    clf3, scaler3, fcols3, tr3, te3, base3 = train(df_p3, "iv_target", use_iv_features=IV_FEATURES, decision_threshold=P3_THRESHOLD)
    print(f"Phase 3  (IV timing)     — train precision: {tr3:.1%}  test precision: {te3:.1%}  base rate: {base3:.1%}")

    # Phase 4 — exit risk target (15d max drawdown >= vol-adjusted bar). Display-only.
    p4_drawdown_threshold = compute_p4_drawdown_threshold(df_full, P4_FORWARD_DAYS)
    df_p4 = add_p4_drawdown_target(df_full, P4_FORWARD_DAYS, p4_drawdown_threshold)
    clf4, scaler4, fcols4, tr4, te4, base4 = train(df_p4, "exit_target", decision_threshold=P4_THRESHOLD)
    print(f"Phase 4  (exit risk)     — train precision: {tr4:.1%}  test precision: {te4:.1%}  base rate: {base4:.1%}\n")

    # Current signals
    direction_prob    = get_current_prob(df_full, clf2,  scaler2,  fcols2)
    dir_prob_63       = get_current_prob(df_full, clf2b, scaler2b, fcols2b)
    expansion_prob    = get_current_prob(df_full, clf3,  scaler3,  fcols3)
    exit_prob         = get_current_prob(df_full, clf4,  scaler4,  fcols4)
    dir_contributors    = get_top_contributors(df_full, clf2,  scaler2,  fcols2)
    dir_contributors_63 = get_top_contributors(df_full, clf2b, scaler2b, fcols2b)
    exp_contributors    = get_top_contributors(df_full, clf3,  scaler3,  fcols3)
    exit_contributors   = get_top_contributors(df_full, clf4,  scaler4,  fcols4)

    latest = df_full[["HV_20", "IV_rank", "IV_pct"]].dropna().iloc[-1]

    # Read today's IV snapshot harvested by indicators.py and compute IV/HV ratio
    iv_info = read_iv_from_csv(df_full, float(latest["HV_20"]))

    print_combined_signal(
        df_full,
        direction_prob,
        dir_prob_63,
        expansion_prob,
        latest["IV_rank"],
        latest["IV_pct"],
        latest["HV_20"],
        base2,
        base2b,
        base3,
        dir_contributors,
        dir_contributors_63,
        exp_contributors,
        iv_info=iv_info,
        exit_prob=exit_prob,
        exit_base_rate=base4,
        exit_contributors=exit_contributors,
        exit_drawdown_threshold=p4_drawdown_threshold,
    )

    print(f"[Phase 2: {'CALIBRATED' if P2_CALIBRATE else 'RAW'} — P2_THRESHOLD={P2_THRESHOLD} | Phase 3 IV: {'REAL' if IV_FEATURES else 'HV proxy'}]")