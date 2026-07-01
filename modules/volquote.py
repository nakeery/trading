"""
Live straddle / strangle pricer (S37, Stage B) — backs lens.py `--vol`.

Off the live Tradier chain for the near (~target_dte) expiry: the ATM straddle and a ~25Δ strangle,
each with cost, breakevens, and the % move needed to profit — concrete trade numbers under the
VOLATILITY SETUP scorecard. Descriptive context, not advice.

Cached per ticker like pc-oi (session-stale: a new market close → re-fetch), reusing pc_oi's cache
helpers. NOTE option prices move intraday, so a cached quote is a SNAPSHOT 'as of HH:MM' — the TTY
refresh prompt (or a forced rerun) pulls a live one. Best-effort: never raises.
"""

import json
import os
import time
import datetime

from modules.tradier import TRADIER_TOKEN, get_current_price, get_expirations, get_chain
from modules.pc_oi import _cache_path, cache_stale, _cache_age, _hhmm, is_monthly_expiry

SCOPEKEY = "straddle4"       # bumped when the cached payload shape changes (auto ±exp-move strangle)
EM_MULT = 1.0                # "auto" strangle wings at ±(EM_MULT × expected move); exp move = straddle/spot


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


def _combo(call, put, spot):
    """A two-leg long-vol position (straddle if same strike, else strangle). Returns cost, breakevens
    and the move from spot needed to reach each breakeven."""
    if not call or not put:
        return None
    cm, pm = _mid(call), _mid(put)
    if cm is None or pm is None:
        return None
    cost = cm + pm
    lo = put["strike"] - cost                       # downside breakeven
    hi = call["strike"] + cost                      # upside breakeven
    leg = lambda o: {"strike": o["strike"], "bid": o["bid"], "ask": o["ask"], "oi": o.get("oi")}
    return {"call_strike": call["strike"], "put_strike": put["strike"], "cost": cost,
            "lo": lo, "hi": hi, "up_move": (hi - spot) / spot, "dn_move": (spot - lo) / spot,
            "legs": {"call": leg(call), "put": leg(put)}}


def _parse(chain):
    rows = []
    for _, r in chain.iterrows():
        try:
            rows.append({"type": r.get("option_type"), "strike": float(r.get("strike")),
                         "bid": float(r.get("bid") or 0), "ask": float(r.get("ask") or 0),
                         "oi": int(r.get("open_interest") or 0)})
        except Exception:
            continue
    return rows


def _nearest_strike(opts, target):
    return min(opts, key=lambda x: abs(x["strike"] - target)) if opts else None


def _fetch(ticker, target_dte):
    spot = get_current_price(ticker)
    today = datetime.date.today()
    exps = get_expirations(ticker)
    if isinstance(exps, str):
        exps = [exps]
    future = [(e, (datetime.date.fromisoformat(e) - today).days) for e in exps]
    future = [(e, d) for e, d in future if d > 0]
    if not future:
        return None
    # prefer the near MONTHLY expiry (3rd Friday) for liquidity; fall back to closest-to-target.
    monthlies = [(e, d) for e, d in future if is_monthly_expiry(datetime.date.fromisoformat(e))]
    pool = monthlies or future
    expiry, dte = min(pool, key=lambda ed: abs(ed[1] - target_dte))
    expiry_kind = "monthly" if monthlies else "nearest"

    rows = _parse(get_chain(ticker, expiry))
    calls = [x for x in rows if x["type"] == "call"]
    puts  = [x for x in rows if x["type"] == "put"]
    if not calls or not puts:
        return None

    atm_strike = min({x["strike"] for x in rows}, key=lambda s: abs(s - spot))
    atm_c = next((x for x in calls if x["strike"] == atm_strike), None)
    atm_p = next((x for x in puts if x["strike"] == atm_strike), None)
    straddle = _combo(atm_c, atm_p, spot)

    # "auto" strangle: wings at ±(expected move), where the expected move = ATM straddle price / spot
    # — vol- and DTE-normalized and self-contained (no greeks). EM_MULT tunes it (1.0 = at the exp move).
    strangle = None
    if straddle:
        em_pct = (straddle["cost"] / spot) * EM_MULT
        strangle = _combo(_nearest_strike(calls, spot * (1 + em_pct)),
                          _nearest_strike(puts,  spot * (1 - em_pct)), spot)
        if strangle:
            strangle["width"] = em_pct

    return {"expiry": expiry, "dte": dte, "expiry_kind": expiry_kind, "spot": spot,
            "atm_strike": atm_strike, "straddle": straddle, "strangle": strangle}


def _wrap(quote, as_of, stale, cached):
    out = dict(quote)
    out.update({"as_of": as_of, "as_of_str": _hhmm(as_of), "age_str": _cache_age(as_of),
                "stale": stale, "cached": cached})
    return out


def straddle_quote(ticker, target_dte=30, interactive=False, data_dir="data"):
    """ATM straddle + ~25Δ strangle for the near (~target_dte) expiry off the live Tradier chain.
    Cached per ticker (session-stale, TTY-gated refresh) like pc-oi. Returns the quote dict (with
    as_of/as_of_str/age_str/stale/cached) or None (no token / no data). Best-effort: never raises."""
    if not TRADIER_TOKEN or TRADIER_TOKEN == "YOUR_TOKEN_HERE":
        return None
    cache = _load(ticker, data_dir)
    stale = cache is not None and cache_stale(cache)

    refresh = cache is None
    if cache is not None and stale:
        if interactive:
            try:
                ans = input(f"  {ticker} straddle quote cached {_cache_age(cache['as_of'])}; a market "
                            f"close has passed — refresh from Tradier? [y/N]: ")
                refresh = ans.strip().lower().startswith("y")
            except EOFError:
                refresh = False
        else:
            refresh = False

    if not refresh and cache is not None:
        return _wrap(cache["quote"], cache["as_of"], stale, True)

    print(f"  straddle: fetching {ticker} chain from Tradier…")
    try:
        quote = _fetch(ticker, target_dte)
    except Exception:
        quote = None
    if quote is None or quote.get("straddle") is None:
        if cache is not None:
            return _wrap(cache["quote"], cache["as_of"], stale, True)
        return None
    _save(ticker, data_dir, quote)
    return _wrap(quote, time.time(), False, False)
