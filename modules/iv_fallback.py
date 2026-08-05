"""
Tradier fallback IV harvest (S74) — the same chain-summary dict massive.get_chain_summary
produces, computed off the live Tradier chain (greeks ride every chain call: smv_vol/delta).

Fires ONLY when the Massive snapshot harvest fails (the motivating case: Massive's
/v3/snapshot/options endpoint started returning 403 NOT_AUTHORIZED on 2026-07-06/07 after a
plan change, killing every ticker's daily IV stamp silently). indicators.py stamps the result
into the SAME IV columns with `iv_source="tradier"` so the mixed vendor basis stays visible —
Tradier's smoothed model vol (smv_vol) is not identical to Massive's quote-mid IV, but a
labeled continuous series beats a dead one.

Placement note: not in tradier.py (thin vendor I/O client — analysis math stays out) and not
in massive.py (one vendor per module). Tenor constants are IMPORTED from massive so the two
vendors keep identical definitions. Pure summary math (`summarize_rows`) is offline-testable.
"""

import datetime

from modules.tradier import TRADIER_TOKEN, get_chain, get_expirations
from modules.massive import (FRONT_MONTH_MIN_DTE, BACK_MONTH_MIN_DTE,
                             LONG_TENOR_TARGET, LONG_TENOR_MIN_DTE, LONG_TENOR_MAX_DTE)

BACK_WINDOW = 35     # back-month expiry search span past BACK_MONTH_MIN_DTE (mirrors massive)


def parse_chain_rows(df, expiry=None, today=None):
    """Tradier chain DataFrame → [{type, strike, expiry, dte, iv, delta, oi}] — the same field
    set massive.get_chain_summary parses, sourced from Tradier's flat columns + greeks dict
    (iv = smv_vol, mid_iv fallback). Bad rows dropped; never raises."""
    today = today or datetime.date.today()
    out = []
    if df is None or getattr(df, "empty", True):
        return out
    for _, r in df.iterrows():
        try:
            g = r.get("greeks") or {}
            if not isinstance(g, dict):
                g = {}
            exp_s = r.get("expiration_date") or expiry
            exp = datetime.date.fromisoformat(str(exp_s))
            out.append({"type": r.get("option_type"), "strike": float(r.get("strike")),
                        "expiry": exp, "dte": (exp - today).days,
                        "iv": g.get("smv_vol") or g.get("mid_iv"), "delta": g.get("delta"),
                        "oi": int(r.get("open_interest") or 0)})
        except Exception:
            continue
    return out


def summarize_rows(front, back, long_rows, spot, target_dte=30):
    """PURE: parsed front/back/long rows → the massive.get_chain_summary dict (same keys, same
    math): ATM by the dte×10+strike score, 25Δ skew = put IV − call IV near the ATM tenor,
    term = front ATM IV / back ATM IV, P/C OI over front+back, ~180d ATM off long_rows.
    None when no usable ATM call."""
    rows = list(front or []) + list(back or [])

    def usable(p):
        return p.get("iv") is not None and p.get("delta") is not None

    calls_all = [p for p in rows if p["type"] == "call"]
    puts_all = [p for p in rows if p["type"] == "put"]
    calls = [p for p in calls_all if usable(p)]
    puts = [p for p in puts_all if usable(p)]
    if not calls:
        return None

    atm = min(calls, key=lambda p: abs(p["dte"] - target_dte) * 10 + abs(p["strike"] - spot))

    skew = None
    near_calls = [p for p in calls if abs(p["dte"] - atm["dte"]) <= 7]
    near_puts = [p for p in puts if abs(p["dte"] - atm["dte"]) <= 7]
    if near_calls and near_puts:
        c25 = min(near_calls, key=lambda p: abs(p["delta"] - 0.25))
        p25 = min(near_puts, key=lambda p: abs(abs(p["delta"]) - 0.25))
        skew = float(p25["iv"]) - float(c25["iv"])

    def find_atm_at(min_dte):
        cands = [p for p in calls if p["dte"] >= min_dte]
        if not cands:
            return None
        return min(cands, key=lambda p: (abs(p["dte"] - min_dte), abs(p["strike"] - spot)))

    front_atm = find_atm_at(FRONT_MONTH_MIN_DTE)
    back_atm = find_atm_at(BACK_MONTH_MIN_DTE)
    term = (float(front_atm["iv"]) / float(back_atm["iv"])
            if (front_atm and back_atm and back_atm["iv"]) else None)

    call_oi = sum(p["oi"] for p in calls_all)
    put_oi = sum(p["oi"] for p in puts_all)
    pc_oi = (put_oi / call_oi) if call_oi > 0 else None

    long_atm = None
    long_calls = [p for p in (long_rows or []) if p["type"] == "call" and p.get("iv") is not None]
    if long_calls:
        long_atm = min(long_calls, key=lambda p: abs(p["dte"] - LONG_TENOR_TARGET) * 10
                       + abs(p["strike"] - spot))

    return {
        "atm_iv_30d":        float(atm["iv"]),
        "atm_strike":        atm["strike"],
        "atm_expiry":        atm["expiry"].isoformat(),
        "atm_dte":           atm["dte"],
        "iv_skew_25d":       skew,
        "term_structure":    term,
        "put_call_oi_ratio": pc_oi,
        "atm_iv_180d":       float(long_atm["iv"]) if long_atm else None,
        "atm_dte_180d":      long_atm["dte"] if long_atm else None,
    }


def _nearest_expiry(cands, target_dte):
    return min(cands, key=lambda c: abs(c[1] - target_dte)) if cands else None


def get_chain_summary_tradier(ticker, spot, target_dte=30):
    """Tradier-sourced stand-in for massive.get_chain_summary: 1 expirations call + ≤3 chain
    calls — the nearest-to-~30d expiry (ATM IV + 25Δ skew + P/C OI), the nearest back-month
    (55-90d, term structure), and the nearest LEAPS tenor in [150, 240] when one is listed
    (atm_iv_180d — skipped silently otherwise). Returns the summary dict or None (no token /
    no chain). Best-effort: never raises."""
    if not TRADIER_TOKEN or TRADIER_TOKEN == "YOUR_TOKEN_HERE" or not spot:
        return None
    try:
        today = datetime.date.today()
        cands = []
        for e in get_expirations(ticker) or []:
            try:
                d = (datetime.date.fromisoformat(e) - today).days
            except (TypeError, ValueError):
                continue
            if d > 0:
                cands.append((e, d))
        if not cands:
            return None

        front_pick = _nearest_expiry([c for c in cands
                                      if abs(c[1] - target_dte) <= 21] or cands, target_dte)
        back_pick = _nearest_expiry(
            [c for c in cands if BACK_MONTH_MIN_DTE <= c[1] <= BACK_MONTH_MIN_DTE + BACK_WINDOW],
            BACK_MONTH_MIN_DTE)
        long_pick = _nearest_expiry(
            [c for c in cands if LONG_TENOR_MIN_DTE <= c[1] <= LONG_TENOR_MAX_DTE],
            LONG_TENOR_TARGET)

        front = parse_chain_rows(get_chain(ticker, front_pick[0]), expiry=front_pick[0],
                                 today=today) if front_pick else []
        back = (parse_chain_rows(get_chain(ticker, back_pick[0]), expiry=back_pick[0],
                                 today=today)
                if back_pick and back_pick != front_pick else [])
        long_rows = (parse_chain_rows(get_chain(ticker, long_pick[0]), expiry=long_pick[0],
                                      today=today)
                     if long_pick else [])
        return summarize_rows(front, back, long_rows, spot, target_dte=target_dte)
    except Exception as e:
        print(f"  Tradier IV fallback failed: {e}")
        return None
