"""
CFTC Commitments of Traders — futures positioning context (S56) for lens.py + market_context.py.

Official free Socrata API (no key; probed live 2026-07-12): the Traders-in-Financial-Futures
(TFF) futures-only dataset, contracts E-MINI S&P 500 / NASDAQ MINI / VIX FUTURES. For each we
read LEVERAGED-FUNDS net position (hedge funds/CTAs — the fast money) as % of open interest,
with a trailing-1y percentile off the same series — the institutional-positioning counterpart
to the retail F&G gauge. CONTEXT only, never a model feature.

Reads publish Friday ~3:30pm ET with data as of Tuesday — a 3-day lag baked into the source.
Cached ~24h (data/cot_cache.json, mirrors fng.py); best-effort: never raises, stale cache on
failure, None when nothing is available.

Framework note (S21): crowded shorts unwinding have historically been contrarian-BUY fuel for
this framework's signals; extreme net-long = complacency, extreme net-short = fear. VIX futures
net-SHORT specs = the carry trade (vol sellers) — a large one is kindling for vol spikes.
"""

import json
import os
import time

import requests

COT_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"   # TFF, futures only
CACHE_FILE = "cot_cache.json"
TTL_HOURS = 24
WEEKS = 60                    # ~1y of weekly reports for the percentile window
CONTRACTS = {"ES": "E-MINI S&P 500", "NQ": "NASDAQ MINI", "VIX": "VIX FUTURES"}


def parse_cot(rows):
    """Socrata TFF rows (one contract, newest-first ok — sorted here) →
    {date, net, net_pct_oi, pct, n_weeks} or None. net = leveraged-funds long − short
    (contracts); net_pct_oi = net / open interest; pct = trailing percentile of net_pct_oi
    within the supplied history. Pure — unit-testable."""
    series = []
    for r in rows or []:
        try:
            date = str(r["report_date_as_yyyy_mm_dd"])[:10]
            lng = float(r["lev_money_positions_long"])
            sht = float(r["lev_money_positions_short"])
            oi = float(r["open_interest_all"])
            if oi <= 0:
                continue
            series.append((date, (lng - sht) / oi, lng - sht))
        except Exception:
            continue
    if not series:
        return None
    series.sort()                                    # oldest → newest
    date, npo, net = series[-1]
    hist = [x[1] for x in series]
    # inline percentile: sentiment.percentile_of floors at ≥63 obs (daily convention) —
    # COT is WEEKLY, so a year is ~52 rows; ≥26 weeks (~6mo) is the sane floor here
    pct = (sum(1 for h in hist if h <= npo) / len(hist)) if len(hist) >= 26 else None
    return {"date": date, "net": net, "net_pct_oi": npo,
            "pct": pct, "n_weeks": len(series)}


def label_cot(read, invert=False):
    """Short tag for a contract read. `invert=True` for VIX futures, where net-SHORT specs =
    the vol-selling carry crowd (complacency kindling), not bearishness."""
    if read is None:
        return "n/a"
    pct = read.get("pct")
    npo = read["net_pct_oi"]
    side = "net long" if npo >= 0 else "net short"
    if pct is None:
        return side
    if invert:
        tag = ("crowded vol-short" if (npo < 0 and pct <= 0.20)
               else "specs long vol (fear)" if (npo > 0 and pct >= 0.80) else "typical")
    else:
        tag = ("crowded long" if pct >= 0.85
               else "crowded short" if pct <= 0.15 else "typical")
    return f"{side} · {tag}"


def _fetch_contract(name):
    r = requests.get(COT_URL, params={
        "$select": ("report_date_as_yyyy_mm_dd,lev_money_positions_long,"
                    "lev_money_positions_short,open_interest_all"),
        "$where": f"contract_market_name = '{name}'",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(WEEKS)}, timeout=25)
    r.raise_for_status()
    return r.json()


def fetch_cot(data_dir="data", ttl_hours=TTL_HOURS):
    """{sym: {date, net, net_pct_oi, pct, n_weeks}} for ES/NQ/VIX, cached ~24h.
    Never raises; stale cache on failure, else None."""
    path = os.path.join(data_dir, CACHE_FILE)
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl_hours * 3600:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    out = {}
    for sym, name in CONTRACTS.items():
        try:
            read = parse_cot(_fetch_contract(name))
        except Exception:
            read = None
        if read:
            out[sym] = read
    if out:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f)
        except Exception:
            pass
        return out
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)                      # stale fallback beats nothing
    except Exception:
        return None
