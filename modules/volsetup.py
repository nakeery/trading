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


def gauge_val(ctx, name):
    """Pull a gauge value by name out of a gather_context() result. None if absent."""
    if not ctx:
        return None
    for g in ctx.get("gauges", []):
        if g.get("name") == name:
            return g.get("value")
    return None


def vol_setup(reads, squeeze, ctx, earnings=None, em=None, macro_days=None):
    """Two-sided long-vol vs short-vol scorecard. `squeeze` = {tf: read_squeeze(...)}. Returns
    {long_vol: [factor strings], short_vol: [...], net, hint}. Descriptive context, not advice."""
    long_v, short_v = [], []

    iv_rank = gauge_val(ctx, "IV Rank (1y)")
    iv_hv   = gauge_val(ctx, "IV/HV ratio")
    term    = gauge_val(ctx, "Term structure")
    skew    = gauge_val(ctx, "25Δ skew (P-C)")

    # IV cheap vs rich
    if iv_rank is not None:
        if iv_rank <= 0.30:
            long_v.append(f"IV rank low ({iv_rank:.2f}) — vol compressed, expansion-prone")
        elif iv_rank >= 0.70:
            short_v.append(f"IV rank high ({iv_rank:.2f}) — vol elevated, contraction-prone")
    if iv_hv is not None:
        if iv_hv <= 1.05:
            long_v.append(f"IV/HV {iv_hv:.2f} — implied ≈/< realized (move cheaply priced)")
        elif iv_hv >= 1.40:
            short_v.append(f"IV/HV {iv_hv:.2f} — implied ≫ realized (premium rich)")

    # compression (squeeze)
    sq_on = [tf for tf, s in (squeeze or {}).items() if s.get("ok") and s.get("squeeze_on")]
    if sq_on:
        long_v.append(f"squeeze ON ({', '.join(sq_on)}) — compressed range, expansion-prone")
    else:
        d = (squeeze or {}).get("1D", {})
        if d.get("ok") and d.get("bb_width_pctile") is not None and d["bb_width_pctile"] <= 0.20:
            long_v.append(f"1D Bollinger width {d['bb_width_pctile']:.0%}ile — coiled")

    # term structure
    if term is not None:
        if term < 0.98:
            long_v.append(f"term contango ({term:.2f}) — front vol relatively cheap")
        elif term > 1.05:
            short_v.append(f"term backwardation ({term:.2f}) — front vol bid (stress/event priced)")

    # skew
    if skew is not None and skew >= 0.05:
        short_v.append(f"heavy put skew ({skew:+.3f}) — downside premium rich")

    # catalysts
    if earnings and earnings.get("days") is not None and 0 <= earnings["days"] <= 45:
        hm = f", typ. ±{earnings['hist_move']:.1%}" if earnings.get("hist_move") else ""
        long_v.append(f"earnings in {earnings['days']}d ({earnings['date']}{hm}) — known vol catalyst")
    if macro_days is not None and 0 <= macro_days <= 10:
        long_v.append(f"macro event in {macro_days}d — event vol ahead")

    # implied vs realized move
    if em and em.get("hv_pct"):
        if em["pct"] < em["hv_pct"] * 0.95:
            long_v.append(f"implied move {em['pct']:.1%} < realized {em['hv_pct']:.1%} — move cheap")
        elif em["pct"] > em["hv_pct"] * 1.20:
            short_v.append(f"implied move {em['pct']:.1%} > realized {em['hv_pct']:.1%} — move rich")

    net, hint = _synthesize(long_v, short_v, earnings)
    return {"long_vol": long_v, "short_vol": short_v, "net": net, "hint": hint}


def _synthesize(long_v, short_v, earnings):
    nl, ns = len(long_v), len(short_v)
    catalyst = bool(earnings and earnings.get("days") is not None and 0 <= earnings["days"] <= 45)
    if nl >= ns + 2:
        net = (f"conditions favor BUYING vol (long straddle/strangle): "
               f"{nl} long-vol vs {ns} short-vol factors")
        hint = ("→ long straddle/strangle into the catalyst — size for the IV crush after the event"
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
