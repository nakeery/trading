"""
Live straddle / strangle pricer (S37, Stage B) — backs lens.py `--vol`.

Off the live Tradier chain: the ATM straddle and an auto ±expected-move strangle (each wing snapped
to the most-liquid nearby OTM strike), with cost, breakevens, and the % move needed to profit —
concrete trade numbers under the VOLATILITY SETUP scorecard. When an earnings date is near, anchors
to POST-earnings expiries (the nearest one + the nearest post-earnings monthly when they differ) for
a pre-earnings long-vol setup; otherwise the near ~target_dte expiry. Descriptive context, not advice.

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

SCOPEKEY = "straddle5"       # bumped when the cached payload shape changes (earnings-anchored blocks)
EM_MULT = 1.0                # "auto" strangle wings at ±(EM_MULT × expected move); exp move = straddle/spot
SNAP_K = 3                   # a wing snaps to the most-liquid of the K nearest OTM strikes to its target
EARN_WINDOW = 45             # anchor to a post-earnings expiry only when earnings is ≤ this many days out


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


def _liquid_strike(opts, target, spot, side):
    """Snap a strangle wing to the most-LIQUID of the nearest SNAP_K OTM strikes to `target`, rather
    than the merely-closest one. `side` is 'call' (keep strikes > spot) or 'put' (keep strikes <
    spot) so the result stays a genuine OTM strangle. Prefer tradeable strikes (bid>0 and ask>0),
    then rank by open interest (desc), breaking ties on the tighter bid-ask. Falls back to the plain
    nearest strike when there are no OTM strikes on that side."""
    otm = [o for o in opts if (o["strike"] > spot if side == "call" else o["strike"] < spot)]
    if not otm:
        return _nearest_strike(opts, target)
    candidates = sorted(otm, key=lambda o: abs(o["strike"] - target))[:SNAP_K]
    tradeable = [o for o in candidates if o["bid"] > 0 and o["ask"] > 0]
    pool = tradeable or candidates
    return max(pool, key=lambda o: (o["oi"], -(o["ask"] - o["bid"])))


def _select_expiries(future, target_dte, earn, earn_days):
    """Choose which expiries to quote. PURE (no network) so it's unit-testable.
    `future` = [(expiry_str, dte), …] with dte>0; `earn` = earnings date or None; `earn_days` = int|None.
    When earnings is known and near (0..EARN_WINDOW), anchor to POST-earnings expiries for a
    pre-earnings long-vol setup: the nearest one (steepest IV ramp / most concentrated event premium)
    plus the nearest post-earnings MONTHLY when it differs (more liquid). Otherwise fall back to the
    near MONTHLY ~target_dte. Returns (selected, notes) where selected is
    [(expiry_str, dte, expiry_kind, days_after_earn), …]."""
    notes = []
    if earn is not None and earn_days is not None and 0 <= earn_days <= EARN_WINDOW:
        post = [(e, d) for e, d in future if datetime.date.fromisoformat(e) > earn]
        if post:
            nearest = min(post, key=lambda ed: ed[1])
            n_monthly = is_monthly_expiry(datetime.date.fromisoformat(nearest[0]))
            selected = [(nearest[0], nearest[1],
                         "post-earnings " + ("monthly" if n_monthly else "weekly"),
                         nearest[1] - earn_days)]
            monthlies = [(e, d) for e, d in post
                         if is_monthly_expiry(datetime.date.fromisoformat(e))]
            if monthlies:
                nm = min(monthlies, key=lambda ed: ed[1])
                if nm[0] != nearest[0]:
                    selected.append((nm[0], nm[1], "post-earnings monthly", nm[1] - earn_days))
            return selected, notes
        notes.append(f"no expiry after earnings — showing standard ~{target_dte}d expiry")
    elif earn is not None and earn_days is not None and earn_days > EARN_WINDOW:
        notes.append(f"earnings {earn_days}d out — beyond the vega-ramp window; "
                     f"standard ~{target_dte}d expiry")
    elif earn is None:
        notes.append(f"no earnings date — standard ~{target_dte}d expiry")

    # fallback: near MONTHLY (3rd Friday) for liquidity; else closest-to-target.
    monthlies = [(e, d) for e, d in future if is_monthly_expiry(datetime.date.fromisoformat(e))]
    pool = monthlies or future
    e, d = min(pool, key=lambda ed: abs(ed[1] - target_dte))
    return [(e, d, "monthly" if monthlies else "nearest", None)], notes


def _build_block(ticker, spot, expiry, dte, expiry_kind, days_after_earn=None):
    """Build the ATM straddle + snapped ±expected-move strangle for ONE expiry off the live chain.
    Returns the block dict, or None if the chain is empty/one-sided or the ATM straddle can't price."""
    rows = _parse(get_chain(ticker, expiry))
    calls = [x for x in rows if x["type"] == "call"]
    puts  = [x for x in rows if x["type"] == "put"]
    if not calls or not puts:
        return None

    atm_strike = min({x["strike"] for x in rows}, key=lambda s: abs(s - spot))
    atm_c = next((x for x in calls if x["strike"] == atm_strike), None)
    atm_p = next((x for x in puts if x["strike"] == atm_strike), None)
    straddle = _combo(atm_c, atm_p, spot)
    if straddle is None:
        return None

    # "auto" strangle: wings at ±(expected move) = ±(ATM straddle / spot), each SNAPPED to the
    # most-liquid nearby OTM strike (vol/DTE-normalized, no greeks). EM_MULT tunes the width.
    em_pct = (straddle["cost"] / spot) * EM_MULT
    cw = _liquid_strike(calls, spot * (1 + em_pct), spot, "call")
    pw = _liquid_strike(puts,  spot * (1 - em_pct), spot, "put")
    strangle = _combo(cw, pw, spot)
    if strangle:
        strangle["width"] = ((spot - pw["strike"]) + (cw["strike"] - spot)) / (2 * spot)
        strangle["target_width"] = em_pct

    return {"expiry": expiry, "dte": dte, "expiry_kind": expiry_kind,
            "days_after_earn": days_after_earn, "atm_strike": atm_strike,
            "straddle": straddle, "strangle": strangle}


def _fetch(ticker, target_dte, earnings_date=None):
    spot = get_current_price(ticker)
    today = datetime.date.today()
    exps = get_expirations(ticker)
    if isinstance(exps, str):
        exps = [exps]
    future = [(e, (datetime.date.fromisoformat(e) - today).days) for e in exps]
    future = [(e, d) for e, d in future if d > 0]
    if not future:
        return None

    earn, earn_days = None, None
    if earnings_date:
        try:
            earn = datetime.date.fromisoformat(earnings_date)
            earn_days = (earn - today).days
        except Exception:
            earn = None

    selected, notes = _select_expiries(future, target_dte, earn, earn_days)
    quotes = [b for b in (_build_block(ticker, spot, e, d, k, dae)
                          for e, d, k, dae in selected) if b]
    if not quotes:
        return None
    return {"spot": spot, "earnings_date": earnings_date, "earn_days": earn_days,
            "quotes": quotes, "notes": notes}


def _wrap(quote, as_of, stale, cached):
    out = dict(quote)
    out.update({"as_of": as_of, "as_of_str": _hhmm(as_of), "age_str": _cache_age(as_of),
                "stale": stale, "cached": cached})
    return out


def straddle_quote(ticker, target_dte=30, earnings_date=None, interactive=False, data_dir="data"):
    """ATM straddle + auto ±expected-move strangle off the live Tradier chain. When `earnings_date`
    (ISO 'YYYY-MM-DD') is within EARN_WINDOW days, anchors to POST-earnings expiries — the nearest
    one and the nearest post-earnings monthly when they differ — for a pre-earnings long-vol setup;
    otherwise the near ~target_dte expiry. Cached per ticker (session-stale, TTY-gated refresh) like
    pc-oi. Returns the quote dict (spot/earn_days/quotes[…]/notes + as_of/as_of_str/age_str/stale/
    cached) or None (no token / no data). Best-effort: never raises."""
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
        quote = _fetch(ticker, target_dte, earnings_date)
    except Exception:
        quote = None
    if quote is None or not quote.get("quotes"):
        if cache is not None:
            return _wrap(cache["quote"], cache["as_of"], stale, True)
        return None
    _save(ticker, data_dir, quote)
    return _wrap(quote, time.time(), False, False)
