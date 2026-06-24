"""
Cross-asset / geopolitical stress backdrop (S35) — opt-in CONTEXT for the Lens (`--geo`).

Surfaces the assets that move on geopolitical / macro shocks (oil first), which the framework's
price-action lens is structurally blind to (see the *Geopolitical / Exogenous Shock Limitation* in
CLAUDE.md). This is DISPLAY / HUMAN-CONTEXT ONLY — never a model feature: macro features were rejected
twice (econ-calendar S20, VIX regime gate S21) because feature-inflation compresses the edge tail and
shocks are unpredictable from history. Surfacing them as context sidesteps both.

Mirrors `modules.sentiment.gather_context`'s gauge-dict shape and reuses its `percentile_of`. Fetches
via yfinance (batched, like `features.add_vix`), FRED (same client pattern as `econ_calendar`), and a
best-effort GPR download. Never raises — any missing source degrades to a note. Results are cached to
`data/geo_cache.json` with a short TTL so repeat `--geo` runs in a day skip the network.
"""

import json
import os
import time

import pandas as pd

try:
    import yfinance as yf
except Exception:                       # pragma: no cover
    yf = None

import requests

from modules.sentiment import percentile_of

try:
    from modules.econ_calendar import FRED_API_KEY, FRED_URL
except Exception:                       # pragma: no cover
    FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
    FRED_URL = "https://api.stlouisfed.org/fred"

CACHE_TTL_HOURS = 6
_GPR_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"

# Each gauge: name, group, source, symbol, fmt, stress = which tail is "stress" (high|low).
GAUGES = [
    # Energy + safe-haven (yfinance) — the canonical geopolitical barometer
    {"name": "WTI crude",     "group": "ENERGY",  "src": "yf",   "sym": "CL=F",       "fmt": "{:.2f}", "stress": "high"},
    {"name": "Brent crude",   "group": "ENERGY",  "src": "yf",   "sym": "BZ=F",       "fmt": "{:.2f}", "stress": "high"},
    {"name": "Oil VIX (OVX)", "group": "ENERGY",  "src": "yf",   "sym": "^OVX",       "fmt": "{:.1f}", "stress": "high"},
    {"name": "Gold",          "group": "HAVEN",   "src": "yf",   "sym": "GC=F",       "fmt": "{:.0f}", "stress": "high"},
    {"name": "US Dollar (DXY)","group": "HAVEN",  "src": "yf",   "sym": "DX-Y.NYB",   "fmt": "{:.2f}", "stress": "high"},
    # Credit & rates stress
    {"name": "HY OAS (credit)","group": "CREDIT", "src": "fred", "sym": "BAMLH0A0HYM2","fmt": "{:.2f}", "stress": "high"},
    {"name": "MOVE (bond vol)","group": "CREDIT", "src": "yf",   "sym": "^MOVE",      "fmt": "{:.1f}", "stress": "high"},
    # Geo-sensitive sectors
    {"name": "Defense (ITA)", "group": "SECTORS", "src": "yf",   "sym": "ITA",        "fmt": "{:.2f}", "stress": "high"},
    {"name": "Semis (SOX)",   "group": "SECTORS", "src": "yf",   "sym": "^SOX",       "fmt": "{:.0f}", "stress": "low"},
    {"name": "Wheat",         "group": "SECTORS", "src": "yf",   "sym": "ZW=F",       "fmt": "{:.0f}", "stress": "high"},
    {"name": "Nat gas",       "group": "SECTORS", "src": "yf",   "sym": "NG=F",       "fmt": "{:.2f}", "stress": "high"},
    # Purpose-built risk indices
    {"name": "EPU (policy)",  "group": "INDICES", "src": "fred", "sym": "USEPUINDXD", "fmt": "{:.0f}", "stress": "high"},
    {"name": "GPR (geopol.)", "group": "INDICES", "src": "gpr",  "sym": "GPRD",       "fmt": "{:.0f}", "stress": "high"},
]


# ── pure helpers (offline-testable) ───────────────────────────────────────────
def _stressed(stress_dir, pct):
    """Is this gauge in its stress tail? high → top decile-ish (>=0.8), low → bottom (<=0.2)."""
    if pct is None:
        return False
    return (stress_dir == "high" and pct >= 0.8) or (stress_dir == "low" and pct <= 0.2)


def _composite(gauges):
    """(level, one-line read) from how many gauges are flashing. Mirrors sentiment._net_read."""
    firing = [g["name"] for g in gauges if g.get("stress")]
    n = len(firing)
    level = "HIGH" if n >= 4 else "ELEVATED" if n >= 2 else "LOW"
    if firing:
        comp = (f"geopolitical/macro stress: {level} — {n} gauge(s) in stress tail "
                f"({', '.join(firing)}). Weight options-implied tail risk (IV/skew/term) higher; "
                f"in this lens stress can be a contrarian BUY — don't auto-fade (see S21).")
    else:
        comp = "geopolitical/macro stress: LOW — no cross-asset gauges in their stress tail."
    return level, comp


# ── data fetch (best-effort; never raises) ────────────────────────────────────
def _fetch_yf(symbols, period="2y"):
    """Batched daily Close for yfinance symbols → {sym: Series}. Missing/failed symbols are absent."""
    if yf is None or not symbols:
        return {}
    try:
        raw = yf.download(symbols, period=period, interval="1d", progress=False)
    except Exception:
        return {}
    if raw is None or len(raw) == 0:
        return {}
    close = raw["Close"] if "Close" in getattr(raw, "columns", []) else raw
    out = {}
    if isinstance(close, pd.Series):                      # single symbol path
        s = close.dropna()
        if len(s):
            out[symbols[0]] = s
    else:
        for s_name in symbols:
            if s_name in close.columns:
                ser = close[s_name].dropna()
                if len(ser):
                    out[s_name] = ser
    return out


def _fetch_fred(series_id, start_years=8):
    """FRED series → Series. Returns None if FRED_API_KEY unset; empty Series on error."""
    if not FRED_API_KEY:
        return None
    try:
        start = (pd.Timestamp.today() - pd.DateOffset(years=start_years)).strftime("%Y-%m-%d")
        r = requests.get(f"{FRED_URL}/series/observations",
                         params={"series_id": series_id, "api_key": FRED_API_KEY,
                                 "file_type": "json", "observation_start": start}, timeout=15)
        r.raise_for_status()
        vals = {o["date"]: float(o["value"]) for o in r.json().get("observations", [])
                if o.get("value") not in (".", "", None)}
        s = pd.Series(vals)
        s.index = pd.to_datetime(s.index)
        return s.sort_index()
    except Exception:
        return pd.Series(dtype=float)


def _fetch_gpr():
    """Best-effort Caldara-Iacoviello GPR daily index → Series (empty if unreachable / no Excel engine)."""
    try:
        df = pd.read_excel(_GPR_URL)
    except Exception:
        return pd.Series(dtype=float)
    cols = {c.lower(): c for c in df.columns}
    dcol = next((cols[c] for c in cols if "date" in c), None)
    gcol = cols.get("gprd") or cols.get("gpr")
    if dcol is None or gcol is None:
        return pd.Series(dtype=float)
    try:
        s = pd.Series(df[gcol].values, index=pd.to_datetime(df[dcol])).dropna().sort_index()
        return s
    except Exception:
        return pd.Series(dtype=float)


def gather_geo_context(data_dir="data", ttl_hours=CACHE_TTL_HOURS, force=False):
    """Cross-asset / geopolitical stress gauges. Returns
    {as_of, gauges:[{group,name,value,fmt,label,pct,stress}], notes:[...], composite, level}.
    Cached to data/geo_cache.json with a TTL; never raises."""
    cache = os.path.join(data_dir, "geo_cache.json")
    if not force and os.path.exists(cache) and (time.time() - os.path.getmtime(cache)) < ttl_hours * 3600:
        try:
            with open(cache, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    gauges, notes = [], []
    yf_data = _fetch_yf([g["sym"] for g in GAUGES if g["src"] == "yf"])
    gpr_series = None  # fetch lazily (only one GPR gauge)

    for g in GAUGES:
        if g["src"] == "yf":
            s = yf_data.get(g["sym"])
        elif g["src"] == "fred":
            s = _fetch_fred(g["sym"])
            if s is None:
                notes.append(f"{g['name']}: set FRED_API_KEY to enable")
                continue
        else:  # gpr
            if gpr_series is None:
                gpr_series = _fetch_gpr()
            s = gpr_series

        if s is None or len(s.dropna()) == 0:
            notes.append(f"{g['name']} ({g['sym']}) unavailable — skipped")
            continue
        s = s.dropna()
        value = float(s.iloc[-1])
        pct = percentile_of(s, value)
        stressed = _stressed(g["stress"], pct)
        gauges.append({"group": g["group"], "name": g["name"], "value": value, "fmt": g["fmt"],
                       "label": ("⚠ stress" if stressed else ""), "pct": pct, "stress": bool(stressed)})

    level, composite = _composite(gauges)
    out = {"as_of": pd.Timestamp.today().strftime("%Y-%m-%d"),
           "gauges": gauges, "notes": notes, "composite": composite, "level": level}
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(out, f)
    except Exception:
        pass
    return out
