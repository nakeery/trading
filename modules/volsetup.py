"""
Volatility-setup context (S37) — backs lens.py `--vol`.

Descriptive ONLY: no prediction, no claimed edge. Characterizes whether current conditions favor
BUYING volatility (long straddle/strangle, long gamma/vega) vs SELLING premium, and makes the
implied-vs-realized move concrete. The long-vol edge is buying when IV is cheap + coiled ahead of a
catalyst, and profiting only if the realized move exceeds what you paid — so this surfaces exactly
those ingredients and lists every firing factor, mirroring structure.rally_drawdown_risk.
"""

import math


def expected_move(spot, iv, dte=30, hv=None):
    """1-σ expected move from annualized IV over `dte` calendar days: spot × iv × √(dte/365).
    Returns {pct, dollars, lo, hi, dte, hv_pct} where hv_pct is the same move implied by realized HV
    (for a cheap/rich read). None if inputs are missing/invalid."""
    if spot is None or iv is None or iv <= 0:
        return None
    frac = math.sqrt(max(dte, 1) / 365.0)
    pct = iv * frac
    return {"pct": pct, "dollars": spot * pct, "lo": spot * (1 - pct), "hi": spot * (1 + pct),
            "dte": dte, "hv_pct": (hv * frac if (hv and hv > 0) else None)}


SQUEEZE_TFS = ("1M", "1W", "1D")   # only daily+ squeezes speak to a multi-week vol position (S40)
IV_PCT_LOW  = 0.30                 # real-IV percentile bands for the cheap/rich factor
IV_PCT_HIGH = 0.70


def gauge_val(ctx, name):
    """Pull a gauge value by name out of a gather_context() result. None if absent."""
    if not ctx:
        return None
    for g in ctx.get("gauges", []):
        if g.get("name") == name:
            return g.get("value")
    return None


def gauge_pct(ctx, name):
    """Pull a gauge's trailing percentile (0-1) by name out of a gather_context() result.
    None if the gauge is absent or its percentile was omitted (thin history)."""
    if not ctx:
        return None
    for g in ctx.get("gauges", []):
        if g.get("name") == name:
            return g.get("pct")
    return None


def vol_setup(reads, squeeze, ctx, earnings=None, em=None, macro_days=None):
    """Two-sided long-vol vs short-vol scorecard. `squeeze` = {tf: read_squeeze(...)}. Returns
    {long_vol: [factor strings], short_vol: [...], notes: [...], net, hint}. Descriptive context,
    not advice. `em` is accepted for signature stability but no longer scored — it duplicates the
    IV/HV factor (see the S43 note below)."""
    long_v, short_v, notes = [], [], []

    iv_pct  = gauge_pct(ctx, "ATM IV (30d)")             # real harvested-IV percentile (S40)
    hv_rank = gauge_val(ctx, "IV Rank (HV-proxy)")       # HV-20 proxy fallback
    iv_hv   = gauge_val(ctx, "IV/HV ratio")
    term    = gauge_val(ctx, "Term structure")
    skew    = gauge_val(ctx, "25Δ skew (P-C)")

    # IV cheap vs rich — real ATM-IV percentile when harvested history exists (the price of what
    # you'd actually buy); HV-20 proxy only as a labeled fallback. Pre-catalyst these diverge: IV
    # ramps while the stock stays quiet, and the proxy misses it (the CRSP 97th-percentile-vs-"mid"
    # case).
    if iv_pct is not None:
        if iv_pct <= IV_PCT_LOW:
            long_v.append(f"ATM IV at {iv_pct * 100:.0f} percentile of its history — "
                          f"vol cheap, expansion-prone")
        elif iv_pct >= IV_PCT_HIGH:
            short_v.append(f"ATM IV at {iv_pct * 100:.0f} percentile of its history — "
                           f"vol elevated, contraction-prone")
    elif hv_rank is not None:
        if hv_rank <= IV_PCT_LOW:
            long_v.append(f"vol rank low ({hv_rank:.2f}, HV-proxy) — vol compressed, expansion-prone")
        elif hv_rank >= IV_PCT_HIGH:
            short_v.append(f"vol rank high ({hv_rank:.2f}, HV-proxy) — vol elevated, contraction-prone")
    if iv_hv is not None:
        if iv_hv <= 1.05:
            long_v.append(f"IV/HV {iv_hv:.2f} — implied ≈/< realized (move cheaply priced)")
        elif iv_hv >= 1.40:
            short_v.append(f"IV/HV {iv_hv:.2f} — implied ≫ realized (premium rich)")

    # compression (squeeze) — intraday (1h/4h) squeezes resolve in hours-to-days and say nothing
    # about a multi-week option's price, so only daily+ squeezes count as a factor (S40); the
    # lens compression line still lists every timeframe.
    sq_on = [tf for tf in SQUEEZE_TFS
             if (squeeze or {}).get(tf, {}).get("ok") and (squeeze or {}).get(tf, {}).get("squeeze_on")]
    if sq_on:
        long_v.append(f"squeeze ON ({', '.join(sq_on)}) — compressed range, expansion-prone")
    else:
        d = (squeeze or {}).get("1D", {})
        if d.get("ok") and d.get("bb_width_pctile") is not None and d["bb_width_pctile"] <= 0.20:
            long_v.append(f"1D Bollinger width {d['bb_width_pctile'] * 100:.0f} percentile — coiled")

    # term structure
    if term is not None:
        if term < 0.98:
            long_v.append(f"term contango ({term:.2f}) — front vol relatively cheap")
        elif term > 1.05:
            short_v.append(f"term backwardation ({term:.2f}) — front vol bid (stress/event priced)")

    # skew
    if skew is not None and skew >= 0.05:
        short_v.append(f"heavy put skew ({skew:+.3f}) — downside premium rich")

    # catalysts — an upcoming print is only a reason to BUY vol while it's still cheap; once IV
    # already ranks high the event premium is priced, so it becomes a note, not a factor (S40).
    if earnings and earnings.get("days") is not None and 0 <= earnings["days"] <= 45:
        hm = f", typ. ±{earnings['hist_move']:.1%}" if earnings.get("hist_move") else ""
        if iv_pct is not None and iv_pct >= IV_PCT_HIGH:
            notes.append(f"earnings in {earnings['days']}d ({earnings['date']}{hm}) but ATM IV already "
                         f"at the {iv_pct * 100:.0f} percentile — event premium likely priced; "
                         f"ramp mostly done")
        else:
            long_v.append(f"earnings in {earnings['days']}d ({earnings['date']}{hm}) — known vol catalyst")
    if macro_days is not None and 0 <= macro_days <= 10:
        long_v.append(f"macro event in {macro_days}d — event vol ahead")

    # NB: the implied-vs-realized MOVE is displayed by the lens but is NOT a factor — em.pct/em.hv_pct
    # reduces to the same atm_iv/HV_20 ratio as the IV/HV factor above (the √(dte/365) cancels), so
    # counting it double-counted one input, enough to flip the 2-factor verdict margin alone (S43).

    net, hint = _synthesize(long_v, short_v, earnings)
    return {"long_vol": long_v, "short_vol": short_v, "notes": notes, "net": net, "hint": hint}


def _synthesize(long_v, short_v, earnings):
    nl, ns = len(long_v), len(short_v)
    catalyst = bool(earnings and earnings.get("days") is not None and 0 <= earnings["days"] <= 45)
    if nl >= ns + 2:
        net = (f"conditions favor BUYING vol (long straddle/strangle): "
               f"{nl} long-vol vs {ns} short-vol factors")
        hint = ("→ long straddle/strangle into the catalyst — exit BEFORE the print; IV crush erases the ramp"
                if catalyst else
                "→ long straddle/strangle for a breakout; theta is the cost if it stays coiled")
    elif ns >= nl + 2:
        net = (f"conditions favor SELLING premium (credit spreads / iron condor): "
               f"{ns} short-vol vs {nl} long-vol factors")
        hint = "→ premium-selling regime; buying vol (straddles) is expensive here"
    else:
        net = f"no clear vol edge ({nl} long-vol vs {ns} short-vol factors)"
        hint = "→ wait for cheaper IV (lower IV-rank) or a catalyst before buying vol"
    return net, hint
