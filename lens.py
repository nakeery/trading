"""
Lens — multi-timeframe market-structure & risk context (S34)
============================================================
A wide-angle read that surrounds YOUR chart analysis so a narrow view doesn't miss something. It
characterizes CURRENT STATE across timeframes (1h/4h/1D/1W/1M) — trend, momentum, volume, volume
profile, options/vol context, macro — and a transparent two-sided rally/drawdown risk scorecard.

It makes NO return prediction and claims NO edge. You bring the entry edge (levels, structure); this
makes sure you're not missing the bigger picture (e.g. oversold on the daily but overbought on the
weekly).

Usage:
    python -X utf8 lens.py                         # prompts for ticker
    python -X utf8 lens.py --thesis bullish --level 150
    python -X utf8 lens.py --no-intraday           # skip 1h/4h (offline / fast)
Piped (Windows):
    cmd /c "(echo QQQ) | python -X utf8 lens.py"
"""

import argparse
import os
import sys

import pandas as pd

from modules.timeframes import build_timeframes
from modules.structure import (
    read_timeframe, read_volume, detect_divergence,
    multi_timeframe_summary, rally_drawdown_risk,
)
from modules.volume_profile import volume_profile

try:
    from modules.sentiment import gather_context
except Exception:
    gather_context = None
try:
    from modules.econ_calendar import next_event_per_series, ALL_SERIES
except Exception:
    next_event_per_series, ALL_SERIES = None, []

_ARROW = {"up": "↑ up", "down": "↓ dn", "mixed": "~ mix"}
_OB = {"overbought": "OB", "oversold": "OS", "neutral": "neut"}


def _ob(state):
    return _OB.get(state, state)


def analyze(ticker, include_intraday=True, data_dir="data"):
    frames, notes = build_timeframes(ticker, data_dir=data_dir, include_intraday=include_intraday)
    reads, divs = {}, {}
    for tf, df in frames.items():
        r = read_timeframe(df)
        if not r.get("ok"):
            continue
        r["_vol"] = read_volume(df)
        reads[tf] = r
        k, why = detect_divergence(df)
        if k:
            divs[tf] = (k, why)
    summary = multi_timeframe_summary(reads)
    prof_src = frames.get("1h", frames.get("1D"))
    # ~6mo on the intraday path (≈126 sessions × ~7 1h-bars) so the shelves reflect near-term
    # structure, not year-old levels; daily fallback = 252 sessions ≈ 1y.
    lookback = 880 if "1h" in frames else 252
    profile = volume_profile(prof_src, lookback=lookback) if prof_src is not None else None
    return frames, reads, divs, summary, profile, notes


def _fmt_vol(v):
    """RVOL (latest-bar volume vs its 20-bar avg) + a directional tag for the price-vs-volume-trend
    relationship over the last ~10 bars (up-confirmed / up-WEAK / dn-distrib / dn-exhaust). The two
    are independent: RVOL is a single-bar level; the tag is a multi-bar trend relationship."""
    if not v or not v.get("ok"):
        return "—"
    rvol = f"{v['rvol']:.1f}x" if v.get("rvol") else "?"
    return f"{rvol} {v.get('tag', '')}"


def print_report(ticker, reads, divs, summary, profile, notes, last_close=None, as_of=None,
                 ctx=None, backdrop=None, thesis=None, level=None):
    w = 78
    print(f"\n{'═'*w}")
    hdr = f"  LENS — {ticker}"
    if last_close is not None:
        hdr += f"   ${last_close:,.2f}"
    if as_of:
        hdr += f"  (close {as_of})"
    print(f"{hdr}   ·   state characterization, NOT a prediction")
    print(f"{'═'*w}")

    # 1. MARKET BACKDROP
    if backdrop:
        print(f"  MARKET BACKDROP — {backdrop}")

    # 2. MULTI-TIMEFRAME TABLE.  RVOL = latest bar vs its 20-bar avg.  ΔPrc%/ΔVol% = price move vs
    # avg-volume trend over the last ~10 bars (these drive VolTrend: up-confirmed/up-WEAK/dn-distrib/
    # dn-exhaust). Trend = price-vs-MA structural trend (a different read from VolTrend).
    print(f"\n  MULTI-TIMEFRAME  (longest → shortest)")
    print(f"  {'TF':<4}{'Trend':<7}{'RSI':<8}{'Stoch':<6}{'MACD':<8}"
          f"{'RVOL':<6}{'ΔPrc%':>7}{'ΔVol%':>8}   {'VolTrend':<13}")
    for tf in reads:
        r = reads[tf]
        v = r.get("_vol") or {}
        rsi = f"{r['rsi']:.0f} {_ob(r['rsi_state'])}" if r.get("rsi") is not None else "—"
        rvol = f"{v['rvol']:.1f}x" if v.get("rvol") else "—"
        dp = f"{v['price_chg_10']:+.1%}" if v.get("price_chg_10") is not None else "—"
        dv = f"{v['vol_trend_10']:+.1%}" if v.get("vol_trend_10") is not None else "—"
        vt = v.get("tag", "—") if v.get("ok") else "—"
        print(f"  {tf:<4}{_ARROW.get(r['trend'], '?'):<7}{rsi:<8}{_ob(r['stoch_state']):<6}"
              f"{r['macd_state']:<8}{rvol:<6}{dp:>7}{dv:>8}   {vt:<13}")
    print(f"  → {summary['synthesis']}")
    if summary.get("rsi_conflict"):
        print(f"  ⚠ {summary['rsi_conflict']}")

    # 3. DIVERGENCES
    if divs:
        print(f"\n  DIVERGENCES")
        for tf, (kind, why) in divs.items():
            print(f"    {tf}: {kind} — {why}")

    # 4. VOLUME PROFILE — full set of volume shelves (HVN = S/R) and gaps (LVN = fast-move zones).
    if profile:
        loc = {"in_value": "inside value", "above_value": "ABOVE value (extended)",
               "below_value": "BELOW value (discount)"}[profile["price_location"]]
        price, poc = profile["price"], profile["poc"]

        def _levels(vals):
            if not vals:
                return "none"
            return "  ".join(f"{x:.2f}{'(POC)' if abs(x - poc) < 1e-6 else ''}" for x in vals)

        hvns = profile.get("hvns", [])
        above = sorted([h for h in hvns if h > price])              # nearest resistance first (lowest above)
        below = sorted([h for h in hvns if h <= price], reverse=True)  # nearest support first (highest below)
        lvns = sorted(profile.get("lvns", []))

        print(f"\n  VOLUME PROFILE  ({profile['n_bars']} bars)   HVN = volume S/R shelves · LVN = fast-move gaps")
        print(f"    POC (fair value): {poc:.2f}   "
              f"Value area: {profile['va_low']:.2f} – {profile['va_high']:.2f}   (price {loc})")
        print(f"    HVN shelves  above price: {_levels(above)}")
        print(f"                 below price: {_levels(below)}")
        print(f"    LVN gaps:    {_levels(lvns)}")

    # 5. RALLY vs DRAWDOWN RISK
    risk = rally_drawdown_risk(reads, profile=profile, ctx=ctx, divergences=divs)
    print(f"\n  RALLY vs DRAWDOWN RISK  (current conditions, not a forecast)")
    print(f"    NET: {risk['net']}")
    if risk["drawdown"]:
        print(f"    drawdown-risk factors:")
        for f in risk["drawdown"]:
            print(f"      • {f}")
    if risk["rally"]:
        print(f"    rally-favorable factors:")
        for f in risk["rally"]:
            print(f"      • {f}")

    # 6. OPTIONS & VOL CONTEXT
    if ctx and ctx.get("gauges"):
        print(f"\n  OPTIONS & VOL CONTEXT  (regime: {ctx['regime']})")
        for g in ctx["gauges"]:
            if g["group"] in ("OPTIONS", "VOL", "MARKET"):
                val = g["fmt"].format(g["value"])
                pct = f"  [{int(round(g['pct']*100))}%ile]" if g.get("pct") is not None else ""
                lab = f"  {g['label']}" if g.get("label") else ""
                print(f"    {g['name']:<20}{val:>9}{lab}{pct}")
        print(f"    NET: {ctx['net']}")

    # 7. MACRO
    if next_event_per_series:
        try:
            ev = next_event_per_series(data_dir="data")
            soon = [(name, d, days) for name, (d, days) in ev.items()
                    if d is not None and days is not None and days <= 10]
            if soon:
                print(f"\n  MACRO (next 10d): " +
                      "  ".join(f"{n} {days}d" for n, d, days in sorted(soon, key=lambda x: x[2])))
        except Exception:
            pass

    # 8. THESIS CHECK
    if thesis:
        print(f"\n  THESIS CHECK — you are {thesis.upper()}" + (f" (level {level})" if level else ""))
        confirm = risk["rally"] if thesis == "bullish" else risk["drawdown"]
        contra  = risk["drawdown"] if thesis == "bullish" else risk["rally"]
        print(f"    CONFIRMATIONS ({len(confirm)}):")
        for f in confirm or ["— none"]:
            print(f"      ✓ {f}")
        print(f"    CONTRADICTIONS ({len(contra)}):")
        for f in contra or ["— none"]:
            print(f"      ✗ {f}")
        blind = []
        if summary.get("conflict"):
            blind.append(summary["conflict"])
        for tf in reads:
            v = reads[tf].get("_vol")
            if v and v.get("unconfirmed"):
                blind.append(f"{tf} move is on falling volume (unconfirmed)")
        if blind:
            print(f"    BLIND SPOTS:")
            for b in blind:
                print(f"      ⚠ {b}")

    for n in notes:
        print(f"\n  note: {n}")
    print(f"{'═'*w}\n")


def market_backdrop(data_dir="data"):
    """SPY D/W/M trend + (via gather_context) VIX regime — the macro tide."""
    try:
        frames, _ = build_timeframes("SPY", data_dir=data_dir, include_intraday=False)
        parts = []
        for tf in ("1M", "1W", "1D"):
            if tf in frames:
                r = read_timeframe(frames[tf])
                if r.get("ok"):
                    parts.append(f"{tf} {r['trend']}")
        return "SPY: " + ", ".join(parts)
    except Exception:
        return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Multi-timeframe market-structure & risk lens.")
    ap.add_argument("--ticker", nargs="+", help="One or more tickers (skips the prompt; e.g. --ticker QQQ JPM F).")
    ap.add_argument("--thesis", choices=["bullish", "bearish"], help="Your bias → confirm/contradict overlay.")
    ap.add_argument("--level", type=float, help="A key level you're watching (annotates the thesis check).")
    ap.add_argument("--no-intraday", action="store_true", help="Skip 1h/4h (offline / fast).")
    ap.add_argument("--no-vix", action="store_true", help="Skip the options/vol + VIX context block.")
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    if args.ticker:
        tickers = [t.upper() for t in args.ticker]
    else:
        try:
            t = input("  Ticker [XYZ]: ").strip().upper()
        except KeyboardInterrupt:
            print(); sys.exit(0)
        if not t:
            print("  No ticker entered."); sys.exit(1)
        tickers = [t]

    backdrop_base = market_backdrop(args.data_dir)   # SPY tide — same for all tickers, computed once

    for ticker in tickers:
        try:
            frames, reads, divs, summary, profile, notes = analyze(
                ticker, include_intraday=not args.no_intraday, data_dir=args.data_dir)
        except FileNotFoundError as e:
            print(f"  Could not load data for {ticker}: {e}")
            continue

        ctx = None
        if not args.no_vix and gather_context is not None:
            try:
                ctx = gather_context(ticker, data_dir=args.data_dir, with_vix=True)
            except Exception as e:
                notes.append(f"options/vol context unavailable ({type(e).__name__}).")

        backdrop = backdrop_base
        if ctx and ctx.get("regime") and ctx["regime"] != "n/a" and backdrop:
            backdrop = f"{backdrop_base}  |  VIX regime: {ctx['regime']}"

        last_close = float(frames["1D"]["Close"].iloc[-1]) if "1D" in frames else None
        as_of = frames["1D"].index[-1].date().isoformat() if "1D" in frames else None

        print_report(ticker, reads, divs, summary, profile, notes, last_close=last_close, as_of=as_of,
                     ctx=ctx, backdrop=backdrop, thesis=args.thesis, level=args.level)
