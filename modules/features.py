"""
Shared feature engineering — direction.py, volatility.py, exit.py, entry.py, backtest.py.

Import pattern:
    from modules.features import (
        HV_WINDOW, IV_RANK_WINDOW,
        P2_FORWARD_DAYS, P2B_FORWARD_DAYS, P3_FORWARD_DAYS, P4_FORWARD_DAYS_LIST,
        P2_VOL_MULTIPLE, P2B_VOL_MULTIPLE, P3_VOL_MULTIPLE, P4_VOL_MULTIPLE,
        compute_hv_features, add_trend_break_features,
        compute_p4_drawdown_threshold, add_p4_drawdown_target,
        compute_vix_features, add_vix, add_benchmarks,
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
P4_FORWARD_DAYS_LIST = [5, 15]  # Phase 4 candidate exit windows — tactical / symmetric.
                                # 32d/63d/126d tested S18 and dropped: tail inversion past ~15d on individual
                                # stocks (NVDA 15d=+15.8pp → 32d=-3.2pp → 63d=-20.7pp). QQQ holds up through
                                # 32d then breaks (+16.0pp → 63d=+2.3pp → 126d=-5.1pp). See context.md S18.

P2_VOL_MULTIPLE  = 0.41  # 0.41-sigma bar; range 0.25 (aggressive) to 1.0 (conservative)
P2B_VOL_MULTIPLE = 0.55  # 63d bar — higher than P2 to offset secular drift inflating QQQ base rate; tune via backtest
P3_VOL_MULTIPLE  = 0.20  # 20% of median HV; range 0.10 to 0.40
P4_VOL_MULTIPLE  = 1.0   # Drawdown threshold = P4_VOL_MULTIPLE × median_HV × sqrt(N/252); starting point, tune via per-ticker backtest


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


def add_trend_break_features(df):
    """Add backward-looking trend-vulnerability features for Phase 4 (exit signal).

    Proxies the "trend break" concept (above MA today, about to drop below) using
    only past data — distance to MA, MA slope, streak length. The naive forward-
    looking definition would be lookahead bias.

    Must run BEFORE normalize_features (which drops MA_20/MA_50).
    No-ops with a warning if MA_20/MA_50 are missing from df.
    """
    if "MA_20" not in df.columns or "MA_50" not in df.columns:
        print("  ⚠ MA_20 or MA_50 missing — skipping trend-break features")
        return df

    df["above_ma20"] = (df["Close"] > df["MA_20"]).astype(int)
    df["above_ma50"] = (df["Close"] > df["MA_50"]).astype(int)

    dist20 = (df["Close"] - df["MA_20"]) / df["MA_20"]
    dist50 = (df["Close"] - df["MA_50"]) / df["MA_50"]
    df["dist_above_ma20_pct"] = dist20.where(dist20 > 0, 0)
    df["dist_above_ma50_pct"] = dist50.where(dist50 > 0, 0)

    df["ma20_slope_5d"] = df["MA_20"].pct_change(5)
    df["ma50_slope_5d"] = df["MA_50"].pct_change(5)

    for col, mask in [("days_above_ma20", df["above_ma20"]), ("days_above_ma50", df["above_ma50"])]:
        groups = (mask != mask.shift()).cumsum()
        df[col] = mask.groupby(groups).cumsum()

    print("  ✓ above_ma20/50, dist_above_ma20/50_pct, ma20/50_slope_5d, days_above_ma20/50")
    return df


def add_bear_duration_features(df):
    """Add bear-market DURATION features (S31, gated by --bear-duration; default OFF).

    Hypothesis: the framework already sees drawdown DEPTH (price_vs_52w_high,
    price_vs_ma200) but not how LONG a decline has persisted. Duration is what
    separates grind-bears (2002: months below the 200-day MA) from V-dips (2020:
    days) — the distinction behind the S25 NVDA "post-drop recovery" misfire.

    Both columns are strictly backward-looking. Uses MA_200 and the 252-day rolling
    high, so MUST run BEFORE normalize_features (which drops MA_* columns). No-ops
    with a warning if MA_200 is missing.

      days_below_ma200     — consecutive sessions Close < MA_200 (0 while above)
      days_since_52w_high  — sessions since Close last set its 252-day rolling max
    """
    if "MA_200" not in df.columns:
        print("  ⚠ MA_200 missing — skipping bear-duration features")
        return df

    # Consecutive-below streak — same groupby-cumsum idiom as days_above_ma20/50.
    below = (df["Close"] < df["MA_200"]).astype(int)
    groups = (below != below.shift()).cumsum()
    df["days_below_ma200"] = below.groupby(groups).cumsum()

    # Sessions since the last 252-day high (0 on a new high). cumcount within the
    # constant run between highs gives the elapsed-session count.
    roll_max = df["Close"].rolling(252, min_periods=1).max()
    is_high  = (df["Close"] >= roll_max)
    df["days_since_52w_high"] = df.groupby(is_high.cumsum()).cumcount()

    print("  ✓ days_below_ma200, days_since_52w_high")
    return df


def compute_p4_drawdown_threshold(df, forward_days, vol_multiple=None, fallback_hv=0.20):
    """Vol-adjusted Phase 4 drawdown threshold: vol_multiple × median_HV × sqrt(N/252).

    Prefers df['HV_20'] if present, else recomputes HV from log-returns. Falls back
    to fallback_hv (default 0.20, AMD-like) if the resulting median is < 5%.
    """
    if vol_multiple is None:
        vol_multiple = P4_VOL_MULTIPLE

    median_hv = None
    if "HV_20" in df.columns:
        s = df["HV_20"].dropna()
        if len(s) >= 20:
            median_hv = s.median()
    if median_hv is None or not np.isfinite(median_hv) or median_hv < 0.05:
        log_ret = np.log(df["Close"] / df["Close"].shift(1))
        s = (log_ret.rolling(HV_WINDOW).std() * np.sqrt(252)).dropna()
        median_hv = s.median() if len(s) >= 20 else None
    if median_hv is None or not np.isfinite(median_hv) or median_hv < 0.05:
        median_hv = fallback_hv

    return vol_multiple * median_hv * np.sqrt(forward_days / 252)


def add_p4_drawdown_target(df, forward_days, drawdown_threshold, target_col="exit_target"):
    """Apply forward-window max-drawdown target.

    target_col = 1 if min(Low[t+1..t+N]) drops drawdown_threshold-or-more below Close[t].
    drawdown_threshold is a positive number (e.g. 0.04 = 4% drawdown bar).
    Returns df with target_col added and last N rows dropped (no forward window).
    """
    n = forward_days
    future_min_low = df["Low"].shift(-n).rolling(n, min_periods=n).min()
    forward_drawdown = (future_min_low - df["Close"]) / df["Close"]
    df = df.copy()
    df[target_col] = (forward_drawdown <= -drawdown_threshold).astype(int)
    return df.iloc[:-n]


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

    # Missingness indicators (S31): VIX9D history starts ~2011, VIX3M ~2007. Before that the
    # ratios below are sentinel-filled 1.0, which otherwise acts as a pre-history era marker
    # (corr -0.5..-0.6 with calendar time — the same family as the Days_to_earnings leak).
    # The indicator lets the model separate a real 1.0 from a filled 1.0 rather than reading
    # the fill as a calendar tag. Mirrors the iv_available/term_available pattern. Safe in
    # walk-forward: the flag is constant within nearly every train/test window (only the one
    # ~2007 transition window mixes eras), so it cannot inject a within-window time gradient.
    df["vix9d_available"] = df["VIX9D"].notna().astype(int)
    df["vix3m_available"] = df["VIX3M"].notna().astype(int)

    df["VIX9D_VIX_ratio"] = (df["VIX9D"] / df["VIX"]).fillna(1.0)
    df["VIX_VIX3M_ratio"] = (df["VIX"] / df["VIX3M"]).fillna(1.0)
    df.drop(columns=["VIX9D", "VIX3M"], inplace=True)
    return df


def add_earnings_proximity(df, ticker):
    """Add Days_to_earnings column, capped at 90. Defaults to 45 (neutral) on failure.

    The cap matters for long-history stock tickers: yfinance only returns ~20
    recent earnings dates, so uncapped values for old rows reach thousands of
    days — a calendar-era marker, not an earnings-proximity signal."""
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
        return min((future[0] - date).days, 90) if future else 90

    df["Days_to_earnings"] = [_days_to_next(d) for d in df.index]
    print("  ✓ Days_to_earnings")
    return df


def earnings_dates(ticker, limit=16):
    """Sorted, tz-naive, normalized earnings dates (past + future) from yfinance.
    Returns a list of pd.Timestamp, or [] on any failure/empty. Best-effort: never raises.
    Shared by next_earnings and modules/vol_history.py."""
    try:
        dates = yf.Ticker(ticker).get_earnings_dates(limit=limit)
        if dates is None or len(dates) == 0:
            return []
        idx = pd.DatetimeIndex(dates.index)
        if idx.tz is not None:
            idx = idx.tz_convert(None)
        return sorted(idx.normalize().unique())
    except Exception:
        return []


def next_earnings(ticker, daily=None):
    """Next scheduled earnings for `ticker` via yfinance + the typical historical earnings move.
    Returns {date: 'YYYY-MM-DD'|None, days: int|None, hist_move: float|None} or None (ETF / no data).
    `hist_move` = median |close-to-close| % around the last few past earnings (needs `daily` OHLCV).
    Best-effort: never raises (mirrors add_earnings_proximity's yfinance access)."""
    ed = earnings_dates(ticker)
    if not ed:
        return None

    today = pd.Timestamp.today().normalize()
    future = [e for e in ed if e >= today]
    past   = [e for e in ed if e < today]
    nxt = future[0] if future else None

    hist = None
    if daily is not None and "Close" in getattr(daily, "columns", []) and len(past) >= 2:
        ret = daily["Close"].pct_change()
        moves = []
        for e in past[-6:]:
            try:
                # the reaction lands on E (before-market report) or E+1 (after-market) — take the
                # larger of the two 1-day moves so the estimate is robust to BMO/AMC timing.
                w = ret.loc[e:].iloc[:2]
                if len(w):
                    moves.append(float(w.abs().max()))
            except Exception:
                continue
        if moves:
            hist = float(pd.Series(moves).median())

    if nxt is None:
        return {"date": None, "days": None, "hist_move": hist}
    return {"date": nxt.date().isoformat(), "days": int((nxt - today).days), "hist_move": hist}


def estimate_next_ex_div(ex_dates, today=None):
    """PURE (S46): next ex-dividend date estimated from PAST ex-dates (yfinance `dividends` index)
    — last ex-date + median cadence, rolled forward past today. Returns a normalized Timestamp, or
    None when history is too thin (<4 payments) or the cadence is irregular (median gap >400d,
    e.g. specials-only)."""
    if ex_dates is None or len(ex_dates) < 4:
        return None
    idx = pd.DatetimeIndex(ex_dates)
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    idx = idx.normalize().sort_values()
    med = idx.to_series().diff().median()
    if med is None or pd.isna(med) or med > pd.Timedelta(days=400) or med <= pd.Timedelta(0):
        return None
    today = pd.Timestamp(today).normalize() if today is not None else pd.Timestamp.today().normalize()
    nxt = idx[-1] + med
    while nxt <= today:
        nxt += med
    return nxt.normalize()


def next_ex_dividend(ticker):
    """Next ex-dividend date for `ticker` (S46) — a long call doesn't earn the dividend, the stock
    gaps down by it, and deep-ITM calls face early-exercise into ex-div. Exact date from the
    yfinance calendar when available; else estimated from the dividend-history cadence (flagged
    `est`). Returns {date, days, est} or None (non-payer / no data). Best-effort: never raises."""
    try:
        t = yf.Ticker(ticker)
        today = pd.Timestamp.today().normalize()
        exd = None
        try:
            cal = t.get_calendar() if hasattr(t, "get_calendar") else t.calendar
            if isinstance(cal, dict):
                exd = cal.get("Ex-Dividend Date")
            elif cal is not None and hasattr(cal, "index") and "Ex-Dividend Date" in list(cal.index):
                exd = cal.loc["Ex-Dividend Date"].iloc[0]
        except Exception:
            exd = None
        if exd is not None:
            d = pd.Timestamp(exd).normalize()
            if d >= today:
                return {"date": d.date().isoformat(), "days": int((d - today).days), "est": False}
        div = t.dividends
        nxt = estimate_next_ex_div(div.index if (div is not None and len(div)) else None, today)
        if nxt is None:
            return None
        return {"date": nxt.date().isoformat(), "days": int((nxt - today).days), "est": True}
    except Exception:
        return None


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
                            p2b_vol_multiple=P2B_VOL_MULTIPLE,
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
    win_threshold       = p2_vol_multiple  * median_hv * np.sqrt(p2_forward_days / 252)
    win_threshold_63    = p2b_vol_multiple * median_hv * np.sqrt(p2b_forward_days / 252)
    expansion_threshold = p3_vol_multiple  * median_hv

    if verbose:
        print(f"  Ticker median HV (20-day, annualized): {median_hv:.1%}")
        print(f"  P2_VOL_MULTIPLE = {p2_vol_multiple}  |  P2B_VOL_MULTIPLE = {p2b_vol_multiple}  |  P3_VOL_MULTIPLE = {p3_vol_multiple}")
        print(f"  WIN_THRESHOLD:       {win_threshold:.2%}")
        print(f"  WIN_THRESHOLD_63:    {win_threshold_63:.2%}")
        print(f"  EXPANSION_THRESHOLD: {expansion_threshold:.2%}")
        print("─" * 42)

    return win_threshold, win_threshold_63, expansion_threshold


def add_vix(df, start_date, end_date):
    """Download VIX/VIX9D/VIX3M and compute all VIX feature columns."""
    vix_raw   = yf.download("^VIX",   start=start_date, end=end_date, progress=False)
    vix9d_raw = yf.download("^VIX9D", start=start_date, end=end_date, progress=False)
    vix3m_raw = yf.download("^VIX3M", start=start_date, end=end_date, progress=False)
    df = compute_vix_features(df, vix_raw, vix9d_raw, vix3m_raw)
    print("  ✓ VIX, VIX_chg_5d, VIX_vs_ma20, VIX9D_VIX_ratio, VIX_VIX3M_ratio")
    return df


def add_benchmarks(df, benchmarks, start_date, end_date):
    """Download benchmark tickers and add relative strength + trend features."""
    for bench_ticker, bench_name in benchmarks:
        raw = yf.download(bench_ticker, start=start_date, end=end_date, progress=False)
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
