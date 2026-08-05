"""
Dealer gamma-exposure (GEX) analytics (S56) — backs lens.py `--gex`.

Off the live Tradier chain (greeks ride every chain fetch): per-strike dealer gamma exposure,
the call wall / put wall (largest gamma-OI strikes — dynamic resistance/support), the zero-gamma
flip level (where net dealer gamma crosses 0 — above it dealers stabilize price, below it they
amplify moves), max pain for the nearest monthly, and today's unusual-activity strikes (volume
running a multiple of open interest = fresh positioning, not stale).

Convention caveat (always printed): the standard naive assumption — dealers are LONG the calls
and SHORT the puts customers bought. Real dealer inventory is unknowable from OI; treat levels
as context, not gospel. OI is also start-of-day (settles once daily), so intraday flow shifts
the walls before the numbers do.

Cached per ticker like pc-oi / volquote (session-stale: a new market close → re-fetch);
`force=True` (lens --live) re-fetches. Best-effort: never raises.
"""

import datetime
import json
import math
import os
import time

from modules.tradier import TRADIER_TOKEN, get_current_price, get_expirations, get_chain
from modules.pc_oi import _cache_path, cache_stale, _cache_age, _hhmm, is_monthly_expiry, \
    rehydrate_blocks
from modules.bs_invert import bs_gamma

SCOPEKEY = "gex1"        # bump when the cached payload shape changes
MAX_DTE = 60             # gamma concentrates near-dated; longer expiries are noise here
MAX_EXPIRIES = 8         # network cap — QQQ/SPY list near-daily expiries
NEAR_EXPIRIES = 5        # ... nearest N always included (front-loaded gamma)
CONTRACT = 100           # shares per contract
RISK_FREE = 0.04         # zero-gamma repricing only — level, not sensitivity-critical
UA_MIN_VOL = 500         # unusual activity: today volume floor ...
UA_MIN_RATIO = 2.0       # ... and volume ≥ this multiple of OI
UA_TOP = 6               # strikes shown
STRIKE_BAND = 0.15       # by-strike display band: ±15% of spot


# ── pure compute (offline-testable on fixture rows) ──────────────────────────
# `rows` = [{type: 'call'|'put', strike, oi, volume, gamma, iv, dte, expiry, bid, ask}, …]

def select_gex_expiries(future, max_dte=MAX_DTE, near=NEAR_EXPIRIES, cap=MAX_EXPIRIES):
    """Which expiries to fetch: the nearest `near` within `max_dte` (front gamma dominates)
    plus every MONTHLY within `max_dte` (institutional OI shelves), deduped, capped at `cap`.
    `future` = [(expiry_str, dte), …] with dte > 0, any order. PURE."""
    inside = sorted(((e, d) for e, d in future if 0 < d <= max_dte), key=lambda ed: ed[1])
    picked = list(inside[:near])
    for e, d in inside:
        if is_monthly_expiry(datetime.date.fromisoformat(e)) and (e, d) not in picked:
            picked.append((e, d))
    return sorted(picked, key=lambda ed: ed[1])[:cap]


def _unit_gex(gamma, oi, spot):
    """Dollar gamma per 1% spot move for one contract line: Γ × OI × 100 × S² × 0.01."""
    return gamma * oi * CONTRACT * spot * spot * 0.01


def gex_by_strike(rows, spot):
    """Aggregate dealer GEX per strike (calls positive, puts negative — naive convention).
    Returns (strikes, net_total): strikes = [{strike, call, put, net}, …] ascending, dollars
    per 1% move; net_total = Σ net across ALL rows (not just the display band)."""
    agg = {}
    net_total = 0.0
    for r in rows:
        g, oi = r.get("gamma"), r.get("oi")
        if not g or not oi:
            continue
        v = _unit_gex(g, oi, spot)
        v = v if r["type"] == "call" else -v
        net_total += v
        slot = agg.setdefault(r["strike"], {"strike": r["strike"], "call": 0.0, "put": 0.0})
        slot["call" if r["type"] == "call" else "put"] += v
    out = []
    for k in sorted(agg):
        s = agg[k]
        s["net"] = s["call"] + s["put"]
        out.append(s)
    return out, net_total


def key_levels(strikes):
    """Call wall = strike with the largest call GEX; put wall = largest |put GEX|.
    `strikes` from gex_by_strike. Returns {call_wall, call_wall_gex, put_wall, put_wall_gex}
    with None fields when a side is empty."""
    calls = [s for s in strikes if s["call"] > 0]
    puts = [s for s in strikes if s["put"] < 0]
    cw = max(calls, key=lambda s: s["call"]) if calls else None
    pw = min(puts, key=lambda s: s["put"]) if puts else None
    return {"call_wall": cw["strike"] if cw else None,
            "call_wall_gex": cw["call"] if cw else None,
            "put_wall": pw["strike"] if pw else None,
            "put_wall_gex": pw["put"] if pw else None}


def net_gex_at(rows, hypo_spot):
    """Net dealer GEX with every contract's gamma RE-PRICED at a hypothetical spot (Black-
    Scholes; needs per-row iv + dte). Rows without iv are skipped — consistent across all
    hypothetical spots, so the CROSSING is unaffected."""
    total = 0.0
    for r in rows:
        iv, oi, dte = r.get("iv"), r.get("oi"), r.get("dte")
        if not iv or not oi or not dte:
            continue
        g = bs_gamma(hypo_spot, r["strike"], RISK_FREE, dte / 365.0, iv)
        v = _unit_gex(g, oi, hypo_spot)
        total += v if r["type"] == "call" else -v
    return total


def zero_gamma(rows, spot, band=0.15, steps=31):
    """The spot level where net dealer gamma crosses 0 (the volatility-regime flip). Scans
    ±`band` around spot and linearly interpolates the sign change NEAREST current spot.
    Returns the level, or None when the profile never crosses in the band (deep one-sided
    positioning) or iv/dte are missing."""
    if not any(r.get("iv") and r.get("dte") for r in rows):
        return None
    lo, hi = spot * (1 - band), spot * (1 + band)
    xs = [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]
    ys = [net_gex_at(rows, x) for x in xs]
    crossings = []
    for i in range(len(xs) - 1):
        if ys[i] == 0:
            crossings.append(xs[i])
        elif (ys[i] < 0) != (ys[i + 1] < 0):
            frac = abs(ys[i]) / (abs(ys[i]) + abs(ys[i + 1]))
            crossings.append(xs[i] + frac * (xs[i + 1] - xs[i]))
    if not crossings:
        return None
    return min(crossings, key=lambda x: abs(x - spot))


def max_pain(rows):
    """OI-weighted max-pain strike for ONE expiry's rows: the settlement price minimizing the
    total intrinsic payout to option holders. Returns the strike, or None on empty/one-sided
    data (a pain minimum needs both wings)."""
    calls = [(r["strike"], r["oi"]) for r in rows if r["type"] == "call" and r.get("oi")]
    puts = [(r["strike"], r["oi"]) for r in rows if r["type"] == "put" and r.get("oi")]
    if not calls or not puts:
        return None
    candidates = sorted({r["strike"] for r in rows})
    best, best_pay = None, None
    for k in candidates:
        pay = (sum(oi * max(0.0, k - s) for s, oi in calls)
               + sum(oi * max(0.0, s - k) for s, oi in puts))
        if best_pay is None or pay < best_pay:
            best, best_pay = k, pay
    return best


def unusual_activity(rows, min_vol=UA_MIN_VOL, min_ratio=UA_MIN_RATIO, top=UA_TOP):
    """Contracts where TODAY'S volume runs a multiple of open interest — fresh positioning a
    stale-OI read misses. vol ≥ min_vol and vol/OI ≥ min_ratio (zero-OI strikes qualify on the
    volume floor alone — brand-new interest). Top `top` by ratio."""
    out = []
    for r in rows:
        vol, oi = r.get("volume") or 0, r.get("oi") or 0
        if vol < min_vol:
            continue
        ratio = (vol / oi) if oi else float("inf")
        if ratio >= min_ratio:
            out.append({"strike": r["strike"], "type": r["type"], "expiry": r["expiry"],
                        "dte": r["dte"], "volume": int(vol), "oi": int(oi),
                        "ratio": None if oi == 0 else ratio})
    out.sort(key=lambda u: (u["ratio"] is not None, -(u["ratio"] or 0), -u["volume"]))
    new = [u for u in out if u["ratio"] is None]
    rest = sorted((u for u in out if u["ratio"] is not None), key=lambda u: -u["ratio"])
    return (new + rest)[:top]


# ── fetch + cache (mirrors volquote.py) ───────────────────────────────────────

def _parse_chain(chain, expiry, dte):
    rows = []
    for _, r in chain.iterrows():
        try:
            greeks = r.get("greeks") or {}
            if not isinstance(greeks, dict):
                greeks = {}
            iv = greeks.get("smv_vol") or greeks.get("mid_iv")
            rows.append({"type": r.get("option_type"), "strike": float(r.get("strike")),
                         "oi": int(r.get("open_interest") or 0),
                         "volume": int(r.get("volume") or 0),
                         "gamma": float(greeks.get("gamma") or 0.0),
                         "iv": float(iv) if iv else None,
                         "expiry": expiry, "dte": int(dte)})
        except Exception:
            continue
    return rows


def _fetch(ticker):
    spot = get_current_price(ticker)
    today = datetime.date.today()
    exps = get_expirations(ticker)
    if isinstance(exps, str):
        exps = [exps]
    future = [(e, (datetime.date.fromisoformat(e) - today).days) for e in exps]
    selected = select_gex_expiries([(e, d) for e, d in future if d > 0])
    if not selected:
        return None

    rows = []
    for e, d in selected:
        rows.extend(_parse_chain(get_chain(ticker, e), e, d))
    if not rows:
        return None

    strikes, net_total = gex_by_strike(rows, spot)
    lvl = key_levels(strikes)
    band = [s for s in strikes
            if spot * (1 - STRIKE_BAND) <= s["strike"] <= spot * (1 + STRIKE_BAND)]

    # max pain on the nearest MONTHLY among the selected expiries (falls back to the nearest)
    monthlies = [(e, d) for e, d in selected
                 if is_monthly_expiry(datetime.date.fromisoformat(e))]
    mp_exp = (min(monthlies, key=lambda ed: ed[1]) if monthlies
              else min(selected, key=lambda ed: ed[1]))
    mp = max_pain([r for r in rows if r["expiry"] == mp_exp[0]])

    return {"spot": spot,
            "expiries": [{"expiry": e, "dte": d} for e, d in selected],
            "net_gex": net_total,
            "by_strike": band,
            "call_wall": lvl["call_wall"], "call_wall_gex": lvl["call_wall_gex"],
            "put_wall": lvl["put_wall"], "put_wall_gex": lvl["put_wall_gex"],
            "zero_gamma": zero_gamma(rows, spot),
            "max_pain": {"expiry": mp_exp[0], "dte": mp_exp[1], "strike": mp}
                        if mp is not None else None,
            "unusual": unusual_activity(rows)}


def _load(ticker, data_dir):
    try:
        with open(_cache_path(ticker, SCOPEKEY, data_dir), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save(ticker, data_dir, payload):
    path = _cache_path(ticker, SCOPEKEY, data_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"as_of": time.time(), "gex": payload}, f)
    except Exception:
        pass


def _wrap(payload, as_of, stale, cached):
    out = dict(payload)
    out.update({"as_of": as_of, "as_of_str": _hhmm(as_of), "age_str": _cache_age(as_of),
                "stale": stale, "cached": cached})
    return out


def _rehydrate_gex(payload):
    """Recompute a cached payload's date-derived fields vs today (S74 — served-stale safety net):
    expiries/unusual entries get fresh dtes and expired ones are DROPPED; max_pain keeps its
    (possibly negative) recomputed dte so the renderer can annotate it as expired. Never raises."""
    p = dict(payload)
    p["expiries"] = rehydrate_blocks(p.get("expiries"))
    p["unusual"] = rehydrate_blocks(p.get("unusual"))
    mp = p.get("max_pain")
    if mp:
        mp = dict(mp)
        try:
            mp["dte"] = (datetime.date.fromisoformat(str(mp["expiry"])) - datetime.date.today()).days
        except Exception:
            pass
        p["max_pain"] = mp
    return p


def gather_gex(ticker, interactive=False, data_dir="data", force=False):
    """Dealer GEX snapshot for `ticker` off the live Tradier chain (expiries ≤ MAX_DTE, capped).
    Cached session-stale like pc-oi; stale caches AUTO-REFRESH (S74 — `interactive` accepted for
    back-compat, unused; `force=True` under lens --live skips the cache). Returns the payload dict
    (+ as_of/as_of_str/age_str/stale/cached) or None (no token / no chain). Best-effort: never
    raises; a fetch failure serves the cache rehydrated (expired entries dropped)."""
    if not TRADIER_TOKEN or TRADIER_TOKEN == "YOUR_TOKEN_HERE":
        return None
    cache = _load(ticker, data_dir)
    stale = cache is not None and cache_stale(cache)

    refresh = cache is None or force or stale              # stale → auto-refresh (prompts removed, S74)

    if not refresh and cache is not None:
        return _wrap(_rehydrate_gex(cache["gex"]), cache["as_of"], stale, True)

    print(f"  gex: fetching {ticker} chains from Tradier…")
    try:
        payload = _fetch(ticker)
    except Exception:
        payload = None
    if payload is None:
        if cache is not None:
            return _wrap(_rehydrate_gex(cache["gex"]), cache["as_of"], stale, True)
        return None
    _save(ticker, data_dir, payload)
    return _wrap(payload, time.time(), False, False)
