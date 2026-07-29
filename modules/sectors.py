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
LOOKUP_CACHE_FILE = "sector_lookup_cache.json"
LOOKUP_TTL_HOURS = 24 * 30          # resolved hits: sector classification is stable, cache ~30d
LOOKUP_MISS_TTL_HOURS = TTL_HOURS   # unresolved/failed lookups: retry every ~6h so a transient
                                     # .info 401 self-heals instead of sticking for a month
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

# S67 — Invesco S&P 500 Equal Weight sector ETF per SPDR (the RYT/EW* family, renamed 2023-06).
# EW twin return − cap-weight return WITHIN the sector tags whether sector strength is broad
# or mega-cap-driven. A missing/dead symbol degrades that row's EW read to None ("—").
EW_TWIN = {
    "XLK": "RSPT", "XLC": "RSPC", "XLY": "RSPD", "XLF": "RSPF", "XLV": "RSPH",
    "XLI": "RSPN", "XLE": "RSPG", "XLB": "RSPM", "XLP": "RSPS", "XLU": "RSPU",
    "XLRE": "RSPR",
}


def ew_comparator(ticker, own_sector_sym=None):
    """PURE (S67): ticker → (symbol, label) equal-weight comparator — "is this name beating
    the AVERAGE stock or just riding mega-caps?". QQQ→QQQE; SPY→RSP; a SPDR sector (the
    ticker itself, or its resolved own-sector) → its RSP* twin; anything else → RSP as the
    average S&P 500 stock. Returns None when the ticker IS an equal-weight vehicle
    (comparing RSP to RSP is noise). No network, no cache."""
    t = (ticker or "").upper()
    if t in {"RSP", "QQQE", *EW_TWIN.values()}:
        return None
    if t in ("QQQ", "^NDX"):
        return ("QQQE", "average NDX-100 stock")
    if t in ("SPY", "^GSPC"):
        return ("RSP", "average S&P 500 stock")
    if t in SECTORS:
        return (EW_TWIN[t], f"average {SECTORS[t]} stock")
    if own_sector_sym in EW_TWIN:
        return (EW_TWIN[own_sector_sym], f"average {SECTORS[own_sector_sym]} stock")
    return ("RSP", "average S&P 500 stock")

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
    [{sym, name, rel_20d, rel_63d, tag, rank, ew_20d, ew_tag}] sorted by 63d RS (20d when 63d
    is missing). rel_h = sector return − SPY return over the last h sessions, aligned per pair
    so one short series never truncates the rest. ew_20d (S67) = equal-weight twin return −
    cap-weight sector return over 20 sessions WITHIN the sector (RSPT vs XLK); ew_tag =
    broad / narrow / mixed on the same ±ROT_DEAD band — None/None when the twin's series is
    absent or thin. Sectors with < REL_SHORT+1 aligned sessions are omitted.
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
        ew_20d = ew_tag = None
        ew_sym = EW_TWIN.get(sym)
        if ew_sym and ew_sym in closes:
            dfe = pd.concat([pd.Series(closes[ew_sym], dtype=float),
                             pd.Series(closes[sym], dtype=float)],
                            axis=1, join="inner", keys=["ew", "cap"]).dropna()
            if len(dfe) > REL_SHORT:
                ew_20d = float((dfe["ew"].pct_change(REL_SHORT)
                                - dfe["cap"].pct_change(REL_SHORT)).iloc[-1])
                ew_tag = ("broad" if ew_20d > ROT_DEAD
                          else "narrow" if ew_20d < -ROT_DEAD else "mixed")
        rows.append({"sym": sym, "name": name, "rel_20d": r20, "rel_63d": r63,
                     "tag": _quadrant(r20, r63), "ew_20d": ew_20d, "ew_tag": ew_tag})
    if not rows:
        return None
    rows.sort(key=lambda r: r["rel_63d"] if r["rel_63d"] is not None else r["rel_20d"],
              reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def _score_constituents(names, closes):
    """Shared scorer behind top/bottom_performers_read: [(sym, name)] + closes →
    [{sym, name, r20, r63}] sorted DESCENDING by 63d return (20d fallback)."""
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
    scored.sort(key=lambda m: m["r63"] if m["r63"] is not None else m["r20"], reverse=True)
    return scored


def top_performers_read(constituents, closes, top_n=TOP_N):
    """PURE: {spdr_sym: [(ticker, name), …]} + {ticker: close series} →
    {spdr_sym: [{sym, name, r20, r63}, …]} — each sector's constituents ranked by 63d return
    (20d when the series is too short for 63d, mirroring rotation_read's sort convention),
    capped at `top_n`. Names with < REL_SHORT+1 sessions are omitted; sectors with no usable
    name are omitted. Offline-testable."""
    out = {}
    for spdr, names in (constituents or {}).items():
        scored = _score_constituents(names, closes)
        if scored:
            out[spdr] = scored[:top_n]
    return out


def bottom_performers_read(constituents, closes, bottom_n=TOP_N):
    """PURE (S65): laggard mirror of top_performers_read — each sector's WORST `bottom_n`
    constituents by 63d return, worst first. Short-candidate material for the lens' SHORT
    SETUP section; same omission rules. Offline-testable."""
    out = {}
    for spdr, names in (constituents or {}).items():
        scored = _score_constituents(names, closes)
        if scored:
            out[spdr] = scored[-bottom_n:][::-1]          # tail of the desc sort, worst first
    return out


def _close_frame(raw, symbols):
    """Close-price frame from a yf.download result with SYMBOL column names in both shapes:
    MultiIndex (list download) and flat (yfinance returns single-level columns when exactly
    one symbol survives — the old `raw[["Close"]]` fallback kept the literal column name
    "Close", so no symbol ever matched and the data in hand was silently discarded)."""
    if isinstance(raw.columns, pd.MultiIndex):
        return raw["Close"]
    close = raw[["Close"]]
    if len(symbols) == 1:
        close = close.rename(columns={"Close": symbols[0]})
    return close


def fetch_top_performers(data_dir="data", ttl_hours=TTL_HOURS):
    """Current top performers per sector, cached (S59 — lens --movers). ~11 yf.Sector
    constituent lookups (each in its own try — one bad sector never costs the rest) + ONE
    batched daily download for all names. Never raises; stale cache on failure, else None.
    Returns {"sectors": {spdr_sym: [{sym, name, r20, r63}, …]}, "bottoms": {same, worst
    first}} (S65 adds "bottoms" — a pre-S65 cache without it is treated as stale)."""
    path = os.path.join(data_dir, TOP_CACHE_FILE)
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl_hours * 3600:
            with open(path, encoding="utf-8") as f:
                cached = json.load(f)
            if isinstance(cached, dict) and "bottoms" in cached:   # S65 shape gate
                return cached
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
            close = _close_frame(raw, symbols)
            close_map = {s: close[s] for s in symbols if s in close.columns}
            sectors = top_performers_read(constituents, close_map)
            if sectors:
                out = {"sectors": sectors,
                       "bottoms": bottom_performers_read(constituents, close_map)}
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


def own_sector(ticker, data_dir="data"):
    """The ticker's own sector ETF symbol. Order: (1) the ticker itself when it IS a SPDR
    (instant, no lookup needed); (2) a live yfinance .info sector lookup mapped through
    benchmarks.SECTOR_BENCHMARK (e.g. AAPL → "Technology" → XLK) — the primary source,
    skipped when a fresh cached resolution already covers this ticker; (3) if the live
    lookup fails or the sector is unmapped, the first SPDR-sector entry in
    benchmarks.TICKER_BENCHMARK (e.g. AMD → XLK via its second entry — ^SOX isn't a sector);
    (4) if that also misses, the last resolved value on disk even past TTL (a stale answer
    beats none — sector classification rarely changes). Cached per ticker in
    data/sector_lookup_cache.json — resolved hits ~30d, unresolved misses only ~6h (so a
    transient .info 401 self-heals instead of sticking for a month). Best-effort: never
    raises, None when nothing resolves anywhere."""
    t = (ticker or "").upper()
    if t in SECTORS:
        return t

    path = os.path.join(data_dir, LOOKUP_CACHE_FILE)
    cache = {}
    try:
        with open(path, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    entry = cache.get(t)
    if entry is not None:
        ttl = LOOKUP_TTL_HOURS if entry.get("sym") else LOOKUP_MISS_TTL_HOURS
        if (time.time() - entry.get("ts", 0)) < ttl * 3600:
            return entry.get("sym")

    sym = None
    try:
        import yfinance as yf
        from modules.benchmarks import SECTOR_BENCHMARK
        sector = yf.Ticker(t).info.get("sector", "")
        if sector in SECTOR_BENCHMARK:
            spdr, _name = SECTOR_BENCHMARK[sector]
            if spdr in SECTORS:
                sym = spdr
    except Exception:
        sym = None

    if sym is None:
        try:
            from modules.benchmarks import TICKER_BENCHMARK
            for bsym, _name in TICKER_BENCHMARK.get(t, []):
                if bsym in SECTORS:
                    sym = bsym
                    break
        except Exception:
            pass

    if sym is None and entry is not None and entry.get("sym"):
        sym = entry["sym"]              # stale-but-resolved beats nothing

    cache[t] = {"sym": sym, "ts": time.time()}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass
    return sym


def fetch_sectors(data_dir="data", ttl_hours=TTL_HOURS):
    """Current sector-rotation table, cached. ONE batched yfinance daily download for all 23
    symbols (11 SPDRs + SPY + the 11 equal-weight twins, S67). Never raises; stale cache on
    failure, else None. Returns {"rows": [...]}. A TTL-fresh pre-S67 cache (rows without
    "ew_tag") is treated as stale and refetched (shape gate); the stale FALLBACK path still
    serves old-shape rows, so consumers must .get() the S67 keys."""
    path = os.path.join(data_dir, CACHE_FILE)
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl_hours * 3600:
            with open(path, encoding="utf-8") as f:
                cached = json.load(f)
            if (isinstance(cached, dict) and cached.get("rows")
                    and "ew_tag" in cached["rows"][0]):            # S67 shape gate
                return cached
    except Exception:
        pass
    try:
        import yfinance as yf
        symbols = sorted(SECTORS) + [BENCH] + sorted(EW_TWIN.values())
        raw = yf.download(symbols, period="1y", interval="1d",
                          progress=False, auto_adjust=True)
        close = _close_frame(raw, symbols)
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
