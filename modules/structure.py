"""
Transparent market-structure reads (S34 — multi-timeframe Lens).

Every function here describes CURRENT STATE on a given timeframe's OHLCV — no prediction, no ML, no
claimed edge. Functions are timeframe-agnostic (run them on 1h/4h/1D/1W/1M frames) so the cockpit can
surface cross-timeframe confluence vs conflict (the oversold-daily / overbought-weekly blind spot).

Uses the `ta` library (already a project dependency) for indicators, mirroring indicators.py.
"""

import numpy as np
import pandas as pd
import ta


def _safe(series, i=-1):
    try:
        v = series.iloc[i]
        return float(v) if pd.notna(v) else None
    except Exception:
        return None


def read_timeframe(ohlcv):
    """Trend / momentum / overbought-oversold state for ONE timeframe. Returns a labeled dict."""
    c, h, l = ohlcv["Close"], ohlcv["High"], ohlcv["Low"]
    if len(c.dropna()) < 30:
        return {"ok": False}
    ma20 = c.rolling(20).mean()
    ma50 = c.rolling(50).mean()
    rsi = ta.momentum.RSIIndicator(c, window=14).rsi()
    stoch = ta.momentum.StochasticOscillator(h, l, c, window=14, smooth_window=3).stoch()
    macd = ta.trend.MACD(c)
    macd_line, macd_sig = macd.macd(), macd.macd_signal()

    price = _safe(c); m20 = _safe(ma20); m50 = _safe(ma50)
    if price is None:                       # trailing NaN bar (e.g. an unfilled today-row) → skip TF
        return {"ok": False}
    r = _safe(rsi); st = _safe(stoch)
    ml, ms = _safe(macd_line), _safe(macd_sig)
    slope20 = (m20 - _safe(ma20, -6)) if (m20 and _safe(ma20, -6)) else 0

    above20 = price > m20 if (price and m20) else None
    above50 = price > m50 if (price and m50) else None
    if above20 and above50 and slope20 > 0:
        trend = "up"
    elif above20 is False and above50 is False and slope20 < 0:
        trend = "down"
    else:
        trend = "mixed"

    # range position over a ~1y-equivalent trailing window for this TF
    win = min(len(c), 252)
    lo, hi = c.iloc[-win:].min(), c.iloc[-win:].max()
    range_pos = (price - lo) / (hi - lo) if hi > lo else 0.5

    return {
        "ok": True,
        "price": price,
        "trend": trend,
        "above_ma20": above20, "above_ma50": above50,
        "dist_ma20_pct": (price / m20 - 1) if (price and m20) else None,
        "rsi": r,
        "rsi_state": "overbought" if (r and r >= 70) else "oversold" if (r and r <= 30) else "neutral",
        "stoch_state": "overbought" if (st and st >= 80) else "oversold" if (st and st <= 20) else "neutral",
        "macd_state": "bullish" if (ml is not None and ms is not None and ml > ms) else "bearish",
        "range_pos": range_pos,
    }


def read_volume(ohlcv, exclude_last=False):
    """Volume = trend strength. RVOL, up/down balance, price-volume confirmation/divergence, OBV slope.

    exclude_last: on a resampled timeframe whose latest bar is still forming (an in-progress week or
    month), that bar holds only a fraction of its eventual volume, so RVOL / ΔVol% read artificially
    low. When True the VOLUME reads are computed on completed bars only; the live close is still used
    for price_chg so the ΔPrc% column stays current."""
    c_live = ohlcv["Close"]                       # live close — keep ΔPrc% on the in-progress bar
    if exclude_last and len(ohlcv) > 1:
        ohlcv = ohlcv.iloc[:-1]                    # drop the partial bar for the volume reads
    c, v = ohlcv["Close"], ohlcv["Volume"]
    if len(v.dropna()) < 25 or v.tail(20).sum() == 0:
        return {"ok": False}
    avgvol = v.rolling(20).mean()
    rvol = _safe(v) / _safe(avgvol) if _safe(avgvol) else None

    last20 = ohlcv.iloc[-20:]
    dchg = last20["Close"].diff()
    upvol = last20["Volume"][dchg > 0].sum()
    downvol = last20["Volume"][dchg < 0].sum()
    ud = (upvol / downvol) if downvol > 0 else float("inf")

    # price direction vs the TREND in average volume, both over the last ~10 bars (NOT the latest-bar
    # RVOL above). Volume should expand in the direction of the trend; if it doesn't, the move is weak.
    price_chg = _safe(c_live) / _safe(c_live, -11) - 1 if _safe(c_live, -11) else 0
    vol_trend = (_safe(avgvol) / _safe(avgvol, -11) - 1) if _safe(avgvol, -11) else 0
    if price_chg > 0 and vol_trend > 0:
        tag, conf = "up-confirmed", "rising price + rising volume (healthy advance)"
    elif price_chg > 0:
        tag, conf = "up-WEAK", "rising price on FALLING volume (advance unconfirmed)"
    elif price_chg < 0 and vol_trend > 0:
        tag, conf = "dn-distrib", "falling price + rising volume (distribution / selling pressure)"
    else:
        tag, conf = "dn-exhaust", "falling price + fading volume (possible exhaustion)"

    obv = ta.volume.OnBalanceVolumeIndicator(c, v).on_balance_volume()
    obv_slope = (_safe(obv) - _safe(obv, -11)) if _safe(obv, -11) is not None else 0

    return {"ok": True, "rvol": rvol, "ud_ratio": ud, "tag": tag, "confirmation": conf,
            "price_chg_10": price_chg, "vol_trend_10": vol_trend,
            "obv_rising": obv_slope > 0,
            "unconfirmed": tag == "up-WEAK",
            "distribution": tag == "dn-distrib"}


def detect_divergence(ohlcv, lookback=40, recent=10):
    """Pragmatic price-vs-momentum divergence on one TF. Compares the recent pivot to the prior pivot
    in RSI and OBV. Returns 'bearish' / 'bullish' / None with a short reason."""
    c, v = ohlcv["Close"], ohlcv["Volume"]
    if len(c.dropna()) < lookback + 5:
        return None, ""
    rsi = ta.momentum.RSIIndicator(c, window=14).rsi()
    obv = ta.volume.OnBalanceVolumeIndicator(c, v).on_balance_volume()
    seg = c.iloc[-lookback:]
    recent_win = seg.iloc[-recent:]
    prior_win = seg.iloc[:-recent]

    # bearish: higher price high but lower RSI/OBV high
    rp_hi, pp_hi = recent_win.idxmax(), prior_win.idxmax()
    if recent_win.max() > prior_win.max():
        if (rsi.get(rp_hi, np.nan) < rsi.get(pp_hi, np.nan)) or (obv.get(rp_hi, np.nan) < obv.get(pp_hi, np.nan)):
            return "bearish", "price higher high, momentum/OBV lower high"
    # bullish: lower price low but higher RSI/OBV low
    rp_lo, pp_lo = recent_win.idxmin(), prior_win.idxmin()
    if recent_win.min() < prior_win.min():
        if (rsi.get(rp_lo, np.nan) > rsi.get(pp_lo, np.nan)) or (obv.get(rp_lo, np.nan) > obv.get(pp_lo, np.nan)):
            return "bullish", "price lower low, momentum/OBV higher low"
    return None, ""


def multi_timeframe_summary(reads):
    """Confluence vs conflict across timeframes. `reads` = {tf: read_timeframe(...)}, in display order.
    Returns {trend_row, rsi_row, conflict, synthesis}."""
    tfs = [tf for tf, r in reads.items() if r.get("ok")]
    trend = {tf: reads[tf]["trend"] for tf in tfs}
    rsi = {tf: reads[tf]["rsi_state"] for tf in tfs}

    higher = [tf for tf in ("1M", "1W") if tf in tfs]
    lower = [tf for tf in ("1D", "4h", "1h") if tf in tfs]
    hi_up = all(trend[tf] == "up" for tf in higher) if higher else False
    hi_dn = all(trend[tf] == "down" for tf in higher) if higher else False
    lo_up = all(trend[tf] == "up" for tf in lower) if lower else False
    lo_dn = all(trend[tf] == "down" for tf in lower) if lower else False

    conflict = None
    if hi_up and lo_dn:
        conflict = "higher timeframes UP but lower timeframes DOWN — a pullback within a larger uptrend."
    elif hi_dn and lo_up:
        conflict = "higher timeframes DOWN but lower timeframes UP — a bounce within a larger downtrend; rallies likely sold into higher-TF resistance."
    # RSI conflict (the user's scenario)
    ob = [tf for tf in tfs if rsi[tf] == "overbought"]
    os_ = [tf for tf in tfs if rsi[tf] == "oversold"]
    rsi_conflict = (f"RSI split: oversold on {','.join(os_)} but overbought on {','.join(ob)} — "
                    f"near-term bounce into higher-TF stretch." if ob and os_ else None)

    if hi_up and lo_up:
        synth = "full bullish confluence across timeframes."
    elif hi_dn and lo_dn:
        synth = "full bearish confluence across timeframes."
    else:
        synth = conflict or "mixed — timeframes not aligned; trade the dominant (higher) timeframe."
    return {"trend_row": trend, "rsi_row": rsi, "conflict": conflict,
            "rsi_conflict": rsi_conflict, "synthesis": synth}


def rally_drawdown_risk(reads, profile=None, ctx=None, divergences=None):
    """Two-sided transparent scorecard. Returns {drawdown: [factors], rally: [factors], net}.
    Each factor is a short string naming the condition + its source. NOT a forecast."""
    dd, rally = [], []
    daily = reads.get("1D", {})

    # higher-TF stretch even if daily oversold (the motivating scenario)
    for tf in ("1W", "1M"):
        r = reads.get(tf, {})
        if r.get("ok") and r.get("rsi_state") == "overbought":
            dd.append(f"{tf} overbought (RSI {r['rsi']:.0f}) — higher-TF stretch")
        if r.get("ok") and r.get("rsi_state") == "oversold":
            rally.append(f"{tf} oversold (RSI {r['rsi']:.0f}) — higher-TF washout")
    # daily extension / OB-OS
    if daily.get("ok"):
        d = daily.get("dist_ma20_pct")
        if d is not None and d > 0.08:
            dd.append(f"daily extended {d:+.0%} above MA20 (mean-reversion pull)")
        if d is not None and d < -0.08:
            rally.append(f"daily {d:+.0%} below MA20 (snap-back potential)")
        if daily.get("range_pos", 0.5) > 0.9:
            dd.append("daily near top of 1y range")
        if daily.get("range_pos", 0.5) < 0.1:
            rally.append("daily near bottom of 1y range (washout)")

    # volume confirmation (passed via reads[tf]['_vol'])
    for tf in ("1D", "1W"):
        vol = reads.get(tf, {}).get("_vol")
        if not (vol and vol.get("ok")):
            continue
        if vol.get("unconfirmed"):
            dd.append(f"{tf} rally on falling volume (weak/unconfirmed)")
        if vol.get("distribution"):
            dd.append(f"{tf} distribution (price down on rising volume)")

    # divergences
    for tf, (kind, why) in (divergences or {}).items():
        if kind == "bearish":
            dd.append(f"{tf} bearish divergence ({why})")
        elif kind == "bullish":
            rally.append(f"{tf} bullish divergence ({why})")

    # volume profile — price into HVN above / value-area edges
    if profile:
        loc = profile.get("price_location")
        if loc == "above_value":
            dd.append("price above value area (extended from volume fair-value)")
        elif loc == "below_value":
            rally.append("price below value area (discount to volume fair-value)")
        if profile.get("near_hvn_above"):
            dd.append(f"approaching volume HVN resistance ~{profile['near_hvn_above']:.2f}")
        if profile.get("near_hvn_below"):
            rally.append(f"volume HVN support ~{profile['near_hvn_below']:.2f} below")

    # options / vol context (from gather_context)
    if ctx:
        for g in ctx.get("gauges", []):
            if g["name"] == "IV/HV ratio" and g["value"] >= 1.40:
                dd.append(f"options rich (IV/HV {g['value']:.2f}) — market pricing near-term risk")
            if g["name"] == "IV/HV ratio" and g["value"] < 0.85:
                rally.append(f"options cheap (IV/HV {g['value']:.2f})")
            if g["name"] == "Term structure" and g["value"] >= 1.05:
                dd.append("term backwardation — near-term stress priced")
        if ctx.get("regime") == "stress":
            dd.append("VIX stress regime (elevated market risk)")

    net = ("DRAWDOWN risk elevated" if len(dd) > len(rally)
           else "RALLY-favorable" if len(rally) > len(dd)
           else "balanced / no clear lean")
    return {"drawdown": dd, "rally": rally, "net": f"{net}  ({len(dd)} drawdown vs {len(rally)} rally factors)"}
