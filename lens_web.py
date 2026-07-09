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
from modules.volume_profile import volume_profile

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


@st.cache_data(ttl=600, show_spinner=False)
def load_iv_history(ticker, bars=252):
    """Trailing IV/HV history for the chart under the candles (S50) — ZERO network: indicators
    CSV only (None for yfinance-fallback tickers / CSVs without the harvested IV columns).
    HV_20 is computed on load exactly as the gauges do (compute_hv_features)."""
    path = os.path.join(DATA_DIR, f"{ticker.lower()}_indicators.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if "atm_iv_30d" not in df.columns or "Close" not in df.columns:
            return None
        t = compute_hv_features(df).tail(bars)

        def col(name):
            if name not in t.columns:
                return [None] * len(t)
            return [None if pd.isna(v) else float(v) for v in t[name]]

        out = {"dates": [d.date().isoformat() for d in t.index],
               "iv30": col("atm_iv_30d"), "iv_event": col("atm_iv_event"),
               "hv20": col("HV_20")}
        return out if any(v is not None for v in out["iv30"]) else None
    except Exception:
        return None


def _iv_fig(hist):
    """IV-vs-HV history figure: harvested ATM IV (30d) vs realized HV-20, the event-tenor IV
    where stamped, and shaded pre-earnings windows (contiguous runs of the S44 atm_iv_event
    stamp — earnings markers with no network call). Returns None when it can't build."""
    try:
        import plotly.graph_objects as go
        d, iv, hv, ev = hist["dates"], hist["iv30"], hist["hv20"], hist["iv_event"]
        if len(d) < 2:
            return None
        fig = go.Figure()
        start = None
        for i, v in enumerate(ev + [None]):                # sentinel closes a trailing run
            if v is not None and start is None:
                start = i
            elif v is None and start is not None:
                fig.add_vrect(x0=d[start], x1=d[i - 1],
                              fillcolor="rgba(224,166,58,0.08)", line_width=0)
                start = None
        fig.add_trace(go.Scatter(x=d, y=hv, name="HV-20 (realized)", mode="lines",
                                 line=dict(color="#4ea3d8", width=1.2)))
        fig.add_trace(go.Scatter(x=d, y=iv, name="ATM IV (30d)", mode="lines",
                                 line=dict(color="#e0a63a", width=1.4)))
        if any(v is not None for v in ev):
            fig.add_trace(go.Scatter(x=d, y=ev, name="event-expiry IV", mode="markers",
                                     marker=dict(color="#d6ba2e", size=3)))
        fig.update_layout(height=230, margin=dict(l=10, r=10, t=10, b=10),
                          template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(14,17,23,1)", yaxis=dict(tickformat=".0%"),
                          legend=dict(orientation="h", y=1.12, x=0, font=dict(size=11)))
        return fig
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
                events=()):
    """Plotly candlestick from a daily OHLCV frame + optional indicator overlays
    [(name, series, color, dash), …], a volume sub-pane, a dotted last/live price line,
    volume-profile aspects (`vprofile` = profile dict + an "aspects" set: value area band, POC
    line, HVN/LVN levels, right-edge volume-at-price histogram), and upcoming-event markers
    (`events` = [(date_iso, label, color), …] — dashed vlines, S50). Returns None when it
    can't build."""
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
            # same COLOR axis as the candles (close vs prior close, first bar falls back to
            # its open) — `up` from the candle masks above already encodes it
            colors = ["rgba(94,196,94,0.55)" if u else "rgba(216,60,52,0.55)" for u in up]
            fig.add_trace(go.Bar(x=df.index, y=df["Volume"], marker_color=colors,
                                 showlegend=False, name="volume"), row=2, col=1)
        if vprofile:
            a = vprofile.get("aspects") or set()
            # The profile spans ~1y of prices — levels and histogram bins can sit far outside
            # the 120-bar window, and autorange would stretch the y-axis to include them,
            # squishing the candles. Pin the price pane to the VISIBLE window's range (bars +
            # overlays + price line, padded) and clip every profile aspect to it.
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
                    # sits at the RIGHT edge and bars extend left, ~28% of the plot width
                    fig.add_trace(go.Bar(x=vols, y=centers, orientation="h",
                                         marker_color="rgba(150,170,200,0.20)",
                                         marker_line_width=0, showlegend=False,
                                         hoverinfo="skip", xaxis="x3", yaxis="y"))
                    fig.update_layout(xaxis3=dict(overlaying="x", range=[max(vols) * 3.5, 0],
                                                  showgrid=False, showticklabels=False,
                                                  visible=False))
        if events:
            # upcoming events (earnings/ex-div/Tier-1 macro/catalysts) as dashed vlines; an
            # invisible marker at the furthest date pulls the x-range forward so future events
            # are visible right of the last candle
            for d_iso, label, color in events:
                fig.add_vline(x=d_iso, line_dash="dot", line_width=1, line_color=color,
                              row=1, col=1,
                              annotation=dict(text=label, textangle=-90, showarrow=False,
                                              font=dict(color=color, size=9)))
            furthest = max(e[0] for e in events)
            if furthest > df.index[-1].date().isoformat():
                fig.add_trace(go.Scatter(x=[furthest], y=[float(df["Close"].iloc[-1])],
                                         mode="markers", marker=dict(opacity=0),
                                         showlegend=False, hoverinfo="skip"), row=1, col=1)
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


def draw_chart(ticker, live=False, payload=None):
    """Chart section. In live mode the latest Tradier quote becomes a provisional today-bar
    (same fetch_live_bar/append_live_bar machinery as the CLI --live; display-only) with a
    LIVE price/timestamp caption — this function runs inside a st.fragment on a timer, and the
    live price line AND the header metric tiles beneath the chart ride each tick (render_all
    skips sec_header in live mode; `payload` is the fallback when the quote is unavailable).
    Indicator checkboxes are DISPLAY-ONLY: they rerun just this section (fragment scope), never
    the report or its debounce."""
    df = load_daily_tail(ticker).copy()
    live_last = None
    bar = None
    prev = None
    if live:
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
                      vprofile=vprofile, events=_event_markers(payload))
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True, key=f"chart_{ticker}")

    if live:
        # header metric tiles ride the same quote as the chart (render_all skips sec_header in
        # live mode); payload-shaped dict so sec_header's LIVE/close labeling is reused as-is
        try:
            if bar:
                lens_web_sections.sec_header({
                    "ticker": ticker, "as_of": str(df.index[-1].date()),
                    "last_bar": {"close": live_last, "prev_close": prev, "open": bar["Open"],
                                 "high": bar["High"], "low": bar["Low"]},
                    "live": {"applied": True, "in_progress": bar.get("in_progress"),
                             "hhmm": bar.get("hhmm")}})
            elif payload:
                lens_web_sections.sec_header(payload)   # no quote — tiles hold the last close
        except Exception as e:
            st.caption(f"header tiles unavailable ({type(e).__name__}: {e}) — "
                       f"see the full text report below")


# ── controls ─────────────────────────────────────────────────────────────────
def _pick_ticker():
    """Recent-data pill → ONE-SHOT event: copy the pick into the search box, then deselect the
    pill. st.pills selection is otherwise persistent state — a stuck pill silently overrode a
    typed ticker on every later run (and the write-back clobbered the box's text)."""
    pick = st.session_state.get("ticker_pills")
    if pick:
        st.session_state["ticker_input"] = pick
        st.session_state["ticker_pills"] = None


st.markdown("### 🔭 LENS — multi-timeframe market-structure & risk")
known = known_tickers()
c1, c2 = st.columns([2, 5])
with c1:
    # key = the single source of truth for the ticker; the pill callback writes into it
    ticker = st.text_input("Ticker", key="ticker_input", placeholder="e.g. CRSP",
                           max_chars=8).strip().upper()
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
    st.pills("recent data", known, selection_mode="single", default=None,
             key="ticker_pills", on_change=_pick_ticker)

run_clicked = st.button("Run", type="primary", use_container_width=False)

# ── generate ─────────────────────────────────────────────────────────────────
# Streamlit reruns the WHOLE script on any interaction (and on the menu's Rerun / the R hotkey),
# and a button reads True only during the run its click happened in. So the rendered report must
# live in session_state and be redrawn on EVERY rerun — gating the display on the click made the
# menu Rerun blank the page. Regenerate only when the (ticker, flags) key changes or Run is
# clicked; otherwise redisplay the stored result (generate_payload's 2-min cache absorbs repeats).
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
elif run_clicked and not ticker:
    st.warning("enter a ticker first (or pick one from the recent-data pills)")
elif ticker and key != st.session_state.get("last_key") \
        and key != st.session_state.get("failed_key"):
    # failed_key: a key whose generate failed doesn't auto-retry on every rerun (each overlay
    # toggle would otherwise eat the 2s debounce + re-error); Run retries it explicitly
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
    with st.spinner(f"running the lens on {ticker}…"):
        if live or run_clicked:
            # explicit Run / live mode = fetch fresh — clear THIS entry only, not every ticker's
            generate_payload.clear(ticker, flags_key)
        try:
            payload, preamble, ansi = generate_payload(ticker, flags_key)
        except Exception as e:
            st.error(f"lens failed for {ticker}: {type(e).__name__}: {e}")
            payload, preamble, ansi = None, "", ""
    if payload is not None:
        st.session_state["last_key"] = key
        st.session_state["last_payload"] = payload
        st.session_state["last_ansi"] = preamble + ansi
        st.session_state.pop("failed_key", None)
        # the generate may have auto-refreshed the indicators CSV (new close stamped) — drop the
        # chart caches so the candles/profile/IV-history always match the report's data vintage
        load_daily_tail.clear()
        load_profile.clear()
        load_iv_history.clear()
        load_ledger.clear()
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
    if shown_live:
        # continuous live chart + header tiles: st.fragment reruns ONLY this section every N
        # seconds — one Tradier quote per tick; the report below stays as rendered (its own
        # sec_header is skipped — the fragment renders the live tiles beneath the chart).
        st.fragment(run_every=LIVE_CHART_EVERY_S)(draw_chart)(
            shown_ticker, True, st.session_state["last_payload"])
    else:
        draw_chart(shown_ticker, False, st.session_state["last_payload"])
        # header tiles drawn here rather than via render_all (mirrors live mode, where the
        # fragment draws them) so the calendar below slots in right under the header's
        # 'state characterization' caption in BOTH modes
        try:
            lens_web_sections.sec_header(st.session_state["last_payload"])
        except Exception as e:
            st.caption(f"header tiles unavailable ({type(e).__name__}: {e}) — "
                       f"see the full text report below")
    render_econ_calendar()
    # IV vs realized-vol history (S50) — zero network (indicators CSV); skipped silently for
    # tickers without harvested IV columns
    hist = load_iv_history(shown_ticker)
    fig_iv = _iv_fig(hist) if hist else None
    if fig_iv is not None:
        lens_web_sections._sec("IV vs REALIZED VOL — trailing year")
        st.plotly_chart(fig_iv, use_container_width=True, key=f"ivhist_{shown_ticker}")
        st.caption("ATM IV (30d, harvested) vs HV-20 (realized) · shaded spans = pre-earnings "
                   "event-IV stamp windows (S44) · gaps = sessions with no harvest")
    # native section renderers (S49) — same payload the ANSI report below is printed from;
    # the header is always drawn above (fragment in live mode, direct call otherwise)
    lens_web_sections.render_all(st.session_state["last_payload"], skip_header=True)
    ledger = load_ledger(shown_ticker)
    if ledger is not None:
        with st.expander(f"signal ledger — entry.py forward ledger, last {len(ledger)} rows "
                         f"(unscored)"):
            st.dataframe(ledger, hide_index=True, width="stretch")
            st.caption("one row per as-of run date (S30); not yet joined to realized returns — "
                       "the standing scorer TODO")
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
    st.info("Type a ticker (or pick one above) to run the lens. "
            "Checkbox blocks mirror the CLI flags; quotes are cached per session like the CLI.")
    render_econ_calendar()      # still reachable before the first report

