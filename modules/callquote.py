"""
Long-call viability quote (S46) — backs lens.py `--call`.

The lens characterizes direction/timing/vol; this block prices the INSTRUMENT itself — the carry
math of a directional long call: premium, breakeven move, theta per day as a % of premium (the
"how fast am I bleeding if the chart stalls" number), delta, OI and spread, at the two tenors the
research consensus favors (~45d — enough time to slow theta — and ~90d for the swing), ATM plus
the ~0.35–0.40Δ trend band. Adds an ATM-IV-by-expiry mini-curve (which tenor is the cheaper vol
buy) and a chain LIQUIDITY GRADE (median ATM-region spread + OI → tight/ok/wide/dead — the
CRSP-style dead-chain catch). Descriptive context, not advice; no prediction.

Cached per ticker session-stale like volquote/pc-oi (option prices move intraday — a cached quote
is a snapshot "as of HH:MM"; TTY-gated refresh; `force=True` under lens --live). Best-effort:
never raises past the fetch guard.
"""

import datetime
import json
import os
import time

from modules.tradier import TRADIER_TOKEN, get_current_price, get_expirations, get_chain
from modules.pc_oi import _cache_path, cache_stale, _cache_age, _hhmm

SCOPEKEY = "call4"           # bumped when the cached payload shape changes (S72: every monthly)
# S72 — EXPIRY WINDOW. Superseded the S69 "nearest expiry to each of 4 target DTEs" rule, which
# quoted only 4 expiries and silently hid the rest: SOFI lists monthlies at 113/141/232 DTE that
# never appeared. Now every MONTHLY inside the window is quoted, and the picker shows them all —
# so the user chooses the tenor instead of the code guessing which 4 they meant. Widen/narrow
# here; each added expiry is one Tradier chain call (~0.55s measured).
EXPIRY_MIN_DTE = 20          # below this it's weekly/gamma territory, not a long-call tenor
EXPIRY_MAX_DTE = 550         # ~18mo — past the next Jan LEAP; beyond it OI thins out badly
MAX_EXPIRIES = 12            # network cap, nearest-first (rarely binds: 10 SOFI / 12 QQQ / 5 CRSP)
# The tenors the CLI curates down to — a terminal can't have a picker, and 12 expiries × 5 targets
# would be 60 rows. The WEB gets every expiry; the CLI shows the nearest monthly to each of these.
TARGET_DTES = (45, 90, 180, 365)
OTM_DELTA = 0.375            # midpoint of the 0.35–0.40Δ trend band
# Per-expiry strike ladder (S69) — the chain rows are already fetched for the ATM/OTM pick, so
# retaining a bounded ladder costs ZERO extra network. Feeds the web strike selector.
LADDER_PCT = 0.25            # keep tradeable calls within ±25% of spot …
LADDER_MAX = 9               # … nearest-to-spot first, capped (payload size + a usable dropdown)
# Liquidity-grade bands — ATM region = the 5 strikes nearest spot, calls + puts:
LIQ_TIGHT_SPR = 0.01         # median spread ≤1% of mid (and OI ≥ LIQ_TIGHT_OI) → "tight"
LIQ_OK_SPR    = 0.03         # ≤3% → "ok"
LIQ_WIDE_SPR  = 0.08         # ≤8% → "wide"; beyond → "dead"
LIQ_TIGHT_OI  = 1000
LIQ_MIN_OI    = 100          # below this, tight/ok demote to "wide"


def _load(ticker, data_dir):
    try:
        with open(_cache_path(ticker, SCOPEKEY, data_dir), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save(ticker, data_dir, quote):
    path = _cache_path(ticker, SCOPEKEY, data_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"as_of": time.time(), "quote": quote}, f)
    except Exception:
        pass


def _mid(o):
    b, a = o.get("bid") or 0, o.get("ask") or 0
    return (b + a) / 2 if (b or a) else None


def _parse(chain):
    """Tradier chain DataFrame → row dicts incl. greeks (delta/theta/smv IV)."""
    rows = []
    for _, r in chain.iterrows():
        try:
            g = r.get("greeks") or {}
            if not isinstance(g, dict):
                g = {}
            rows.append({"type": r.get("option_type"), "strike": float(r.get("strike")),
                         "bid": float(r.get("bid") or 0), "ask": float(r.get("ask") or 0),
                         "oi": int(r.get("open_interest") or 0),
                         "volume": int(r.get("volume") or 0),
                         "delta": g.get("delta"), "theta": g.get("theta"),
                         "iv": g.get("smv_vol") or g.get("mid_iv")})
        except Exception:
            continue
    return rows


def pick_call_candidates(rows, spot, otm_delta=OTM_DELTA):
    """PURE: parsed chain rows → (atm_call, otm_call|None). ATM = tradeable (bid>0) call with
    strike nearest spot; OTM = tradeable OTM call with delta nearest `otm_delta` (skipped when no
    deltas available or it collapses onto the ATM strike)."""
    calls = [r for r in rows if r["type"] == "call" and (r.get("bid") or 0) > 0]
    if not calls:
        return None, None
    atm = min(calls, key=lambda r: abs(r["strike"] - spot))
    otm = None
    with_delta = [r for r in calls if r["strike"] > spot and r.get("delta") is not None]
    if with_delta:
        otm = min(with_delta, key=lambda r: abs(float(r["delta"]) - otm_delta))
        if otm["strike"] == atm["strike"]:
            otm = None
    return atm, otm


def _candidate(o, spot):
    """One quoted call → display dict: mid premium, BE price/move, theta/day (% of premium),
    delta/OI/spread; at-ask BE when the mid understates the executable cost by >3% (S40 pattern)."""
    if o is None:
        return None
    m = _mid(o)
    if not m or m <= 0 or not spot:
        return None
    theta = o.get("theta")
    out = {"strike": o["strike"],
           "delta": float(o["delta"]) if o.get("delta") is not None else None,
           "mid": m, "be": o["strike"] + m, "be_move": (o["strike"] + m) / spot - 1,
           "theta_pct": (abs(float(theta)) / m) if theta else None,
           "oi": o.get("oi"), "iv": o.get("iv"),
           "spread_pct": ((o["ask"] - o["bid"]) / m) if (o["bid"] > 0 and o["ask"] > 0) else None}
    if o["ask"] > 0 and o["ask"] > m * 1.03:
        out.update({"ask": o["ask"], "be_ask": o["strike"] + o["ask"],
                    "be_move_ask": (o["strike"] + o["ask"]) / spot - 1})
    return out


def liquidity_grade(rows, spot, n_strikes=2):
    """PURE: chain-liquidity verdict off the ATM region (the 1+2×n_strikes strikes nearest spot,
    calls + puts). {grade, spread_pct (median, mid-relative), oi, volume, n_no_bid, n} or None.
    Bands: ≤1% + OI≥1000 tight · ≤3% ok · ≤8% wide · beyond / majority-no-bid dead; OI<100 caps
    tight/ok at wide."""
    strikes = sorted({r["strike"] for r in rows}, key=lambda s: abs(s - spot))[:1 + 2 * n_strikes]
    region = [r for r in rows if r["strike"] in strikes]
    if not region:
        return None
    no_bid = sum(1 for r in region if (r.get("bid") or 0) <= 0)
    sprs = sorted((r["ask"] - r["bid"]) / m for r in region
                  if r["bid"] > 0 and r["ask"] > 0 and (m := _mid(r)))
    med = sprs[len(sprs) // 2] if sprs else None
    oi = sum(int(r.get("oi") or 0) for r in region)
    vol = sum(int(r.get("volume") or 0) for r in region)
    if med is None or no_bid > len(region) // 2 or med > LIQ_WIDE_SPR:
        grade = "dead"
    elif med <= LIQ_TIGHT_SPR and oi >= LIQ_TIGHT_OI:
        grade = "tight"
    elif med <= LIQ_OK_SPR:
        grade = "ok"
    else:
        grade = "wide"
    if grade in ("tight", "ok") and oi < LIQ_MIN_OI:
        grade = "wide"
    return {"grade": grade, "spread_pct": med, "oi": oi, "volume": vol,
            "n_no_bid": no_bid, "n": len(region)}


def curve_read(points):
    """PURE: [(label, dte, atm_iv), …] → {points, tag} with a front-vs-back cheap-tenor tag,
    or None with <2 valid points. Sorted by dte."""
    pts = sorted([p for p in (points or []) if p[2]], key=lambda p: p[1])
    if len(pts) < 2:
        return None
    ratio = pts[0][2] / pts[-1][2] if pts[-1][2] else None
    tag = ("back cheaper — longer tenor is the better vol buy" if ratio and ratio > 1.03
           else "front cheaper" if ratio and ratio < 0.97 else "flat curve")
    return {"points": [{"label": l, "dte": d, "iv": float(iv)} for l, d, iv in pts], "tag": tag}


def _third_friday(year, month):
    """PURE: the standard monthly-expiration date for a month — its third Friday."""
    fridays = [d for d in range(1, 29)
               if datetime.date(year, month, d).weekday() == 4]
    return datetime.date(year, month, fridays[2])


def monthly_expiries(future):
    """PURE: the MONTHLY expiries out of `future` [(iso, dte), …], holiday-aware (S72).

    List-aware on purpose. `pc_oi.is_monthly_expiry` is date-only (Friday, day 15-21) and so
    cannot see a holiday shift: when the third Friday is a market holiday the monthly moves to
    the Thursday before it, and that date then reads as "not monthly". Probed live 2026-07-30 —
    SOFI/QQQ/AMD all list 2027-06-17 (Thu) and NOT 2027-06-18, because Juneteenth 2027 falls on
    a Saturday and is observed that Friday. Under the old rule the June-2027 LEAP was classified
    non-monthly and would have been dropped by a monthlies-only filter.

    Rule per (year, month) present in the list: the third Friday if it is listed, else the day
    before it if THAT is listed. Anything else (weeklies, month-end quarterlies like 26-12-31 or
    27-03-31) is not a monthly — which a bare "Thursday in the 15-21 window" test would get
    wrong on tickers that list Thursday weeklies (QQQ lists daily expiries)."""
    listed = {e for e, _ in future}
    keep = set()
    for e, _ in future:
        d = datetime.date.fromisoformat(e)
        tf = _third_friday(d.year, d.month)
        if tf.isoformat() in listed:
            keep.add(tf.isoformat())
        else:
            prev = (tf - datetime.timedelta(days=1)).isoformat()
            if prev in listed:
                keep.add(prev)
    return sorted([(e, d) for e, d in future if e in keep], key=lambda ed: ed[1])


def select_expiries(future, min_dte=EXPIRY_MIN_DTE, max_dte=EXPIRY_MAX_DTE, max_n=MAX_EXPIRIES):
    """PURE: every monthly expiry inside the DTE window, nearest-first, capped (S72).

    Replaces the S69 nearest-to-target rule. Quoting the whole window means the expiry picker
    offers what the chain actually lists, so no tenor is hidden and none has to be labeled
    "~1yr" (the label was the thing that could lie — the grid is ticker-specific)."""
    sel = [(e, d) for e, d in monthly_expiries(future) if min_dte <= d <= max_dte]
    return sorted(sel[:max_n], key=lambda ed: ed[1])


def nearest_to_targets(pairs, targets=TARGET_DTES):
    """PURE: the subset of [(key, dte), …] nearest each target DTE, deduped, sorted (S72).
    The CLI's curation — a terminal has no picker, so it shows one row per canonical tenor
    while the payload (and the web) carry every quoted monthly."""
    if not pairs:
        return []
    sel = []
    for t in targets:
        k, d = min(pairs, key=lambda kd: abs(kd[1] - t))
        if all(k != s[0] for s in sel):
            sel.append((k, d))
    return sorted(sel, key=lambda kd: kd[1])


def strike_ladder(rows, spot, max_n=LADDER_MAX, pct=LADDER_PCT, otm_delta=OTM_DELTA):
    """PURE: parsed chain rows → a bounded ladder of tradeable call candidates around spot (S69),
    nearest-to-spot first, each formatted by `_candidate` so mid/iv/delta/oi/spread semantics match
    the ATM/OTM blocks exactly. Every entry carries `kind` ('atm' / 'otm' for the ~0.375Δ pick /
    'other') and `moneyness` so a strike selector can label itself. Zero network — these rows were
    already fetched for the ATM pick."""
    calls = [r for r in rows if r["type"] == "call" and (r.get("bid") or 0) > 0]
    if not calls or not spot:
        return []
    atm, otm = pick_call_candidates(rows, spot, otm_delta=otm_delta)
    atm_k = atm["strike"] if atm else None
    otm_k = otm["strike"] if otm else None
    near = [r for r in calls if abs(r["strike"] - spot) / spot <= pct]
    near.sort(key=lambda r: abs(r["strike"] - spot))
    out = []
    for r in near[:max_n]:
        c = _candidate(r, spot)
        if not c:
            continue
        c["kind"] = ("atm" if r["strike"] == atm_k
                     else "otm" if r["strike"] == otm_k else "other")
        c["moneyness"] = r["strike"] / spot - 1.0
        out.append(c)
    # the ~0.375Δ pick can sit outside `pct` on a wide chain — never lose it, the CLI/default rows
    # and the pre-S69 `otm` block both reference that strike
    if otm_k is not None and all(c["strike"] != otm_k for c in out):
        c = _candidate(otm, spot)
        if c:
            c["kind"] = "otm"
            c["moneyness"] = otm_k / spot - 1.0
            out.append(c)
    return sorted(out, key=lambda c: c["strike"])


def _fetch(ticker, earnings_date=None, ex_div_date=None):
    spot = get_current_price(ticker)
    today = datetime.date.today()
    exps = get_expirations(ticker)
    if isinstance(exps, str):
        exps = [exps]
    future = [(e, (datetime.date.fromisoformat(e) - today).days) for e in exps]
    future = [(e, d) for e, d in future if d > 0]
    if not future or not spot:
        return None

    earn = earn_days = None
    if earnings_date:
        try:
            earn = datetime.date.fromisoformat(earnings_date)
            earn_days = (earn - today).days
        except Exception:
            earn = None
    exd = None
    if ex_div_date:
        try:
            exd = datetime.date.fromisoformat(ex_div_date)
        except Exception:
            exd = None

    blocks, curve_pts, grade = [], [], None
    for e, d in select_expiries(future):
        rows = _parse(get_chain(ticker, e))
        atm, otm = pick_call_candidates(rows, spot)
        cand = _candidate(atm, spot)
        if cand is None:
            continue
        blk = {"expiry": e, "dte": d,
               # every quoted expiry IS a monthly now (select_expiries filters), but the flag
               # stays for consumers and old caches — holiday-aware, unlike is_monthly_expiry
               "monthly": True,
               "atm": cand, "otm": _candidate(otm, spot),
               # S69: the full bounded ladder off the SAME parsed rows (no extra call) — the
               # level-projection strike selector prices any of these
               "ladder": strike_ladder(rows, spot), "notes": []}
        ed = datetime.date.fromisoformat(e)
        if earn is not None and earn_days is not None and 0 <= earn_days <= 45:
            blk["notes"].append("expires BEFORE earnings — no event exposure" if ed <= earn else
                                f"{(ed - earn).days}d after earnings — carries event premium (crush risk)")
        if exd is not None and today < exd <= ed:
            blk["notes"].append(f"ex-div {exd.isoformat()} before expiry — the call doesn't earn it; "
                                f"deep-ITM early-exercise risk into ex-div")
        blocks.append(blk)
        if cand.get("iv"):
            curve_pts.append((e[2:], d, float(cand["iv"])))   # YY-MM-DD — LEAPS need the year (S47)
        if grade is None:
            grade = liquidity_grade(rows, spot)
    if not blocks:
        return None

    # The IV curve needs no separate fetch pass any more (S72): every monthly in the window is
    # already quoted above, so curve_pts is complete and richer than the old 7-point cap — and
    # strictly cheaper than fetching some expiries twice. Chain calls per --call run = exactly
    # len(select_expiries(...)).
    return {"spot": spot, "earn_days": earn_days, "quotes": blocks,
            "curve": curve_read(curve_pts), "liquidity": grade}


def _wrap(quote, as_of, stale, cached):
    out = dict(quote)
    out.update({"as_of": as_of, "as_of_str": _hhmm(as_of), "age_str": _cache_age(as_of),
                "stale": stale, "cached": cached})
    return out


def call_quote(ticker, earnings_date=None, ex_div_date=None, interactive=False,
               data_dir="data", force=False):
    """Long-call viability quote off the live Tradier chain (see module docstring). Cached per
    ticker session-stale; `force=True` (lens --live) requotes fresh. Returns the quote dict
    (+ as_of/as_of_str/age_str/stale/cached) or None. Best-effort: never raises."""
    if not TRADIER_TOKEN or TRADIER_TOKEN == "YOUR_TOKEN_HERE":
        return None
    cache = _load(ticker, data_dir)
    stale = cache is not None and cache_stale(cache)

    refresh = cache is None or force
    if not force and cache is not None and stale:
        if interactive:
            try:
                ans = input(f"  {ticker} call quote cached {_cache_age(cache['as_of'])}; a market "
                            f"close has passed — refresh from Tradier? [y/N]: ")
                refresh = ans.strip().lower().startswith("y")
            except EOFError:
                refresh = False
        else:
            refresh = False

    if not refresh and cache is not None:
        return _wrap(cache["quote"], cache["as_of"], stale, True)

    print(f"  call: fetching {ticker} chain from Tradier…")
    try:
        quote = _fetch(ticker, earnings_date, ex_div_date)
    except Exception:
        quote = None
    if quote is None or not quote.get("quotes"):
        if cache is not None:
            return _wrap(cache["quote"], cache["as_of"], stale, True)
        return None
    _save(ticker, data_dir, quote)
    return _wrap(quote, time.time(), False, False)


def cached_liquidity(ticker, data_dir="data"):
    """Liquidity grade from an existing --call cache, ZERO network — the default-on OPTIONS line.
    {grade, spread_pct, oi, volume, as_of_str, age_str, stale} or None when no cache exists."""
    c = _load(ticker, data_dir)
    liq = ((c or {}).get("quote") or {}).get("liquidity")
    if not liq:
        return None
    out = dict(liq)
    out.update({"as_of_str": _hhmm(c["as_of"]), "age_str": _cache_age(c["as_of"]),
                "stale": cache_stale(c)})
    return out


def cached_call_quote(ticker, data_dir="data"):
    """Full quote blob from an existing --call cache, ZERO network — the level-projection
    sibling of cached_liquidity (S68). _wrap-shaped (+ as_of_str/age_str/stale/cached=True)
    or None when no usable cache exists."""
    c = _load(ticker, data_dir)
    if not c or not ((c.get("quote") or {}).get("quotes")):
        return None
    return _wrap(c["quote"], c["as_of"], cache_stale(c), True)
