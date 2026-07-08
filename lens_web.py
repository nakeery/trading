"""
lens_web — the Lens as a local web page (S48).

    .\\trade\\Scripts\\python.exe -m streamlit run lens_web.py

A browser window with a ticker search bar over the SAME lens engine the CLI uses
(`lens.render_ticker`, extracted S48): flag checkboxes replace the CLI switches, the report's
terminal colors are preserved via ANSI→HTML, and the sixel candle panel is superseded by a real
interactive Plotly candlestick (hover OHLC, zoom) — a browser shows true images, so sixel is
unnecessary here. The terminal CLI is untouched.

Notes: cache-refresh prompts are non-interactive in server mode (session-stale caches are reused;
tick "live" to force-refresh quotes). Report generation is cached ~2 min per (ticker, flags) so
widget interactions don't refetch — the module-level JSON caches still dedupe the network.
"""

import contextlib
import io
import os
import time
from types import SimpleNamespace

import pandas as pd
import streamlit as st
from ansi2html import Ansi2HTMLConverter

import lens
from modules.timeframes import _load_daily, fetch_live_bar, append_live_bar
from modules.volume_profile import volume_profile

DATA_DIR = "data"
CHART_BARS = 120
CHART_WARMUP = 200  # extra bars loaded BEFORE the display window so MA200/BB are warm at its left edge
DEBOUNCE_S = 2.0    # settle time after a checkbox/argument change before regenerating — rapid
                    # clicks batch into ONE run instead of one fetch per click (Run bypasses it)
LIVE_CHART_EVERY_S = 10   # live-mode chart refresh cadence (one Tradier quote per tick; the
                          # chart redraws in a st.fragment — the report below is NOT re-fetched)

st.set_page_config(page_title="LENS", page_icon="🔭", layout="wide")


def known_tickers(data_dir=DATA_DIR):
    try:
        return sorted(f[:-len("_indicators.csv")].upper()
                      for f in os.listdir(data_dir) if f.endswith("_indicators.csv"))
    except Exception:
        return []


def make_args(flags):
    """argparse-shaped namespace for lens.render_ticker — candle 'none' (Plotly replaces it)."""
    return SimpleNamespace(
        ticker=None, thesis=flags.get("thesis"), level=flags.get("level"),
        no_intraday=False, no_vix=False, geo=flags["geo"], no_color=False,
        candle="none", candle_px=128, prev=10, data_dir=DATA_DIR,
        no_refresh=False, refresh=False,
        pc_oi=([] if flags["pc_oi"] == "all" else [flags["pc_oi"]]) if flags["pc_oi"] != "off" else None,
        insider=flags["insider"], squeeze=flags["squeeze"], live=flags["live"],
        vol=flags["vol"], call=flags["call"],
    )


@st.cache_data(ttl=120, show_spinner=False)
def generate_report(ticker, flags_key):
    """Captured ANSI report for one ticker. `flags_key` is a hashable dict-as-tuple so the cache
    keys on the exact flag combination; `live` runs bypass this via a unique key upstream."""
    flags = dict(flags_key)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        lens.render_ticker(ticker, make_args(flags), use_color=True, interactive=False,
                           backdrop_base=lens.build_backdrop(DATA_DIR))
    return buf.getvalue()


@st.cache_data(ttl=600, show_spinner=False)
def load_daily_tail(ticker, bars=CHART_BARS, warmup=CHART_WARMUP):
    """Cached daily-bar tail for the chart (display window + indicator warm-up) — keeps the
    yfinance-fallback path (no CSV) from re-downloading full history on every live tick."""
    return _load_daily(ticker, DATA_DIR).tail(bars + warmup)


VP_ASPECTS = ["value area", "POC", "HVN", "LVN", "histogram"]


@st.cache_data(ttl=600, show_spinner=False)
def load_profile(ticker):
    """Volume profile over the last ~1y of DAILY bars (the lens' daily-fallback convention;
    the report's own profile may use finer 1h bars over ~6mo, so levels can differ slightly)."""
    try:
        return volume_profile(load_daily_tail(ticker), lookback=252, with_hist=True)
    except Exception:
        return None


def _candle_fig(df, overlays=(), show_volume=False, price_line=None, vprofile=None):
    """Plotly candlestick from a daily OHLCV frame + optional indicator overlays
    [(name, series, color, dash), …], a volume sub-pane, a dotted last/live price line, and
    volume-profile aspects (`vprofile` = profile dict + an "aspects" set: value area band, POC
    line, HVN/LVN levels, right-edge volume-at-price histogram). Returns None when it can't
    build."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        if df is None or len(df) < 2:
            return None
        rows = 2 if show_volume else 1
        fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                            row_heights=[0.76, 0.24] if show_volume else None)
        # TradingView hollow-candle convention (matches the lens' terminal candles): COLOR =
        # close vs PRIOR close (green up / red down), FILL = close vs THIS bar's open (hollow
        # when close ≥ open, solid otherwise). Plotly's single trace can only key on close-vs-
        # open, so the bars are split into four style groups — within each group the close-vs-
        # open state is uniform, so setting both increasing/decreasing styles is safe.
        GREEN, RED, HOLLOW = "#5ec45e", "#d83c34", "rgba(0,0,0,0)"
        pc = df["Close"].shift(1).fillna(df["Open"])
        up = df["Close"] >= pc
        hollow = df["Close"] >= df["Open"]
        for mask, color, fill in ((up & hollow, GREEN, HOLLOW), (up & ~hollow, GREEN, GREEN),
                                  (~up & hollow, RED, HOLLOW), (~up & ~hollow, RED, RED)):
            sub = df[mask]
            if not len(sub):
                continue
            fig.add_trace(go.Candlestick(
                x=sub.index, open=sub["Open"], high=sub["High"], low=sub["Low"],
                close=sub["Close"],
                increasing=dict(line=dict(color=color, width=1.2), fillcolor=fill),
                decreasing=dict(line=dict(color=color, width=1.2), fillcolor=fill),
                showlegend=False), row=1, col=1)
        for name, series, color, dash in overlays:
            fig.add_trace(go.Scatter(x=series.index, y=series, name=name, mode="lines",
                                     line=dict(color=color, width=1.2, dash=dash)), row=1, col=1)
        if show_volume:
            up = (df["Close"] >= df["Close"].shift(1)).fillna(True)
            colors = ["rgba(94,196,94,0.55)" if u else "rgba(216,60,52,0.55)" for u in up]
            fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=colors,
                                 showlegend=False, name="volume"), row=2, col=1)
        if vprofile:
            a = vprofile.get("aspects") or set()
            ann = dict(x=0.0, xanchor="left", showarrow=False)     # inside-left level tags
            if "value area" in a:
                fig.add_hrect(y0=vprofile["va_low"], y1=vprofile["va_high"],
                              fillcolor="rgba(94,140,200,0.10)", line_width=0, row=1, col=1)
            if "POC" in a:
                fig.add_hline(y=vprofile["poc"], line_width=1.2, line_color="#e0a63a",
                              row=1, col=1,
                              annotation=dict(text=f"POC {vprofile['poc']:,.2f}",
                                              font=dict(color="#e0a63a", size=10), **ann))
            if "HVN" in a:
                for h in vprofile.get("hvns", []):
                    if abs(h - vprofile["poc"]) < 1e-6:
                        continue                                   # POC is itself an HVN
                    fig.add_hline(y=h, line_dash="dash", line_width=1, line_color="#9fb4d0",
                                  row=1, col=1,
                                  annotation=dict(text=f"HVN {h:,.2f}",
                                                  font=dict(color="#9fb4d0", size=9), **ann))
            if "LVN" in a:
                for l in vprofile.get("lvns", []):
                    fig.add_hline(y=l, line_dash="dot", line_width=1, line_color="#6a7686",
                                  row=1, col=1,
                                  annotation=dict(text=f"LVN {l:,.2f}",
                                                  font=dict(color="#6a7686", size=9), **ann))
            if "histogram" in a and vprofile.get("hist_volumes"):
                vols = vprofile["hist_volumes"]
                # right-edge volume-at-price bars on an overlaying, reversed x-axis: value 0 sits
                # at the RIGHT edge and bars extend left, occupying ~28% of the plot width
                fig.add_trace(go.Bar(x=vols, y=vprofile["hist_centers"], orientation="h",
                                     marker_color="rgba(150,170,200,0.20)",
                                     marker_line_width=0, showlegend=False, hoverinfo="skip",
                                     xaxis="x3", yaxis="y"))
                fig.update_layout(xaxis3=dict(overlaying="x", range=[max(vols) * 3.5, 0],
                                              showgrid=False, showticklabels=False,
                                              visible=False))
        if price_line is not None:
            # price-tag style: label anchored LEFT at the plot's right edge, extending into the
            # widened right margin — never clipped by the plot area
            # NB: no explicit xref here — add_hline appends " domain" to the annotation xref
            # itself; setting it manually produced "x domain domain" and a ValueError
            fig.add_hline(y=price_line, line_dash="dot", line_width=1, line_color="#e8c547",
                          row=1, col=1,
                          annotation=dict(text=f"{price_line:,.2f}", x=1.0, xanchor="left",
                                          font=dict(color="#e8c547", size=12), showarrow=False))
        fig.update_layout(height=440 if show_volume else 360,
                          margin=dict(l=10, r=64, t=26, b=10),
                          xaxis_rangeslider_visible=False, template="plotly_dark",
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(14,17,23,1)",
                          legend=dict(orientation="h", y=1.05, x=0, font=dict(size=11)))
        return fig
    except Exception:
        return None


def draw_chart(ticker, live=False):
    """Chart section. In live mode the latest Tradier quote becomes a provisional today-bar
    (same fetch_live_bar/append_live_bar machinery as the CLI --live; display-only) with a
    LIVE price/timestamp caption — this function runs inside a st.fragment on a timer, and the
    live price line rides each tick. Indicator checkboxes are DISPLAY-ONLY: they rerun just this
    section (fragment scope), never the report or its debounce."""
    df = load_daily_tail(ticker).copy()
    live_last = None
    if live:
        bar = None
        try:
            bar = fetch_live_bar(ticker)
        except Exception:
            pass
        if bar:
            df, _ = append_live_bar(df, bar)
            live_last = float(bar["Close"])
            prev = float(df["Close"].iloc[-2]) if len(df) > 1 else live_last
            chg = (live_last / prev - 1) if prev else 0.0
            now_et = pd.Timestamp.now(tz="America/New_York").strftime("%H:%M:%S")
            state = "session in progress" if bar.get("in_progress") else "session closed"
            st.caption(f"🔴 LIVE {now_et} ET — {ticker} ${live_last:,.2f} ({chg:+.2%} vs prior "
                       f"close) · {state} · chart updates every {LIVE_CHART_EVERY_S}s")
        else:
            st.caption("live: no Tradier session data right now (market closed / no token?) — "
                       "showing last close")

    oc = st.columns(8)
    ma20 = oc[0].checkbox("MA20", value=True, key="ov_ma20")
    ma50 = oc[1].checkbox("MA50", value=True, key="ov_ma50")
    ma200 = oc[2].checkbox("MA200", key="ov_ma200")
    ema9 = oc[3].checkbox("EMA9", key="ov_ema9")
    bb = oc[4].checkbox("BB(20,2σ)", key="ov_bb")
    vol_pane = oc[5].checkbox("volume", value=True, key="ov_volume")
    pline = oc[6].checkbox("price line", value=True, key="ov_pline")
    vp_on = oc[7].checkbox("vol profile", key="ov_vp")

    vprofile = None
    if vp_on:
        aspects = st.pills("profile aspects", VP_ASPECTS, selection_mode="multi",
                           default=VP_ASPECTS, key="ov_vp_aspects")
        prof = load_profile(ticker)
        if prof:
            vprofile = dict(prof)
            vprofile["aspects"] = set(aspects or [])
            st.caption(f"profile: daily bars, ~1y · POC {prof['poc']:,.2f} · value area "
                       f"{prof['va_low']:,.2f}–{prof['va_high']:,.2f} (the report's profile may "
                       f"use finer 1h bars over ~6mo — levels can differ slightly)")
        else:
            st.caption("volume profile unavailable for this ticker")

    # overlays computed on the warm-up-extended frame, then sliced to the display window so
    # MA200/BB are fully formed at the left edge (matches the CSV's indicator conventions)
    close = df["Close"]
    ov = []
    if ma20:
        ov.append(("MA20", close.rolling(20).mean(), "#d6ba2e", "solid"))
    if ma50:
        ov.append(("MA50", close.rolling(50).mean(), "#4ea3d8", "solid"))
    if ma200:
        ov.append(("MA200", close.rolling(200).mean(), "#b070d0", "solid"))
    if ema9:
        ov.append(("EMA9", close.ewm(span=9, adjust=False).mean(), "#cfcfcf", "dot"))
    if bb:
        m, s = close.rolling(20).mean(), close.rolling(20).std()
        ov.append(("BB upper", m + 2 * s, "#7f8ea3", "dash"))
        ov.append(("BB lower", m - 2 * s, "#7f8ea3", "dash"))

    view = df.tail(CHART_BARS)
    price = live_last if live_last is not None else float(view["Close"].iloc[-1])
    fig = _candle_fig(view, overlays=[(n, s.tail(CHART_BARS), c, d) for n, s, c, d in ov],
                      show_volume=vol_pane, price_line=price if pline else None,
                      vprofile=vprofile)
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True, key=f"chart_{ticker}")


# ── controls ─────────────────────────────────────────────────────────────────
st.markdown("### 🔭 LENS — multi-timeframe market-structure & risk")
known = known_tickers()
c1, c2 = st.columns([2, 5])
with c1:
    ticker = st.text_input("Ticker", value=st.session_state.get("ticker", ""),
                           placeholder="e.g. CRSP", max_chars=8).strip().upper()
with c2:
    st.caption("blocks")
    f1, f2, f3, f4, f5, f6, f7 = st.columns(7)
    vol = f1.checkbox("vol")
    call = f2.checkbox("call")
    squeeze = f3.checkbox("squeeze")
    insider = f4.checkbox("insider")
    geo = f5.checkbox("geo")
    live = f6.checkbox("live")
    pc_oi = f7.selectbox("pc-oi", ["off", "all", "near", "leaps", "monthly"], index=0,
                         label_visibility="collapsed")

with st.expander("thesis overlay (optional)"):
    t1, t2 = st.columns(2)
    thesis = t1.selectbox("bias", ["none", "bullish", "bearish"], index=0)
    level = t2.number_input("key level", value=0.0, step=1.0)

if known:
    picked = st.pills("recent data", known, selection_mode="single", default=None,
                      key=f"pills_{st.session_state.get('pills_nonce', 0)}")
    if picked:
        ticker = picked

run_clicked = st.button("Run", type="primary", use_container_width=False)

# ── generate ─────────────────────────────────────────────────────────────────
# Streamlit reruns the WHOLE script on any interaction (and on the menu's Rerun / the R hotkey),
# and a button reads True only during the run its click happened in. So the rendered report must
# live in session_state and be redrawn on EVERY rerun — gating the display on the click made the
# menu Rerun blank the page. Regenerate only when the (ticker, flags) key changes or Run is
# clicked; otherwise redisplay the stored result (generate_report's 2-min cache absorbs repeats).
flags = {"vol": vol, "call": call, "squeeze": squeeze, "insider": insider,
         "geo": geo, "live": live, "pc_oi": pc_oi,
         "thesis": None if thesis == "none" else thesis,
         "level": level or None}
flags_key = tuple(sorted(flags.items()))
key = (ticker, flags_key)

# 2s debounce on argument changes: a changed key starts (or continues) a settle timer; the script
# sleeps out the remainder and reruns itself, and only regenerates once the key has been stable
# for DEBOUNCE_S. Another click during the wait re-enters with a NEW key → the timer restarts, so
# rapid toggles collapse into one fetch. The Run button bypasses the wait (explicit intent).
should_generate = False
if ticker and run_clicked:
    should_generate = True
    st.session_state.pop("pending_key", None)
elif ticker and key != st.session_state.get("last_key"):
    now = time.time()
    if st.session_state.get("pending_key") != key:
        st.session_state["pending_key"] = key
        st.session_state["pending_at"] = now
    remaining = DEBOUNCE_S - (now - st.session_state["pending_at"])
    if remaining > 0.05:
        st.caption(f"⏳ applying in {remaining:.1f}s — keep clicking to batch changes")
        time.sleep(remaining)
        st.rerun()
    else:
        should_generate = True
        st.session_state.pop("pending_key", None)

if should_generate:
    st.session_state["ticker"] = ticker
    with st.spinner(f"running the lens on {ticker}…"):
        if live or run_clicked:
            generate_report.clear()          # explicit Run / live mode = fetch fresh, not cached
        try:
            report = generate_report(ticker, flags_key)
        except Exception as e:
            st.error(f"lens failed for {ticker}: {type(e).__name__}: {e}")
            report = None
    if report:
        st.session_state["last_key"] = key
        st.session_state["last_report"] = report

# ── display (every rerun, from session state) ────────────────────────────────
if st.session_state.get("last_report"):
    shown_ticker = st.session_state["last_key"][0]
    shown_live = bool(dict(st.session_state["last_key"][1]).get("live"))
    if shown_live:
        # continuous live chart: st.fragment reruns ONLY this section every N seconds —
        # one Tradier quote per tick; the report below stays as rendered.
        st.fragment(run_every=LIVE_CHART_EVERY_S)(draw_chart)(shown_ticker, True)
    else:
        draw_chart(shown_ticker, False)
    html = Ansi2HTMLConverter(inline=True, dark_bg=True).convert(
        st.session_state["last_report"], full=False)
    # st.html, NOT st.markdown — markdown ends an HTML block at the first blank line, which
    # shredded the <pre> (the report is full of blank lines) and broke monospace alignment.
    st.html(
        f'<div style="background:#0e1117;border:1px solid #2a2f3a;border-radius:8px;'
        f'padding:14px;overflow-x:auto;">'
        f'<pre style="font-family:Cascadia Mono,Consolas,monospace;font-size:13px;'
        f'line-height:1.35;color:#d8dee9;margin:0;">{html}</pre></div>')
else:
    st.info("Type a ticker (or pick one below) to run the lens. "
            "Checkbox blocks mirror the CLI flags; quotes are cached per session like the CLI.")
