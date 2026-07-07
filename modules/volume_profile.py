"""
Volume-at-price profile (S34 — multi-timeframe Lens).

Builds a histogram of volume by price level over a lookback window and derives the structural levels a
chartist cross-checks against their own:
  POC         — Point of Control: the max-volume price (magnet / fair value).
  Value Area  — the price band holding ~70% of volume (where most trade occurred).
  HVN / LVN   — high / low volume nodes: HVNs are strong S/R (price stalls); LVNs are gaps price moves
                through fast.

From whatever OHLCV is passed (1h intraday gives a finer profile; daily works too). Each daily/intraday
bar's volume is spread uniformly across its High–Low range, then binned — the standard approximation
when tick data isn't available.
"""

import numpy as np
import pandas as pd

VALUE_AREA_FRAC = 0.70
HVN_NEAR_PCT = 0.05     # near_hvn_above/below only report a shelf within ±5% of price — "approaching"
                        # in the risk scorecard means genuinely near, not the nearest at any distance (S43)


def volume_profile(ohlcv, lookback=None, bins=50, ref_price=None):
    df = ohlcv.tail(lookback) if lookback else ohlcv
    df = df.dropna(subset=["High", "Low", "Close", "Volume"])
    if len(df) < 5 or df["Volume"].sum() == 0:
        return None
    lo, hi = float(df["Low"].min()), float(df["High"].max())
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    vap = np.zeros(bins)

    for low, high, vol in zip(df["Low"].values, df["High"].values, df["Volume"].values):
        lo_i = int(np.clip(np.searchsorted(edges, low, side="right") - 1, 0, bins - 1))
        hi_i = int(np.clip(np.searchsorted(edges, high, side="right") - 1, 0, bins - 1))
        span = hi_i - lo_i + 1
        vap[lo_i:hi_i + 1] += vol / span

    total = vap.sum()
    poc_idx = int(vap.argmax())
    poc = float(centers[poc_idx])

    # Value area: expand from POC, always adding the larger adjacent bin, until 70% of volume.
    acc = vap[poc_idx]
    lo_ptr, hi_ptr = poc_idx - 1, poc_idx + 1
    included = {poc_idx}
    target = VALUE_AREA_FRAC * total
    while acc < target and (lo_ptr >= 0 or hi_ptr < bins):
        below = vap[lo_ptr] if lo_ptr >= 0 else -1.0
        above = vap[hi_ptr] if hi_ptr < bins else -1.0
        if above >= below:
            included.add(hi_ptr); acc += max(above, 0); hi_ptr += 1
        else:
            included.add(lo_ptr); acc += max(below, 0); lo_ptr -= 1
    va_lo, va_hi = float(centers[min(included)]), float(centers[max(included)])

    # HVN / LVN: local extrema of the volume-at-price curve, filtered by significance.
    mean, std = vap.mean(), vap.std()
    hvns, lvns = [], []
    for i in range(1, bins - 1):
        if vap[i] >= vap[i - 1] and vap[i] >= vap[i + 1] and vap[i] > mean + 0.5 * std:
            hvns.append(float(centers[i]))
        if vap[i] <= vap[i - 1] and vap[i] <= vap[i + 1] and vap[i] < mean - 0.5 * std:
            lvns.append(float(centers[i]))

    # ref_price: the caller's current price (e.g. the lens' 1D close) — the profile source can be a
    # stale 1h cache whose last close lags the daily bar, silently skewing price_location (S43).
    price = float(ref_price) if ref_price is not None else float(ohlcv["Close"].iloc[-1])
    location = ("in_value" if va_lo <= price <= va_hi
                else "above_value" if price > va_hi else "below_value")
    hvn_above = min((h for h in hvns if price < h <= price * (1 + HVN_NEAR_PCT)), default=None)
    hvn_below = max((h for h in hvns if price * (1 - HVN_NEAR_PCT) <= h < price), default=None)

    return {
        "poc": poc, "va_low": va_lo, "va_high": va_hi,
        "price": price, "price_location": location,
        "hvns": sorted(hvns), "lvns": sorted(lvns),
        "near_hvn_above": hvn_above, "near_hvn_below": hvn_below,
        "n_bars": len(df),
    }
