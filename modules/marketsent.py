"""
Market-wide sentiment + liquidity gauges (S58) — for the lens MARKET BACKDROP line and
market_context.py. Four independent gauges, each in its own try (a miss never costs the rest):

  • CBOE put/call ratios (daily, official site; probed live 2026-07-14): the daily market-stats
    page embeds total/index/equity ratios in its Next.js data blob. EQUITY P/C is the retail
    fear/complacency read (index P/C is hedging-dominated). No historical feed on the free
    page → the equity ratio ACCUMULATES into this cache forward-only; banded read meanwhile,
    trailing percentile once ≥63 days have built up.
  • AAII bull−bear spread (weekly survey; official free .xls with FULL history since 1987 —
    probed current through last week): percentile is real from day one. Contrarian read (S21):
    a crowded poll is a fade tell, not a trade signal.
  • NAAIM exposure index (weekly manager survey; site table carries ~10 weeks): current level
    + banded read; accumulates weekly into the cache for an eventual ≥26-week percentile.
  • Fed net liquidity = WALCL − TGA − RRP (FRED, reuses $env:FRED_API_KEY): the macro liquidity
    tide. Weekly-aligned; 13-week change gives the rising/falling read.

CONTEXT only, never a model feature. Cached ~6h (data/marketsent_cache.json, fng.py pattern);
best-effort: never raises, stale cache served on failure, None when nothing is available.
"""

import json
import os
import re
import time

import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/126 Safari/537.36"}
CACHE_FILE = "marketsent_cache.json"
TTL_HOURS = 6
TIMEOUT = 25

CBOE_URL = "https://www.cboe.com/us/options/market_statistics/daily/"
AAII_URL = "https://www.aaii.com/files/surveys/sentiment.xls"
NAAIM_URL = "https://naaim.org/programs/naaim-exposure-index/"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

EQ_PC_LOW, EQ_PC_HIGH = 0.55, 0.85   # equity P/C: below = complacent, above = fearful
NAAIM_HIGH, NAAIM_LOW = 90.0, 30.0   # manager exposure: leveraged-long vs defensive
AAII_CROWD = 0.80                    # spread percentile beyond (1−this)/this = crowded poll
LIQ_DEAD_BN = 25.0                   # |13w Δ net liquidity| ≤ $25bn reads flat
HIST_MIN_DAILY = 63                  # daily-series percentile floor (sentiment.py convention)
HIST_MIN_WEEKLY = 26                 # weekly floor (cot.py convention)


# ── pure parsers / reads (offline-testable) ──────────────────────────────────
def parse_cboe(html):
    """CBOE daily market-stats page → {"total", "index", "equity"} ratios (floats) or None.
    The Next.js blob escapes its JSON — strip backslashes, then read name/value pairs."""
    h = (html or "").replace("\\", "")
    pairs = dict(re.findall(r'"name":"([A-Z+/ ()]+? PUT/CALL RATIO)","value":"([0-9.]+)"', h))
    out = {}
    for key, name in (("total", "TOTAL PUT/CALL RATIO"), ("index", "INDEX PUT/CALL RATIO"),
                      ("equity", "EQUITY PUT/CALL RATIO")):
        if name in pairs:
            try:
                out[key] = float(pairs[name])
            except ValueError:
                pass
    return out or None


def label_equity_pc(v):
    if v is None:
        return ""
    if v < EQ_PC_LOW:
        return "complacent (heavy call tilt)"
    if v > EQ_PC_HIGH:
        return "fearful (heavy put tilt)"
    return "normal"


def aaii_read(rows):
    """PURE: [{date, bull, bear}] (chronological, full history) → the latest bull−bear spread
    with a FULL-HISTORY percentile + contrarian tag. Needs ≥HIST_MIN_WEEKLY rows."""
    rows = [r for r in (rows or []) if r.get("bull") is not None and r.get("bear") is not None]
    if len(rows) < HIST_MIN_WEEKLY:
        return None
    spreads = [float(r["bull"]) - float(r["bear"]) for r in rows]
    cur = spreads[-1]
    pct = sum(s < cur for s in spreads[:-1]) / max(len(spreads) - 1, 1)
    tag = ("crowded bullish — contrarian caution" if pct >= AAII_CROWD
           else "crowded bearish — contrarian support" if pct <= 1 - AAII_CROWD
           else "unremarkable")
    return {"date": str(rows[-1]["date"])[:10], "bull": float(rows[-1]["bull"]),
            "bear": float(rows[-1]["bear"]), "spread": cur, "pct": float(pct), "tag": tag}


def naaim_read(rows, hist=None):
    """PURE: [(date_iso, value)] newest-first (the site table, ~10 weeks) → latest exposure +
    banded tag; percentile from the ACCUMULATED cache history once ≥HIST_MIN_WEEKLY weeks."""
    if not rows:
        return None
    date, cur = rows[0][0], float(rows[0][1])
    tag = ("leveraged/max long" if cur >= NAAIM_HIGH
           else "defensive" if cur <= NAAIM_LOW else "moderate")
    pct = None
    vals = [v for d, v in (hist or {}).items() if d != date]
    if len(vals) >= HIST_MIN_WEEKLY:
        pct = float(sum(float(v) < cur for v in vals) / len(vals))
    avg4 = sum(float(v) for _, v in rows[:4]) / min(len(rows), 4)
    return {"date": date, "value": cur, "avg4": avg4, "tag": tag, "pct": pct}


def liq_read(walcl_mn, tga_mn, rrp_bn):
    """PURE: three {date_iso: value} dicts in FRED-native units (WALCL and WTREGEN $mn;
    RRPONTSYD $bn — probed live 2026-07-14) → net liquidity = WALCL − TGA − RRP in $bn,
    weekly-aligned (W-WED, ffill): level, 13w change, rising/falling tag, trailing-1y level
    percentile."""
    def _ser(d):
        s = pd.Series({pd.Timestamp(k): float(v) for k, v in (d or {}).items()
                       if v is not None}).sort_index()
        return s.resample("W-WED").last().ffill()

    w, t, r = _ser(walcl_mn) / 1000.0, _ser(tga_mn) / 1000.0, _ser(rrp_bn)
    net = (w - t - r).dropna()
    if len(net) < 14:
        return None
    cur = float(net.iloc[-1])
    chg13 = cur - float(net.iloc[-14])              # 13 weeks back
    tag = ("rising" if chg13 > LIQ_DEAD_BN
           else "falling" if chg13 < -LIQ_DEAD_BN else "flat")
    yr = net.iloc[-53:-1]
    pct = float((yr < cur).mean()) if len(yr) >= HIST_MIN_WEEKLY else None
    return {"date": net.index[-1].date().isoformat(), "level_bn": cur,
            "chg_13w_bn": chg13, "tag": tag, "pct": pct}


# ── fetchers (each its own failure domain) ───────────────────────────────────
def _fetch_cboe(hist):
    import requests
    r = requests.get(CBOE_URL, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    ratios = parse_cboe(r.text)
    if not ratios or ratios.get("equity") is None:
        return None
    today = time.strftime("%Y-%m-%d")
    hist.setdefault(today, ratios["equity"])        # forward-only accumulation
    vals = [v for d, v in hist.items() if d != today]
    pct = (float(sum(float(v) < ratios["equity"] for v in vals) / len(vals))
           if len(vals) >= HIST_MIN_DAILY else None)
    return {"date": today, **ratios, "tag": label_equity_pc(ratios["equity"]), "pct": pct}


def _fetch_aaii():
    import io

    import requests
    r = requests.get(AAII_URL, headers={**UA, "Referer": "https://www.aaii.com/sentimentsurvey"},
                     timeout=TIMEOUT)
    r.raise_for_status()
    if r.content[:4] != b"\xd0\xcf\x11\xe0":       # OLE2 magic — the server intermittently
        return None                                # serves an HTML page instead of the .xls
    df = pd.read_excel(io.BytesIO(r.content), engine="xlrd", header=None, usecols=[0, 1, 3])
    df.columns = ["date", "bull", "bear"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna()
    return aaii_read(df.to_dict("records"))


def _fetch_naaim(hist):
    import requests
    r = requests.get(NAAIM_URL, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    rows = re.findall(r"<td>(\d{2})/(\d{2})/(\d{4})</td>\s*<td>([\-0-9.]+)</td>", r.text)
    rows = [(f"{y}-{m}-{d}", float(v)) for m, d, y, v in rows]
    for d, v in rows:                                # site carries ~10 weeks — bank them all
        hist.setdefault(d, v)
    return naaim_read(rows, hist=hist)


def _fetch_liq():
    import requests
    key = os.environ.get("FRED_API_KEY")
    if not key:
        return None
    start = (pd.Timestamp.today() - pd.Timedelta(days=3 * 365)).date().isoformat()

    def _obs(series):
        resp = requests.get(FRED_URL, params={
            "series_id": series, "api_key": key, "file_type": "json",
            "observation_start": start}, timeout=TIMEOUT)
        resp.raise_for_status()
        return {o["date"]: o["value"] for o in resp.json().get("observations", [])
                if o.get("value") not in (None, ".")}

    return liq_read(_obs("WALCL"), _obs("WTREGEN"), _obs("RRPONTSYD"))


def fetch_marketsent(data_dir="data", ttl_hours=TTL_HOURS):
    """All four gauges, cached ~6h: {"gauges": {cboe, aaii, naaim, liq}, "hist": {...}}.
    Per-gauge best-effort — a failed gauge falls back to its cached value; never raises."""
    path = os.path.join(data_dir, CACHE_FILE)
    old = None
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
        if (time.time() - os.path.getmtime(path)) < ttl_hours * 3600:
            return old
    except Exception:
        pass
    hist = (old or {}).get("hist") or {}
    hist.setdefault("eq_pc", {})
    hist.setdefault("naaim", {})
    gauges, prior = {}, (old or {}).get("gauges") or {}
    for name, call in (("cboe", lambda: _fetch_cboe(hist["eq_pc"])),
                       ("aaii", _fetch_aaii),
                       ("naaim", lambda: _fetch_naaim(hist["naaim"])),
                       ("liq", _fetch_liq)):
        try:
            gauges[name] = call() or prior.get(name)
        except Exception:
            gauges[name] = prior.get(name)          # stale gauge beats a hole
    if not any(gauges.values()):
        return old
    out = {"gauges": gauges, "hist": hist, "as_of_str": time.strftime("%Y-%m-%d %H:%M")}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f)
    except Exception:
        pass
    return out
