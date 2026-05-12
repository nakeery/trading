"""
Shared feature engineering — direction.py, volatility.py, backtest.py.

Import pattern:
    from modules.features import (
        HV_WINDOW, IV_RANK_WINDOW,
        P2_FORWARD_DAYS, P2B_FORWARD_DAYS, P3_FORWARD_DAYS,
        P2_VOL_MULTIPLE, P3_VOL_MULTIPLE,
        compute_hv_features, compute_vix_features,
        add_earnings_proximity, normalize_features, compute_vol_thresholds,
    )
"""

import numpy as np
import pandas as pd
import yfinance as yf

# ─── Shared constants ────────────────────────────────────────────────────────
HV_WINDOW        = 20    # Rolling window for realized vol (trading days)
IV_RANK_WINDOW   = 252   # 1-year lookback for IV rank / percentile

P2_FORWARD_DAYS  = 15    # Phase 2 direction window (entry timing)
P2B_FORWARD_DAYS = 63    # Phase 2B direction window (~1 quarter, LEAPS-aligned)
P3_FORWARD_DAYS  = 10    # Phase 3 IV expansion window

P2_VOL_MULTIPLE  = 0.41  # 0.41-sigma bar; range 0.25 (aggressive) to 1.0 (conservative)
P3_VOL_MULTIPLE  = 0.20  # 20% of median HV; range 0.10 to 0.40


# ─── Feature computation functions ───────────────────────────────────────────

def compute_hv_features(df, hv_window=HV_WINDOW, rank_window=IV_RANK_WINDOW):
    """Add HV_20, IV_rank, IV_pct, HV_chg_5d, HV_chg_10d, HV_vs_ma20."""
    log_ret = np.log(df["Close"] / df["Close"].shift(1))
    df["HV_20"] = log_ret.rolling(hv_window).std() * np.sqrt(252)

    hv_high = df["HV_20"].rolling(rank_window).max()
    hv_low  = df["HV_20"].rolling(rank_window).min()
    df["IV_rank"] = (df["HV_20"] - hv_low) / (hv_high - hv_low)
    df["IV_pct"]  = df["HV_20"].rolling(rank_window).apply(
        lambda x: (x[:-1] < x[-1]).mean(), raw=True
    )
    df["HV_chg_5d"]  = df["HV_20"].pct_change(5)
    df["HV_chg_10d"] = df["HV_20"].pct_change(10)
    df["HV_vs_ma20"] = df["HV_20"] / df["HV_20"].rolling(20).mean() - 1
    return df


def compute_vix_features(df, vix_df, vix9d_df, vix3m_df):
    """Join pre-fetched VIX dataframes (each must have a 'Close' column) and
    compute all VIX feature columns.  The *_df arguments accept raw yf.download()
    output or cached equivalents — column flattening is handled internally."""
    for raw in [vix_df, vix9d_df, vix3m_df]:
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

    vix = vix_df[["Close"]].rename(columns={"Close": "VIX"})
    vix["VIX_chg_5d"]  = vix["VIX"].pct_change(5)
    vix["VIX_vs_ma20"] = vix["VIX"] / vix["VIX"].rolling(20).mean() - 1
    df = df.join(vix, how="left")
    df[["VIX", "VIX_chg_5d", "VIX_vs_ma20"]] = df[["VIX", "VIX_chg_5d", "VIX_vs_ma20"]].ffill()

    for raw_df, col in [(vix9d_df, "VIX9D"), (vix3m_df, "VIX3M")]:
        series = raw_df[["Close"]].rename(columns={"Close": col})
        df = df.join(series, how="left")
        df[col] = df[col].ffill()

    df["VIX9D_VIX_ratio"] = (df["VIX9D"] / df["VIX"]).fillna(1.0)
    df["VIX_VIX3M_ratio"] = (df["VIX"] / df["VIX3M"]).fillna(1.0)
    df.drop(columns=["VIX9D", "VIX3M"], inplace=True)
    return df


def add_earnings_proximity(df, ticker):
    """Add Days_to_earnings column. Defaults to 45 (neutral) on failure."""
    yf_ticker = yf.Ticker(ticker)
    ed = []
    try:
        dates = yf_ticker.get_earnings_dates(limit=20)
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


def normalize_features(df):
    """Replace absolute price-level indicators with scale-invariant ratios.

    Handles: MA/EMA → price_vs ratios; KC bands → price_vs_kc ratios;
    MACD → normalized by Close; OBV → OBV_chg_5d;
    universal: price_vs_52w_high/low, vol_ratio.
    All column checks are guarded — safe when indicators CSV omits optional cols.
    """
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

    return df


def compute_vol_thresholds(df, verbose=True,
                            p2_vol_multiple=P2_VOL_MULTIPLE,
                            p3_vol_multiple=P3_VOL_MULTIPLE,
                            hv_window=HV_WINDOW,
                            p2_forward_days=P2_FORWARD_DAYS,
                            p2b_forward_days=P2B_FORWARD_DAYS):
    """Compute vol-adjusted WIN_THRESHOLD, WIN_THRESHOLD_63, EXPANSION_THRESHOLD.

    Returns (win_threshold, win_threshold_63, expansion_threshold).
    Falls back to AMD defaults (0.05, 0.10, 0.10) if HV data is insufficient.
    """
    AMD_DEFAULTS = (0.05, 0.10, 0.10)
    log_ret   = np.log(df["Close"] / df["Close"].shift(1))
    hv_series = log_ret.rolling(hv_window).std() * np.sqrt(252)
    hv_valid  = hv_series.dropna()

    if verbose:
        print("\nVol-Adjusted Threshold Calibration")
        print("─" * 42)
    if len(hv_valid) < 20 or hv_valid.median() < 0.05:
        if verbose:
            print("  WARNING: Insufficient/invalid HV data — using AMD defaults.")
            print("─" * 42)
        return AMD_DEFAULTS

    median_hv           = hv_valid.median()
    win_threshold       = p2_vol_multiple * median_hv * np.sqrt(p2_forward_days / 252)
    win_threshold_63    = p2_vol_multiple * median_hv * np.sqrt(p2b_forward_days / 252)
    expansion_threshold = p3_vol_multiple * median_hv

    if verbose:
        print(f"  Ticker median HV (20-day, annualized): {median_hv:.1%}")
        print(f"  P2_VOL_MULTIPLE = {p2_vol_multiple}  |  P3_VOL_MULTIPLE = {p3_vol_multiple}")
        print(f"  WIN_THRESHOLD:       {win_threshold:.2%}")
        print(f"  WIN_THRESHOLD_63:    {win_threshold_63:.2%}")
        print(f"  EXPANSION_THRESHOLD: {expansion_threshold:.2%}")
        print("─" * 42)

    return win_threshold, win_threshold_63, expansion_threshold
