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
_GREEN, _RED, _RESET = "\033[32m", "\033[31m", "\033[0m"


def _ramp(t):
    """t in [0,1] -> 24-bit ANSI fg colour: red (0) → amber (0.5) → green (1), softened for dark bg."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    stops = [(216, 60, 52), (214, 186, 46), (94, 196, 94)]   # red · amber · green
    s = 0 if t < 0.5 else 1
    u = (t - s * 0.5) / 0.5
    lo, hi = stops[s], stops[s + 1]
    rgb = tuple(int(lo[i] + (hi[i] - lo[i]) * u) for i in range(3))
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def _heat(val, lo, hi):
    """Per-column heatmap escape: red at the column min, green at the max, amber between. '' if flat."""
    if val is None or lo is None or hi is None or hi - lo < 1e-12:
        return ""
    return _ramp((val - lo) / (hi - lo))


def _rsi_tint(rsi):
    """Absolute RSI tint: oversold (<=30) green, overbought (>=70) red, amber across the neutral band."""
    if rsi is None:
        return ""
    t = (rsi - 30) / 40.0
    return _ramp(1 - (0.0 if t < 0 else 1.0 if t > 1 else t))


def _ob(state):
    return _OB.get(state, state)


def _enable_windows_ansi():
    """Flip ENABLE_VIRTUAL_TERMINAL_PROCESSING so Windows consoles interpret ANSI colour codes.
    No-op on non-Windows or on failure (Windows Terminal / VS Code already enable it)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)                     # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint()
        k.GetConsoleMode(h, ctypes.byref(mode))
        k.SetConsoleMode(h, mode.value | 0x0004)    # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def render_candle(o, h, l, c, prev_close, height=5, color=True):
    """A small text candlestick for the last bar, TradingView 'hollow' style:
      colour = green if close >= prev_close else red   (direction vs the PRIOR close)
      body   = hollow if close >= open else filled █    (close vs THIS bar's open)
    The two axes are independent. Returns a list of strings (ANSI-wrapped when `color`),
    High at top -> Low at bottom."""
    col = (_GREEN if c >= prev_close else _RED) if color else ""
    rst = _RESET if color else ""
    hollow = c >= o

    def _wrap(cell):
        return f"  {col}{cell}{rst}"

    rng = h - l
    if rng <= 1e-9:                                 # flat bar — nothing to draw
        return [_wrap("───")]

    body_hi, body_lo = max(o, c), min(o, c)
    up_span, lo_span = h - body_hi, body_lo - l

    # Segments top→bottom: upper wick, body (always present), lower wick. Each segment that EXISTS is
    # guaranteed ≥1 row, so a thin body or a small wick never vanishes into a neighbour's band (the
    # bug on long-wick bars like a hammer). Remaining rows are shared in proportion to price span.
    segs = []
    if up_span > 1e-9:
        segs.append(["up", up_span, 1])
    segs.append(["body", max(body_hi - body_lo, 0.0), 1])
    if lo_span > 1e-9:
        segs.append(["lo", lo_span, 1])

    extra = height - len(segs)
    if extra > 0:
        total = sum(s[1] for s in segs) or 1.0
        quotas = [s[1] / total * extra for s in segs]
        for s, q in zip(segs, quotas):
            s[2] += int(q)
        leftover = extra - sum(int(q) for q in quotas)
        for i in sorted(range(len(segs)), key=lambda j: quotas[j] - int(quotas[j]),
                        reverse=True)[:leftover]:
            segs[i][2] += 1

    rows = []
    for name, _span, n in segs:
        if name != "body":
            rows += [_wrap(" │ ")] * n                          # wick
        elif not hollow:
            rows += [_wrap("███")] * n                          # filled body
        elif n == 1:
            rows += [_wrap("├─┤")]                              # thin body, single row
        else:
            rows += [_wrap("┌─┐")] + [_wrap("│ │")] * (n - 2) + [_wrap("└─┘")]
    return rows


def braille_candle(o, h, l, c, prev_close, hcells=9, color=True):
    """Higher-resolution last-bar candle drawn with Unicode braille: each cell packs a 2x4 dot grid,
    giving ~2x horizontal and 4x vertical sub-cell resolution (as sharp as a text stream gets). Same
    convention as render_candle — colour green/red vs prior close, body hollow/filled vs open. Returns
    a list of (optionally ANSI-wrapped) strings, High at top -> Low at bottom."""
    col = (_GREEN if c >= prev_close else _RED) if color else ""
    rst = _RESET if color else ""
    if h <= l:                                              # flat bar — degenerate
        return [f"  {col}{'⠒' * 4}{rst}"]

    w, H = 8, hcells * 4                                    # dot canvas: 8 wide x (4*hcells) tall
    _DOT = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
            (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80}
    cells = {}

    def plot(px, py):
        if 0 <= px < w and 0 <= py < H:
            cells[(px // 2, py // 4)] = cells.get((px // 2, py // 4), 0) | _DOT[(px % 2, py % 4)]

    def ypx(price):
        return round((h - price) / (h - l) * (H - 1))      # high -> 0 (top), low -> H-1 (bottom)

    cl, cr = w // 2 - 1, w // 2                             # centered wick columns
    bt, bb = ypx(max(o, c)), ypx(min(o, c))                # body top / bottom in dot rows
    for y in range(ypx(h), bt):                            # upper wick (above body)
        plot(cl, y); plot(cr, y)
    for y in range(bb + 1, ypx(l) + 1):                    # lower wick (below body)
        plot(cl, y); plot(cr, y)
    hollow = c >= o
    for y in range(bt, bb + 1):                            # body
        if hollow and bt != bb and y not in (bt, bb):
            plot(0, y); plot(w - 1, y)                     # hollow: left/right edges only
        else:
            for x in range(w):                            # filled body / top+bottom caps: full width
                plot(x, y)

    ncx, ncy = (w + 1) // 2, (H + 3) // 4
    rows = []
    for cy in range(ncy):
        glyphs = ''.join(chr(0x2800 + cells.get((cx, cy), 0)) for cx in range(ncx))
        rows.append(f"  {col}{glyphs}{rst}")
    return rows


_DOTS = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
         (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80}


def render_candles(bars, style="box", color=True, height=7):
    """Render bars [(o, h, l, c), ...] side by side on a shared, padded price scale so adjacent days
    are directly comparable (gaps, relative size). Up day (close >= open) = green hollow body, down =
    red filled. Returns rows top->bottom (high -> low)."""
    bars = [b for b in bars if all(x is not None for x in b)]
    if not bars:
        return []
    hi, lo = max(b[1] for b in bars), min(b[2] for b in bars)
    pad = (hi - lo) * 0.10 or 0.5      # headroom so candles at the high/low aren't flush to the edge
    hi, lo = hi + pad, lo - pad
    return (_braille_candles(bars, hi, lo, height, color) if style == "braille"
            else _box_candles(bars, hi, lo, height, color))


def _box_candles(bars, hi, lo, height, color):
    """3 chars per candle on a fixed shared grid: hollow body (up) / █ body (down) + │ wicks."""
    def row(p):
        return int(round((hi - p) / (hi - lo) * (height - 1)))
    out = []
    for r in range(height):
        cells = []
        for (o, h, l, c) in bars:
            up, bt, bb = c >= o, row(max(o, c)), row(min(o, c))
            if bt <= r <= bb:
                cell = "███" if not up else "├─┤" if bt == bb else "┌─┐" if r == bt else "└─┘" if r == bb else "│ │"
            elif row(h) <= r <= row(l):
                cell = " │ "
            else:
                cell = "   "
            cells.append(f"{_GREEN if up else _RED}{cell}{_RESET}" if (color and cell.strip()) else cell)
        out.append("  " + " ".join(cells))
    return out


def _braille_candles(bars, hi, lo, hcells, color):
    """Braille panel: each candle = 4 dots (2 cells) wide — 2-wide centred wick + 4-wide filled body,
    1-cell gap — coloured per candle (green up / red down by close-vs-open)."""
    n, cw, gap = len(bars), 4, 2
    W, H = n * (cw + gap) - gap, hcells * 4
    grid = {}

    def plot(px, py):
        if 0 <= px < W and 0 <= py < H:
            grid[(px // 2, py // 4)] = grid.get((px // 2, py // 4), 0) | _DOTS[(px % 2, py % 4)]

    def ypx(p):
        return int(round((hi - p) / (hi - lo) * (H - 1)))

    for k, (o, h, l, c) in enumerate(bars):
        x0 = k * (cw + gap)
        for y in range(ypx(h), ypx(l) + 1):                  # wick: centre 2 dot-columns
            plot(x0 + 1, y); plot(x0 + 2, y)
        for y in range(ypx(max(o, c)), ypx(min(o, c)) + 1):  # body: all 4 columns
            for x in range(x0, x0 + cw):
                plot(x, y)

    blank, stride = chr(0x2800), (cw + gap) // 2
    out = []
    for cy in range((H + 3) // 4):
        line = ""
        for cx in range((W + 1) // 2):
            ch = chr(0x2800 + grid.get((cx, cy), 0))
            k, within = cx // stride, cx % stride
            if color and ch != blank and within < cw // 2 and k < n:
                _o, _h, _l, _c = bars[k]
                line += f"{_GREEN if _c >= _o else _RED}{ch}{_RESET}"
            else:
                line += ch
        out.append("  " + line)
    return out


def _rle_sixels(seq):
    """Run-length-encode a list of sixel byte values into a Sixel data string."""
    out, i, n = [], 0, len(seq)
    while i < n:
        j = i
        while j < n and seq[j] == seq[i]:
            j += 1
        run, ch = j - i, chr(seq[i])
        out.append(f"!{run}{ch}" if run >= 4 else ch * run)
        i = j
    return "".join(out)


def _to_sixel(grid, palette):
    """Encode a pixel grid (grid[y][x] = palette index; 0 = transparent) into a Sixel escape string.
    `palette` maps index -> (r, g, b) with components in 0-100 (Sixel's colour scale)."""
    H = len(grid)
    W = len(grid[0]) if H else 0
    out = ["\x1bP0;1;0q", f'"1;1;{W};{H}']            # DCS (transparent bg) + raster attrs
    for i in sorted(palette):
        r, g, b = palette[i]
        out.append(f"#{i};2;{r};{g};{b}")
    for band in range(0, H, 6):
        rows = grid[band:band + 6]
        present = sorted({c for rr in rows for c in rr if c})
        for ci, c in enumerate(present):
            seq = []
            for x in range(W):
                bits = 0
                for k, rr in enumerate(rows):
                    if rr[x] == c:
                        bits |= 1 << k
                seq.append(0x3F + bits)
            while seq and seq[-1] == 0x3F:           # trailing empties are implied
                seq.pop()
            out.append(f"#{c}" + _rle_sixels(seq))
            if ci != len(present) - 1:
                out.append("$")                      # CR: overlay next colour on this band
        if band + 6 < H:
            out.append("-")                          # next 6-row band
    out.append("\x1b\\")                             # ST
    return "".join(out)


def sixel_candles(bars, color=True, cell_w=14, gap=8, height_px=128):
    """Draw bars [(o, h, l, c), ...] as a true-pixel candlestick bitmap -> a Sixel escape string.
    Shared padded price scale; up day (close >= open) = green hollow, down = red filled."""
    bars = [b for b in bars if all(x is not None for x in b)]
    if not bars:
        return ""
    hi, lo = max(b[1] for b in bars), min(b[2] for b in bars)
    pad = (hi - lo) * 0.10 or 0.5                    # headroom so highs/lows aren't flush to the edge
    hi, lo = hi + pad, lo - pad
    n = len(bars)
    W, H = n * cell_w + (n - 1) * gap, max(24, height_px)
    grid = [[0] * W for _ in range(H)]

    def ypx(p):
        return int(round((hi - p) / (hi - lo) * (H - 1)))

    for k, (o, h, l, c) in enumerate(bars):
        ci = 1 if c >= o else 2                       # 1 = green (up), 2 = red (down)
        x0 = k * (cell_w + gap)
        wx = x0 + cell_w // 2 - 1                     # left column of the 2px wick
        yh, yl, yt, yb = ypx(h), ypx(l), ypx(max(o, c)), ypx(min(o, c))
        up = c >= o
        for y in range(yh, yt):                       # upper wick (above body)
            grid[y][wx] = ci; grid[y][wx + 1] = ci
        for y in range(yb + 1, yl + 1):               # lower wick (below body)
            grid[y][wx] = ci; grid[y][wx + 1] = ci
        for y in range(yt, yb + 1):                   # body: hollow (up) outline / filled (down)
            for x in range(x0, x0 + cell_w):
                if not up or y < yt + 2 or y > yb - 2 or x < x0 + 2 or x >= x0 + cell_w - 2:
                    grid[y][x] = ci
    palette = {1: (20, 75, 40), 2: (85, 25, 30)} if color else {1: (80, 80, 80), 2: (80, 80, 80)}
    return _to_sixel(grid, palette)


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


def print_report(ticker, reads, divs, summary, profile, notes, last_bar=None, as_of=None,
                 ctx=None, backdrop=None, thesis=None, level=None, color=True, candle_style="box",
                 panel_bars=None, candle_px=128):
    w = 78
    print(f"\n{'═'*w}")
    hdr = f"  LENS — {ticker}"
    if last_bar is not None:
        chg = last_bar["close"] - last_bar["prev_close"]
        chg_pct = (chg / last_bar["prev_close"] * 100) if last_bar["prev_close"] else 0.0
        arrow = "▲" if chg >= 0 else "▼"
        hdr += f"   ${last_bar['close']:,.2f}  {arrow} {chg:+.2f} ({chg_pct:+.2f}%)"
    if as_of:
        hdr += f"  (close {as_of})"
    print(f"{hdr}   ·   state characterization, NOT a prediction")
    print(f"{'═'*w}")

    # last-bar OHLC + range
    if last_bar is not None:
        o, h, l, c = last_bar["open"], last_bar["high"], last_bar["low"], last_bar["close"]
        pc = last_bar["prev_close"]
        rng = h - l
        rng_pct = (rng / pc * 100) if pc else 0.0
        print(f"  O ${o:,.2f}   H ${h:,.2f}   L ${l:,.2f}   C ${c:,.2f}    "
              f"range ${rng:,.2f} ({rng_pct:.2f}%)")

    # candle: sixel pixel image, or text panel (today + N previous), or one detailed candle (--prev 0)
    eff_style = "braille" if candle_style == "sixel" else candle_style   # text fallback when sixel off
    if candle_style == "sixel" and color and panel_bars:
        ohlc = [(b[1], b[2], b[3], b[4]) for b in panel_bars]
        sys.stdout.write("\n  " + sixel_candles(ohlc, color=color, height_px=candle_px) + "\n")
        span = (f"{panel_bars[0][0][5:]} (prev) → {panel_bars[-1][0][5:]} (today)"
                if len(panel_bars) > 1 else f"{panel_bars[-1][0][5:]} (today)")
        print(f"  {span}   ·   green = up · red = down day")
    elif panel_bars and len(panel_bars) > 1:
        for line in render_candles([(b[1], b[2], b[3], b[4]) for b in panel_bars],
                                   style=eff_style, color=color):
            print(line)
        print(f"  {panel_bars[0][0][5:]} (prev) → {panel_bars[-1][0][5:]} (today)"
              f"   ·   green = up · red = down day")
    elif last_bar is not None:
        up, hollow = c >= pc, c >= o
        candle = (braille_candle(o, h, l, c, pc, color=color) if eff_style == "braille"
                  else render_candle(o, h, l, c, pc, color=color))
        legend = (f"   {'green' if up else 'red'} · {'hollow' if hollow else 'filled'} "
                  f"({'close ≥ open' if hollow else 'close < open'}, "
                  f"{'up' if up else 'down'} vs prior close)")
        candle[len(candle) // 2] += legend
        for line in candle:
            print(line)

    # 1. MARKET BACKDROP
    if backdrop:
        print(f"  MARKET BACKDROP — {backdrop}")

    # 2. MULTI-TIMEFRAME TABLE.  RVOL = latest bar vs its 20-bar avg.  ΔPrc%/ΔVol% = price move vs
    # avg-volume trend over the last ~10 bars (these drive VolTrend: up-confirmed/up-WEAK/dn-distrib/
    # dn-exhaust). Trend = price-vs-MA structural trend (a different read from VolTrend).
    print(f"\n  MULTI-TIMEFRAME  (longest → shortest)")
    print(f"  {'TF':<4}{'Trend':<7}{'RSI':<8}{'Stoch':<6}{'MACD':<8}"
          f"{'RVOL':<6}{'ΔPrc%':>7}{'ΔVol%':>8}   {'VolTrend':<13}")
    # per-column ranges for the heatmap (red = column min, green = max) on ΔPrc% / ΔVol% / RVOL
    def _range(key):
        vals = [x for x in ((reads[tf].get("_vol") or {}).get(key) for tf in reads) if x is not None]
        return (min(vals), max(vals)) if vals else (None, None)
    dp_lo, dp_hi = _range("price_chg_10")
    dv_lo, dv_hi = _range("vol_trend_10")
    rv_lo, rv_hi = _range("rvol")

    def _wrap(cell, esc):
        return f"{esc}{cell}{_RESET}" if (color and esc) else cell

    for tf in reads:
        r = reads[tf]
        v = r.get("_vol") or {}
        rsi = f"{r['rsi']:.0f} {_ob(r['rsi_state'])}" if r.get("rsi") is not None else "—"
        rvol = f"{v['rvol']:.1f}x" if v.get("rvol") else "—"
        dp = f"{v['price_chg_10']:+.1%}" if v.get("price_chg_10") is not None else "—"
        dv = f"{v['vol_trend_10']:+.1%}" if v.get("vol_trend_10") is not None else "—"
        vt = v.get("tag", "—") if v.get("ok") else "—"
        rsi_c = _wrap(f"{rsi:<8}", _rsi_tint(r.get("rsi")))
        rvol_c = _wrap(f"{rvol:<6}", _heat(v.get("rvol"), rv_lo, rv_hi))
        dp_c = _wrap(f"{dp:>7}", _heat(v.get("price_chg_10"), dp_lo, dp_hi))
        dv_c = _wrap(f"{dv:>8}", _heat(v.get("vol_trend_10"), dv_lo, dv_hi))
        print(f"  {tf:<4}{_ARROW.get(r['trend'], '?'):<7}{rsi_c}{_ob(r['stoch_state']):<6}"
              f"{r['macd_state']:<8}{rvol_c}{dp_c}{dv_c}   {vt:<13}")
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
    ap.add_argument("--no-color", action="store_true", help="Disable ANSI colour on the candle (auto-off when piped/redirected).")
    ap.add_argument("--candle", choices=["box", "braille", "sixel"], default="box", help="Candle style: box (default), braille, or sixel true-pixel image (Sixel-capable terminal only).")
    ap.add_argument("--candle-px", type=int, default=128, help="Sixel candle pixel height — the resolution knob (default 128; taller = finer).")
    ap.add_argument("--prev", type=int, default=0, help="Previous candles to show beside today's (default 0 = single detailed candle).")
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    _enable_windows_ansi()
    use_color = sys.stdout.isatty() and not args.no_color and os.environ.get("NO_COLOR") is None

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

        last_bar, as_of, panel_bars = None, None, None
        if "1D" in frames:
            d = frames["1D"]
            row = d.iloc[-1]
            prev_close = float(d["Close"].iloc[-2]) if len(d) > 1 else float(row["Open"])
            last_bar = {"open": float(row["Open"]), "high": float(row["High"]),
                        "low": float(row["Low"]), "close": float(row["Close"]),
                        "prev_close": prev_close}
            as_of = d.index[-1].date().isoformat()
            tail = d.iloc[-(max(0, args.prev) + 1):]
            panel_bars = [(idx.date().isoformat(), float(rw["Open"]), float(rw["High"]),
                           float(rw["Low"]), float(rw["Close"])) for idx, rw in tail.iterrows()]

        print_report(ticker, reads, divs, summary, profile, notes, last_bar=last_bar, as_of=as_of,
                     ctx=ctx, backdrop=backdrop, thesis=args.thesis, level=args.level, color=use_color,
                     candle_style=args.candle, panel_bars=panel_bars, candle_px=args.candle_px)
