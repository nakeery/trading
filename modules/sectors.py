"""
Sector rotation (S58) — the 11 SPDR sectors ranked by relative strength vs SPY, for lens.py.

Answers "is this name in a leading or lagging sector?" — the setup check's RS row reads the
TICKER vs its benchmark; this table reads the BENCHMARKS vs the market, so a strong RS read in
a lagging sector (or the reverse) is visible instead of silent. Horizons mirror breadth.py /
setupcheck.RS_HORIZONS (20d momentum, 63d leadership); the quadrant tag is an RRG-style read:
leading (ahead on both), improving (20d ahead, 63d behind), weakening (20d behind, 63d ahead),
lagging (behind on both).

CONTEXT only, never a model feature (S20/S32) and NOT a risk-scorecard factor (S43). Cached ~6h
(data/sectors_cache.json, mirrors fng.py/breadth.py); best-effort: never raises, stale cache
served on failure, None when nothing is available.
"""

import json
import os
import time

import pandas as pd

CACHE_FILE = "sectors_cache.json"
TTL_HOURS = 6
BENCH = "SPY"
SECTORS = {
    "XLK":  "Technology",
    "XLC":  "Communication",
    "XLY":  "Cons Discret",
    "XLF":  "Financials",
    "XLV":  "Health Care",
    "XLI":  "Industrials",
    "XLE":  "Energy",
    "XLB":  "Materials",
    "XLP":  "Cons Staples",
    "XLU":  "Utilities",
    "XLRE": "Real Estate",
}
REL_SHORT, REL_LONG = 20, 63     # sessions — mirror breadth.py / setupcheck.RS_HORIZONS
ROT_DEAD = 0.005                 # |RS| ≤ 0.5% reads flat (noise band, mirrors BREADTH_DEAD)

# ── top performers per sector (S59, opt-in via lens --movers) ────────────────
# yfinance Sector keys per SPDR (all 11 probed live 2026-07-16). Constituents come from
# yf.Sector(key).top_companies — each sector's LARGEST names by market weight (Yahoo's
# classification), not full ETF membership.
YF_SECTOR_KEYS = {
    "XLK":  "technology",
    "XLC":  "communication-services",
    "XLY":  "consumer-cyclical",
    "XLF":  "financial-services",
    "XLV":  "healthcare",
    "XLI":  "industrials",
    "XLE":  "energy",
    "XLB":  "basic-materials",
    "XLP":  "consumer-defensive",
    "XLU":  "utilities",
    "XLRE": "real-estate",
}
UNIVERSE_N = 10                  # largest constituents considered per sector
TOP_N = 3                        # performers shown per sector
TOP_CACHE_FILE = "sector_top_cache.json"


def _quadrant(r20, r63):
    """RRG-style tag from the two RS horizons (±ROT_DEAD noise band; missing 63d treated flat)."""
    s20 = 1 if r20 > ROT_DEAD else -1 if r20 < -ROT_DEAD else 0
    s63 = 1 if (r63 or 0) > ROT_DEAD else -1 if (r63 or 0) < -ROT_DEAD else 0
    if s20 > 0:
        return "leading" if s63 > 0 else "improving"
    if s20 < 0:
        return "weakening" if s63 > 0 else "lagging"
    return "leading" if s63 > 0 else "lagging" if s63 < 0 else "in line"


def rotation_read(closes, bench=BENCH):
    """PURE: {sym: close series} (must include `bench`) → ranked rows
    [{sym, name, rel_20d, rel_63d, tag, rank}] sorted by 63d RS (20d when 63d is missing).
    rel_h = sector return − SPY return over the last h sessions, aligned per pair so one short
    series never truncates the rest. Sectors with < REL_SHORT+1 aligned sessions are omitted.
    Offline-testable."""
    if bench not in (closes or {}):
        return None
    spy = pd.Series(closes[bench], dtype=float).dropna()
    rows = []
    for sym, name in SECTORS.items():
        if sym not in closes:
            continue
        df = pd.concat([pd.Series(closes[sym], dtype=float), spy],
                       axis=1, join="inner", keys=["sec", "spy"]).dropna()
        if len(df) <= REL_SHORT:
            continue
        r20 = float((df["sec"].pct_change(REL_SHORT) - df["spy"].pct_change(REL_SHORT)).iloc[-1])
        r63 = (float((df["sec"].pct_change(REL_LONG) - df["spy"].pct_change(REL_LONG)).iloc[-1])
               if len(df) > REL_LONG else None)
        rows.append({"sym": sym, "name": name, "rel_20d": r20, "rel_63d": r63,
                     "tag": _quadrant(r20, r63)})
    if not rows:
        return None
    rows.sort(key=lambda r: r["rel_63d"] if r["rel_63d"] is not None else r["rel_20d"],
              reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def top_performers_read(constituents, closes, top_n=TOP_N):
    """PURE: {spdr_sym: [(ticker, name), …]} + {ticker: close series} →
    {spdr_sym: [{sym, name, r20, r63}, …]} — each sector's constituents ranked by 63d return
    (20d when the series is too short for 63d, mirroring rotation_read's sort convention),
    capped at `top_n`. Names with < REL_SHORT+1 sessions are omitted; sectors with no usable
    name are omitted. Offline-testable."""
    out = {}
    for spdr, names in (constituents or {}).items():
        scored = []
        for sym, name in names or []:
            if sym not in (closes or {}):
                continue
            s = pd.Series(closes[sym], dtype=float).dropna()
            if len(s) <= REL_SHORT:
                continue
            r20 = float(s.pct_change(REL_SHORT).iloc[-1])
            r63 = float(s.pct_change(REL_LONG).iloc[-1]) if len(s) > REL_LONG else None
            scored.append({"sym": sym, "name": name, "r20": r20, "r63": r63})
        if not scored:
            continue
        scored.sort(key=lambda m: m["r63"] if m["r63"] is not None else m["r20"], reverse=True)
        out[spdr] = scored[:top_n]
    return out


def fetch_top_performers(data_dir="data", ttl_hours=TTL_HOURS):
    """Current top performers per sector, cached (S59 — lens --movers). ~11 yf.Sector
    constituent lookups (each in its own try — one bad sector never costs the rest) + ONE
    batched daily download for all names. Never raises; stale cache on failure, else None.
    Returns {"sectors": {spdr_sym: [{sym, name, r20, r63}, …]}}."""
    path = os.path.join(data_dir, TOP_CACHE_FILE)
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl_hours * 3600:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    try:
        import yfinance as yf
        constituents = {}
        for spdr, key in YF_SECTOR_KEYS.items():
            try:
                tc = yf.Sector(key).top_companies
                if tc is not None and len(tc):
                    constituents[spdr] = [(str(sym), str(row.get("name", sym)))
                                          for sym, row in tc.head(UNIVERSE_N).iterrows()]
            except Exception:
                continue
        symbols = sorted({sym for names in constituents.values() for sym, _ in names})
        if symbols:
            raw = yf.download(symbols, period="6mo", interval="1d",
                              progress=False, auto_adjust=True)
            close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
            sectors = top_performers_read(
                constituents, {s: close[s] for s in symbols if s in close.columns})
            if sectors:
                out = {"sectors": sectors}
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


def own_sector(ticker):
    """The ticker's own sector ETF symbol, no network: the ticker itself when it IS one,
    else the first SPDR-sector entry in benchmarks.TICKER_BENCHMARK (e.g. AMD → XLK via its
    second entry — ^SOX isn't a sector). None when unknown (yfinance .info 401s, so no
    lookup fallback)."""
    t = (ticker or "").upper()
    if t in SECTORS:
        return t
    try:
        from modules.benchmarks import TICKER_BENCHMARK
        for sym, _name in TICKER_BENCHMARK.get(t, []):
            if sym in SECTORS:
                return sym
    except Exception:
        pass
    return None


def fetch_sectors(data_dir="data", ttl_hours=TTL_HOURS):
    """Current sector-rotation table, cached. One batched yfinance daily download for all 12
    symbols. Never raises; stale cache on failure, else None. Returns {"rows": [...]}."""
    path = os.path.join(data_dir, CACHE_FILE)
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl_hours * 3600:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    try:
        import yfinance as yf
        symbols = sorted(SECTORS) + [BENCH]
        raw = yf.download(symbols, period="1y", interval="1d",
                          progress=False, auto_adjust=True)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        rows = rotation_read({s: close[s] for s in symbols if s in close.columns})
        if rows:
            out = {"rows": rows}
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
