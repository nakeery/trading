"""
Equal-weight market breadth (S45) — RSP−SPY and QQQE−QQQ for lens.py + market_context.py.

The MARKET BACKDROP's "SPY up" is cap-weighted — the top ~10 mega-caps are ~35-40% of the index,
so the headline can rise while the MEDIAN stock falls (a narrow, mega-cap-led tape). The
equal-weight twin (RSP; QQQE for the even-more-top-heavy NDX) weights every constituent the same,
so its RELATIVE performance is a direct breadth read: equal-weight lagging = narrow rally
(fragile tape — and an individual-name entry trades the AVERAGE stock's tape, not the headline's);
equal-weight leading = broad participation.

Design (lessons applied): the raw eq/cap ratio drifts DOWN secularly (a decade of mega-cap
outperformance), so long-window level percentiles would read "narrow" permanently — we use
short-horizon relative returns (20d/63d, matching setupcheck.RS_HORIZONS) and a trailing-1y
percentile of the rolling 20d-spread series. CONTEXT only, never a model feature (S20/S32), and
NOT a risk-scorecard factor (S43 — near-always-on factors inflate the tally). Narrow breadth is a
fragility tell, not a sell signal (S21).

Cached ~6h (data/breadth_cache.json, mirrors fng.py); best-effort: never raises, stale cache
served on failure, None when nothing is available.

S67 promotes the read from a backdrop one-liner to a full MARKET BREADTH section: each pair
gains a spread sparkline, a distance-from-52w-high for the cap leg, and a two-sided
divergence read (narrowing / broad / repair — `divergence_read`); a small-cap PARTICIPATION
pair (IWM−SPY — Russell 2000, NOT equal weight, labeled as such) rides the same single
batched download. build_backdrop keeps reading only "pairs", so the backdrop segment is
byte-unchanged.
"""

import json
import os
import time

import pandas as pd

from modules.sentiment import percentile_of, spark_of

CACHE_FILE = "breadth_cache.json"
TTL_HOURS = 6
PAIRS = {"RSP−SPY": ("RSP", "SPY"), "QQQE−QQQ": ("QQQE", "QQQ")}
PARTICIPATION = {"IWM−SPY": ("IWM", "SPY")}   # small-cap participation — NOT equal weight (S67)
REL_SHORT, REL_LONG = 20, 63     # sessions — mirror setupcheck.RS_HORIZONS
BREADTH_DEAD = 0.005             # |20d spread| ≤ 0.5% reads "mixed" (noise band)
NEAR_HIGH = 0.02                 # cap leg within 2% of its 252d closing high = "at the highs"
OFF_HIGH = 0.05                  # cap leg >5% off its high = clearly off (repair territory)


def divergence_read(rel_20d, pct, cap_off_high):
    """PURE (S67): two-sided narrowing-tape read → (state, desc). near-high means the
    cap-weight leg sits within NEAR_HIGH of its 252d closing high (cap_off_high ≥ −NEAR_HIGH).
      narrowing — near-high while the equal-weight spread is negative or in its bottom
                  quartile: mega-caps carrying the index without the average stock;
      broad     — near-high with the average stock leading: participation confirms;
      repair    — cap leg >OFF_HIGH off its high while equal-weight leads: breadth repairing;
      neutral   — everything else, and any None input.
    Display-only; NOT a scorecard factor (S43) — narrow breadth is fragility, not a sell
    signal (S21)."""
    if rel_20d is None or cap_off_high is None:
        return "neutral", ""
    near_high = cap_off_high >= -NEAR_HIGH
    if near_high and (rel_20d < -BREADTH_DEAD or (pct is not None and pct <= 0.25)):
        return ("narrowing",
                "cap-weight highs without the average stock — mega-caps carrying the index")
    if near_high and rel_20d > BREADTH_DEAD:
        return "broad", "average stock confirms the highs"
    if cap_off_high < -OFF_HIGH and rel_20d > BREADTH_DEAD:
        return ("repair",
                "equal-weight leading while the index is off its highs — breadth repairing")
    return "neutral", ""


def read_breadth(pairs):
    """PURE: {label: (eq_closes, cap_closes)} → {label: {rel_20d, rel_63d, pct, tag, spark,
    cap_off_high, div_state, div_desc}}.
    rel_h = equal-weight return − cap-weight return over the last h sessions; pct = trailing
    percentile of the current 20d spread within its own rolling series (drift-free by
    construction); tag = broad-led / narrow / mixed on a ±BREADTH_DEAD noise band; spark (S67)
    = the trailing 20d-spread series downsampled to ≤60 floats (same ≥63-obs floor as the
    percentile — [] when thin); cap_off_high = cap leg's distance from its 252d closing high
    (≤ 0); div_state/div_desc = `divergence_read`. Pairs with fewer than REL_SHORT+1 aligned
    sessions are omitted. Offline-testable."""
    out = {}
    for label, (eq, cap) in (pairs or {}).items():
        df = pd.concat([pd.Series(eq, dtype=float), pd.Series(cap, dtype=float)],
                       axis=1, join="inner", keys=["eq", "cap"]).dropna()
        if len(df) <= REL_SHORT:
            continue
        spread20 = df["eq"].pct_change(REL_SHORT) - df["cap"].pct_change(REL_SHORT)
        rel_20d = float(spread20.iloc[-1])
        rel_63d = (float((df["eq"].pct_change(REL_LONG) - df["cap"].pct_change(REL_LONG)).iloc[-1])
                   if len(df) > REL_LONG else None)
        tag = ("broad-led" if rel_20d > BREADTH_DEAD
               else "narrow" if rel_20d < -BREADTH_DEAD else "mixed")
        pct = percentile_of(spread20, rel_20d)
        cap_off_high = float(df["cap"].iloc[-1] / df["cap"].tail(252).max() - 1)
        div_state, div_desc = divergence_read(rel_20d, pct, cap_off_high)
        out[label] = {"rel_20d": rel_20d, "rel_63d": rel_63d, "pct": pct, "tag": tag,
                      "spark": spark_of(spread20), "cap_off_high": cap_off_high,
                      "div_state": div_state, "div_desc": div_desc}
    return out or None


def fetch_breadth(data_dir="data", ttl_hours=TTL_HOURS):
    """Current equal-weight breadth read, cached. ONE batched yfinance daily download for all
    five tickers (PAIRS + PARTICIPATION). Never raises; stale cache on failure, else None.
    Returns {"pairs": {...}, "participation": {...}}. A TTL-fresh pre-S67 cache (no
    "participation" key) is treated as stale and refetched (shape gate); the stale FALLBACK
    path still serves the old shape, so consumers must .get() the S67 fields."""
    path = os.path.join(data_dir, CACHE_FILE)
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl_hours * 3600:
            with open(path, encoding="utf-8") as f:
                cached = json.load(f)
            if isinstance(cached, dict) and "participation" in cached:   # S67 shape gate
                return cached
    except Exception:
        pass
    try:
        import yfinance as yf
        symbols = sorted({s for pair in {**PAIRS, **PARTICIPATION}.values() for s in pair})
        raw = yf.download(symbols, period="2y", interval="1d",
                          progress=False, auto_adjust=True)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        def _closes(defs):
            return {label: (close[eq], close[cap])
                    for label, (eq, cap) in defs.items()
                    if eq in close.columns and cap in close.columns}
        read = read_breadth(_closes(PAIRS))
        if read:
            out = {"pairs": read, "participation": read_breadth(_closes(PARTICIPATION)) or {}}
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(out, f)
            except Exception:
                pass
            return out
    except Exception:
        pass
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)                    # stale fallback beats nothing
    except Exception:
        return None
