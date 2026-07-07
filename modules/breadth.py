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
"""

import json
import os
import time

import pandas as pd

from modules.sentiment import percentile_of

CACHE_FILE = "breadth_cache.json"
TTL_HOURS = 6
PAIRS = {"RSP−SPY": ("RSP", "SPY"), "QQQE−QQQ": ("QQQE", "QQQ")}
REL_SHORT, REL_LONG = 20, 63     # sessions — mirror setupcheck.RS_HORIZONS
BREADTH_DEAD = 0.005             # |20d spread| ≤ 0.5% reads "mixed" (noise band)


def read_breadth(pairs):
    """PURE: {label: (eq_closes, cap_closes)} → {label: {rel_20d, rel_63d, pct, tag}}.
    rel_h = equal-weight return − cap-weight return over the last h sessions; pct = trailing
    percentile of the current 20d spread within its own rolling series (drift-free by
    construction); tag = broad-led / narrow / mixed on a ±BREADTH_DEAD noise band. Pairs with
    fewer than REL_SHORT+1 aligned sessions are omitted. Offline-testable."""
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
        out[label] = {"rel_20d": rel_20d, "rel_63d": rel_63d,
                      "pct": percentile_of(spread20, rel_20d), "tag": tag}
    return out or None


def fetch_breadth(data_dir="data", ttl_hours=TTL_HOURS):
    """Current equal-weight breadth read, cached. One batched yfinance daily download for all
    four tickers. Never raises; stale cache on failure, else None. Returns {"pairs": {...}}."""
    path = os.path.join(data_dir, CACHE_FILE)
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl_hours * 3600:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    try:
        import yfinance as yf
        symbols = sorted({s for pair in PAIRS.values() for s in pair})
        raw = yf.download(symbols, period="2y", interval="1d",
                          progress=False, auto_adjust=True)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        pairs = {label: (close[eq], close[cap])
                 for label, (eq, cap) in PAIRS.items()
                 if eq in close.columns and cap in close.columns}
        read = read_breadth(pairs)
        if read:
            out = {"pairs": read}
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
