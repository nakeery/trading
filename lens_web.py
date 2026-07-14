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
import json
import os
import re
import time
from types import SimpleNamespace

import pandas as pd
import streamlit as st
from ansi2html import Ansi2HTMLConverter

import lens
import lens_web_sections
from modules.features import compute_hv_features
from modules.timeframes import _load_daily, fetch_live_bar, append_live_bar

try:
    from modules.setupcheck import TIER1_MACRO
except Exception:                                     # pragma: no cover — optional dep path
    TIER1_MACRO = {"FOMC", "CPI", "NFP", "PCE"}

DATA_DIR = "data"
CHART_BARS = 120
CHART_WARMUP = 200  # extra bars loaded BEFORE the display window so MA200/BB are warm at its left edge
DEBOUNCE_S = 2.0    # settle time after a checkbox/argument change before regenerating — rapid
                    # clicks batch into ONE run instead of one fetch per click (Run bypasses it)
LIVE_CHART_EVERY_S = 10   # live-mode chart refresh cadence (one Tradier quote per tick; the
                          # chart redraws in a st.fragment — the report below is NOT re-fetched)
LIVE_MISS_LIMIT = 3       # consecutive empty live quotes before polling pauses (S55 — the
                          # fragment otherwise hits Tradier every 10s all night; Run resumes)

st.set_page_config(page_title="LENS", page_icon="🔭", layout="wide")


def known_tickers(data_dir=DATA_DIR):
    try:
        return sorted(f[:-len("_indicators.csv")].upper()
                      for f in os.listdir(data_dir) if f.endswith("_indicators.csv"))
    except Exception:
        return []


def make_args(flags):
    """argparse-shaped namespace for lens.render_ticker — candle 'none' (Plotly replaces it).
    `as_of` (S57 backtest mode) rides through to gather_report; live is forced off with it —
    a real-time quote on a historical report is a contradiction."""
    return SimpleNamespace(
        ticker=None, thesis=flags.get("thesis"), level=flags.get("level"),
        no_intraday=False, no_vix=False, geo=flags["geo"], no_color=False,
        candle="none", candle_px=128, prev=10, data_dir=DATA_DIR,
        no_refresh=False, refresh=False, as_of=flags.get("as_of"),
        pc_oi=([] if flags["pc_oi"] == "all" else [flags["pc_oi"]]) if flags["pc_oi"] != "off" else None,
        insider=flags["insider"], squeeze=flags["squeeze"],
        live=flags["live"] and not flags.get("as_of"),
        vol=flags["vol"], call=flags["call"], gex=flags["gex"],
        street=flags.get("street", False),
    )


@st.cache_data(ttl=120, show_spinner=False)
def generate_payload(ticker, flags_key):
    """One compute, two renderings (S49): gather_report produces the structured payload the
    native sections render from, then render_payload prints the CLI-identical ANSI report from
    that same payload (zero extra I/O — risk/macro ride the payload) for the expander.
    Returns (payload, preamble, ansi): `preamble` is whatever the compute phase printed
    (refresh/progress noise, or the load-error line when payload is None). `flags_key` is a
    hashable dict-as-tuple so the cache keys on the exact flag combination."""
    flags = dict(flags_key)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        payload = lens.gather_report(ticker, make_args(flags), interactive=False,
                                     backdrop_base=lens.build_backdrop(DATA_DIR))
    preamble = buf.getvalue()
    ansi = ""
    if payload is not None:
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            lens.render_payload(payload, use_color=True, candle_style="none")
        ansi = buf2.getvalue()
    return payload, preamble, ansi


@st.cache_data(ttl=600, show_spinner=False)
def load_daily_full(ticker):
    """Cached full daily history — the ONE loader behind the chart tail and seasonality (S55;
    they previously each made their own _load_daily call, i.e. two identical full yfinance
    downloads for CSV-less tickers) — keeps the fallback path from re-downloading on every
    live tick."""
    return _load_daily(ticker, DATA_DIR)


def load_daily_tail(ticker, bars=CHART_BARS, warmup=CHART_WARMUP):
    """Daily-bar tail for the chart (display window + indicator warm-up), floored at 260 rows
    so range52's 252-bar window stays a real 52 weeks if CHART_WARMUP ever shrinks."""
    return load_daily_full(ticker).tail(max(bars + warmup, 260))


def chart_frame(ticker, as_of=None, start=None):
    """(df, n_view) for the chart window (S57 date range): the daily frame truncated to `as_of`
    (backtest mode — the chart must not show bars the as-of report couldn't see), display bars
    counted from `start` when given (else the usual CHART_BARS), warm-up-extended like
    load_daily_tail (same 260-row floor for range52)."""
    full = load_daily_full(ticker)
    if as_of:
        full = full.loc[:pd.Timestamp(as_of)]
    n_view = CHART_BARS
    if start:
        n_view = max(int((full.index >= pd.Timestamp(start)).sum()), 20)
    return full.tail(max(n_view + CHART_WARMUP, 260)), n_view


VP_ASPECTS = ["value area", "POC", "HVN", "LVN", "histogram"]


@st.cache_data(ttl=600, show_spinner=False)
def load_iv_history(ticker, bars=252, asof=None):
    """Trailing IV/HV history for the chart under the candles (S50) — ZERO network: indicators
    CSV only (None for yfinance-fallback tickers / CSVs without the harvested IV columns).
    HV_20 is computed on load exactly as the gauges do (compute_hv_features). `asof` (S57)
    truncates the trailing year to the backtest date."""
    path = os.path.join(DATA_DIR, f"{ticker.lower()}_indicators.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if "atm_iv_30d" not in df.columns or "Close" not in df.columns:
            return None
        t = compute_hv_features(df)
        if asof:
            t = t.loc[:pd.Timestamp(asof)]
        t = t.tail(bars)

        def col(name):
            if name not in t.columns:
                return [None] * len(t)
            return [None if pd.isna(v) else float(v) for v in t[name]]

        out = {"dates": [d.date().isoformat() for d in t.index],
               "iv30": col("atm_iv_30d"), "iv_event": col("atm_iv_event"),
               "hv20": col("HV_20"), "skew": col("iv_skew_25d")}
        return out if any(v is not None for v in out["iv30"]) else None
    except Exception:
        return None


def _iv_fig(hist):
    """IV-vs-HV history figure: harvested ATM IV (30d) vs realized HV-20, the event-tenor IV
    where stamped, shaded pre-earnings windows (contiguous runs of the S44 atm_iv_event
    stamp — earnings markers with no network call), and (S56) a 25Δ-skew subpane when the
    harvest carries it — a rising skew = downside protection getting bid. Returns None when
    it can't build."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        d, iv, hv, ev = hist["dates"], hist["iv30"], hist["hv20"], hist["iv_event"]
        sk = hist.get("skew") or []
        has_skew = any(v is not None for v in sk)
        if len(d) < 2:
            return None
        fig = make_subplots(rows=2 if has_skew else 1, cols=1, shared_xaxes=True,
                            vertical_spacing=0.06,
                            row_heights=[0.68, 0.32] if has_skew else None)
        fig.add_trace(go.Scatter(x=d, y=hv, name="HV-20 (realized)", mode="lines",
                                 line=dict(color="#4ea3d8", width=1.2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=d, y=iv, name="ATM IV (30d)", mode="lines",
                                 line=dict(color="#e0a63a", width=1.4)), row=1, col=1)
        if any(v is not None for v in ev):
            fig.add_trace(go.Scatter(x=d, y=ev, name="event-expiry IV", mode="markers",
                                     marker=dict(color="#d6ba2e", size=3)), row=1, col=1)
        if has_skew:
            fig.add_trace(go.Scatter(x=d, y=sk, name="25Δ skew (put−call IV)", mode="lines",
                                     line=dict(color="#b070d0", width=1.2)), row=2, col=1)
            fig.add_hline(y=0, line_width=0.8, line_color="#4a5160", row=2, col=1)
            fig.update_yaxes(tickformat="+.0%", row=2, col=1)
        # pre-earnings shading AFTER the traces: on a make_subplots figure with no traces yet,
        # add_vrect silently adds NOTHING (plotly 6.x) — the loop originally ran first and the
        # shading never rendered. row/col pins it to the IV pane (bare add_vrect would also
        # shade the skew subpane); the ±12h pad keeps a single-session run visible.
        start = None
        for i, v in enumerate(ev + [None]):                # sentinel closes a trailing run
            if v is not None and start is None:
                start = i
            elif v is None and start is not None:
                fig.add_vrect(x0=pd.Timestamp(d[start]) - pd.Timedelta(hours=12),
                              x1=pd.Timestamp(d[i - 1]) + pd.Timedelta(hours=12),
                              fillcolor="rgba(224,166,58,0.08)", line_width=0, row=1, col=1)
                start = None
        fig.update_layout(height=310 if has_skew else 230,
                          margin=dict(l=10, r=10, t=10, b=10),
                          template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(14,17,23,1)", yaxis=dict(tickformat=".0%"),
                          legend=dict(orientation="h", y=1.12, x=0, font=dict(size=11)))
        return fig
    except Exception:
        return None


def range52(df, window=252):
    """52-week range read off the trailing daily bars (incl. a live provisional bar when
    present): position in range + distance from high. None when history is too thin."""
    try:
        t = df.tail(window)
        if len(t) < 200:
            return None
        hi, lo = float(t["High"].max()), float(t["Low"].min())
        last = float(t["Close"].iloc[-1])
        if hi <= lo:
            return None
        return {"hi": hi, "lo": lo, "pos": (last - lo) / (hi - lo), "off_hi": 1 - last / hi}
    except Exception:
        return None


# ── day-over-day snapshots + diff (S56) ──────────────────────────────────────
HISTORY_DIR = os.path.join(DATA_DIR, "payload_history")
SNAP_KEEP = 90            # snapshots kept per ticker
GAUGE_MOVE_PP = 0.10      # gauge percentile move worth surfacing (10 points)


def snap_from_payload(p):
    """Compact, diffable slice of a payload (pure): setup marks, risk factor strings, gauge
    value/percentile pairs, close. NOT the full payload — snapshots stay tiny on disk."""
    setup = {str(r[0]): str(r[1]) for r in (p.get("setup") or {}).get("rows", [])
             if isinstance(r, (list, tuple)) and len(r) >= 2}
    risk = p.get("risk") or {}
    gauges = {g["name"]: [g.get("value"), g.get("pct")]
              for g in (p.get("ctx") or {}).get("gauges", [])
              if g.get("value") is not None}
    lb = p.get("last_bar") or {}
    return {"as_of": p.get("as_of"), "close": lb.get("close"), "setup": setup,
            "dd": [str(x) for x in risk.get("drawdown") or []],
            "rally": [str(x) for x in risk.get("rally") or []], "gauges": gauges,
            "regime": (risk.get("regime") or {}).get("label")}   # S57 trend regime (None = no regime)


def save_snapshot(ticker, payload):
    """Persist today's snapshot (one file per as-of date — a same-day re-run overwrites),
    pruned to SNAP_KEEP. Best-effort: never raises."""
    try:
        snap = snap_from_payload(payload)
        if not snap["as_of"]:
            return
        d = os.path.join(HISTORY_DIR, ticker.lower())
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{snap['as_of']}.json"), "w", encoding="utf-8") as f:
            json.dump(snap, f)
        files = sorted(f for f in os.listdir(d) if f.endswith(".json"))
        for old in files[:-SNAP_KEEP]:
            os.remove(os.path.join(d, old))
    except Exception:
        pass


def load_prev_snapshot(ticker, before_iso):
    """Most recent snapshot STRICTLY BEFORE `before_iso` (so a same-day re-run diffs against
    the prior session, not itself). None when there is no history yet."""
    try:
        d = os.path.join(HISTORY_DIR, ticker.lower())
        prior = sorted(f for f in os.listdir(d)
                       if f.endswith(".json") and f[:-5] < before_iso)
        if not prior:
            return None
        with open(os.path.join(d, prior[-1]), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def diff_snapshots(prev, cur):
    """What changed between two snapshots (pure): setup-mark flips, risk factors added/
    removed, gauge percentile moves ≥ GAUGE_MOVE_PP. Returns None when nothing notable."""
    flips = [(k, prev["setup"][k], v) for k, v in (cur.get("setup") or {}).items()
             if k in (prev.get("setup") or {}) and prev["setup"][k] != v]
    out = {"flips": flips}
    # trend-regime flip (S57) — only when the prior snapshot carries the key (pre-S57 snapshots
    # don't; a missing→labeled transition would otherwise read as a flip on day one)
    out["regime_flip"] = ((prev.get("regime"), cur.get("regime"))
                          if "regime" in prev and prev.get("regime") != cur.get("regime")
                          else None)
    for side in ("dd", "rally"):
        p, c = set(prev.get(side) or []), set(cur.get(side) or [])
        out[f"{side}_added"] = sorted(c - p)
        out[f"{side}_removed"] = sorted(p - c)
    moves = []
    for name, (val, pct) in (cur.get("gauges") or {}).items():
        pv = (prev.get("gauges") or {}).get(name)
        if pv and pct is not None and pv[1] is not None and abs(pct - pv[1]) >= GAUGE_MOVE_PP:
            moves.append((name, pv[1], pct))
    out["gauge_moves"] = sorted(moves, key=lambda m: -abs(m[2] - m[1]))
    return out if any(out[k] for k in out) else None


def render_diff(ticker, payload):
    """'What changed' expander (S56) — latest report vs the prior stored session's snapshot.
    Silent when there's no history or nothing notable moved."""
    cur = snap_from_payload(payload)
    if not cur["as_of"]:
        return
    prev = load_prev_snapshot(ticker, cur["as_of"])
    if not prev:
        return
    d = diff_snapshots(prev, cur)
    if d is None:
        chg = ((cur["close"] / prev["close"] - 1)
               if cur.get("close") and prev.get("close") else None)
        st.caption(f"Δ vs {prev['as_of']}: no notable state changes"
                   + (f" · close {chg:+.2%}" if chg is not None else ""))
        return
    with st.expander(f"Δ what changed since {prev['as_of']}", expanded=False):
        if cur.get("close") and prev.get("close"):
            st.caption(f"close {prev['close']:,.2f} → {cur['close']:,.2f} "
                       f"({cur['close'] / prev['close'] - 1:+.2%})")
        if d.get("regime_flip"):
            a, b = d["regime_flip"]
            st.markdown(f"**trend regime:** {a or 'no regime'} → {b or 'no regime'}")
        if d["flips"]:
            st.markdown("**setup-check flips:** "
                        + " · ".join(f"{k}: {a} → {b}" for k, a, b in d["flips"]))
        for label, key in (("new drawdown-risk factors", "dd_added"),
                           ("cleared drawdown-risk factors", "dd_removed"),
                           ("new rally factors", "rally_added"),
                           ("cleared rally factors", "rally_removed")):
            if d[key]:
                st.markdown(f"**{label}:**")
                for x in d[key]:
                    st.markdown(f"- {x}")
        if d["gauge_moves"]:
            from modules.sentiment import ordinal_percentile
            st.markdown("**gauge percentile moves (≥10 points):** "
                        + " · ".join(f"{n} {ordinal_percentile(a)} → {ordinal_percentile(b)}"
                                     for n, a, b in d["gauge_moves"][:6]))
        st.caption("state diff vs the prior stored session — snapshots accumulate per run "
                   "under data/payload_history/")


# ── watchlist landing grid (S56) ─────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def load_tile(ticker):
    """Watchlist-tile data off the indicators CSV — zero network (known_tickers() only lists
    tickers WITH a CSV). None when the file is unreadable/too thin."""
    path = os.path.join(DATA_DIR, f"{ticker.lower()}_indicators.csv")
    try:
        c = pd.read_csv(path, index_col=0, parse_dates=True)["Close"].dropna()
        if len(c) < 21:
            return None
        last, prev = float(c.iloc[-1]), float(c.iloc[-2])
        ma20 = float(c.rolling(20).mean().iloc[-1])
        ma50 = float(c.rolling(50).mean().iloc[-1]) if len(c) >= 50 else None
        return {"closes": [float(v) for v in c.tail(60)], "last": last,
                "chg": last / prev - 1 if prev else 0.0,
                "ma20_up": last >= ma20,
                "ma50_up": (last >= ma50) if ma50 is not None else None,
                "as_of": c.index[-1].date().isoformat()}
    except Exception:
        return None


def _spark_fig(closes):
    """Tiny axis-less sparkline; green/red by the 60-bar trend."""
    try:
        import plotly.graph_objects as go
        color = "#5ec45e" if closes[-1] >= closes[0] else "#d83c34"
        fig = go.Figure(go.Scatter(y=closes, mode="lines",
                                   line=dict(color=color, width=1.4)))
        fig.update_layout(height=54, margin=dict(l=0, r=0, t=2, b=2), showlegend=False,
                          xaxis=dict(visible=False), yaxis=dict(visible=False),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          hovermode=False)
        return fig
    except Exception:
        return None


def _pick_from_tile(t):
    """Tile/pill pick → search box + one-shot explicit-intent flag (skips the debounce)."""
    st.session_state["ticker_input"] = t
    st.session_state["pill_clicked"] = True


def render_watchlist(known):
    """Empty-state landing grid: one compact tile per known ticker (CSV only, zero network) —
    sparkline, last close + Δ, MA20/50 arrows, latest snapshot's setup score when one exists."""
    st.caption("watchlist — every ticker with indicators data on disk; click one to run the lens")
    per_row = 4
    for i in range(0, len(known), per_row):
        cols = st.columns(per_row)
        for col, t in zip(cols, known[i:i + per_row]):
            tile = load_tile(t)
            with col.container(border=True):
                b1, b2 = st.columns([1, 1.4])
                b1.button(t, key=f"tile_{t}", on_click=_pick_from_tile, args=(t,))
                if not tile:
                    b2.caption("no data")
                    continue
                cc = "#5ec45e" if tile["chg"] >= 0 else "#d83c34"
                b2.markdown(f'<div style="text-align:right;line-height:1.25;">'
                            f'<span style="font-weight:600;">{tile["last"]:,.2f}</span><br>'
                            f'<span style="color:{cc};font-size:0.85em;">{tile["chg"]:+.2%}'
                            f'</span></div>', unsafe_allow_html=True)
                fig = _spark_fig(tile["closes"])
                if fig is not None:
                    st.plotly_chart(fig, width="stretch", key=f"spark_{t}",
                                    config={"displayModeBar": False, "staticPlot": True})
                arrows = f"MA20 {'▲' if tile['ma20_up'] else '▼'}"
                if tile["ma50_up"] is not None:
                    arrows += f" · MA50 {'▲' if tile['ma50_up'] else '▼'}"
                setup_chip = ""
                try:
                    snaps = sorted(f for f in os.listdir(os.path.join(HISTORY_DIR, t.lower()))
                                   if f.endswith(".json"))
                    if snaps:
                        with open(os.path.join(HISTORY_DIR, t.lower(), snaps[-1]),
                                  encoding="utf-8") as f:
                            marks = list((json.load(f).get("setup") or {}).values())
                        if marks:
                            ok = sum(1 for m in marks if m == "✓")
                            setup_chip = f" · setup {ok}/{len(marks)}"
                except Exception:
                    pass
                st.caption(f"{arrows}{setup_chip} · {tile['as_of']}")


def _header_tiles(p, df):
    """Header metric tiles from a payload-shaped dict, with the 52-week-range tile injected
    from the chart's daily frame (S55 — the same block previously lived in both the live and
    non-live paths). Never raises: a failure degrades to a caption, the ANSI expander below
    is the lossless fallback."""
    try:
        hdr = dict(p)                                   # shallow copy — never mutate the cache
        hdr["range52"] = range52(df)
        lens_web_sections.sec_header(hdr)
    except Exception as e:
        st.caption(f"header tiles unavailable ({type(e).__name__}: {e}) — "
                   f"see the full text report below")


@st.cache_data(ttl=3600, show_spinner=False)
def load_seasonality(ticker):
    """Monthly seasonality base rates (S53) — zero network when the indicators CSV exists
    (yfinance-fallback tickers ride load_daily_full's cache — S55: no second download). Needs
    the FULL history — decades, not the chart's 320-bar tail."""
    try:
        from modules.seasonality import monthly_seasonality
        return monthly_seasonality(load_daily_full(ticker)["Close"])
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def load_earnings_reactions(ticker, n=10, asof=None):
    """Realized post-print reactions (S53): gap/1d/5d + pre-print IV per past earnings —
    indicators CSV + the same yfinance earnings-dates call the lens run already makes
    (cached here ~1h). None for ETFs / no CSV / no usable prints. `asof` (S57) truncates the
    frame so post-as-of prints can't leak into a backtest view (earnings_reactions only uses
    dates ≤ the frame's last bar)."""
    path = os.path.join(DATA_DIR, f"{ticker.lower()}_indicators.csv")
    if not os.path.exists(path):
        return None
    try:
        from modules.features import earnings_dates
        from modules.vol_history import earnings_reactions
        df = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
        if asof:
            df = df.loc[:pd.Timestamp(asof)]
        out = earnings_reactions(df, earnings_dates(ticker), n=n)
        return out if out.get("status") == "ok" else None
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def load_ledger(ticker, rows=30):
    """Tail of entry.py's forward signal ledger (S30 — one row per as-of run date) — zero
    network; None when the ticker has no ledger yet."""
    path = os.path.join(DATA_DIR, f"{ticker.lower()}_signal_ledger.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        return df.tail(rows) if len(df) else None
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def load_ledger_score(ticker):
    """Realized-return scoring of the signal ledger (S56 — the S30 standing TODO landed):
    score_ledger.score() joins each ledger row to its 15d/63d forward return off the
    indicators CSV, WIN-tagged against the row's OWN stamped thresholds. Zero network."""
    try:
        from score_ledger import score
        res = score(ticker, DATA_DIR)
        return res if res.get("status") == "ok" else None
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def load_econ_calendar():
    """Two-month econ-release window + per-series coverage + cache age for the calendar
    expander (S51; S52 adds per-event URL + the headline result string once the print is
    out) — ZERO network: reads data/econ_calendar.csv + econ_results.json; the refresh button
    is the only network path. None when the module/cache is unavailable."""
    try:
        from modules.econ_calendar import (events_in_range, coverage_end_per_series,
                                           load_results, headline_result, ALL_SERIES,
                                           HEADLINE_SERIES)
        today = pd.Timestamp.today().normalize()
        start = today.replace(day=1)
        end = start + pd.offsets.MonthBegin(2) - pd.Timedelta(days=1)   # last day of next month
        ev = events_in_range(start, end)
        results, _fetched = load_results(DATA_DIR)
        rid = {name: r for name, r, _ in ALL_SERIES}
        events = []
        for d, s, t, rn in zip(ev["date"], ev["series"], ev["tier"], ev["release_name"]):
            s = str(s)
            # chip → the FRED GRAPH of the headline data series (the /series/ page opens on
            # the interactive chart; FOMC lands on the DFEDTARU target-rate step chart);
            # release page only as a fallback for series without a headline mapping
            url = (f"https://fred.stlouisfed.org/series/{HEADLINE_SERIES[s][0]}"
                   if s in HEADLINE_SERIES
                   else f"https://fred.stlouisfed.org/release?rid={rid[s]}" if s in rid
                   else None)
            res = headline_result(s, d, results.get(s) or [])
            events.append((d.date().isoformat(), s, int(t), url, res, str(rn)))
        cov = {k: (v.date().isoformat() if v is not None else None)
               for k, v in coverage_end_per_series().items()}
        path = os.path.join(DATA_DIR, "econ_calendar.csv")
        mtime = os.path.getmtime(path) if os.path.exists(path) else None
        return {"events": events, "coverage": cov, "mtime": mtime,
                "grid_end": end.date().isoformat()}
    except Exception:
        return None


ECON_TIER_STYLE = {1: ("rgba(224,166,58,0.18)", "#e0a63a"),    # Tier 1 — amber (FOMC/CPI/NFP/PCE)
                   2: ("rgba(78,163,216,0.15)", "#9fb4d0")}    # Tier 2 — blue-gray


def _chip_html(s, t, url, res, rn):
    """One release chip: tier-colored, linked to the official release page (new tab), with
    the headline print as a second line once it's out (and the full release name + result in
    the hover tooltip)."""
    import html as _html
    bg, fg = ECON_TIER_STYLE.get(t, ECON_TIER_STYLE[2])
    tip = _html.escape(rn + (f" — {res}" if res else " — scheduled"), quote=True)
    body = _html.escape(s)
    if res:
        body += (f'<div style="color:#d8dee9;font-size:0.92em;font-weight:400;">'
                 f'{_html.escape(res)}</div>')
    chip = (f'<div title="{tip}" style="background:{bg};color:{fg};border-radius:4px;'
            f'font-size:0.7em;padding:0 3px;margin-top:2px;text-align:center;'
            f'overflow:hidden;">{body}</div>')
    if url:
        return f'<a href="{url}" target="_blank" style="text-decoration:none;">{chip}</a>'
    return chip


def _month_grid_html(year, month, events_by_day, today_iso):
    """One month as a Mon–Fri HTML grid (releases never land on weekends): day number +
    tier-colored release chips (linked, with headline results once out — S52), today
    outlined. Themed like the report panels."""
    import calendar as _cal
    th = "".join(f'<th style="color:#8b95a7;font-size:0.7em;font-weight:400;'
                 f'padding:2px;">{d}</th>' for d in ("Mon", "Tue", "Wed", "Thu", "Fri"))
    rows = []
    for week in _cal.monthcalendar(year, month):
        cells = []
        for day in week[:5]:
            if day == 0:
                cells.append('<td style="border:1px solid transparent;"></td>')
                continue
            iso = f"{year:04d}-{month:02d}-{day:02d}"
            chips = "".join(_chip_html(s, t, url, res, rn)
                            for s, t, url, res, rn in events_by_day.get(iso, ()))
            border = "1.5px solid #e8c547" if iso == today_iso else "1px solid #2a2f3a"
            cells.append(f'<td style="border:{border};vertical-align:top;padding:3px;'
                         f'height:54px;"><div style="color:#8b95a7;font-size:0.7em;">{day}'
                         f'</div>{chips}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (f'<div style="color:#d8dee9;font-size:0.88em;margin:2px 0 4px;">'
            f'{_cal.month_name[month]} {year}</div>'
            f'<table style="border-collapse:collapse;width:100%;table-layout:fixed;">'
            f'<thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table>')


def render_econ_calendar():
    """Econ-calendar expander (S51) — market-level, independent of the ticker report. Where it
    appears on the page = where this is CALLED in the script run (Streamlit renders top-to-
    bottom in execution order): currently right below the header tiles' 'state characterization'
    caption, and after the empty-state message when no report has run yet."""
    with st.expander("📅 economic calendar — FRED release dates"):
        try:
            from modules.econ_calendar import refresh_if_stale, fetch_release_results
        except Exception:
            refresh_if_stale = None
        bcol, ccol = st.columns([1, 3])
        if refresh_if_stale is not None and bcol.button("↻ refresh from FRED"):
            with st.spinner("refreshing release dates + results from FRED…"):
                # max_age_days=-1 is a TRUE force (age is integer days, so 0 <= 0 would count a
                # same-day cache as fresh); refresh_if_stale never raises, never overwrites a
                # good cache with a worse one, and reports no-key/failure cleanly. stdout is
                # captured: the module prints per-series progress with ✓ marks, which
                # UnicodeEncodeError under a cp1252 console (streamlit without -X utf8).
                # fetch_release_results (S52) rides the same click — headline prints for the
                # past chips; no default-on network.
                with contextlib.redirect_stdout(io.StringIO()):
                    status, msg = refresh_if_stale(max_age_days=-1)
                    _r_status, r_msg = fetch_release_results(DATA_DIR)
            load_econ_calendar.clear()
            (st.success if status == "refreshed"
             else st.error if ("failed" in status or "missing" in status)
             else st.warning)(f"{msg} · {r_msg}")
        cal = load_econ_calendar()
        if cal is None:
            st.warning("econ calendar unavailable (module import / cache read failed)")
            return
        if cal["mtime"]:
            age_d = (time.time() - cal["mtime"]) / 86400
            ccol.caption(f"cache refreshed {age_d:.1f}d ago · amber = Tier 1 (FOMC/CPI/NFP/PCE), "
                         f"blue = Tier 2 · chips link to the FRED graph of the headline series; "
                         f"past chips show the headline print (several numbers ride each "
                         f"release — this is the market's shorthand) · the price chart marks "
                         f"Tier-1 dates ≤{EVENT_HORIZON_D}d")
        if not cal["events"]:
            st.warning("no release dates in the two-month window — the cache has likely gone "
                       "stale; refresh from FRED (needs $env:FRED_API_KEY, weekly cadence)")
        events_by_day = {}
        for iso, s, t, url, res, rn in cal["events"]:
            events_by_day.setdefault(iso, []).append((s, t, url, res, rn))
        today = pd.Timestamp.today().normalize()
        nxt = today.replace(day=1) + pd.offsets.MonthBegin(1)
        today_iso = today.date().isoformat()
        m1, m2 = st.columns(2)
        with m1:
            st.html(_month_grid_html(today.year, today.month, events_by_day, today_iso))
        with m2:
            st.html(_month_grid_html(nxt.year, nxt.month, events_by_day, today_iso))
        short = [f"{k}: {v or 'no data'}" for k, v in sorted(cal["coverage"].items())
                 if v is None or v < cal["grid_end"]]
        if short:
            st.caption("series whose forward coverage ends inside the grid — "
                       + " · ".join(short))


EVENT_HORIZON_D = 30   # chart event markers: only events this close — further dates would
                       # stretch the x-axis and squeeze the candles


def _event_markers(p, horizon_days=EVENT_HORIZON_D):
    """[(date_iso, label, color)] of upcoming events from payload data the report already
    carries (S50): earnings (`earn`), ex-div (`exd`, '~' when cadence-estimated), Tier-1 macro
    (`macro_events`), and catalysts.csv binary events (`cats`, e.g. PDUFA)."""
    if not p:
        return []
    out = []
    earn = p.get("earn")
    if earn and earn.get("date") and earn.get("days") is not None \
            and 0 <= earn["days"] <= horizon_days:
        out.append((earn["date"], "earnings", "#e0a63a"))
    exd = p.get("exd")
    if exd and exd.get("date") and exd.get("days") is not None \
            and 0 <= exd["days"] <= horizon_days:
        out.append((exd["date"], "ex-div" + ("~" if exd.get("est") else ""), "#9aa4b2"))
    for name, val in (p.get("macro_events") or {}).items():
        try:
            d, days = val
        except Exception:
            continue
        if name in TIER1_MACRO and d is not None and days is not None \
                and 0 <= days <= horizon_days:
            out.append((pd.Timestamp(d).date().isoformat(), name, "#8b95a7"))
    for c in p.get("cats") or []:
        try:
            d_iso, days, typ = c[0], c[1], c[2]
        except Exception:
            continue
        if 0 <= days <= horizon_days:
            out.append((d_iso, typ or "catalyst", "#d83c34"))
    return sorted(out)


def _candle_fig(df, overlays=(), show_volume=False, price_line=None, vprofile=None,
                events=(), glevels=(), rsi=None, macd=None, prev_close=None):
    """Plotly candlestick from a daily OHLCV frame + optional indicator overlays
    [(name, series, color, dash), …], a volume sub-pane, a dotted last/live price line,
    volume-profile aspects (`vprofile` = profile dict + an "aspects" set: value area band, POC
    line, HVN/LVN levels, right-edge volume-at-price histogram), upcoming-event markers
    (`events` = [(date_iso, label, color), …] — dashed vlines, S50), dealer-positioning
    levels (`glevels` = [(label, y, color, dash), …] — GEX walls/zero-gamma/max pain, tagged
    inside-right, S56), and momentum subpanes (S56): `rsi` = RSI(14) series, `macd` =
    (macd, signal, hist) series triple. `prev_close` = prior-close series computed on the
    caller's warm-up frame (true color for the first visible bar). Returns None when it
    can't build."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        if df is None or len(df) < 2:
            return None
        # pane layout: price + optional volume/RSI/MACD rows (row numbers assigned in order)
        panes = [("price", 0.62)]
        if show_volume:
            panes.append(("volume", 0.14))
        if rsi is not None:
            panes.append(("rsi", 0.12))
        if macd is not None:
            panes.append(("macd", 0.12))
        w = sum(h for _, h in panes)
        rowno = {name: i + 1 for i, (name, _) in enumerate(panes)}
        rows = len(panes)
        fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                            row_heights=[h / w for _, h in panes] if rows > 1 else None)
        # TradingView hollow-candle convention (matches the lens' terminal candles): COLOR =
        # close vs PRIOR close (green up / red down), FILL = close vs THIS bar's open (hollow
        # when close ≥ open, solid otherwise). Plotly's single trace can only key on close-vs-
        # open, so the bars are split into four style groups — within each group the close-vs-
        # open state is uniform, so setting both increasing/decreasing styles is safe.
        GREEN, RED, HOLLOW = "#5ec45e", "#d83c34", "rgba(0,0,0,0)"
        # prev_close (from the caller's warm-up frame) gives the FIRST visible bar its true
        # prior close; the shift-within-view fallback would color it by close-vs-open instead
        pc = prev_close if prev_close is not None else df["Close"].shift(1)
        pc = pc.fillna(df["Open"])
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
            # same COLOR axis as the candles (close vs prior close, first bar falls back to
            # its open) — `up` from the candle masks above already encodes it
            colors = ["rgba(94,196,94,0.55)" if u else "rgba(216,60,52,0.55)" for u in up]
            fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=colors,
                                 showlegend=False, name="volume"),
                          row=rowno["volume"], col=1)
        if rsi is not None:
            r_row = rowno["rsi"]
            fig.add_trace(go.Scatter(x=rsi.index, y=rsi, name="RSI(14)", mode="lines",
                                     line=dict(color="#d6ba2e", width=1.2), showlegend=False),
                          row=r_row, col=1)
            for lvl, col_ in ((70, "#d83c34"), (30, "#5ec45e")):
                fig.add_hline(y=lvl, line_dash="dot", line_width=0.8, line_color=col_,
                              row=r_row, col=1)
            fig.update_yaxes(range=[0, 100], tickvals=[30, 50, 70], title_text="RSI",
                             title_font_size=10, row=r_row, col=1)
        if macd is not None:
            m_row = rowno["macd"]
            m_line, m_sig, m_hist = macd
            hcol = ["rgba(94,196,94,0.55)" if (v is not None and v >= 0)
                    else "rgba(216,60,52,0.55)" for v in m_hist]
            fig.add_trace(go.Bar(x=m_hist.index, y=m_hist, marker_color=hcol,
                                 showlegend=False, name="MACD hist"), row=m_row, col=1)
            fig.add_trace(go.Scatter(x=m_line.index, y=m_line, name="MACD", mode="lines",
                                     line=dict(color="#4ea3d8", width=1.1), showlegend=False),
                          row=m_row, col=1)
            fig.add_trace(go.Scatter(x=m_sig.index, y=m_sig, name="signal", mode="lines",
                                     line=dict(color="#e0a63a", width=1.0), showlegend=False),
                          row=m_row, col=1)
            fig.update_yaxes(title_text="MACD", title_font_size=10, row=m_row, col=1)
        ylo = yhi = None
        if vprofile or glevels:
            # Profile levels span ~1y of prices and GEX levels can sit outside the window —
            # autorange would stretch the y-axis to include them, squishing the candles. Pin
            # the price pane to the VISIBLE window's range (bars + overlays + price line,
            # padded) and clip every level to it.
            ylo = float(df["Low"].min())
            yhi = float(df["High"].max())
            for _n, s, _c, _d in overlays:
                sv = s.dropna()
                if len(sv):
                    ylo, yhi = min(ylo, float(sv.min())), max(yhi, float(sv.max()))
            if price_line is not None:
                ylo, yhi = min(ylo, price_line), max(yhi, price_line)
            pad = (yhi - ylo) * 0.03 or 1.0
            ylo, yhi = ylo - pad, yhi + pad
            fig.update_yaxes(range=[ylo, yhi], row=1, col=1)
        if vprofile:
            a = vprofile.get("aspects") or set()
            ann = dict(x=0.0, xanchor="left", showarrow=False)     # inside-left level tags
            if "value area" in a and vprofile["va_low"] < yhi and vprofile["va_high"] > ylo:
                fig.add_hrect(y0=max(vprofile["va_low"], ylo), y1=min(vprofile["va_high"], yhi),
                              fillcolor="rgba(94,140,200,0.10)", line_width=0, row=1, col=1)
            if "POC" in a and ylo <= vprofile["poc"] <= yhi:
                fig.add_hline(y=vprofile["poc"], line_width=1.2, line_color="#e0a63a",
                              row=1, col=1,
                              annotation=dict(text=f"POC {vprofile['poc']:,.2f}",
                                              font=dict(color="#e0a63a", size=10), **ann))
            if "HVN" in a:
                for h in vprofile.get("hvns", []):
                    if abs(h - vprofile["poc"]) < 1e-6 or not ylo <= h <= yhi:
                        continue                                   # POC dup / outside the window
                    fig.add_hline(y=h, line_dash="dash", line_width=1, line_color="#9fb4d0",
                                  row=1, col=1,
                                  annotation=dict(text=f"HVN {h:,.2f}",
                                                  font=dict(color="#9fb4d0", size=9), **ann))
            if "LVN" in a:
                for l in vprofile.get("lvns", []):
                    if not ylo <= l <= yhi:
                        continue
                    fig.add_hline(y=l, line_dash="dot", line_width=1, line_color="#6a7686",
                                  row=1, col=1,
                                  annotation=dict(text=f"LVN {l:,.2f}",
                                                  font=dict(color="#6a7686", size=9), **ann))
            if "histogram" in a and vprofile.get("hist_volumes"):
                pairs = [(c, v) for c, v in zip(vprofile["hist_centers"],
                                                vprofile["hist_volumes"])
                         if ylo <= c <= yhi]
                if pairs:
                    centers, vols = [p[0] for p in pairs], [p[1] for p in pairs]
                    # right-edge volume-at-price bars on an overlaying, reversed x-axis: value 0
                    # sits at the RIGHT edge and bars extend left, ~28% of the plot width.
                    # Axis id x9 is deliberately clear of the subplot rows' x2/x3/x4 (S56 —
                    # the RSI/MACD panes claimed x3 and collided with the old id)
                    fig.add_trace(go.Bar(x=vols, y=centers, orientation="h",
                                         marker_color="rgba(150,170,200,0.20)",
                                         marker_line_width=0, showlegend=False,
                                         hoverinfo="skip", xaxis="x9", yaxis="y"))
                    fig.update_layout(xaxis9=dict(overlaying="x", range=[max(vols) * 3.5, 0],
                                                  showgrid=False, showticklabels=False,
                                                  visible=False))
        for label, y, gcolor, gdash in glevels or ():
            # dealer-positioning levels (S56) — tagged inside-RIGHT so they never collide
            # with the profile's inside-left POC/HVN/LVN tags
            if ylo is not None and not ylo <= y <= yhi:
                continue
            fig.add_hline(y=y, line_dash=gdash, line_width=1.1, line_color=gcolor,
                          row=1, col=1,
                          annotation=dict(text=f"{label} {y:,.2f}", x=0.99, xanchor="right",
                                          showarrow=False,
                                          font=dict(color=gcolor, size=9)))
        if events:
            # upcoming events (earnings/ex-div/Tier-1 macro/catalysts) as dashed vlines; an
            # invisible marker at the furthest date pulls the x-range forward so future events
            # are visible right of the last candle. Weekend dates (e.g. a Saturday PDUFA) are
            # snapped to the next trading day — the weekend rangebreak below would hide them.
            snapped = []
            for d_iso, label, color in events:
                ts = pd.Timestamp(d_iso)
                if ts.weekday() >= 5:
                    ts += pd.offsets.BDay(1)
                d_plot = ts.strftime("%Y-%m-%d")
                snapped.append(d_plot)
                fig.add_vline(x=d_plot, line_dash="dot", line_width=1, line_color=color,
                              row=1, col=1,
                              annotation=dict(text=label, textangle=-90, showarrow=False,
                                              font=dict(color=color, size=9)))
            furthest = max(snapped)
            if furthest > df.index[-1].date().isoformat():
                fig.add_trace(go.Scatter(x=[furthest], y=[float(df["Close"].iloc[-1])],
                                         mode="markers", marker=dict(opacity=0),
                                         showlegend=False, hoverinfo="skip"), row=1, col=1)
        # collapse non-trading gaps (S54): hide weekends + any missing weekdays inside the bar
        # span (holidays), so candles on either side of a market close sit adjacent. Only dates
        # WITHIN the data span count as holidays — future weekdays (the event-marker extension)
        # must survive, or upcoming markers would collapse onto the last candle. Applied to
        # every subplot row's date axis (x..x4 with volume/RSI/MACD panes on) — x9, the numeric
        # volume-profile overlay, is excluded: rangebreaks are a date-axis feature.
        rb = [dict(bounds=["sat", "mon"])]
        holidays = pd.bdate_range(df.index[0], df.index[-1]).difference(df.index.normalize())
        if len(holidays):
            rb.append(dict(values=[d.strftime("%Y-%m-%d") for d in holidays]))
        # every subplot row has its own date x-axis (xaxis, xaxis2, …) — x9 (the numeric
        # volume-profile overlay) is excluded: rangebreaks are a date-axis feature
        fig.update_layout(**{f"xaxis{i + 1 if i else ''}": dict(rangebreaks=rb)
                             for i in range(rows)})
        if price_line is not None:
            # price-tag style: label anchored LEFT at the plot's right edge, extending into the
            # widened right margin — never clipped by the plot area
            # NB: no explicit xref here — add_hline appends " domain" to the annotation xref
            # itself; setting it manually produced "x domain domain" and a ValueError
            fig.add_hline(y=price_line, line_dash="dot", line_width=1, line_color="#e8c547",
                          row=1, col=1,
                          annotation=dict(text=f"{price_line:,.2f}", x=1.0, xanchor="left",
                                          font=dict(color="#e8c547", size=12), showarrow=False))
        fig.update_layout(height=360 + 85 * (rows - 1),
                          margin=dict(l=10, r=64, t=26, b=10),
                          xaxis_rangeslider_visible=False, template="plotly_dark",
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(14,17,23,1)",
                          legend=dict(orientation="h", y=1.05, x=0, font=dict(size=11)))
        return fig
    except Exception:
        return None


def draw_chart(ticker, live=False, payload=None, as_of=None, start=None):
    """Chart section. In live mode the latest Tradier quote becomes a provisional today-bar
    (same fetch_live_bar/append_live_bar machinery as the CLI --live; display-only) with a
    LIVE price/timestamp caption — this function runs inside a st.fragment on a timer, and the
    live price line AND the header metric tiles beneath the chart ride each tick (render_all
    skips sec_header in live mode; `payload` is the fallback when the quote is unavailable).
    Indicator checkboxes are DISPLAY-ONLY: they rerun just this section (fragment scope), never
    the report or its debounce. `as_of`/`start` (S57 date range): candles truncated to the
    backtest as-of date, window pulled back to `start`; live is forced off under as_of."""
    if as_of:
        live = False
    df, n_view = chart_frame(ticker, as_of, start)
    df = df.copy()
    live_last = None
    bar = None
    prev = None
    if live:
        # backoff (S55): after LIVE_MISS_LIMIT consecutive empty quotes stop calling Tradier —
        # the fragment keeps ticking, but a closed market / missing token isn't polled all
        # night. Any successful bar or a new generate (Run) resets the counter.
        misses = st.session_state.get("live_misses", 0)
        if misses < LIVE_MISS_LIMIT:
            try:
                bar = fetch_live_bar(ticker)
            except Exception:
                pass
        if bar:
            st.session_state["live_misses"] = 0
            df, _ = append_live_bar(df, bar)
            live_last = float(bar["Close"])
            prev = float(df["Close"].iloc[-2]) if len(df) > 1 else live_last
            chg = (live_last / prev - 1) if prev else 0.0
            now_et = pd.Timestamp.now(tz="America/New_York").strftime("%H:%M:%S")
            state = "session in progress" if bar.get("in_progress") else "session closed"
            st.caption(f"🔴 LIVE {now_et} ET — {ticker} ${live_last:,.2f} ({chg:+.2%} vs prior "
                       f"close) · {state} · chart updates every {LIVE_CHART_EVERY_S}s")
        elif misses >= LIVE_MISS_LIMIT:
            st.caption(f"live: polling paused after {LIVE_MISS_LIMIT} empty Tradier responses "
                       f"(market closed / no token?) — showing last close; Run resumes")
        else:
            st.session_state["live_misses"] = misses + 1
            st.caption("live: no Tradier session data right now (market closed / no token?) — "
                       "showing last close")

    has_gex = bool((payload or {}).get("gex"))
    oc = st.columns(11)
    ma20 = oc[0].checkbox("MA20", value=True, key="ov_ma20")
    ma50 = oc[1].checkbox("MA50", value=True, key="ov_ma50")
    ma200 = oc[2].checkbox("MA200", key="ov_ma200")
    ema9 = oc[3].checkbox("EMA9", key="ov_ema9")
    bb = oc[4].checkbox("BB(20,2σ)", key="ov_bb")
    vol_pane = oc[5].checkbox("volume", value=True, key="ov_volume")
    rsi_on = oc[6].checkbox("RSI", key="ov_rsi")
    macd_on = oc[7].checkbox("MACD", key="ov_macd")
    pline = oc[8].checkbox("price line", value=True, key="ov_pline")
    vp_on = oc[9].checkbox("vol profile", key="ov_vp")
    gex_on = oc[10].checkbox("GEX levels", value=True, key="ov_gex") if has_gex else False

    glevels = []
    if gex_on:
        g = payload["gex"]
        if g.get("call_wall") is not None:
            glevels.append(("call wall", float(g["call_wall"]), "#5ec45e", "dash"))
        if g.get("put_wall") is not None:
            glevels.append(("put wall", float(g["put_wall"]), "#d83c34", "dash"))
        if g.get("zero_gamma") is not None:
            glevels.append(("zero-γ", float(g["zero_gamma"]), "#e0a63a", "dot"))
        if g.get("max_pain") and g["max_pain"].get("strike") is not None:
            glevels.append(("max pain", float(g["max_pain"]["strike"]), "#9aa4b2", "dot"))

    vprofile = None
    if vp_on:
        aspects = st.pills("profile aspects", VP_ASPECTS, selection_mode="multi",
                           default=VP_ASPECTS, key="ov_vp_aspects")
        # the REPORT's own profile — chart levels must match the Volume Profile section
        # exactly (S54; recomputing here on daily/1y disagreed wildly on names like SOFI
        # where the 1y value area spans an old high-price shelf), so there is deliberately
        # NO local fallback when the report carried none (S55)
        prof = (payload or {}).get("profile")
        if prof:
            vprofile = dict(prof)
            vprofile["aspects"] = set(aspects or [])
            st.caption(f"profile: report levels (1h bars ~6mo when available, else daily ~1y)"
                       f" · POC {prof['poc']:,.2f} · value area "
                       f"{prof['va_low']:,.2f}–{prof['va_high']:,.2f}")
        else:
            st.caption("volume profile unavailable — the report carried none for this ticker")

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
        # ddof=0 (population std) — the ta library's Bollinger convention, so these bands match
        # the report's Bollinger–Keltner squeeze (structure.read_squeeze)
        m, s = close.rolling(20).mean(), close.rolling(20).std(ddof=0)
        ov.append(("BB upper", m + 2 * s, "#7f8ea3", "dash"))
        ov.append(("BB lower", m - 2 * s, "#7f8ea3", "dash"))

    # momentum subpanes (S56) — computed on the warm-up-extended frame like the MAs, so
    # RSI/MACD are fully formed at the window's left edge; display-only
    rsi_s = macd_t = None
    if rsi_on:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rsi_s = (100 - 100 / (1 + gain / loss)).tail(n_view)
    if macd_on:
        m = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        sig = m.ewm(span=9, adjust=False).mean()
        macd_t = (m.tail(n_view), sig.tail(n_view), (m - sig).tail(n_view))

    view = df.tail(n_view)
    price = live_last if live_last is not None else float(view["Close"].iloc[-1])
    fig = _candle_fig(view, overlays=[(n, s.tail(n_view), c, d) for n, s, c, d in ov],
                      show_volume=vol_pane, price_line=price if pline else None,
                      vprofile=vprofile, events=_event_markers(payload), glevels=glevels,
                      rsi=rsi_s, macd=macd_t,
                      prev_close=df["Close"].shift(1).tail(n_view))
    if fig is not None:
        st.plotly_chart(fig, width="stretch", key=f"chart_{ticker}")

    if live:
        # header metric tiles ride the same quote as the chart (render_all skips sec_header in
        # live mode); payload-shaped dict so sec_header's LIVE/close labeling is reused as-is
        if bar:
            _header_tiles({
                "ticker": ticker, "as_of": str(df.index[-1].date()),
                "last_bar": {"close": live_last, "prev_close": prev, "open": bar["Open"],
                             "high": bar["High"], "low": bar["Low"]},
                "live": {"applied": True, "in_progress": bar.get("in_progress"),
                         "hhmm": bar.get("hhmm")}},
                df)                                     # df includes the live bar → tile ticks
        elif payload:
            _header_tiles(payload, df)                  # no quote — tiles hold the last close


# ── controls ─────────────────────────────────────────────────────────────────
def _pick_ticker():
    """Recent-data pill → ONE-SHOT event: copy the pick into the search box, then deselect the
    pill. st.pills selection is otherwise persistent state — a stuck pill silently overrode a
    typed ticker on every later run (and the write-back clobbered the box's text)."""
    pick = st.session_state.get("ticker_pills")
    if pick:
        st.session_state["ticker_input"] = pick
        st.session_state["ticker_pills"] = None
        st.session_state["pill_clicked"] = True   # explicit intent (S55) — skips the debounce


st.markdown("### 🔭 LENS — multi-timeframe market-structure & risk")
known = known_tickers()

# deep links (S56): ?ticker=QQQ&vol=1&pc_oi=near prefills the controls and auto-runs once
# (explicit intent → debounce bypassed). Consumed on the FIRST run only, before the widgets
# instantiate; the URL is written back after each successful generate, so the current view
# is always shareable/bookmarkable.
FLAG_NAMES = ("vol", "call", "gex", "squeeze", "insider", "street", "geo", "live")
if "qp_done" not in st.session_state:
    st.session_state["qp_done"] = True
    try:
        qp_t = (st.query_params.get("ticker") or "").strip().upper()
        if qp_t and not st.session_state.get("ticker_input"):
            st.session_state["ticker_input"] = qp_t
            st.session_state["pill_clicked"] = True
        for f in FLAG_NAMES:
            if st.query_params.get(f) == "1":
                st.session_state[f"flag_{f}"] = True
        qp_pc = st.query_params.get("pc_oi")
        if qp_pc in ("all", "near", "leaps", "monthly"):
            st.session_state["flag_pc_oi"] = qp_pc
        qp_asof = st.query_params.get("asof")            # S57 date range deep links
        if qp_asof:
            st.session_state["asof_on"] = True
            st.session_state["asof_date"] = pd.Timestamp(qp_asof).date()
        qp_from = st.query_params.get("from")
        if qp_from:
            st.session_state["chart_from"] = pd.Timestamp(qp_from).date()
    except Exception:
        pass

c1, c2 = st.columns([2, 5])
with c1:
    # key = the single source of truth for the ticker; the pill callback writes into it
    ticker = st.text_input("Ticker", key="ticker_input", placeholder="e.g. CRSP",
                           max_chars=8).strip().upper()
with c2:
    st.caption("blocks")
    f1, f2, f3, f4, f5, f6, f7, f8, f9 = st.columns(9)
    vol = f1.checkbox("vol", key="flag_vol")
    call = f2.checkbox("call", key="flag_call")
    gex = f3.checkbox("gex", key="flag_gex")
    squeeze = f4.checkbox("squeeze", key="flag_squeeze")
    insider = f5.checkbox("insider", key="flag_insider")
    street = f6.checkbox("street", key="flag_street")
    geo = f7.checkbox("geo", key="flag_geo")
    live = f8.checkbox("live", key="flag_live")
    pc_oi = f9.selectbox("pc-oi", ["off", "all", "near", "leaps", "monthly"],
                         key="flag_pc_oi", label_visibility="collapsed")

with st.expander("thesis overlay (optional)"):
    t1, t2 = st.columns(2)
    thesis = t1.selectbox("bias", ["none", "bullish", "bearish"], index=0)
    level = t2.number_input("key level", value=0.0, step=1.0)

# ── date range / as-of backtest (S57) ────────────────────────────────────────
# `as-of` rewinds the WHOLE report (frames truncated engine-side — no lookahead) so the user
# can backtest their own charting reads; `chart from` only widens the chart window (display-
# only — changing it never regenerates the report). Session keys are pre-seeded instead of
# passing value= so the deep-link block above can prefill them without the Streamlit
# default-vs-session-state warning.
st.session_state.setdefault("asof_date", pd.Timestamp.today().date())
st.session_state.setdefault("chart_from", None)
with st.expander("🕰 date range / as-of backtest (optional)"):
    d1, d2, d3 = st.columns([1, 1.2, 1.4])
    asof_on = d1.checkbox("as-of mode", key="asof_on",
                          help="Rewind the whole report to a past date — every frame is "
                               "truncated engine-side, so nothing after that date leaks in.")
    asof_date = d2.date_input("report as of", key="asof_date",
                              max_value=pd.Timestamp.today().date())
    chart_from = d3.date_input("chart from (window start, optional)", key="chart_from")
    if asof_on:
        st.caption("historical mode — the report and chart end at the as-of date; live-chain / "
                   "current-only blocks (pc-oi, gex, vol quote, call, squeeze, insider, street, "
                   "geo, live) are disabled: there is no historical source for them")

asof_iso = asof_date.isoformat() if (asof_on and asof_date) else None
if chart_from and asof_iso and chart_from.isoformat() > asof_iso:
    st.warning("chart-from is after the as-of date — ignoring the window start")
    chart_from = None
from_iso = chart_from.isoformat() if chart_from else None

if known:
    st.pills("recent data", known, selection_mode="single", default=None,
             key="ticker_pills", on_change=_pick_ticker)

run_clicked = st.button("Run", type="primary")

# ── generate ─────────────────────────────────────────────────────────────────
# Streamlit reruns the WHOLE script on any interaction (and on the menu's Rerun / the R hotkey),
# and a button reads True only during the run its click happened in. So the rendered report must
# live in session_state and be redrawn on EVERY rerun — gating the display on the click made the
# menu Rerun blank the page. Regenerate only when the (ticker, flags) key changes or Run is
# clicked; otherwise redisplay the stored result (generate_payload's 2-min cache absorbs repeats).
flags = {"vol": vol, "call": call, "gex": gex, "squeeze": squeeze, "insider": insider,
         "street": street, "geo": geo, "live": live and not asof_iso, "pc_oi": pc_oi,
         "thesis": None if thesis == "none" else thesis,
         "level": level or None, "as_of": asof_iso}
# NB: `chart_from` is deliberately NOT in flags — it only moves the chart window, so changing
# it must not re-key the cache / trigger a regenerate
flags_key = tuple(sorted(flags.items()))
key = (ticker, flags_key)
# consumed every run: a pill pick is explicit intent like Run — it skips the debounce below
# (but NOT the 2-min cache: only Run force-refreshes)
pill_clicked = st.session_state.pop("pill_clicked", False)

# 2s debounce on argument changes: a changed key starts (or continues) a settle timer; the script
# sleeps out the remainder and reruns itself, and only regenerates once the key has been stable
# for DEBOUNCE_S. Another click during the wait re-enters with a NEW key → the timer restarts, so
# rapid toggles collapse into one fetch. The Run button bypasses the wait (explicit intent).
should_generate = False
if ticker and run_clicked:
    should_generate = True
    st.session_state.pop("pending_key", None)
elif run_clicked and not ticker:
    st.warning("enter a ticker first (or pick one from the recent-data pills)")
elif ticker and key != st.session_state.get("last_key") \
        and key != st.session_state.get("failed_key"):
    # failed_key: a key whose generate failed doesn't auto-retry on every rerun (each overlay
    # toggle would otherwise eat the 2s debounce + re-error); Run retries it explicitly
    if pill_clicked:
        should_generate = True
        st.session_state.pop("pending_key", None)
    else:
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
    # st.status (S56) — the spinner upgraded to a stage log: the compute preamble (refresh/
    # progress notices the CLI would print) lands inside it instead of vanishing
    with st.status(f"running the lens on {ticker}…", expanded=False) as gen_status:
        if flags["live"] or run_clicked:
            # explicit Run / live mode = fetch fresh — clear THIS entry only, not every ticker's
            generate_payload.clear(ticker, flags_key)
        try:
            payload, preamble, ansi = generate_payload(ticker, flags_key)
        except Exception as e:
            st.error(f"lens failed for {ticker}: {type(e).__name__}: {e}")
            payload, preamble, ansi = None, "", ""
        for ln in re.sub(r"\x1b\[[0-9;]*m", "", preamble).strip().splitlines():
            st.write(ln)
        gen_status.update(label=(f"lens complete — {ticker}" if payload is not None
                                 else f"lens failed — {ticker}"),
                          state="complete" if payload is not None else "error")
    if payload is not None:
        st.session_state["last_key"] = key
        st.session_state["last_payload"] = payload
        st.session_state["last_ansi"] = preamble + ansi
        st.session_state.pop("failed_key", None)
        st.session_state["live_misses"] = 0            # fresh generate resumes live polling
        # day-over-day diff history (S56) — skipped for as-of runs (S57): a backtest rerun
        # must not overwrite that date's REAL end-of-day snapshot with a partial-blocks one
        if payload.get("as_of_mode") is None:
            save_snapshot(ticker, payload)
        try:                                           # shareable URL reflects the current view
            st.query_params["ticker"] = ticker
            for f in FLAG_NAMES:
                if flags[f]:
                    st.query_params[f] = "1"
                elif f in st.query_params:
                    del st.query_params[f]
            if flags["pc_oi"] != "off":
                st.query_params["pc_oi"] = flags["pc_oi"]
            elif "pc_oi" in st.query_params:
                del st.query_params["pc_oi"]
            for k, v in (("asof", flags["as_of"]), ("from", from_iso)):   # S57 date range
                if v:
                    st.query_params[k] = v
                elif k in st.query_params:
                    del st.query_params[k]
        except Exception:
            pass
        # the generate may have auto-refreshed the indicators CSV (new close stamped) — drop the
        # chart caches so the candles/profile/IV-history always match the report's data vintage
        load_daily_full.clear()
        load_iv_history.clear()
        load_ledger.clear()
        load_ledger_score.clear()
        load_seasonality.clear()
        load_earnings_reactions.clear()
        load_tile.clear()
    else:
        st.session_state["failed_key"] = key
        if preamble:
            # gather printed the load-error line instead of returning a payload; the subprocess
            # noise in it can carry ANSI escapes — strip them (st.error shows them raw)
            st.error(re.sub(r"\x1b\[[0-9;]*m", "", preamble).strip())

# ── display (every rerun, from session state) ────────────────────────────────
if st.session_state.get("last_payload"):
    shown_ticker = st.session_state["last_key"][0]
    shown_live = bool(dict(st.session_state["last_key"][1]).get("live"))
    # as-of date the SHOWN report was computed for (S57) — None on a normal run; live and
    # as-of are mutually exclusive (flags force live off), so the fragment path is never as-of
    shown_asof = st.session_state["last_payload"].get("as_of_mode")
    if shown_asof:
        st.warning(f"🕰 AS-OF {shown_asof} — historical backtest view: report, chart, and "
                   f"gauges reflect data through that session only (no lookahead); "
                   f"live-chain/current-only blocks are disabled")
    if shown_live:
        # continuous live chart + header tiles: st.fragment reruns ONLY this section every N
        # seconds — one Tradier quote per tick; the report below stays as rendered (its own
        # sec_header is skipped — the fragment renders the live tiles beneath the chart).
        st.fragment(run_every=LIVE_CHART_EVERY_S)(draw_chart)(
            shown_ticker, True, st.session_state["last_payload"], None, from_iso)
    else:
        draw_chart(shown_ticker, False, st.session_state["last_payload"], shown_asof, from_iso)
        # header tiles drawn here rather than via render_all (mirrors live mode, where the
        # fragment draws them) so the calendar below slots in right under the header's
        # 'state characterization' caption in BOTH modes
        _header_tiles(st.session_state["last_payload"],
                      chart_frame(shown_ticker, shown_asof, from_iso)[0])
    if not shown_asof:
        render_diff(shown_ticker, st.session_state["last_payload"])   # day-over-day diff (S56)
    render_econ_calendar()
    # IV vs realized-vol history (S50) — zero network (indicators CSV); skipped silently for
    # tickers without harvested IV columns. Truncated to the as-of date in backtest mode.
    hist = load_iv_history(shown_ticker, asof=shown_asof)
    fig_iv = _iv_fig(hist) if hist else None
    if fig_iv is not None:
        lens_web_sections._sec("IV vs REALIZED VOL — trailing year"
                               + (f" to {shown_asof}" if shown_asof else ""))
        st.plotly_chart(fig_iv, width="stretch", key=f"ivhist_{shown_ticker}")
        cap = ("ATM IV (30d, harvested) vs HV-20 (realized) · shaded spans = pre-earnings "
               "event-IV stamp windows (S44) · gaps = sessions with no harvest")
        if any(v is not None for v in (hist.get("skew") or [])):
            cap += (" · lower pane: 25Δ skew, put IV − call IV (rising = downside protection "
                    "getting bid)")
        st.caption(cap)
    # earnings reaction history (S53) — realized prints; skipped silently for ETFs/no data.
    # As-of mode truncates so post-as-of prints can't leak into the backtest view.
    rx = load_earnings_reactions(shown_ticker, asof=shown_asof)
    if rx:
        with st.expander(f"📊 earnings reactions — last {len(rx['rows'])} prints"):
            tbl = pd.DataFrame([{
                "Print": r["date"],
                "Gap": f"{r['gap']:+.1%}" if r["gap"] is not None else "—",
                "1d": f"{r['d1']:+.1%}",
                "5d": f"{r['d5']:+.1%}" if r["d5"] is not None else "—",
                "pre-print IV": f"{r['pre_iv']:.0%}" if r["pre_iv"] is not None else "—",
            } for r in rx["rows"]])

            def _tint(_):
                sty = pd.DataFrame("", index=tbl.index, columns=tbl.columns)
                for i, r in enumerate(rx["rows"]):
                    for cname, v in (("Gap", r["gap"]), ("1d", r["d1"]), ("5d", r["d5"])):
                        if v is not None:
                            sty.loc[i, cname] = (f"color: "
                                                 f"{'#5ec45e' if v > 0 else '#d83c34'}; "
                                                 f"font-weight: 600")
                return sty

            st.dataframe(tbl.style.apply(_tint, axis=None), hide_index=True, width="stretch")
            line = (f"median |print move| {rx['med_abs_d1']:.1%} · up {rx['up']} / "
                    f"down {rx['dn']}")
            em = ((st.session_state["last_payload"].get("vol") or {}).get("em") or {})
            if em.get("pct"):
                line += f" · current expected move ±{em['pct']:.1%} (~{em.get('dte', '?')}d)"
            st.caption(line + " · realized close-to-close moves; the --vol study covers the "
                              "implied side (ramp/crush/straddle P&L)")
    # seasonality (S53) — monthly base rates, DISPLAY-ONLY forever (calendar-time features
    # are the S31 leak class; never a model input)
    seas = load_seasonality(shown_ticker)
    if seas and seas.get("status") == "ok":
        with st.expander(f"📈 seasonality — monthly base rates over {seas['years']:.0f}y "
                         f"(display-only)"):
            import calendar as _cal
            cur = pd.Timestamp.today().month
            months, recent = seas["months"], seas["recent"]

            def wintxt(s):
                return f"{s['up']}/{s['n']}" if s["n"] else "—"

            def medtxt(s):
                return f"{s['median']:+.1%}" if s["median"] is not None else "—"

            cols = [_cal.month_abbr[m] for m in range(1, 13)]
            df_s = pd.DataFrame(
                [[wintxt(s) for s in months], [medtxt(s) for s in months],
                 [wintxt(s) for s in recent], [medtxt(s) for s in recent]],
                index=[f"win ({seas['years']:.0f}y)", f"median ({seas['years']:.0f}y)",
                       "win (10y)", "median (10y)"],
                columns=cols)

            def _style(_):
                sty = pd.DataFrame("", index=df_s.index, columns=df_s.columns)
                for j, (fs, rs) in enumerate(zip(months, recent)):
                    for i, s in ((0, fs), (2, rs)):
                        if s["win"] is not None:
                            sty.iloc[i, j] = (f"color: {lens_web_sections._ramp_hex(s['win'])}"
                                              f"; font-weight: 600")
                    for i, s in ((1, fs), (3, rs)):
                        if s["median"] is not None:
                            t = 0.5 + max(-0.5, min(0.5, s["median"] / 0.08))
                            sty.iloc[i, j] = f"color: {lens_web_sections._ramp_hex(t)}"
                    if j + 1 == cur:                      # highlight the current month
                        for i in range(4):
                            sty.iloc[i, j] += "; background-color: rgba(232,197,71,0.10)"
                return sty

            st.dataframe(df_s.style.apply(_style, axis=None), width="stretch")
            cs, cr = months[cur - 1], recent[cur - 1]
            st.caption(f"{_cal.month_name[cur]} historically: {wintxt(cs)} up, median "
                       f"{medtxt(cs)} (full) · {wintxt(cr)} up, median {medtxt(cr)} (last "
                       f"10y — a month strong in both windows is a real prior; one that "
                       f"flips is noise) · base rates, NOT edge; stays display-only (S31)")
    # sidebar quick-nav (S56) — anchor links to the section headers below (lens_web_sections
    # stamps a stable slug id on each header div); entries appear only when the payload
    # carries that section
    _p = st.session_state["last_payload"]
    _nav = [("Market backdrop", "market-backdrop", _p.get("backdrop")),
            ("Multi-timeframe", "multi-timeframe", _p.get("reads")),
            ("Volume profile", "volume-profile", _p.get("profile")),
            ("Rally vs drawdown", "rally-vs-drawdown-risk", _p.get("risk")),
            ("Setup check", "setup-check", _p.get("setup")),
            ("Options & vol", "options-vol-context", _p.get("ctx")),
            ("Short/squeeze", "short-positioning-squeeze", _p.get("squeeze")),
            ("Insider activity", "insider-activity", _p.get("insider")),
            ("Put/call OI", "put-call-oi", _p.get("pcoi")),
            ("Gamma exposure", "gamma-exposure", _p.get("gex")),
            ("Volatility setup", "volatility-setup", _p.get("vol")),
            ("Long call viability", "long-call-viability", _p.get("callq")),
            ("Geo backdrop", "geopolitical-cross-asset-backdrop", _p.get("geo"))]
    with st.sidebar:
        st.markdown(f"**{shown_ticker}** — sections")
        st.markdown("\n".join(f"- [{label}](#{slug})" for label, slug, present in _nav
                              if present))
    # native section renderers (S49) — same payload the ANSI report below is printed from;
    # the header is always drawn above (fragment in live mode, direct call otherwise)
    lens_web_sections.render_all(st.session_state["last_payload"], skip_header=True)
    # signal ledger hidden in as-of mode (S57): its rows/scores span dates after the backtest
    # as-of — showing realized outcomes would defeat the no-lookahead point
    ledger = load_ledger(shown_ticker) if not shown_asof else None
    if ledger is not None:
        sc = load_ledger_score(shown_ticker)
        with st.expander(f"signal ledger — entry.py forward ledger, last {len(ledger)} rows"
                         f"{' (scored vs realized returns)' if sc else ' (unscored)'}"):
            led = ledger.copy()
            if sc:
                by_date = {r["date"]: r for r in sc["rows"]}

                def _cell(d, k, wk):
                    r = by_date.get(str(d)[:10])   # score dates are ISO; tolerate a timestamped cell
                    if not r or r[k] is None:
                        return "pending"
                    mark = "" if r[wk] is None else (" ✓" if r[wk] else " ✗")
                    return f"{r[k]:+.1%}{mark}"

                # after the `signal` column — the CSV reads as date, ticker, signal_pre_gate,
                # signal, … (entry.py writes `date` as the index, then the row dict)
                led.insert(4, "fwd 15d", [_cell(d, "fwd15", "win15") for d in led["date"]])
                led.insert(5, "fwd 63d", [_cell(d, "fwd63", "win63") for d in led["date"]])
            st.dataframe(led, hide_index=True, width="stretch")
            if sc:
                segs = []
                for sig, a in sc["summary"].items():
                    if a["avg15"] is not None:
                        segs.append(f"{sig}: {a['scored15']} scored, avg 15d {a['avg15']:+.1%}")
                st.caption(("one row per as-of run date (S30) · "
                            + (" · ".join(segs) + " · " if segs else "")
                            + f"{sc['pending15']} pending 15d / {sc['pending63']} pending 63d "
                            f"· ✓/✗ = fwd return vs the row's OWN vol-adjusted threshold "
                            f"(every tier — on a STAY OUT row a ✗ means staying out was "
                            f"right) · also: python score_ledger.py"))
            else:
                st.caption("one row per as-of run date (S30); scoring needs the indicators "
                           "CSV — run score_ledger.py for detail")
    with st.expander("full text report (CLI-identical)", expanded=False):
        html = Ansi2HTMLConverter(inline=True, dark_bg=True).convert(
            st.session_state.get("last_ansi", ""), full=False)
        # st.html, NOT st.markdown — markdown ends an HTML block at the first blank line, which
        # shredded the <pre> (the report is full of blank lines) and broke monospace alignment.
        st.html(
            f'<div style="background:#0e1117;border:1px solid #2a2f3a;border-radius:8px;'
            f'padding:14px;overflow-x:auto;">'
            f'<pre style="font-family:Cascadia Mono,Consolas,monospace;font-size:13px;'
            f'line-height:1.35;color:#d8dee9;margin:0;">{html}</pre></div>')
else:
    st.info("Type a ticker (or pick one from the watchlist below) to run the lens. "
            "Checkbox blocks mirror the CLI flags; quotes are cached per session like the CLI.")
    render_econ_calendar()      # still reachable before the first report
    if known:
        render_watchlist(known)     # landing grid (S56) — CSV-only tiles, zero network

