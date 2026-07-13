"""
lens_web_sections — native Streamlit renderers for the lens payload (S49).

One function per report section, in print_report's order, each mirroring its None/empty
guard so a partial payload never raises. `render_all(payload)` drives them; lens_web.py
keeps the full ANSI report in an expander below as the lossless reference rendering.

Display conventions: percentiles via sentiment.ordinal_percentile (97ᵗʰ percentile — Unicode
superscript, survives st.dataframe's HTML escaping); heat/tint colors mirror the CLI ramp
(lens._ramp stops) so the web table reads like the terminal one; charts reuse the app's
candle green/red — identity is never color-alone (position + legend + the table below).
"""

import html

import pandas as pd
import streamlit as st

from lens import HEAT_DEAD, RSI_NEUTRAL, RSI_DEAD, RSI_FULL, _ARROW, _OB
from modules.sentiment import ordinal_percentile

try:
    from modules.pc_oi import pc_label, LEAPS_MIN_DTE, LEAPS_MAX_DTE
except Exception:                                     # pragma: no cover — optional dep path
    pc_label, LEAPS_MIN_DTE, LEAPS_MAX_DTE = (lambda pc: ""), 365, 1200

GREEN, RED, AMBER = "#5ec45e", "#d83c34", "#d6ba2e"
BLUE, GOLD, GRAY, INK = "#4ea3d8", "#e0a63a", "#9aa4b2", "#d8dee9"
_RAMP_STOPS = [(216, 60, 52), (214, 186, 46), (94, 196, 94)]   # red · amber · green (= lens._ramp)


# ── small helpers ────────────────────────────────────────────────────────────
def _ramp_hex(t):
    """t in [0,1] → hex on the CLI's red→amber→green ramp."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    s = 0 if t < 0.5 else 1
    u = (t - s * 0.5) / 0.5
    lo, hi = _RAMP_STOPS[s], _RAMP_STOPS[s + 1]
    r, g, b = (round(lo[i] + (hi[i] - lo[i]) * u) for i in range(3))
    return f"#{r:02x}{g:02x}{b:02x}"


def _heat_hex(val, neutral, half_scale, dead=0.0):
    """Web analog of lens._heat — same dead-zone/half-scale logic, hex instead of ANSI."""
    if val is None:
        return None
    d = val - neutral
    if (half_scale is None or half_scale < 1e-12
            or (dead > 0.0 and abs(d) <= dead + 1e-9)):
        return _ramp_hex(0.5)
    d = d - dead if d > 0 else d + dead
    return _ramp_hex(0.5 + 0.5 * d / half_scale)


def _rsi_hex(rsi):
    """Web analog of lens._rsi_tint — oversold→green, overbought→red, 40–60 amber."""
    if rsi is None:
        return None
    d = rsi - RSI_NEUTRAL
    if abs(d) <= RSI_DEAD + 1e-9:
        return _ramp_hex(0.5)
    d = d - RSI_DEAD if d > 0 else d + RSI_DEAD
    return _ramp_hex(0.5 - 0.5 * d / max(RSI_FULL - RSI_DEAD, 1e-9))


def _slug(title):
    """Stable anchor id from a section title: the part before any '—'/'(' qualifier (those
    carry run-specific text like regimes and as-of stamps), lowercased, non-alnum → '-'.
    lens_web.py's sidebar quick-nav links against these (S56)."""
    import re
    base = re.split(r"—|\(", title)[0]
    return re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")


def _sec(title):
    st.markdown(
        f'<div id="{_slug(title)}" style="margin:1.1em 0 0.35em;color:#8b95a7;'
        f'font-size:0.82em;letter-spacing:0.06em;text-transform:uppercase;'
        f'border-bottom:1px solid #2a2f3a;padding-bottom:3px;">{html.escape(title)}</div>',
        unsafe_allow_html=True)


def _net_color(text):
    """Verdict pill color from NET-line keywords; gray when the tilt isn't obvious."""
    t = (text or "").lower()
    if any(k in t for k in ("drawdown", "risk-tilted", "rich", "bearish", "selling", "stress")):
        return RED
    if any(k in t for k in ("rally", "favorable", "cheap", "bullish", "fuel", "buying")):
        return GREEN
    return GRAY


def _pill(text, color=GRAY):
    return (f'<span style="border:1px solid {color};color:{color};padding:1px 10px;'
            f'border-radius:10px;font-size:0.85em;font-weight:600;white-space:nowrap;">'
            f'{html.escape(str(text))}</span>')


def _net(label, text):
    st.markdown(f'{_pill(label, _net_color(text))}&nbsp; <span style="color:{INK};">'
                f'{html.escape(str(text))}</span>', unsafe_allow_html=True)


def _bullets(items, color=INK, marker="•"):
    if not items:
        return
    rows = "".join(f'<div style="margin:1px 0;color:{color};">{marker} {html.escape(str(f))}</div>'
                   for f in items)
    st.markdown(rows, unsafe_allow_html=True)


def _df(df, styler=None, **col_cfg):
    st.dataframe(styler if styler is not None else df, hide_index=True, width="stretch",
                 column_config=col_cfg or None)


def _pct_txt(pct):
    """0–1 fraction → ordinal cell text ('97ᵗʰ') or em-dash when no percentile."""
    return ordinal_percentile(pct, word=False) if pct is not None else "—"


# ── sections (print_report order) ────────────────────────────────────────────
def sec_header(p):
    lb = p.get("last_bar")
    if not lb:
        return
    chg = lb["close"] - lb["prev_close"]
    pct = (chg / lb["prev_close"] * 100) if lb["prev_close"] else 0.0
    live = p.get("live")
    when = (f"LIVE {live['hhmm']} ET" if live and live.get("applied") and live.get("in_progress")
            else f"close {p['as_of']}" if p.get("as_of") else "")
    rng = lb["high"] - lb["low"]
    rng_pct = (rng / lb["prev_close"] * 100) if lb["prev_close"] else 0.0
    r52 = p.get("range52")                # web-side injection (S53) — absent in the raw payload
    c = st.columns(6 if r52 else 5)
    c[0].metric(f"{p['ticker']}  ·  {when}", f"${lb['close']:,.2f}", f"{chg:+.2f} ({pct:+.2f}%)")
    c[1].metric("Open", f"${lb['open']:,.2f}")
    c[2].metric("High", f"${lb['high']:,.2f}")
    c[3].metric("Low", f"${lb['low']:,.2f}")
    c[4].metric("Range", f"${rng:,.2f}", f"{rng_pct:.2f}%", delta_color="off")
    if r52:
        c[5].metric("52w range", f"{r52['pos']:.0%} of range",
                    "at 52w high" if r52["off_hi"] <= 0.001
                    else f"−{r52['off_hi']:.1%} from high", delta_color="off")
    st.caption("state characterization, NOT a prediction")


def sec_backdrop(p):
    b = p.get("backdrop")
    if not b:
        return
    _sec("MARKET BACKDROP")
    segs = [html.escape(s.strip()) for s in b.split("  |  ") if s.strip()]
    st.markdown('<div style="line-height:2.1;">' +
                " ".join(f'<span style="border:1px solid #2a2f3a;border-radius:8px;'
                         f'padding:2px 9px;margin-right:6px;color:{INK};font-size:0.9em;'
                         f'white-space:nowrap;display:inline-block;">{s}</span>' for s in segs) +
                "</div>", unsafe_allow_html=True)


def sec_multi_tf(p):
    reads, summary = p.get("reads") or {}, p.get("summary") or {}
    if not reads:
        return
    _sec("MULTI-TIMEFRAME  (longest → shortest)")

    def _hs(key, neutral, dead):
        vals = [x for x in ((reads[tf].get("_vol") or {}).get(key) for tf in reads)
                if x is not None]
        m = max((abs(x - neutral) - dead for x in vals), default=None)
        return m if (m is not None and m > 1e-12) else None

    dp_hs = _hs("price_chg_10", 0.0, HEAT_DEAD["price_chg_10"])
    dv_hs = _hs("vol_trend_10", 0.0, HEAT_DEAD["vol_trend_10"])
    rv_hs = _hs("rvol", 1.0, HEAT_DEAD["rvol"])

    rows, colors = [], []
    for tf in reads:
        r = reads[tf]
        v = r.get("_vol") or {}
        rows.append({
            "TF": f"{tf}*" if r.get("_partial") else tf,
            "Trend": _ARROW.get(r.get("trend"), "?"),
            "RSI": (f"{r['rsi']:.0f} {_OB.get(r.get('rsi_state'), r.get('rsi_state')) or '—'}"
                    if r.get("rsi") is not None else "—"),
            "Stoch": _OB.get(r.get("stoch_state"), r.get("stoch_state")) or "—",
            "MACD": r.get("macd_state") or "—",
            "RVOL": f"{v['rvol']:.1f}x" if v.get("rvol") else "—",
            "ΔPrc%": f"{v['price_chg_10']:+.1%}" if v.get("price_chg_10") is not None else "—",
            "ΔVol%": f"{v['vol_trend_10']:+.1%}" if v.get("vol_trend_10") is not None else "—",
            "VolTrend": (v.get("tag") or "—") if v.get("ok") else "—",
        })
        colors.append({
            "Trend": {"up": GREEN, "down": RED, "mixed": AMBER}.get(r.get("trend")),
            "RSI": _rsi_hex(r.get("rsi")),
            "RVOL": _heat_hex(v.get("rvol"), 1.0, rv_hs, HEAT_DEAD["rvol"]),
            "ΔPrc%": _heat_hex(v.get("price_chg_10"), 0.0, dp_hs, HEAT_DEAD["price_chg_10"]),
            "ΔVol%": _heat_hex(v.get("vol_trend_10"), 0.0, dv_hs, HEAT_DEAD["vol_trend_10"]),
        })
    df = pd.DataFrame(rows)

    def _style_row(row):
        cmap = colors[row.name]
        return [f"color: {cmap[col]}; font-weight: 600" if cmap.get(col) else ""
                for col in row.index]

    _df(df, styler=df.style.apply(_style_row, axis=1))
    if summary.get("synthesis"):
        st.markdown(f"**→ {summary['synthesis']}**")
    if summary.get("rsi_conflict"):
        st.warning(summary["rsi_conflict"])
    legend = ("RVOL = latest bar vs 20-bar avg (1.0 = normal) · ΔPrc% = price move over last "
              "10 bars · ΔVol% = 10-bar change in the 20-bar avg volume → VolTrend")
    if any(reads[tf].get("_partial") for tf in reads):
        legend += (" · * in-progress bar — RVOL/ΔVol%/VolTrend use the last completed bar "
                   "(price/RSI/ΔPrc% stay live)")
    st.caption(legend)


def sec_divergences(p):
    divs = p.get("divs")
    if not divs:
        return
    _sec("DIVERGENCES")
    lines = []
    for tf, (kind, why) in divs.items():
        c = GREEN if "bull" in str(kind).lower() else RED if "bear" in str(kind).lower() else INK
        lines.append(f'<div>• <b>{html.escape(str(tf))}</b>: '
                     f'<span style="color:{c};font-weight:600;">{html.escape(str(kind))}</span>'
                     f' — {html.escape(str(why))}</div>')
    st.markdown("".join(lines), unsafe_allow_html=True)


def sec_volume_profile(p):
    profile = p.get("profile")
    if not profile:
        return
    _sec(f"VOLUME PROFILE  ({profile.get('n_bars', '?')} bars)")
    loc_txt = {"in_value": "inside value", "above_value": "ABOVE value (extended)",
               "below_value": "BELOW value (discount)"}.get(profile.get("price_location"), "?")
    loc_col = {"in_value": GRAY, "above_value": AMBER,
               "below_value": BLUE}.get(profile.get("price_location"), GRAY)
    price, poc = profile.get("price"), profile.get("poc")
    c = st.columns(3)
    c[0].metric("POC (fair value)", f"{poc:,.2f}" if poc is not None else "—")
    c[1].metric("Value area", f"{profile['va_low']:,.2f} – {profile['va_high']:,.2f}")
    with c[2]:
        st.markdown(f'<div style="margin-top:1.6em;">{_pill(loc_txt, loc_col)}</div>',
                    unsafe_allow_html=True)
    hvns = profile.get("hvns", [])
    above = sorted([h for h in hvns if price is not None and h > price])
    below = sorted([h for h in hvns if price is not None and h <= price], reverse=True)

    def _lv(vals):
        return "  ".join(f"{x:,.2f}{' (POC)' if poc is not None and abs(x - poc) < 1e-6 else ''}"
                         for x in vals) if vals else "none"

    st.caption(f"HVN shelves — above price: {_lv(above)}  ·  below price: {_lv(below)}")
    st.caption(f"LVN gaps: {_lv(profile.get('lvns', []))}   ·   drawn on the chart via the "
               f"“vol profile” toggle above")


def sec_risk(p):
    risk = p.get("risk")
    if not risk:
        return
    _sec("RALLY vs DRAWDOWN RISK  (current conditions, not a forecast)")
    _net("NET", risk.get("net", "n/a"))
    reg = risk.get("regime")
    if reg:
        # S57 trend-regime context — the tallies below stay two-sided; this line says which
        # lens to read them through (stretch inside an intact trend = pullback timing)
        col = GREEN if reg.get("state") == "up" else RED
        st.markdown(f'{_pill(reg.get("label", ""), col)}&nbsp; <span style="color:{INK};">'
                    f'{html.escape(" · ".join(reg.get("why") or []))}</span>',
                    unsafe_allow_html=True)
        if reg.get("note"):
            st.caption(f"↳ {reg['note']}")
    c1, c2 = st.columns(2)
    with c1:
        if risk.get("drawdown"):
            st.markdown(f'<div style="color:{RED};font-weight:600;margin-top:6px;">'
                        f'drawdown-risk factors</div>', unsafe_allow_html=True)
            _bullets(risk["drawdown"], color=INK)
    with c2:
        if risk.get("rally"):
            st.markdown(f'<div style="color:{GREEN};font-weight:600;margin-top:6px;">'
                        f'rally-favorable factors</div>', unsafe_allow_html=True)
            _bullets(risk["rally"], color=INK)


def sec_setup(p):
    setup = p.get("setup")
    if not setup or not setup.get("rows"):
        return
    _sec("SETUP CHECK")
    _net("NET", setup.get("net", "n/a"))
    df = pd.DataFrame([{"": mark, "Check": label, "Detail": detail}
                       for label, mark, detail in setup["rows"]])

    def _mark_style(v):
        c = GREEN if v == "✓" else RED if v == "✗" else GRAY
        return f"color: {c}; font-weight: 700"

    _df(df, styler=df.style.map(_mark_style, subset=[""]))
    if setup.get("footer"):
        st.caption(setup["footer"])


def _gauge_table(gauges, groups=None):
    """Shared gauge renderer (OPTIONS & VOL CONTEXT + GEO): value pre-formatted via the
    gauge's own fmt, read label, ordinal percentile, and — when a gauge carries its trailing
    series (`spark`, S50) — a native sparkline column showing the shape behind the percentile
    (grinding up vs spiking reads differently; the number alone can't say which)."""
    rows = []
    for g in gauges:
        if groups is not None and g.get("group") not in groups:
            continue
        rows.append({"Group": g.get("group", ""), "Gauge": g["name"],
                     "Value": g["fmt"].format(g["value"]),
                     "Read": g.get("label") or "",
                     "Percentile": _pct_txt(g.get("pct")),
                     "1y": g.get("spark") or None})
    if not rows:
        return False
    if any(r["1y"] for r in rows):
        _df(pd.DataFrame(rows),
            **{"1y": st.column_config.LineChartColumn("1y", width="small")})
    else:
        _df(pd.DataFrame(rows).drop(columns=["1y"]))
    return True


def sec_options(p):
    ctx, liq = p.get("ctx"), p.get("liq")
    if not ctx or not ctx.get("gauges"):
        return
    _sec(f"OPTIONS & VOL CONTEXT  (regime: {ctx.get('regime', 'n/a')})")
    _gauge_table(ctx["gauges"], groups=("OPTIONS", "VOL", "MARKET"))
    if liq:
        spr = f"{liq['spread_pct']:.1%}" if liq.get("spread_pct") is not None else "n/a"
        st.caption(f"options liquidity: {liq['grade']}  (ATM spread {spr}, OI {liq['oi']:,}) "
                   f"— as of {liq['as_of_str']}{'  (stale)' if liq.get('stale') else ''}")
    _net("NET", ctx.get("net", "n/a"))


def sec_squeeze(p):
    sq = p.get("squeeze")
    if not sq:
        return
    _sec("SHORT POSITIONING / SQUEEZE  (context, not a prediction)")
    si, sv, read = sq.get("si"), sq.get("svr") or {}, sq.get("read") or {}
    c = st.columns(3)
    if si and si.get("interest"):
        chg = f"{si['chg']:+.1%} vs prior" if si.get("chg") is not None else None
        c[0].metric(f"Short interest (settled {si.get('settle_date', '?')})",
                    f"{si['interest'] / 1e6:,.1f}M sh", chg, delta_color="off")
        if si.get("dtc") is not None:
            adv = f"avg daily vol {si['adv'] / 1e6:,.1f}M" if si.get("adv") else None
            c[1].metric("Days-to-cover", f"{si['dtc']:.1f}", adv, delta_color="off")
    else:
        c[0].caption("short interest n/a — no data from the NASDAQ API or FINRA's consolidated feed")
    if sv.get("now") is not None:
        cap = f"{ordinal_percentile(sv['pct'])} of {sv['n']} sessions" if sv.get("pct") is not None else None
        c[2].metric("Short-volume (latest)", f"{sv['now']:.0%}", cap, delta_color="off")
        if sv.get("avg5") is not None and sv.get("avg20") is not None:
            st.caption(f"short-volume 5d avg {sv['avg5']:.0%} · 20d avg {sv['avg20']:.0%}")
    bz = sq.get("buzz")
    if bz:
        was = f" (was #{bz['rank_prev']})" if bz.get("rank_prev") else ""
        chg = f", {bz['chg']:+.0%} vs prior 24h" if bz.get("chg") is not None else ""
        st.markdown(f'<div style="color:{INK};">retail buzz: <b>#{bz["rank"]}</b> on reddit '
                    f'stock boards{html.escape(was)} — {bz["mentions"]} mentions'
                    f'{html.escape(chg)} (ApeWisdom)</div>', unsafe_allow_html=True)
    _net("NET", read.get("net", "n/a"))
    c1, c2 = st.columns(2)
    with c1:
        if read.get("fuel"):
            st.markdown(f'<div style="color:{GREEN};font-weight:600;">squeeze fuel</div>',
                        unsafe_allow_html=True)
            _bullets(read["fuel"])
    with c2:
        if read.get("counter"):
            st.markdown(f'<div style="color:{RED};font-weight:600;">counter</div>',
                        unsafe_allow_html=True)
            _bullets(read["counter"])
    for cav in read.get("caveats", []):
        st.caption(f"· {cav}")
    if bz:
        st.caption("· buzz = attention, not direction — crowded names gap on headlines both ways")


def sec_insider(p):
    ins = p.get("insider")
    if not ins:
        return
    rd = ins.get("read") or {}
    _sec(f"INSIDER ACTIVITY — SEC Form 4, trailing {ins.get('lookback_days', 90)}d  "
         f"(context, not a prediction)")
    usd = rd.get("net_usd")
    c = st.columns(3)
    c[0].metric("Net open-market flow", f"${usd:+,.0f}" if usd else "$0",
                delta_color="off")
    c[1].metric("Buys / sells", f"{rd.get('n_buys', 0)} / {rd.get('n_sells', 0)}")
    c[2].metric("Distinct insiders", f"{rd.get('n_owners', 0)}")
    lb = rd.get("latest_buy")
    if lb:
        px = f" @ {lb['price']:,.2f}" if lb.get("price") else ""
        usd_b = f"  (${lb['usd']:,.0f})" if lb.get("usd") else ""
        st.caption(f"latest buy — {lb['date']}  {lb['owner']} ({lb['role']})  "
                   f"{lb['shares']:,.0f} sh{px}{usd_b}")
    _net("NET", rd.get("net", "n/a"))
    _bullets(rd.get("positive"), color=GREEN)
    _bullets(rd.get("flags"), color=AMBER, marker="⚑")
    for cav in rd.get("caveats", []):
        st.caption(f"· {cav}")


def sec_pcoi(p):
    pc = p.get("pcoi")
    if not pc or not pc.get("rows"):
        return
    hdr = f"PUT/CALL OI — live Tradier chain, by expiry  ({pc.get('scope', '')})"
    if pc.get("as_of_str"):
        hdr += f" · as of {pc['as_of_str']}" + ("  (stale)" if pc.get("stale") else "")
    _sec(hdr)
    rows = pc["rows"]
    if any(r.get("call_oi") is not None or r.get("put_oi") is not None for r in rows):
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            x = [f"{r['expiry']}{' *' if LEAPS_MIN_DTE <= r['dte'] <= LEAPS_MAX_DTE else ''}"
                 for r in rows]
            has_vol = any(r.get("call_vol") is not None or r.get("put_vol") is not None
                          for r in rows)
            fig = make_subplots(rows=2 if has_vol else 1, cols=1, shared_xaxes=True,
                                vertical_spacing=0.07,
                                row_heights=[0.62, 0.38] if has_vol else None)
            fig.add_trace(go.Bar(x=x, y=[r.get("call_oi") for r in rows], name="Call OI",
                                 marker_color=GREEN, marker_line_width=0), row=1, col=1)
            fig.add_trace(go.Bar(x=x, y=[r.get("put_oi") for r in rows], name="Put OI",
                                 marker_color=RED, marker_line_width=0), row=1, col=1)
            if has_vol:
                # latest-session FLOW beneath the POSITIONING pane — same green/red but
                # translucent (the price chart's volume-pane convention) so the two panes
                # aren't misread as one scale
                fig.add_trace(go.Bar(x=x, y=[r.get("call_vol") for r in rows], name="Call Vol",
                                     marker_color="rgba(94,196,94,0.55)", marker_line_width=0),
                              row=2, col=1)
                fig.add_trace(go.Bar(x=x, y=[r.get("put_vol") for r in rows], name="Put Vol",
                                     marker_color="rgba(216,60,52,0.55)", marker_line_width=0),
                              row=2, col=1)
                fig.update_yaxes(title_text="volume", title_font_size=11, row=2, col=1)
            fig.update_yaxes(title_text="open interest", title_font_size=11, row=1, col=1)
            fig.update_layout(barmode="group", bargroupgap=0.08,
                              height=390 if has_vol else 280,
                              margin=dict(l=10, r=10, t=10, b=10), template="plotly_dark",
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(14,17,23,1)",
                              legend=dict(orientation="h", y=1.08, x=0, font=dict(size=11)))
            st.plotly_chart(fig, width="stretch")
        except Exception:
            pass

    # OI-by-strike walls (S50): per-strike OI captured by pc_by_expiry (spot ±20%), summed
    # across the fetched scope — where the heavy positioning sits relative to spot. Old caches
    # predate the capture (no by_strike key) → caption instead of a chart.
    strikes = {}
    for r in rows:
        for k, c_oi, p_oi in (r.get("by_strike") or []):
            agg = strikes.setdefault(float(k), [0.0, 0.0])
            agg[0] += c_oi
            agg[1] += p_oi
    if strikes:
        try:
            import plotly.graph_objects as go
            spot = pc.get("price")
            ks = sorted(strikes)
            if spot and len(ks) > 40:                       # densest names: 40 strikes nearest spot
                ks = sorted(sorted(ks, key=lambda k: abs(k - spot))[:40])
            calls = [strikes[k][0] for k in ks]
            puts = [-strikes[k][1] for k in ks]             # negative x → diverging left
            fig = go.Figure()
            fig.add_trace(go.Bar(y=ks, x=calls, orientation="h", name="Call OI",
                                 marker_color=GREEN, marker_line_width=0,
                                 hovertemplate="%{y}: %{x:,.0f} calls<extra></extra>"))
            fig.add_trace(go.Bar(y=ks, x=puts, orientation="h", name="Put OI",
                                 marker_color=RED, marker_line_width=0,
                                 customdata=[abs(v) for v in puts],
                                 hovertemplate="%{y}: %{customdata:,.0f} puts<extra></extra>"))
            if spot:
                fig.add_hline(y=spot, line_dash="dot", line_width=1, line_color="#e8c547",
                              annotation=dict(text=f"spot {spot:,.2f}", x=1.0, xanchor="left",
                                              font=dict(color="#e8c547", size=10),
                                              showarrow=False))
            wall_c = ks[calls.index(max(calls))]
            wall_p = ks[puts.index(min(puts))]
            for w, lbl, col in ((wall_c, "call wall", GREEN), (wall_p, "put wall", RED)):
                fig.add_annotation(y=w, x=0, text=f"{lbl} {w:g}", showarrow=False,
                                   xanchor="center", font=dict(color=col, size=10),
                                   bgcolor="rgba(14,17,23,0.75)")
            fig.update_layout(barmode="relative", bargap=0.15,
                              height=max(300, 11 * len(ks)),
                              margin=dict(l=10, r=64, t=10, b=10), template="plotly_dark",
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(14,17,23,1)",
                              legend=dict(orientation="h", y=1.04, x=0, font=dict(size=11)),
                              xaxis=dict(showticklabels=False,
                                         title=dict(text="← puts   ·   calls →",
                                                    font=dict(size=11))),
                              yaxis=dict(title=dict(text="strike", font=dict(size=11))))
            st.plotly_chart(fig, width="stretch")
            st.caption(f"open interest by strike (±20% of spot), summed across the "
                       f"{len(rows)} fetched expiries — walls mark the heaviest strikes")
        except Exception:
            pass
    else:
        st.caption("strike-level OI appears after the next chain refresh "
                   "(tick live, or Run after a market close)")

    tbl = [{"Expiry": r["expiry"], "DTE": r["dte"],
            "P/C OI": f"{r['pc']:.2f}" if r.get("pc") is not None else "n/a",
            "P/C Vol": f"{r['pc_vol']:.2f}" if r.get("pc_vol") is not None else "n/a",
            "Positioning": pc_label(r.get("pc")) +
                           (" *" if LEAPS_MIN_DTE <= r["dte"] <= LEAPS_MAX_DTE else "")}
           for r in rows]
    if len(rows) > 1 and pc.get("total"):
        t = pc["total"]
        tbl.append({"Expiry": "TOTAL", "DTE": None,
                    "P/C OI": f"{t['pc']:.2f}" if t.get("pc") is not None else "n/a",
                    "P/C Vol": f"{t['pc_vol']:.2f}" if t.get("pc_vol") is not None else "n/a",
                    "Positioning": pc_label(t.get("pc"))})
    _df(pd.DataFrame(tbl))
    st.caption("P/C OI = put OI / call OI (positioning) · P/C Vol = latest-session flow "
               "(lower pane) · * = LEAPS tenor")


def _gexfmt(v, sign=True):
    """Compact dollar-gamma formatter (mirrors print_report's local _gexfmt)."""
    s = "+" if (sign and v >= 0) else ("-" if v < 0 else "")
    a = abs(v)
    if a >= 1e9:
        return f"{s}${a / 1e9:.2f}bn"
    if a >= 1e6:
        return f"{s}${a / 1e6:.0f}m"
    return f"{s}${a / 1e3:.0f}k"


def sec_gex(p):
    g = p.get("gex")
    if not g or not g.get("by_strike"):
        return
    hdr = (f"GAMMA EXPOSURE — dealer positioning, Tradier chain  "
           f"(≤{max(e['dte'] for e in g['expiries'])}d, {len(g['expiries'])} expiries)")
    if g.get("as_of_str"):
        hdr += f" · as of {g['as_of_str']}" + ("  (stale)" if g.get("stale") else "")
    _sec(hdr)
    regime = ("dealers long gamma — stabilizing (sell rallies, buy dips)" if g["net_gex"] > 0
              else "dealers short gamma — amplifying (buy rallies, sell dips)")
    _net(f"net GEX {_gexfmt(g['net_gex'])}/1%", regime)

    chips = []
    if g.get("call_wall") is not None:
        chips.append((f"call wall {g['call_wall']:g}  ({_gexfmt(g['call_wall_gex'], sign=False)})",
                      GREEN))
    if g.get("put_wall") is not None:
        chips.append((f"put wall {g['put_wall']:g}  ({_gexfmt(abs(g['put_wall_gex']), sign=False)})",
                      RED))
    if g.get("zero_gamma") is not None:
        side = "below" if g["zero_gamma"] < g.get("spot", 0) else "above"
        chips.append((f"zero-gamma ~{g['zero_gamma']:.2f} ({side} spot)", GOLD))
    mp = g.get("max_pain")
    if mp:
        chips.append((f"max pain {mp['strike']:g} ({mp['expiry']}, {mp['dte']}d)", GRAY))
    if chips:
        st.markdown('<div style="line-height:2.3;margin:4px 0;">'
                    + " ".join(_pill(t, c) for t, c in chips) + "</div>",
                    unsafe_allow_html=True)

    # diverging per-strike bars: calls up (green), puts down (red) — the wall geometry
    try:
        import plotly.graph_objects as go
        rows = g["by_strike"]
        if rows:
            x = [r["strike"] for r in rows]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=x, y=[r["call"] for r in rows], name="call GEX",
                                 marker_color=GREEN, marker_line_width=0))
            fig.add_trace(go.Bar(x=x, y=[r["put"] for r in rows], name="put GEX (dealer-short)",
                                 marker_color=RED, marker_line_width=0))
            if g.get("spot"):
                fig.add_vline(x=g["spot"], line_dash="dot", line_width=1, line_color="#e8c547",
                              annotation=dict(text="spot", font=dict(color="#e8c547", size=10)))
            if g.get("zero_gamma") is not None:
                fig.add_vline(x=g["zero_gamma"], line_dash="dash", line_width=1,
                              line_color=GOLD,
                              annotation=dict(text="zero-γ", font=dict(color=GOLD, size=10),
                                              yanchor="bottom", y=0))
            fig.add_hline(y=0, line_width=0.8, line_color="#4a5160")
            fig.update_layout(barmode="relative", height=280,
                              margin=dict(l=10, r=10, t=10, b=10), template="plotly_dark",
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(14,17,23,1)",
                              yaxis=dict(title="dealer $Γ / 1% move", title_font_size=11),
                              legend=dict(orientation="h", y=1.08, x=0, font=dict(size=11)))
            st.plotly_chart(fig, width="stretch")
    except Exception:
        pass

    if g.get("unusual"):
        tbl = [{"Strike": f"{u['strike']:g}{u['type'][0]}", "Expiry": u["expiry"],
                "DTE": u["dte"], "Volume": f"{u['volume']:,}",
                "OI": f"{u['oi']:,}" if u["oi"] else "0",
                "Vol/OI": f"×{u['ratio']:.1f}" if u["ratio"] is not None else "NEW"}
               for u in g["unusual"]]
        st.markdown(f'<div style="color:{INK};margin-top:2px;">unusual activity today '
                    f'(volume running a multiple of OI):</div>', unsafe_allow_html=True)
        _df(pd.DataFrame(tbl))
    st.caption("assumes dealers long calls / short puts (standard convention) — real inventory "
               "unknown · OI settles once daily (start-of-day); intraday flow shifts walls "
               "first · levels also drawable on the price chart (“GEX levels” toggle)")


def _quote_caveats(cb):
    """at-ask / no-bid honesty lines shared by straddle+strangle rows (mirrors print_report)."""
    out = []
    if cb.get("no_bid"):
        out.append("⚠ a leg has no bid — the mid cost is indicative, not executable")
    ca = cb.get("cost_ask")
    if ca and ca > cb["cost"] * 1.03:
        out.append(f"at ask: ${ca:.2f}/sh → BE {cb['lo_ask']:.2f} / {cb['hi_ask']:.2f}  "
                   f"(need −{cb['dn_move_ask']:.1%} / +{cb['up_move_ask']:.1%})")
    lg = cb.get("legs")
    if lg:
        def one(o, cp):
            oi = f"{int(o['oi']):,}" if o.get("oi") is not None else "—"
            return f"{o['strike']:g}{cp} OI {oi} bid/ask {o['bid']:.2f}/{o['ask']:.2f}"
        out.append(f"legs: {one(lg['put'], 'p')}  ·  {one(lg['call'], 'c')}")
    return out


def sec_vol(p):
    vol = p.get("vol")
    if not vol or not vol.get("setup"):
        return
    s, em, eg, sq = vol["setup"], vol.get("em"), vol.get("earnings"), vol.get("squeeze") or {}
    _sec("VOLATILITY SETUP — straddle/strangle context  (not a prediction)")
    on = [tf for tf in ("1M", "1W", "1D", "4h", "1h") if sq.get(tf, {}).get("squeeze_on")]
    st.markdown("compression: " +
                (" ".join(_pill(f"squeeze ON {tf}", AMBER) for tf in on) if on
                 else _pill("no active squeeze", GRAY)), unsafe_allow_html=True)
    if em:
        c = st.columns(4)
        c[0].metric(f"Expected move (~{em['dte']}d)", f"±{em['pct']:.1%}",
                    f"±${em['dollars']:.2f}", delta_color="off")
        c[1].metric("Lower BE band", f"{em['lo']:,.2f}")
        c[2].metric("Upper BE band", f"{em['hi']:,.2f}")
        if em.get("hv_pct"):
            c[3].metric("Realized (HV)", f"±{em['hv_pct']:.1%}", delta_color="off")
    if eg and eg.get("date"):
        hm = f", typ. ±{eg['hist_move']:.1%}" if eg.get("hist_move") else ""
        st.caption(f"earnings: {eg['date']} ({eg['days']}d{hm})")
    hist = vol.get("history")
    if hist and hist.get("status") == "ok":
        st.caption(f"history ({hist['usable']} earnings): {hist['summary']}")
    elif hist and hist.get("status") == "insufficient_iv":
        st.caption(f"history: IV history thin — accumulates via the daily harvest; "
                   f"`backfill_iv.py` can restore liquid names ({hist['ticker']})")
    _net("NET", s.get("net", "n/a"))
    for n in s.get("notes", []):
        st.caption(f"· {n}")
    c1, c2 = st.columns(2)
    with c1:
        if s.get("long_vol"):
            st.markdown(f'<div style="color:{GREEN};font-weight:600;">favors BUYING vol</div>',
                        unsafe_allow_html=True)
            _bullets(s["long_vol"])
    with c2:
        if s.get("short_vol"):
            st.markdown(f'<div style="color:{RED};font-weight:600;">favors SELLING premium</div>',
                        unsafe_allow_html=True)
            _bullets(s["short_vol"])
    if s.get("hint"):
        st.caption(s["hint"])
    q = vol.get("quote")
    if q and q.get("quotes"):
        st.markdown(f"**live quote** — spot {q['spot']:.2f}, as of {q['as_of_str']}"
                    f"{'  (stale)' if q.get('stale') else ''}")
        for note in q.get("notes", []):
            st.caption(f"· {note}")
        for blk in q["quotes"]:
            kind = blk.get("expiry_kind", "")
            dae = blk.get("days_after_earn")
            after = f"; {dae}d after earnings" if dae is not None else ""
            st.markdown(f"exp **{blk['expiry']}** ({kind + ', ' if kind else ''}"
                        f"{blk['dte']}d{after})")
            rows, caveats = [], []
            stq, sg = blk.get("straddle"), blk.get("strangle")
            if stq:
                rows.append({"Vehicle": f"ATM straddle {stq['call_strike']:g}",
                             "Cost $/sh": f"{stq['cost']:.2f}",
                             "BE low": f"{stq['lo']:.2f}", "BE high": f"{stq['hi']:.2f}",
                             "Need": f"−{stq['dn_move']:.1%} / +{stq['up_move']:.1%}"})
                caveats += _quote_caveats(stq)
            if sg:
                dnw, upw, tw = sg.get("dn_width"), sg.get("up_width"), sg.get("target_width")
                if dnw is not None and upw is not None:
                    off = tw is not None and (abs(dnw - tw) >= 0.01 or abs(upw - tw) >= 0.01)
                    wing = f"−{dnw:.1%} / +{upw:.1%}" + (f", target ±{tw:.0%}" if off else "")
                else:
                    wing = f"≈±{sg['width']:.0%}"
                rows.append({"Vehicle": f"strangle ({wing}) {sg['put_strike']:g}p/{sg['call_strike']:g}c",
                             "Cost $/sh": f"{sg['cost']:.2f}",
                             "BE low": f"{sg['lo']:.2f}", "BE high": f"{sg['hi']:.2f}",
                             "Need": f"−{sg['dn_move']:.1%} / +{sg['up_move']:.1%}"})
                caveats += _quote_caveats(sg)
            if rows:
                _df(pd.DataFrame(rows))
            for cav in caveats:
                st.caption(cav)
        st.caption("vega: straddle = max vega (enter close to the print) · strangle = cheaper + "
                   "lower theta (enter earlier / run more names / vega convexity)")


def sec_call(p):
    cq, ctx = p.get("callq"), p.get("ctx")
    if not cq or not cq.get("quotes"):
        return
    _sec("LONG CALL VIABILITY  (context, not advice)")
    st.caption(f"spot {cq['spot']:.2f}, as of {cq['as_of_str']}"
               f"{'  (stale)' if cq.get('stale') else ''}")
    cliq = cq.get("liquidity")
    if cliq:
        spr = f"{cliq['spread_pct']:.1%}" if cliq.get("spread_pct") is not None else "n/a"
        st.caption(f"chain liquidity: {cliq['grade'].upper()}  (ATM-region spread {spr}, "
                   f"OI {cliq['oi']:,}, day vol {cliq['volume']:,})")
    rows, ask_lines = [], []
    for blk in cq["quotes"]:
        mon = "monthly, " if blk.get("monthly") else ""
        exp = f"{blk['expiry']} ({mon}{blk['dte']}d)"
        for kind in ("atm", "otm"):
            cnd = blk.get(kind)
            if not cnd:
                continue
            rows.append({
                "Expiry": exp, "Type": kind.upper(), "Strike": f"{cnd['strike']:g}c",
                "Δ": f"{cnd['delta']:.2f}" if cnd.get("delta") is not None else "—",
                "Mid $/sh": f"{cnd['mid']:.2f}",
                "BE": f"{cnd['be']:.2f} ({cnd['be_move']:+.1%})",
                "Theta/day": f"{cnd['theta_pct']:.1%}" if cnd.get("theta_pct") else "n/a",
                "OI": f"{int(cnd['oi']):,}" if cnd.get("oi") is not None else "—",
                "Spread": f"{cnd['spread_pct']:.1%}" if cnd.get("spread_pct") is not None else "n/a",
            })
            if cnd.get("be_ask") is not None:
                ask_lines.append(f"{exp} {kind.upper()} at ask ${cnd['ask']:.2f} → "
                                 f"BE {cnd['be_ask']:.2f} ({cnd['be_move_ask']:+.1%})")
    if rows:
        _df(pd.DataFrame(rows))
    for ln in ask_lines:
        st.caption(f"· {ln}")
    for blk in cq["quotes"]:
        for n in blk.get("notes", []):
            st.caption(f"· {blk['expiry']}: {n}")
    curve = cq.get("curve")
    if curve and curve.get("points"):
        try:
            import plotly.graph_objects as go
            pts = curve["points"]
            fig = go.Figure(go.Scatter(x=[pt["label"] for pt in pts],
                                       y=[pt["iv"] * 100 for pt in pts],
                                       mode="lines+markers", line=dict(color=BLUE, width=2),
                                       marker=dict(size=8, color=BLUE)))
            fig.update_layout(height=220, margin=dict(l=10, r=10, t=24, b=10),
                              template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                              plot_bgcolor="rgba(14,17,23,1)", yaxis_title="ATM IV %",
                              title=dict(text=f"IV by expiry — {curve.get('tag', '')}",
                                         font=dict(size=13)))
            st.plotly_chart(fig, width="stretch")
        except Exception:
            st.caption("IV by expiry: " +
                       " · ".join(f"{pt['label']} {pt['iv']:.1%}" for pt in curve["points"]) +
                       f" — {curve.get('tag', '')}")
    ivp = None
    for g in (ctx or {}).get("gauges", []):
        if g.get("name") == "ATM IV (30d)":
            ivp = g.get("pct")
            break
    if ivp is not None and ivp >= 0.70:
        st.warning(f"ATM IV (30d) at the {ordinal_percentile(ivp)} of its history — paying up "
                   f"for a direction bet; debit spreads cut the vega/theta bill")
    st.caption("guide: more DTE = slower theta · 0.35–0.40Δ in trends, lower Δ in chop · "
               "BE move must be plausible within the tenor")


def sec_geo(p):
    geo = p.get("geo")
    if not geo or not geo.get("gauges"):
        return
    _sec("GEOPOLITICAL / CROSS-ASSET BACKDROP  (context, not a prediction)")
    _gauge_table(geo["gauges"])
    _net("NET", geo.get("composite", "n/a"))
    for n in geo.get("notes", []):
        st.caption(f"· {n}")


def sec_catalysts(p):
    cats = p.get("cats")
    if not cats:
        return
    _sec("KNOWN CATALYSTS (catalysts.csv)")
    _df(pd.DataFrame([{"Date": d, "Days": days, "Type": typ, "Description": desc}
                      for d, days, typ, desc in cats]))


def sec_macro(p):
    ev = p.get("macro_events")
    if not ev:
        return
    soon = [(name, d, days) for name, (d, days) in ev.items()
            if d is not None and days is not None and days <= 10]
    if not soon:
        return
    _sec("MACRO (next 10d)")
    _df(pd.DataFrame([{"Release": n, "Date": str(d)[:10], "Days": days}
                      for n, d, days in sorted(soon, key=lambda x: x[2])]))


def sec_thesis(p):
    thesis, risk = p.get("thesis"), p.get("risk") or {}
    if not thesis:
        return
    level = p.get("level")
    _sec(f"THESIS CHECK — you are {thesis.upper()}" + (f" (level {level})" if level else ""))
    confirm = risk.get("rally") if thesis == "bullish" else risk.get("drawdown")
    contra = risk.get("drawdown") if thesis == "bullish" else risk.get("rally")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f'<div style="color:{GREEN};font-weight:600;">'
                    f'CONFIRMATIONS ({len(confirm or [])})</div>', unsafe_allow_html=True)
        _bullets(confirm or ["— none"], marker="✓")
    with c2:
        st.markdown(f'<div style="color:{RED};font-weight:600;">'
                    f'CONTRADICTIONS ({len(contra or [])})</div>', unsafe_allow_html=True)
        _bullets(contra or ["— none"], marker="✗")
    summary, reads = p.get("summary") or {}, p.get("reads") or {}
    blind = []
    if summary.get("conflict"):
        blind.append(summary["conflict"])
    for tf in reads:
        v = reads[tf].get("_vol")
        if v and v.get("unconfirmed"):
            blind.append(f"{tf} move is on falling volume (unconfirmed)")
    for b in blind:
        st.warning(f"blind spot: {b}")


def sec_notes(p):
    for n in p.get("notes") or []:
        st.caption(f"note: {n}")


_SECTIONS = [sec_header, sec_backdrop, sec_multi_tf, sec_divergences, sec_volume_profile,
             sec_risk, sec_setup, sec_options, sec_squeeze, sec_insider, sec_pcoi, sec_gex,
             sec_vol, sec_call, sec_geo, sec_catalysts, sec_macro, sec_thesis, sec_notes]


def render_all(p, skip_header=False):
    """Render every section from the payload (print_report order). A failing section shows a
    warning instead of killing the page — the ANSI expander below is the lossless fallback.
    `skip_header` drops sec_header — live mode renders the tiles inside the chart fragment
    instead, off each fresh Tradier tick."""
    for fn in _SECTIONS:
        if skip_header and fn is sec_header:
            continue
        try:
            fn(p)
        except Exception as e:
            st.warning(f"{fn.__name__} failed to render ({type(e).__name__}: {e}) — "
                       f"see the full text report below")
