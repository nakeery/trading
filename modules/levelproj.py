"""
Level projections (S68) — "what would a move to this key level look like?" for lens.py.

The S65 PRICE LADDER shows every level's % distance; this module adds the deeper math for
the KEY levels only (the user's --level, nearest support/resistance, nearest confluence
zones): an estimated travel time at the recent pace, and a long-call P&L projection —
Black-Scholes repricing of the --call quoted contracts at the target (session cache read
zero-network when the flag is off), falling back to a synthetic ATM call modeled from the
harvested IV when no quote exists. Each contract shows TWO numbers: value if spot got there
immediately (T unchanged) and at the recent pace (T reduced by the travel estimate — the
theta cost of a slow grind made explicit).

S69: callquote now quotes four tenors (~45d/~90d/~6mo/~1yr — the last two are what this
project actually trades) and hands over a bounded STRIKE LADDER per expiry. Every candidate is
repriced here, server-side, so the web expiry/strike selectors just filter rows that already
exist and no Black-Scholes is duplicated in TypeScript. Renderers default to the ATM row per
tenor (`kind == "atm"`).

Honesty posture (S43): IV held constant (no skew shift, no vol path), the pace estimate is
a straight-line sigma-days heuristic (a random-walk first-passage read would be slower),
synthetic premiums carry no spread/fees — the caveat line prints unconditionally. Display
only: never a model feature, never a risk-scorecard factor, not advice (S28/S32).

All functions PURE (clock injectable) — offline-testable; zero network in this module.
"""

import math
from datetime import date

from modules.bs_invert import black_scholes_call

RISK_FREE = 0.04        # matches gex.RISK_FREE — level, not sensitivity-critical
# 30d = the harvested ATM IV tenor; 180d/365d (S69) = the tenors this project trades. The long legs
# used to be dead in practice: they were keyed to the `atm_iv_180d` gauge, which has never been
# populated in any indicators CSV, so the row silently vanished. They now source IV from the --call
# IV-by-expiry curve (already cached, zero network) and fall back to the HV-20 proxy.
SYNTH_DTES = (30, 180, 365)
MAX_ZONE_TARGETS = 2    # confluence zones beyond user/S/R, nearest by |dist|
MAX_TRAVEL_SESSIONS = 252
PACE_NOTE = ("sessions = |move| / avg daily move (HV-20/sqrt252) — straight-line; "
             "real paths are noisier and slower")


def travel_sessions(dist_pct, hv20):
    """PURE: estimated trading sessions to travel |dist_pct| at the recent pace.
    daily sigma = hv20/sqrt(252); linear sigma-days ('how many average daily moves') capped
    at MAX_TRAVEL_SESSIONS — deliberately the simple heuristic; a first-passage (d/sigma)^2
    read would be longer (the pace note says so). None when hv20 is missing/degenerate."""
    if dist_pct is None or hv20 is None or hv20 <= 0:
        return None
    daily = hv20 / math.sqrt(252)
    if daily <= 0:
        return None
    return min(abs(dist_pct) / daily, MAX_TRAVEL_SESSIONS)


def _legs(target, strike, iv, dte, r, travel_td):
    """Instant + paced BS values for one call at `target`. paced None when no pace."""
    t_inst = max(dte, 0) / 365.0
    instant = black_scholes_call(target, strike, r, t_inst, iv)
    paced = None
    if travel_td is not None:
        # trading-day hold → calendar-day decrement (the options_pnl conversion);
        # floor at 0 → black_scholes_call's degenerate guard returns intrinsic
        rem_cal = max(dte - travel_td * 365.0 / 252.0, 0.0)
        paced = {"value": black_scholes_call(target, strike, r, rem_cal / 365.0, iv),
                 "t_rem_days": rem_cal}
    return instant, paced


def reprice_contract(target, cand, dte, expiry=None, r=RISK_FREE, travel_td=None):
    """PURE: one callquote candidate dict repriced at `target` (IV held constant).
    Needs cand['iv'] and cand['mid'] — returns None otherwise (missing greeks happen).
    P&L is vs the mid, plus vs the ask when the candidate carries one (S40 at-ask honesty).
    A downside target prices honestly to a loss."""
    iv = (cand or {}).get("iv")
    mid = (cand or {}).get("mid")
    strike = (cand or {}).get("strike")
    if not iv or not mid or not strike or target is None or dte is None:
        return None
    ask = cand.get("ask")
    inst_v, paced = _legs(float(target), float(strike), float(iv), float(dte), r, travel_td)
    out = {"strike": float(strike), "dte": float(dte), "expiry": expiry, "iv": float(iv),
           "entry_mid": float(mid), "entry_ask": float(ask) if ask else None,
           "instant": {"value": inst_v, "pnl_mid_pct": inst_v / mid - 1.0,
                       "pnl_ask_pct": (inst_v / ask - 1.0) if ask else None},
           "paced": None}
    if paced is not None:
        out["paced"] = {"value": paced["value"], "pnl_mid_pct": paced["value"] / mid - 1.0,
                        "pnl_ask_pct": (paced["value"] / ask - 1.0) if ask else None,
                        "t_rem_days": paced["t_rem_days"]}
    return out


def synthetic_call(spot, target, iv, dte, r=RISK_FREE, travel_td=None,
                   iv_src="ATM IV (30d)"):
    """PURE: modeled ATM call — K = spot, premium = BS(spot, spot, r, dte/365, iv).
    Same instant/paced shapes as reprice_contract, P&L vs the modeled premium (no
    spread/fees — it is NOT a quote). None when the inputs can't price."""
    if not spot or not iv or iv <= 0 or spot <= 0 or target is None or not dte:
        return None
    premium = black_scholes_call(float(spot), float(spot), r, dte / 365.0, float(iv))
    if premium <= 0:
        return None
    inst_v, paced = _legs(float(target), float(spot), float(iv), float(dte), r, travel_td)
    out = {"strike": float(spot), "dte": float(dte), "iv": float(iv), "iv_src": iv_src,
           "premium": premium,
           "instant": {"value": inst_v, "pnl_mid_pct": inst_v / premium - 1.0,
                       "pnl_ask_pct": None},
           "paced": None}
    if paced is not None:
        out["paced"] = {"value": paced["value"],
                        "pnl_mid_pct": paced["value"] / premium - 1.0,
                        "pnl_ask_pct": None, "t_rem_days": paced["t_rem_days"]}
    return out


def curve_iv(callq, dte, max_gap=120):
    """PURE: nearest ATM IV to `dte` from the --call IV-by-expiry curve, or None (S69).
    The curve is already in the cached quote blob (reaches ~170-250 DTE for every tracked
    ticker) and costs nothing to read — it is the only working long-tenor IV source, since the
    harvested `atm_iv_180d` column has never been populated. `max_gap` keeps a 22d front point
    from standing in for a 365d tenor."""
    pts = ((callq or {}).get("curve") or {}).get("points") or []
    usable = [p for p in pts if p.get("iv") and p.get("dte") is not None]
    if not usable or dte is None:
        return None
    best = min(usable, key=lambda p: abs(p["dte"] - dte))
    if abs(best["dte"] - dte) > max_gap:
        return None
    return float(best["iv"]), int(best["dte"])


def _synth_legs(callq, iv30, iv180, hv20):
    """PURE: the (dte, iv, source-label) table for the modeled fallback rows (S69).
    Per tenor the IV preference is: harvested gauge → --call curve → HV-20 proxy. Each row is
    labeled with what it actually used, so a proxy is never mistaken for a real quote."""
    out = []
    for dte in SYNTH_DTES:
        gauge = iv30 if dte <= 45 else (iv180 if dte <= 240 else None)
        label = "ATM IV (30d)" if dte <= 45 else "ATM IV (180d)"
        if gauge:
            out.append((dte, gauge, label))
            continue
        cv = curve_iv(callq, dte)
        if cv:
            out.append((dte, cv[0], f"chain IV ~{cv[1]}d"))
        elif hv20:
            out.append((dte, hv20, "HV-20 proxy"))
    return out


def _pick_targets(ladder):
    """Key targets in priority order: your --level, nearest support, nearest resistance,
    then the nearest MAX_ZONE_TARGETS confluence-zone rows. Deduped within ±0.5% relative
    (the user's raw level vs its cluster's mid price differ slightly by construction)."""
    spot = ladder.get("spot") or 0
    picked = []

    def _dup(price):
        return any(spot and abs(price - t["price"]) / spot <= 0.005 for t in picked)

    ul = ladder.get("user_level")
    if ul and ul.get("price") is not None:
        picked.append({"price": float(ul["price"]), "dist_pct": ul.get("dist_pct"),
                       "kind": "your level",
                       "label": " · ".join(ul.get("confluence") or [])})
    for kind, key in (("support", "nearest_support"), ("resistance", "nearest_resistance")):
        row = ladder.get(key)
        if row and row.get("price") is not None and not _dup(row["price"]):
            picked.append({"price": float(row["price"]), "dist_pct": row.get("dist_pct"),
                           "kind": kind, "label": " · ".join(row.get("tags") or [])})
    zone_rows = [r for r in (ladder.get("levels") or [])
                 if r.get("zone") is not None and r.get("price") is not None
                 and not _dup(r["price"])]
    zone_rows.sort(key=lambda r: abs(r.get("dist_pct") or 0))
    for row in zone_rows[:MAX_ZONE_TARGETS]:
        picked.append({"price": float(row["price"]), "dist_pct": row.get("dist_pct"),
                       "kind": "confluence", "label": " · ".join(row.get("tags") or [])})
        # keep _dup() seeing the newly picked zone too (picked mutated in place)
    return picked


def project_targets(ladder, hv20=None, callq=None, iv30=None, iv180=None, r=RISK_FREE,
                    today=None):
    """PURE orchestrator: build_ladder output (+ optional --call quote dict, harvested IV
    gauges, HV-20) → the projections dict, or None when there is nothing to project.
    `today` injectable for tests (defaults to date.today() — used only to refresh the
    cached quote blocks' dte from their expiry strings, which were stamped on cache day)."""
    if not ladder:
        return None
    targets = _pick_targets(ladder)
    if not targets:
        return None
    spot = ladder.get("spot")
    today = today or date.today()

    # quoted contracts (--call this run, or its session cache): (cand, dte, expiry, kind).
    # A STALE cache's mids were struck at a different spot — you cannot enter at them, and
    # P&L vs a stale premium is misleading (a fresh-session drop makes every upside target
    # read as a loss). Honesty fix: re-model the ENTRY at the CURRENT spot (same strike/IV,
    # refreshed dte), drop the ask leg (the stale spread is equally dead), and flag the row.
    stale = bool((callq or {}).get("stale"))
    quoted = []
    for blk in (callq or {}).get("quotes") or []:
        dte, expiry = blk.get("dte"), blk.get("expiry")
        try:                              # cached dte is stamped on cache day — refresh
            dte = max((date.fromisoformat(expiry) - today).days, 0)
        except (TypeError, ValueError):
            pass
        # S69: price the whole per-expiry strike LADDER when present (the web strike selector
        # filters these client-side, so every offered strike must already be repriced here).
        # Pre-S69 blocks carry only atm/otm — fall back so an old cache still renders.
        cands = blk.get("ladder")
        if cands:
            cands = [dict(c) for c in cands if c.get("iv") and c.get("mid")]
        else:
            cands = [dict(blk[k], kind=k) for k in ("atm", "otm")
                     if (blk.get(k) or {}).get("iv") and (blk.get(k) or {}).get("mid")]
        for cand in cands:
            kind = cand.get("kind") or "other"
            modeled_entry = False
            if stale and spot:
                m = black_scholes_call(float(spot), float(cand["strike"]), r,
                                       max(dte or 0, 0) / 365.0, float(cand["iv"]))
                if m > 0:
                    cand = {k: v for k, v in cand.items() if k != "ask"}
                    cand["mid"] = m
                    modeled_entry = True
            quoted.append((cand, dte, expiry, kind, modeled_entry))

    for t in targets:
        tsess = travel_sessions(t.get("dist_pct"), hv20)
        t["travel_sessions"] = tsess
        t["contracts"], t["synthetic"] = [], []
        for cand, dte, expiry, kind, modeled_entry in quoted:
            c = reprice_contract(t["price"], cand, dte, expiry=expiry, r=r, travel_td=tsess)
            if c:
                c["kind"] = kind
                c["src"] = "quoted"
                c["entry_modeled"] = modeled_entry
                # carried through for the web strike selector's labels (S69)
                c["moneyness"] = cand.get("moneyness")
                c["delta"] = cand.get("delta")
                t["contracts"].append(c)
        if not t["contracts"]:            # synthetic fallback — modeled, not a quote
            for dte, iv, src in _synth_legs(callq, iv30, iv180, hv20):
                s = synthetic_call(spot, t["price"], iv, dte, r=r, travel_td=tsess, iv_src=src)
                if s:
                    s["src"] = "modeled"
                    t["synthetic"].append(s)

    qm = None
    if quoted and callq:
        qm = {"as_of_str": callq.get("as_of_str"), "age_str": callq.get("age_str"),
              "stale": bool(callq.get("stale"))}
    return {"targets": targets, "quote_meta": qm,
            "params": {"hv20": hv20, "r": r}, "pace_note": PACE_NOTE}
