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
import subprocess
import sys

import pandas as pd

from modules.timeframes import build_timeframes, last_bar_partial, fetch_live_bar, apply_live_bar
from modules.structure import (
    read_timeframe, read_volume, detect_divergence,
    multi_timeframe_summary, rally_drawdown_risk, read_squeeze,
)
from modules.volume_profile import volume_profile

try:
    from modules.sentiment import gather_context
except Exception:
    gather_context = None
try:
    from modules.geocontext import gather_geo_context
except Exception:
    gather_geo_context = None
try:
    from modules.pc_oi import gather_pc_oi, pc_label, LEAPS_MIN_DTE, LEAPS_MAX_DTE
except Exception:
    gather_pc_oi = pc_label = LEAPS_MIN_DTE = LEAPS_MAX_DTE = None
try:
    from modules.volsetup import expected_move, vol_setup, gauge_val, gauge_pct
    from modules.features import next_earnings
except Exception:
    expected_move = vol_setup = gauge_val = gauge_pct = next_earnings = None
try:
    from modules.features import next_ex_dividend
except Exception:
    next_ex_dividend = None
try:
    from modules.callquote import call_quote, cached_liquidity
except Exception:
    call_quote = cached_liquidity = None
try:
    from modules.benchmarks import upcoming_catalysts
except Exception:
    upcoming_catalysts = None
try:
    from modules.volquote import straddle_quote
except Exception:
    straddle_quote = None
try:
    from modules.vol_history import pre_earnings_vol_study
except Exception:
    pre_earnings_vol_study = None
try:
    from modules.tradier import get_atm_iv
except Exception:
    get_atm_iv = None
try:
    from modules.shortint import gather_squeeze
except Exception:
    gather_squeeze = None
try:
    from modules.setupcheck import setup_check, fetch_rs, fetch_beta, TIER1_MACRO
except Exception:
    setup_check = fetch_rs = fetch_beta = None
    TIER1_MACRO = set()
try:
    from modules.fng import fetch_fng
except Exception:
    fetch_fng = None
try:
    from modules.breadth import fetch_breadth
except Exception:
    fetch_breadth = None
try:
    from modules.insider import gather_insider
except Exception:
    gather_insider = None
try:
    from modules.econ_calendar import next_event_per_series, ALL_SERIES
except Exception:
    next_event_per_series, ALL_SERIES = None, []

_ARROW = {"up": "↑ up", "down": "↓ dn", "mixed": "~ mix"}
_OB = {"overbought": "OB", "oversold": "OS", "neutral": "neut"}
_GREEN, _RED, _RESET = "\033[32m", "\033[31m", "\033[0m"
_DIM = "\033[2m"


def _ramp(t):
    """t in [0,1] -> 24-bit ANSI fg colour: red (0) → amber (0.5) → green (1), softened for dark bg."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    stops = [(216, 60, 52), (214, 186, 46), (94, 196, 94)]   # red · amber · green
    s = 0 if t < 0.5 else 1
    u = (t - s * 0.5) / 0.5
    lo, hi = stops[s], stops[s + 1]
    rgb = tuple(int(lo[i] + (hi[i] - lo[i]) * u) for i in range(3))
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


# Heatmap dead-zone per column: |value − neutral| within this band is treated as noise and shown
# UNCOLORED — the single tuning spot for the three heatmap columns. Set an entry to 0.0 to disable.
HEAT_DEAD = {
    "rvol":         0.10,   # 0.90x–1.10x ≈ normal volume → uncolored
    "price_chg_10": 0.01,   # |10-bar price move| < 1% → uncolored
    "vol_trend_10": 0.05,   # |10-bar volume-trend change| < 5% → uncolored
}


def _heat(val, neutral, half_scale, dead=0.0):
    """Heatmap escape anchored at `neutral` (amber): above → green, below → red. Values within
    ±`dead` of neutral — or a column with no spread beyond the band — are flattened to AMBER (the
    neutral point of the scale), NOT left white. Sign relative to neutral is ABSOLUTE (a value above
    neutral is never red). Returns '' only when `val` itself is missing (white = no data)."""
    if val is None:
        return ""                              # genuinely missing → uncolored (white)
    d = val - neutral
    if (half_scale is None or half_scale < 1e-12
            or (dead > 0.0 and abs(d) <= dead + 1e-9)):  # epsilon → boundary inclusive despite FP
        return _ramp(0.5)                      # neutral / inside dead-zone / no spread → amber
    d = d - dead if d > 0 else d + dead          # ramp from the band edge (amber → full)
    return _ramp(0.5 + 0.5 * d / half_scale)


# RSI tint thresholds (absolute 0–100 scale). 50 = neutral (amber); oversold (≤30) → full green,
# overbought (≥70) → full red. Within ±RSI_DEAD of 50 (the 40–60 neutral zone) reads flat amber —
# the same dead-zone idea as HEAT_DEAD, sized in RSI points. Tune RSI_DEAD to widen/narrow the band.
RSI_NEUTRAL = 50.0    # textbook RSI midpoint → amber
RSI_FULL = 20.0       # ±20 from 50 = the classic 30 / 70 OB–OS lines → full green / red
RSI_DEAD = 10.0       # ±10 around 50 (40–60) → flat amber (neutral zone); set 0.0 to disable


def _rsi_tint(rsi):
    """Absolute RSI tint anchored at 50 (amber): oversold (<50) → green, overbought (>50) → red
    (contrarian read — a washout is bullish). Within ±RSI_DEAD of 50 (the 40–60 neutral zone) reads
    flat amber; full green/red by the 30/70 OB–OS lines. Returns '' only when rsi is missing."""
    if rsi is None:
        return ""
    d = rsi - RSI_NEUTRAL
    if abs(d) <= RSI_DEAD + 1e-9:                       # epsilon → boundary inclusive despite FP
        return _ramp(0.5)                              # neutral zone → amber
    d = d - RSI_DEAD if d > 0 else d + RSI_DEAD          # ramp from the band edge
    return _ramp(0.5 - 0.5 * d / max(RSI_FULL - RSI_DEAD, 1e-9))  # oversold→green, overbought→red


def _ob(state):
    return _OB.get(state, state) or "—"       # None state (indicator NaN on a thin frame) → dash


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
        for (o, h, l, c, pc) in bars:
            hollow, bt, bb = c >= o, row(max(o, c)), row(min(o, c))
            if bt <= r <= bb:
                cell = "███" if not hollow else "├─┤" if bt == bb else "┌─┐" if r == bt else "└─┘" if r == bb else "│ │"
            elif row(h) <= r <= row(l):
                cell = " │ "
            else:
                cell = "   "
            cells.append(f"{_GREEN if c >= pc else _RED}{cell}{_RESET}" if (color and cell.strip()) else cell)
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

    for k, (o, h, l, c, pc) in enumerate(bars):
        x0 = k * (cw + gap)
        for y in range(ypx(h), ypx(l) + 1):                  # wick: centre 2 dot-columns
            plot(x0 + 1, y); plot(x0 + 2, y)
        bt, bb, hollow = ypx(max(o, c)), ypx(min(o, c)), c >= o
        for y in range(bt, bb + 1):                           # body: hollow outline (close>=open) / filled
            if hollow and bb > bt and y not in (bt, bb):
                plot(x0, y); plot(x0 + cw - 1, y)
            else:
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
                _o, _h, _l, _c, _pc = bars[k]
                line += f"{_GREEN if _c >= _pc else _RED}{ch}{_RESET}"
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

    for k, (o, h, l, c, pc) in enumerate(bars):
        ci = 1 if c >= pc else 2                       # colour: green = up vs PRIOR close, red = down
        x0 = k * (cell_w + gap)
        wx = x0 + cell_w // 2 - 1                     # left column of the 2px wick
        yh, yl, yt, yb = ypx(h), ypx(l), ypx(max(o, c)), ypx(min(o, c))
        hollow = c >= o                               # fill: hollow when close >= open (TradingView)
        for y in range(yh, yt):                       # upper wick (above body)
            grid[y][wx] = ci; grid[y][wx + 1] = ci
        for y in range(yb + 1, yl + 1):               # lower wick (below body)
            grid[y][wx] = ci; grid[y][wx + 1] = ci
        for y in range(yt, yb + 1):                   # body: hollow outline / filled
            for x in range(x0, x0 + cell_w):
                if not hollow or y < yt + 2 or y > yb - 2 or x < x0 + 2 or x >= x0 + cell_w - 2:
                    grid[y][x] = ci
    palette = {1: (20, 75, 40), 2: (85, 25, 30)} if color else {1: (80, 80, 80), 2: (80, 80, 80)}
    return _to_sixel(grid, palette)


def analyze(ticker, include_intraday=True, data_dir="data", live=False):
    frames, notes = build_timeframes(ticker, data_dir=data_dir, include_intraday=include_intraday,
                                     intraday_ttl_hours=0 if live else 3, live=live)
    live_bar = None
    if live:
        live_bar = fetch_live_bar(ticker)
        if live_bar is None:
            notes.append("live: no Tradier session data for today — showing last close.")
        else:
            # display-only provisional today-bar; skipped when the frame already covers today
            # (post-close refresh already ran). 1W/1M re-derived so the forming period absorbs it.
            live_bar["applied"] = apply_live_bar(frames, live_bar)
    live_partial = bool(live_bar and live_bar.get("applied") and live_bar.get("in_progress"))
    now_naive = pd.Timestamp.now(tz="America/New_York").tz_localize(None)
    reads, divs = {}, {}
    for tf, df in frames.items():
        r = read_timeframe(df)
        if not r.get("ok"):
            continue
        partial = last_bar_partial(frames.get("1D"), tf) or (live_partial and tf == "1D")
        if live and tf in ("1h", "4h") and len(df):
            # in live mode the last intraday bar can be the forming hour — treat it as partial so
            # RVOL/ΔVol% use the last completed bar (same convention as the W/M/1D partial bars).
            bar_min = 60 if tf == "1h" else 240
            partial = partial or (now_naive < df.index[-1] + pd.Timedelta(minutes=bar_min))
        r["_vol"] = read_volume(df, exclude_last=partial)
        r["_partial"] = partial
        reads[tf] = r
        k, why = detect_divergence(df)
        if k:
            divs[tf] = (k, why)
    summary = multi_timeframe_summary(reads)
    prof_src = frames.get("1h", frames.get("1D"))
    # ~6mo on the intraday path (≈126 sessions × ~7 1h-bars) so the shelves reflect near-term
    # structure, not year-old levels; daily fallback = 252 sessions ≈ 1y. Reference price comes
    # from the 1D close — the 1h cache can lag it (stale-cache fallback), skewing price_location.
    lookback = 880 if "1h" in frames else 252
    ref = float(frames["1D"]["Close"].iloc[-1]) if "1D" in frames else None
    profile = (volume_profile(prof_src, lookback=lookback, ref_price=ref)
               if prof_src is not None else None)
    return frames, reads, divs, summary, profile, notes, live_bar


def _section(title, color=True, w=78):
    """Section headline embedded in a dimmed single rule — visual separation between the lens
    blocks (the top header keeps its double line): `── TITLE ─────…` (S42)."""
    dim, rst = (_DIM, _RESET) if color else ("", "")
    pad = max(3, w - len(title) - 6)          # 2 indent + 2 rule + 2 spaces around the title
    print(f"\n  {dim}──{rst} {title} {dim}{'─' * pad}{rst}")


def print_report(ticker, reads, divs, summary, profile, notes, last_bar=None, as_of=None,
                 ctx=None, backdrop=None, thesis=None, level=None, color=True, candle_style="box",
                 panel_bars=None, candle_px=128, geo=None, pcoi=None, vol=None, live=None,
                 setup=None, squeeze=None, insider=None, callq=None, liq=None, cats=None):
    w = 78
    print(f"\n{'═'*w}")
    hdr = f"  LENS — {ticker}"
    if last_bar is not None:
        chg = last_bar["close"] - last_bar["prev_close"]
        chg_pct = (chg / last_bar["prev_close"] * 100) if last_bar["prev_close"] else 0.0
        arrow = "▲" if chg >= 0 else "▼"
        hdr += f"   ${last_bar['close']:,.2f}  {arrow} {chg:+.2f} ({chg_pct:+.2f}%)"
    if live and live.get("applied") and live.get("in_progress"):
        hdr += f"  (LIVE {live['hhmm']} ET, session in progress)"
    elif as_of:
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
        ohlc = [(b[1], b[2], b[3], b[4], b[5]) for b in panel_bars]
        sys.stdout.write("\n  " + sixel_candles(ohlc, color=color, height_px=candle_px) + "\n")
        span = (f"{panel_bars[0][0][5:]} (prev) → {panel_bars[-1][0][5:]} (today)"
                if len(panel_bars) > 1 else f"{panel_bars[-1][0][5:]} (today)")
        print(f"  {span}   ·   green/red = up/down vs prior close · hollow = close ≥ open")
    elif panel_bars and len(panel_bars) > 1:
        for line in render_candles([(b[1], b[2], b[3], b[4], b[5]) for b in panel_bars],
                                   style=eff_style, color=color):
            print(line)
        print(f"  {panel_bars[0][0][5:]} (prev) → {panel_bars[-1][0][5:]} (today)"
              f"   ·   green/red = up/down vs prior close · hollow = close ≥ open")
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
        _section(f"MARKET BACKDROP — {backdrop}", color)

    # 2. MULTI-TIMEFRAME TABLE — column decode is printed at runtime (legend below). Trend = the
    # price-vs-MA structural trend, a different read from VolTrend (which is ΔPrc% vs ΔVol%).
    _section("MULTI-TIMEFRAME  (longest → shortest)", color)
    dim = _DIM if color else ""
    rst = _RESET if color else ""
    print(f"  {dim}RVOL = latest bar vs 20-bar avg (1.0 = normal)  ·  ΔPrc% = price move over last 10 bars{rst}")
    print(f"  {dim}ΔVol% = 10-bar change in the 20-bar AVG volume (trend, not raw volume)  →  VolTrend{rst}")
    has_partial = any(reads[tf].get("_partial") for tf in reads)
    if has_partial:
        print(f"  {dim}* in-progress bar — RVOL/ΔVol%/VolTrend use the last completed bar "
              f"(price/RSI/ΔPrc% stay live){rst}")
    print(f"  {'TF':<4}{'Trend':<7}{'RSI':<8}{'Stoch':<6}{'MACD':<8}"
          f"{'RVOL':<6}{'ΔPrc%':>7}{'ΔVol%':>8}   {'VolTrend':<13}")
    # per-column half-scales for the heatmap, anchored at a fixed neutral (0 for the signed Δ%
    # columns → +green/−red; 1.0 for RVOL since it is a ratio that is never negative). Measured from
    # the dead-zone edge (HEAT_DEAD) so the largest beyond-band mover still reaches full saturation.
    def _half_scale(key, neutral, dead):
        vals = [x for x in ((reads[tf].get("_vol") or {}).get(key) for tf in reads) if x is not None]
        m = max((abs(x - neutral) - dead for x in vals), default=None)
        return m if (m is not None and m > 1e-12) else None
    dp_hs = _half_scale("price_chg_10", 0.0, HEAT_DEAD["price_chg_10"])
    dv_hs = _half_scale("vol_trend_10", 0.0, HEAT_DEAD["vol_trend_10"])
    rv_hs = _half_scale("rvol", 1.0, HEAT_DEAD["rvol"])

    def _wrap(cell, esc):
        return f"{esc}{cell}{_RESET}" if (color and esc) else cell

    for tf in reads:
        r = reads[tf]
        v = r.get("_vol") or {}
        rsi = f"{r['rsi']:.0f} {_ob(r['rsi_state'])}" if r.get("rsi") is not None else "—"
        rvol = f"{v['rvol']:.1f}x" if v.get("rvol") else "—"
        dp = f"{v['price_chg_10']:+.1%}" if v.get("price_chg_10") is not None else "—"
        dv = f"{v['vol_trend_10']:+.1%}" if v.get("vol_trend_10") is not None else "—"
        vt = (v.get("tag") or "—") if v.get("ok") else "—"
        rsi_c = _wrap(f"{rsi:<8}", _rsi_tint(r.get("rsi")))
        rvol_c = _wrap(f"{rvol:<6}", _heat(v.get("rvol"), 1.0, rv_hs, HEAT_DEAD["rvol"]))
        dp_c = _wrap(f"{dp:>7}", _heat(v.get("price_chg_10"), 0.0, dp_hs, HEAT_DEAD["price_chg_10"]))
        dv_c = _wrap(f"{dv:>8}", _heat(v.get("vol_trend_10"), 0.0, dv_hs, HEAT_DEAD["vol_trend_10"]))
        tf_lbl = f"{tf}*" if r.get("_partial") else tf
        print(f"  {tf_lbl:<4}{_ARROW.get(r['trend'], '?'):<7}{rsi_c}{_ob(r['stoch_state']):<6}"
              f"{(r['macd_state'] or '—'):<8}{rvol_c}{dp_c}{dv_c}   {vt:<13}")
    print(f"  → {summary['synthesis']}")
    if summary.get("rsi_conflict"):
        print(f"  ⚠ {summary['rsi_conflict']}")

    # 3. DIVERGENCES
    if divs:
        _section("DIVERGENCES", color)
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

        _section(f"VOLUME PROFILE  ({profile['n_bars']} bars)   HVN = S/R shelves · LVN = fast-move gaps", color)
        print(f"    POC (fair value): {poc:.2f}   "
              f"Value area: {profile['va_low']:.2f} – {profile['va_high']:.2f}   (price {loc})")
        print(f"    HVN shelves  above price: {_levels(above)}")
        print(f"                 below price: {_levels(below)}")
        print(f"    LVN gaps:    {_levels(lvns)}")

    # 5. RALLY vs DRAWDOWN RISK
    risk = rally_drawdown_risk(reads, profile=profile, ctx=ctx, divergences=divs)
    _section("RALLY vs DRAWDOWN RISK  (current conditions, not a forecast)", color)
    print(f"    NET: {risk['net']}")
    if risk["drawdown"]:
        print(f"    drawdown-risk factors:")
        for f in risk["drawdown"]:
            print(f"      • {f}")
    if risk["rally"]:
        print(f"    rally-favorable factors:")
        for f in risk["rally"]:
            print(f"      • {f}")

    # 5b. SETUP CHECK — transparent completeness checklist (S41; default-on, best-effort)
    if setup and setup.get("rows"):
        _section(f"SETUP CHECK  ({setup['net']})", color)
        for label, mark, detail in setup["rows"]:
            print(f"    {mark} {label:<18}{detail}")
        print(f"    · {setup['footer']}")

    # 6. OPTIONS & VOL CONTEXT
    if ctx and ctx.get("gauges"):
        _section(f"OPTIONS & VOL CONTEXT  (regime: {ctx['regime']})", color)
        for g in ctx["gauges"]:
            if g["group"] in ("OPTIONS", "VOL", "MARKET"):
                val = g["fmt"].format(g["value"])
                pct = f"  [{int(round(g['pct']*100))} percentile]" if g.get("pct") is not None else ""
                lab = f"  {g['label']}" if g.get("label") else ""
                print(f"    {g['name']:<20}{val:>9}{lab}{pct}")
        if liq:
            spr = f"{liq['spread_pct']:.1%}" if liq.get("spread_pct") is not None else "n/a"
            stale_s = "  (stale)" if liq.get("stale") else ""
            print(f"    options liquidity: {liq['grade']}  (ATM spread {spr}, OI {liq['oi']:,}) "
                  f"— as of {liq['as_of_str']}{stale_s}")
        print(f"    NET: {ctx['net']}")

    # 6a. SHORT POSITIONING / SQUEEZE (--squeeze; S41 — fuel context, not an ignition forecast)
    if squeeze:
        _section("SHORT POSITIONING / SQUEEZE  (context, not a prediction)", color)
        si = squeeze.get("si")
        if si and si.get("interest"):
            chg = f"   Δ vs prior settlement {si['chg']:+.1%}" if si.get("chg") is not None else ""
            age = f", {si['settle_age']}d ago" if si.get("settle_age") is not None else ""
            print(f"    short interest   {si['interest']/1e6:,.1f}M shares (settled {si.get('settle_date')}{age}){chg}")
            if si.get("dtc") is not None:
                adv = f"  (avg daily vol {si['adv']/1e6:,.1f}M)" if si.get("adv") else ""
                print(f"    days-to-cover    {si['dtc']:.1f}{adv}")
        else:
            print(f"    short interest   n/a — source covers NASDAQ-listed names only "
                  f"(NYSE tickers return no data)")
        sv = squeeze.get("svr") or {}
        if sv.get("now") is not None:
            pct = f"  [{sv['pct']:.0%}ile of {sv['n']} sessions]" if sv.get("pct") is not None else ""
            avgs = ""
            if sv.get("avg5") is not None and sv.get("avg20") is not None:
                avgs = f" · 5d avg {sv['avg5']:.0%} · 20d avg {sv['avg20']:.0%}"
            print(f"    short-volume     {sv['now']:.0%} of volume (latest){avgs}{pct}")
        read = squeeze.get("read") or {}
        print(f"    NET: {read.get('net', 'n/a')}")
        if read.get("fuel"):
            print(f"    squeeze fuel:")
            for f in read["fuel"]:
                print(f"      • {f}")
        if read.get("counter"):
            print(f"    counter:")
            for f in read["counter"]:
                print(f"      • {f}")
        for c in read.get("caveats", []):
            print(f"    · {c}")

    # 6b. INSIDER ACTIVITY (--insider; S42 — SEC Form 4 open-market flow, cluster-buy detection)
    if insider:
        rd = insider.get("read") or {}
        _section(f"INSIDER ACTIVITY — SEC Form 4, trailing {insider.get('lookback_days', 90)}d  "
                 f"(context, not a prediction)", color)
        usd = rd.get("net_usd")
        usd_s = f"${usd:+,.0f}" if usd else "$0"
        print(f"    net open-market flow  {usd_s}  ({rd.get('n_buys', 0)} buys / "
              f"{rd.get('n_sells', 0)} sells, {rd.get('n_owners', 0)} distinct insiders)")
        lb = rd.get("latest_buy")
        if lb:
            px = f" @ {lb['price']:,.2f}" if lb.get("price") else ""
            usd_b = f"  (${lb['usd']:,.0f})" if lb.get("usd") else ""
            print(f"    latest buy   {lb['date']}  {lb['owner']} ({lb['role']})  "
                  f"{lb['shares']:,.0f} sh{px}{usd_b}")
        print(f"    NET: {rd.get('net', 'n/a')}")
        for f in rd.get("positive", []):
            print(f"      • {f}")
        for f in rd.get("flags", []):
            print(f"      ⚑ {f}")
        for c in rd.get("caveats", []):
            print(f"    · {c}")

    # PUT/CALL OI — live Tradier chain, by expiry (--pc-oi; positioning, not a prediction).
    # Distinct from the OPTIONS "Put/Call OI" gauge above (Massive-harvested ~30d blended snapshot).
    if pcoi and pcoi.get("rows"):
        _hdr = f"({pcoi['scope']})"
        if pcoi.get("as_of_str"):
            _hdr += f" · as of {pcoi['as_of_str']}" + ("  (stale)" if pcoi.get("stale") else "")
        _section(f"PUT/CALL OI — live Tradier chain, by expiry  {_hdr}", color)
        print(f"    {'Expiry':>10}  {'DTE':>4}  {'P/C OI':>6}  {'P/C Vol':>7}   Positioning")
        for r in pcoi["rows"]:
            pco = f"{r['pc']:.2f}"     if r["pc"]     is not None else "n/a"
            pcv = f"{r['pc_vol']:.2f}" if r["pc_vol"] is not None else "n/a"
            leaps = " *" if LEAPS_MIN_DTE <= r["dte"] <= LEAPS_MAX_DTE else ""
            print(f"    {r['expiry']:>10}  {r['dte']:>4}  {pco:>6}  {pcv:>7}   {pc_label(r['pc'])}{leaps}")
        if len(pcoi["rows"]) > 1:
            t = pcoi["total"]
            tpc  = f"{t['pc']:.2f}"     if t["pc"]     is not None else "n/a"
            tpcv = f"{t['pc_vol']:.2f}" if t["pc_vol"] is not None else "n/a"
            print(f"    {'TOTAL':>10}  {'':>4}  {tpc:>6}  {tpcv:>7}   {pc_label(t['pc'])}  ({pcoi['scope']})")
        print(f"    P/C OI = put OI / call OI (positioning) · P/C Vol = latest-session flow · * = LEAPS tenor")

    # VOLATILITY SETUP — long-vol (straddle/strangle) context (--vol; descriptive, not a prediction).
    if vol and vol.get("setup"):
        s = vol["setup"]; em = vol.get("em"); eg = vol.get("earnings"); sq = vol.get("squeeze") or {}
        _section("VOLATILITY SETUP — straddle/strangle context  (not a prediction)", color)
        on = [tf for tf in ("1M", "1W", "1D", "4h", "1h") if sq.get(tf, {}).get("squeeze_on")]
        print(f"    compression: squeeze ON on {', '.join(on)}" if on
              else "    compression: no active squeeze")
        if em:
            line = (f"    expected move (~{em['dte']}d): ±{em['pct']:.1%}  "
                    f"(±${em['dollars']:.2f} → {em['lo']:.2f} / {em['hi']:.2f})")
            if em.get("hv_pct"):
                line += f"   vs realized ±{em['hv_pct']:.1%}"
            print(line)
        if eg and eg.get("date"):
            hm = f", typ. ±{eg['hist_move']:.1%}" if eg.get("hist_move") else ""
            print(f"    earnings: {eg['date']} ({eg['days']}d{hm})")
        hist = vol.get("history")
        if hist and hist.get("status") == "ok":
            print(f"    history ({hist['usable']} earnings): {hist['summary']}")
        elif hist and hist.get("status") == "insufficient_iv":
            # backfill only helps liquid names (trades-based; the CRSP dead end, S40) — the daily
            # harvest through earnings windows is the path that always works (S44).
            print(f"    history: IV history thin — accumulates via the daily harvest; "
                  f"`backfill_iv.py` can restore liquid names ({hist['ticker']})")
        print(f"    NET: {s['net']}")
        for n in s.get("notes", []):
            print(f"      · {n}")
        if s["long_vol"]:
            print(f"    favors BUYING vol (straddle/strangle):")
            for f in s["long_vol"]:
                print(f"      • {f}")
        if s["short_vol"]:
            print(f"    favors SELLING premium:")
            for f in s["short_vol"]:
                print(f"      • {f}")
        print(f"    {s['hint']}")
        q = vol.get("quote")
        if q and q.get("quotes"):
            tag = "  (stale)" if q.get("stale") else ""
            print(f"    live quote — spot {q['spot']:.2f}, as of {q['as_of_str']}{tag}:")
            for note in q.get("notes", []):
                print(f"      · {note}")
            if len(q["quotes"]) > 1:
                print("      two vehicles — nearest post-earnings (steepest ramp) vs nearest monthly (more liquid):")

            def _legln(cb):
                lg = cb.get("legs")
                if not lg:
                    return None
                def one(o, cp):
                    oi = f"{int(o['oi']):,}" if o.get("oi") is not None else "—"
                    return f"{o['strike']:g}{cp}  OI {oi}  bid/ask {o['bid']:.2f}/{o['ask']:.2f}"
                return f"          {one(lg['put'], 'p')}   ·   {one(lg['call'], 'c')}"

            def _askln(cb):
                # executable (ask-side) cost/BEs — shown only when the mid understates it by >3%,
                # so tight-spread names stay clean and wide-spread ones stop flattering themselves
                ca = cb.get("cost_ask")
                if not ca or ca <= cb["cost"] * 1.03:
                    return None
                return (f"          at ask: ${ca:.2f}/sh → BE {cb['lo_ask']:.2f} / {cb['hi_ask']:.2f}  "
                        f"(need −{cb['dn_move_ask']:.1%} / +{cb['up_move_ask']:.1%})")

            def _nbln(cb):
                # a no-bid leg makes the mid (= ask/2 on that leg) fictional — say so (S43)
                return ("          ⚠ a leg has no bid — the mid cost is indicative, not executable"
                        if cb.get("no_bid") else None)

            for blk in q["quotes"]:
                kind = blk.get("expiry_kind", "")
                dae = blk.get("days_after_earn")
                after = f"; {dae}d after earnings" if dae is not None else ""
                print(f"      exp {blk['expiry']} ({kind + ', ' if kind else ''}{blk['dte']}d{after}):")
                stq = blk.get("straddle"); sg = blk.get("strangle")
                if stq:
                    print(f"        ATM straddle  {stq['call_strike']:g}: ${stq['cost']:.2f}/sh  "
                          f"BE {stq['lo']:.2f} / {stq['hi']:.2f}  (need −{stq['dn_move']:.1%} / +{stq['up_move']:.1%})")
                    for ln in (_legln(stq), _nbln(stq), _askln(stq)):
                        if ln:
                            print(ln)
                if sg:
                    tw = sg.get("target_width")
                    dnw, upw = sg.get("dn_width"), sg.get("up_width")
                    if dnw is not None and upw is not None:
                        # per-wing widths (S40) — a snapped/tilted strangle shows as e.g. −3.5% / +6.6%
                        off = tw is not None and (abs(dnw - tw) >= 0.01 or abs(upw - tw) >= 0.01)
                        wing = f"−{dnw:.1%} / +{upw:.1%}" + (f", target ±{tw:.0%}" if off else "")
                    else:
                        drift = (f", target ±{tw:.0%}"
                                 if tw is not None and round(tw * 100) != round(sg["width"] * 100) else "")
                        wing = f"≈±{sg['width']:.0%}{drift}"
                    print(f"        auto strangle ({wing})  {sg['put_strike']:g} / {sg['call_strike']:g}: "
                          f"${sg['cost']:.2f}/sh  BE {sg['lo']:.2f} / {sg['hi']:.2f}  (need −{sg['dn_move']:.1%} / +{sg['up_move']:.1%})")
                    for ln in (_legln(sg), _nbln(sg), _askln(sg)):
                        if ln:
                            print(ln)
            print("      vega: straddle = max vega (enter close to the print); "
                  "strangle = cheaper + lower theta (enter earlier / run more names / vega convexity)")

    # LONG CALL VIABILITY (--call; S46 — the directional instrument's carry math; context, not advice)
    if callq and callq.get("quotes"):
        tag = "  (stale)" if callq.get("stale") else ""
        _section("LONG CALL VIABILITY  (context, not advice)", color)
        print(f"    spot {callq['spot']:.2f}, as of {callq['as_of_str']}{tag}")
        cliq = callq.get("liquidity")
        if cliq:
            spr = f"{cliq['spread_pct']:.1%}" if cliq.get("spread_pct") is not None else "n/a"
            print(f"    chain liquidity: {cliq['grade'].upper()}  (ATM-region spread {spr}, "
                  f"OI {cliq['oi']:,}, day vol {cliq['volume']:,})")

        def _callln(kind, c):
            if not c:
                return
            dlt = f"Δ{c['delta']:.2f}" if c.get("delta") is not None else "Δ—"
            th = f"theta {c['theta_pct']:.1%}/d of premium" if c.get("theta_pct") else "theta n/a"
            spr = f"spr {c['spread_pct']:.1%}" if c.get("spread_pct") is not None else "spr n/a"
            oi = f"OI {int(c['oi']):,}" if c.get("oi") is not None else "OI —"
            print(f"        {kind:<4}{c['strike']:g}c  {dlt}  ${c['mid']:.2f}/sh  "
                  f"BE {c['be']:.2f} ({c['be_move']:+.1%})  {th}  {oi}  {spr}")
            if c.get("be_ask") is not None:
                print(f"            at ask ${c['ask']:.2f} → BE {c['be_ask']:.2f} ({c['be_move_ask']:+.1%})")

        for blk in callq["quotes"]:
            mon = "monthly, " if blk.get("monthly") else ""
            print(f"      exp {blk['expiry']} ({mon}{blk['dte']}d):")
            _callln("ATM", blk.get("atm"))
            _callln("OTM", blk.get("otm"))
            for n in blk.get("notes", []):
                print(f"          · {n}")
        curve = callq.get("curve")
        if curve and curve.get("points"):
            pts = " · ".join(f"{p['label']} {p['iv']:.1%}" for p in curve["points"])
            print(f"      IV by expiry: {pts}  — {curve['tag']}")
        ivp = gauge_pct(ctx, "ATM IV (30d)") if gauge_pct is not None else None
        if ivp is not None and ivp >= 0.70:
            print(f"      ⚠ ATM IV at {ivp:.0%}ile of its history — paying up for a direction bet; "
                  f"debit spreads cut the vega/theta bill")
        print("      guide: more DTE = slower theta · 0.35–0.40Δ in trends, lower Δ in chop · "
              "BE move must be plausible within the tenor")

    # 6b. GEOPOLITICAL / CROSS-ASSET BACKDROP (--geo; context, not a prediction)
    if geo and geo.get("gauges"):
        _section("GEOPOLITICAL / CROSS-ASSET BACKDROP  (context, not a prediction)", color)
        last_grp = None
        for g in geo["gauges"]:
            if g["group"] != last_grp:
                print(f"    {g['group']}:")
                last_grp = g["group"]
            tag = f"  {g['label']}" if g.get("label") else ""
            pct = f"  [{int(round(g['pct']*100))} percentile]" if g.get("pct") is not None else ""
            print(f"      {g['name']:<18}{g['fmt'].format(g['value']):>9}{tag}{pct}")
        print(f"    NET: {geo['composite']}")
        for n in geo.get("notes", []):
            print(f"      · {n}")

    # 7a. KNOWN CATALYSTS (S46) — catalysts.csv binary events (PDUFA / trial readouts) ≤45d out;
    # until now only the ML layer saw these dates.
    if cats:
        _section("KNOWN CATALYSTS (catalysts.csv)", color)
        for d, days, typ, desc in cats:
            print(f"    {d} ({days}d)  {typ}: {desc}")

    # 7. MACRO
    if next_event_per_series:
        try:
            ev = next_event_per_series(data_dir="data")
            soon = [(name, d, days) for name, (d, days) in ev.items()
                    if d is not None and days is not None and days <= 10]
            if soon:
                _section("MACRO (next 10d): " +
                         "  ".join(f"{n} {days}d" for n, d, days in sorted(soon, key=lambda x: x[2])),
                         color)
        except Exception:
            pass

    # 8. THESIS CHECK
    if thesis:
        _section(f"THESIS CHECK — you are {thesis.upper()}" + (f" (level {level})" if level else ""),
                 color)
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


def _expected_last_session():
    """Most recent COMPLETED daily session (naive date): today if a weekday past 4 PM ET, else the
    prior weekday. Holidays are approximated as weekdays — the data source simply returns no bar for
    them (same convention as augment_recent_prices_from_tradier in indicators.py)."""
    now_et = pd.Timestamp.now(tz="America/New_York")
    d = pd.Timestamp(now_et.date())
    if not (now_et.weekday() < 5 and now_et.hour >= 16):
        d -= pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d


def _indicators_stale(ticker, data_dir):
    """True when the indicators CSV exists but is missing the latest completed session AND has not
    been refreshed since that session closed. Missing CSV -> False (build_timeframes' yfinance
    fallback handles unknown tickers). Never raises — any error returns False so a freshness-check
    glitch never blocks the lens."""
    path = os.path.join(data_dir, f"{ticker.lower()}_indicators.csv")
    if not os.path.exists(path):
        return False
    try:
        expected = _expected_last_session()
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        last = df["Close"].dropna().index.max()              # last REAL bar (skips NaN today-row)
        if last is not None and pd.Timestamp(last).normalize() >= expected:
            return False
        mtime_et = pd.Timestamp(os.path.getmtime(path), unit="s", tz="UTC").tz_convert("America/New_York")
        session_close = (expected + pd.Timedelta(hours=16)).tz_localize("America/New_York")
        return mtime_et < session_close                      # holiday guard: don't re-refresh post-close
    except Exception:
        return False


def _refresh_indicators(ticker, data_dir):
    """Run indicators.py for `ticker` to rewrite its CSV (quiet, headless). Best-effort: on any
    failure print a short note and return False so the lens proceeds on whatever data exists."""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "indicators.py")
    cmd = [sys.executable, "-X", "utf8", script,
           "--ticker", ticker, "--no-chart", "--data-dir", data_dir]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",     # child runs -X utf8; decode UTF-8
                           cwd=os.path.dirname(script), timeout=600)  # (not the cp1252 locale default)
        if r.returncode != 0:
            tail = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[-1]
            print(f"    refresh failed for {ticker} — using existing data ({tail})")
            return False
        return True
    except Exception as e:
        print(f"    refresh skipped for {ticker} ({type(e).__name__}) — using existing data")
        return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Multi-timeframe market-structure & risk lens.")
    ap.add_argument("--ticker", nargs="+", help="One or more tickers (skips the prompt; e.g. --ticker QQQ JPM F).")
    ap.add_argument("--thesis", choices=["bullish", "bearish"], help="Your bias → confirm/contradict overlay.")
    ap.add_argument("--level", type=float, help="A key level you're watching (annotates the thesis check).")
    ap.add_argument("--no-intraday", action="store_true", help="Skip 1h/4h (offline / fast).")
    ap.add_argument("--no-vix", action="store_true", help="Skip the options/vol + VIX context block.")
    ap.add_argument("--geo", action="store_true", help="Add a cross-asset / geopolitical stress backdrop (oil/OVX/gold/DXY, credit & rates, geo-sensitive sectors, EPU/GPR). Network; cached ~6h.")
    ap.add_argument("--no-color", action="store_true", help="Disable ANSI colour on the candle (auto-off when piped/redirected).")
    ap.add_argument("--candle", choices=["box", "braille", "sixel"], default="sixel", help="Candle style: sixel true-pixel image (default; Sixel-capable terminal only, falls back to braille when piped/--no-color), box, or braille.")
    ap.add_argument("--candle-px", type=int, default=128, help="Sixel candle pixel height — the resolution knob (default 128; taller = finer).")
    ap.add_argument("--prev", type=int, default=10, help="Previous candles to show beside today's (default 10).")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--no-refresh", action="store_true",
                    help="Skip the auto-refresh of stale indicators CSVs (render whatever is on disk).")
    ap.add_argument("--refresh", action="store_true",
                    help="Force a data refresh (run indicators.py) even if the CSV looks current; builds a missing CSV too.")
    ap.add_argument("--pc-oi", nargs="*", choices=["all", "near", "leaps", "monthly"],
                    help="Add a live Tradier put/call OI block by expiry. Bare = all expiries; combine any of "
                         "near (≤45 DTE) / leaps (180–365 DTE) / monthly (3rd-Friday only), e.g. `--pc-oi leaps monthly`. "
                         "Network; needs TRADIER_TOKEN.")
    ap.add_argument("--insider", action="store_true",
                    help="Add an INSIDER ACTIVITY block: trailing-90d open-market Form 4 flow from "
                         "SEC EDGAR (official API) with cluster-buy detection. Network; cached; "
                         "set $env:SEC_CONTACT to put your contact in the SEC User-Agent.")
    ap.add_argument("--squeeze", action="store_true",
                    help="Add a SHORT POSITIONING / SQUEEZE block: bi-monthly short interest + "
                         "days-to-cover (NASDAQ), daily short-volume ratio with trailing percentile "
                         "(FINRA Reg SHO), and a two-sided squeeze-fuel scorecard. Network; cached.")
    ap.add_argument("--live", action="store_true",
                    help="Intraday mode: append a live provisional today-bar from the Tradier quote "
                         "(real-time; display-only, marked * while the session is open), force-refresh "
                         "the intraday cache and the --pc-oi/--vol quote caches, and show a live "
                         "Tradier ATM IV beside the harvested gauge.")
    ap.add_argument("--vol", action="store_true",
                    help="Add a VOLATILITY SETUP block — Bollinger-Keltner squeeze, expected move + breakevens, "
                         "earnings catalyst, and a two-sided long-vol (straddle/strangle) vs short-vol scorecard.")
    ap.add_argument("--call", action="store_true",
                    help="Add a LONG CALL VIABILITY block — ~45d/~90d monthly call quotes (ATM + "
                         "~0.35-0.40 delta) with breakeven move, theta/day as %% of premium, an "
                         "ATM-IV-by-expiry curve, and a chain liquidity grade. Network; needs "
                         "TRADIER_TOKEN; cached like --vol.")
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
    if fetch_breadth is not None:                    # equal-weight breadth (S45) — market-level, cached ~6h
        br = fetch_breadth(data_dir=args.data_dir)
        segs = []
        for lbl, d in ((br or {}).get("pairs") or {}).items():
            pct = f" [{d['pct']:.0%}ile]" if d.get("pct") is not None else ""
            segs.append(f"{lbl} {d['rel_20d']:+.1%}{pct} {d['tag']}")
        if segs:
            seg = "breadth(20d) " + " · ".join(segs)
            backdrop_base = f"{backdrop_base}  |  {seg}" if backdrop_base else seg
    if fetch_fng is not None:                        # CNN Fear & Greed (S41) — market-level, cached ~6h
        fng = fetch_fng(data_dir=args.data_dir)
        if fng and fng.get("score") is not None:
            pct = f" [{fng['pct']:.0%}ile]" if fng.get("pct") is not None else ""
            seg = f"F&G {fng['score']:.0f} {fng['rating']}{pct}"
            backdrop_base = f"{backdrop_base}  |  {seg}" if backdrop_base else seg

    for ticker in tickers:
        if not args.no_refresh:
            csv_missing = not os.path.exists(
                os.path.join(args.data_dir, f"{ticker.lower()}_indicators.csv"))
            if args.refresh or csv_missing or _indicators_stale(ticker, args.data_dir):
                print(f"  ↻ {ticker}: {'building' if csv_missing else 'refreshing'} indicators data…")
                _refresh_indicators(ticker, args.data_dir)
        try:
            frames, reads, divs, summary, profile, notes, live_bar = analyze(
                ticker, include_intraday=not args.no_intraday, data_dir=args.data_dir,
                live=args.live)
        except FileNotFoundError as e:
            print(f"  Could not load data for {ticker}: {e}")
            continue

        ctx = None
        if not args.no_vix and gather_context is not None:
            try:
                ctx = gather_context(ticker, data_dir=args.data_dir, with_vix=True)
            except Exception as e:
                notes.append(f"options/vol context unavailable ({type(e).__name__}).")

        # --live: real-time ATM IV from Tradier (smv), shown beside the harvested gauge so
        # "IV now" and "IV's place in its history" are both visible intraday.
        live_iv = None
        if args.live and get_atm_iv is not None:
            try:
                spot_now = float(frames["1D"]["Close"].iloc[-1]) if "1D" in frames else None
                live_iv = get_atm_iv(ticker, current_price=spot_now)
            except Exception:
                live_iv = None
            if live_iv and ctx and ctx.get("gauges"):
                gs = ctx["gauges"]
                pos = next((i + 1 for i, x in enumerate(gs) if x.get("name") == "ATM IV (30d)"), 0)
                gs.insert(pos, {"group": "OPTIONS", "name": "ATM IV (live)", "value": live_iv["iv"],
                                "fmt": "{:.1%}", "label": f"Tradier now, {live_iv['dte']}d",
                                "pct": None})

        backdrop = backdrop_base
        if ctx and ctx.get("regime") and ctx["regime"] != "n/a" and backdrop:
            backdrop = f"{backdrop_base}  |  VIX regime: {ctx['regime']}"

        geo = None
        if args.geo and gather_geo_context is not None:
            try:
                geo = gather_geo_context(data_dir=args.data_dir)
            except Exception as e:
                notes.append(f"geopolitical backdrop unavailable ({type(e).__name__}).")

        pc = None
        if args.pc_oi is not None and gather_pc_oi is not None:   # [] (bare = all) is falsy → test is-not-None
            toks = set(args.pc_oi)
            monthly = "monthly" in toks
            tenor = "near" if "near" in toks else "leaps" if "leaps" in toks else "all"
            try:
                pc = gather_pc_oi(ticker, preset=tenor, monthly=monthly,
                                  interactive=sys.stdin.isatty(), data_dir=args.data_dir,
                                  force=args.live)
            except Exception as e:
                notes.append(f"put/call OI unavailable ({type(e).__name__}).")
            else:
                if pc is None:
                    notes.append("put/call OI unavailable (no Tradier token or no chain data).")
                elif pc.get("cached") and pc.get("stale"):
                    notes.append(f"put/call OI cached {pc['age_str']} and stale — run in a terminal to refresh.")

        # earnings date — shared by the --vol block and the SETUP CHECK (S41)
        earn = None
        if next_earnings is not None:
            try:
                earn = next_earnings(ticker, daily=frames.get("1D"))
            except Exception:
                earn = None

        # next ex-dividend (S46) — shared by the SETUP CHECK catalyst row and the --call block
        exd = None
        if next_ex_dividend is not None:
            try:
                exd = next_ex_dividend(ticker)
            except Exception:
                exd = None

        # earnings-window capture guard (S44): inside the pre-earnings window, a missed daily IV
        # harvest is UNRECOVERABLE for the vol study (Massive history is trades-only — thin names
        # can't be backfilled). Surface a missing harvest the same day instead of post-print.
        if earn and earn.get("days") is not None and 0 <= earn["days"] <= 10:
            try:
                _csv = os.path.join(args.data_dir, f"{ticker.lower()}_indicators.csv")
                _iv = pd.read_csv(_csv, index_col=0, parse_dates=True)["atm_iv_30d"].dropna()
                _last_iv = _iv.index.max() if len(_iv) else None
                if _last_iv is None or pd.Timestamp(_last_iv).normalize() < _expected_last_session():
                    notes.append(f"earnings in {earn['days']}d and the latest session's IV harvest is "
                                 f"missing — run `indicators.py --ticker {ticker}` (missed pre-earnings "
                                 f"sessions cannot be backfilled).")
            except Exception:
                pass

        vol = None
        if args.vol and vol_setup is not None:
            try:
                spot = float(frames["1D"]["Close"].iloc[-1]) if "1D" in frames else None
                squeeze = {tf: read_squeeze(frames[tf]) for tf in frames}
                # --live: prefer the real-time Tradier IV for the expected move (spot is already
                # live via the provisional today-bar); the scorecard percentile stays harvest-based.
                # The live IV carries its own tenor — scale the move by that DTE, not a fixed 30.
                live_ok = bool((live_iv or {}).get("iv"))
                em_iv = live_iv["iv"] if live_ok else gauge_val(ctx, "ATM IV (30d)")
                em_dte = (live_iv.get("dte") or 30) if live_ok else 30
                em = expected_move(spot, em_iv, dte=em_dte,
                                   hv=gauge_val(ctx, "HV-20 (annualized)"))
                vol = {"squeeze": squeeze, "em": em, "earnings": earn,
                       "setup": vol_setup(reads, squeeze, ctx, earnings=earn, em=em),
                       "quote": (straddle_quote(ticker, earnings_date=(earn or {}).get("date"),
                                                interactive=sys.stdin.isatty(),
                                                data_dir=args.data_dir,
                                                force=args.live) if straddle_quote else None),
                       "history": (pre_earnings_vol_study(ticker, interactive=sys.stdin.isatty(),
                                                          data_dir=args.data_dir)
                                   if pre_earnings_vol_study else None)}
            except Exception as e:
                notes.append(f"vol setup unavailable ({type(e).__name__}).")

        # LONG CALL VIABILITY (--call; S46) — the directional instrument's carry math, cached.
        callq = None
        if args.call and call_quote is not None:
            try:
                callq = call_quote(ticker, earnings_date=(earn or {}).get("date"),
                                   ex_div_date=(exd or {}).get("date"),
                                   interactive=sys.stdin.isatty(), data_dir=args.data_dir,
                                   force=args.live)
            except Exception as e:
                notes.append(f"call viability unavailable ({type(e).__name__}).")
            else:
                if callq is None:
                    notes.append("call viability unavailable (no Tradier token or no chain data).")
                elif callq.get("cached") and callq.get("stale"):
                    notes.append(f"call quote cached {callq['age_str']} and stale — run in a terminal to refresh.")

        # chain liquidity grade (S46) — default-on, ZERO network: reads the freshest --call cache.
        liq = cached_liquidity(ticker, data_dir=args.data_dir) if cached_liquidity is not None else None

        # known binary catalysts (S46) — surfaces catalysts.csv (PDUFA/trial dates) in the lens.
        cats = upcoming_catalysts(ticker) if upcoming_catalysts is not None else []

        # SHORT POSITIONING / SQUEEZE (--squeeze; S41) — reuses the lens' own profile + pc flow.
        sqz = None
        if args.squeeze and gather_squeeze is not None:
            rvol_1d = ((reads.get("1D") or {}).get("_vol") or {}).get("rvol")
            sqz = gather_squeeze(ticker, daily=frames.get("1D"), rvol=rvol_1d, pc=pc,
                                 profile=profile, data_dir=args.data_dir)
            if sqz is None:
                notes.append("short-positioning data unavailable (NASDAQ/FINRA fetch failed).")

        # INSIDER ACTIVITY (--insider; S42) — SEC EDGAR Form 4 open-market flow, cached.
        ins = None
        if args.insider and gather_insider is not None:
            ins = gather_insider(ticker, data_dir=args.data_dir)
            if ins is None:
                notes.append("insider activity unavailable (EDGAR fetch failed / unknown ticker).")

        # SETUP CHECK (S41; default-on, best-effort) — pure synthesis + one RS benchmark fetch.
        setup = None
        if setup_check is not None and reads:
            try:
                macro_t1 = None
                if next_event_per_series is not None:
                    ev = next_event_per_series(data_dir=args.data_dir)
                    t1 = [days for name, (d, days) in ev.items()
                          if name in TIER1_MACRO and days is not None]
                    macro_t1 = min(t1) if t1 else None
                rs = (fetch_rs(ticker, frames["1D"], data_dir=args.data_dir)
                      if (fetch_rs is not None and "1D" in frames) else None)
                beta = (fetch_beta(ticker, frames["1D"])
                        if (fetch_beta is not None and "1D" in frames) else None)
                setup = setup_check(reads, profile=profile, ctx=ctx, earn=earn,
                                    macro_tier1_days=macro_t1, rs=rs, beta=beta, ex_div=exd)
            except Exception as e:
                notes.append(f"setup check unavailable ({type(e).__name__}).")

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
            pcs = d["Close"].shift(1)                  # prior close per bar → hollow-candle colour
            panel_bars = [(idx.date().isoformat(), float(rw["Open"]), float(rw["High"]),
                           float(rw["Low"]), float(rw["Close"]),
                           float(pcs.loc[idx]) if pd.notna(pcs.loc[idx]) else float(rw["Open"]))
                          for idx, rw in tail.iterrows()]

        print_report(ticker, reads, divs, summary, profile, notes, last_bar=last_bar, as_of=as_of,
                     ctx=ctx, backdrop=backdrop, thesis=args.thesis, level=args.level, color=use_color,
                     candle_style=args.candle, panel_bars=panel_bars, candle_px=args.candle_px,
                     geo=geo, pcoi=pc, vol=vol, live=live_bar, setup=setup, squeeze=sqz,
                     insider=ins, callq=callq, liq=liq, cats=cats)
