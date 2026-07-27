"""Chart figure builders for the FastAPI backend (S60) — ports lens_web.py's chart stack.

The complex Plotly figures stay SERVER-SIDE (built here, sent as fig JSON, rendered by
react-plotly.js unchanged) so the two-axis hollow-candle convention, volume-profile aspects,
event vlines, and rangebreaks are never re-implemented in JS. Ports, near-verbatim:
_candle_fig, _iv_fig, _event_markers, chart_frame, load_daily_full, load_iv_history, range52,
and draw_chart's overlay/RSI/MACD computation. The chart uses the LATEST generated payload for
profile/events/GEX levels (reportgen.LATEST — the session_state["last_payload"] analogue;
S54: the chart renders the PAYLOAD's profile, never a local recompute).
"""

import json
import os

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

from api.cache import cached, frame_cache, iv_cache
from modules.features import compute_hv_features
from modules.timeframes import _load_daily, append_live_bar, fetch_live_bar

try:
    from modules.setupcheck import TIER1_MACRO
except Exception:                                     # pragma: no cover — optional dep path
    TIER1_MACRO = {"FOMC", "CPI", "NFP", "PCE"}

DATA_DIR = "data"
CHART_BARS = 120
CHART_WARMUP = 200  # extra bars loaded BEFORE the display window so MA200/BB are warm at its left edge
EVENT_HORIZON_D = 30   # chart event markers: only events this close — further dates would
                       # stretch the x-axis and squeeze the candles

# overlay tokens the /api/chart `overlays` param accepts (defaults mirror the Streamlit app)
OVERLAY_TOKENS = ("ma20", "ma50", "ma200", "ema9", "bb", "volume", "rsi", "macd",
                  "pline", "vp", "gex")
DEFAULT_OVERLAYS = ("ma20", "ma50", "volume", "pline", "gex")
VP_ASPECTS = ("value area", "POC", "HVN", "LVN", "histogram")


def load_daily_full(ticker, force=False):
    """Cached full daily history — the ONE loader behind the chart tail (ports S55)."""
    return cached(frame_cache, ticker.upper(),
                  lambda: _load_daily(ticker, DATA_DIR), force=force)


def chart_frame(ticker, as_of=None, start=None):
    """(df, n_view) for the chart window (S57 date range): the daily frame truncated to
    `as_of` (backtest mode), display bars counted from `start` when given, warm-up-extended
    with a 260-row floor so range52's 252-bar window stays a real 52 weeks."""
    full = load_daily_full(ticker)
    if as_of:
        full = full.loc[:pd.Timestamp(as_of)]
    n_view = CHART_BARS
    if start:
        n_view = max(int((full.index >= pd.Timestamp(start)).sum()), 20)
    return full.tail(max(n_view + CHART_WARMUP, 260)), n_view


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


def load_iv_history(ticker, bars=252, asof=None, force=False):
    """Trailing IV/HV history (S50) — ZERO network: indicators CSV only (None for
    yfinance-fallback tickers / CSVs without the harvested IV columns)."""
    def _load():
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
    return cached(iv_cache, (ticker.upper(), asof), _load, force=force)


def iv_fig(hist):
    """IV-vs-HV history figure (+25Δ-skew subpane, pre-earnings shading). None when it
    can't build. Ports _iv_fig verbatim."""
    try:
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
        # add_vrect silently adds NOTHING (plotly 6.x). row/col pins it to the IV pane; the
        # ±12h pad keeps a single-session run visible.
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


def event_markers(p, horizon_days=EVENT_HORIZON_D):
    """[(date_iso, label, color)] of upcoming events from payload data the report already
    carries (S50): earnings, ex-div ('~' when cadence-estimated), Tier-1 macro, catalysts."""
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


def gex_levels(payload):
    """Dealer-positioning hlines from the payload's gex block (S56)."""
    g = (payload or {}).get("gex")
    if not g:
        return []
    glevels = []
    if g.get("call_wall") is not None:
        glevels.append(("call wall", float(g["call_wall"]), "#5ec45e", "dash"))
    if g.get("put_wall") is not None:
        glevels.append(("put wall", float(g["put_wall"]), "#d83c34", "dash"))
    if g.get("zero_gamma") is not None:
        glevels.append(("zero-γ", float(g["zero_gamma"]), "#e0a63a", "dot"))
    if g.get("max_pain") and g["max_pain"].get("strike") is not None:
        glevels.append(("max pain", float(g["max_pain"]["strike"]), "#9aa4b2", "dot"))
    return glevels


def candle_fig(df, overlays=(), show_volume=False, price_line=None, vprofile=None,
               events=(), glevels=(), rsi=None, macd=None, prev_close=None):
    """Plotly candlestick from a daily OHLCV frame — ports _candle_fig verbatim (two-axis
    hollow convention via four split style-group traces, subpanes, profile aspects, GEX
    levels, event vlines, rangebreaks). Returns None when it can't build."""
    try:
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
        # close vs PRIOR close, FILL = close vs THIS bar's open. Plotly's single trace can
        # only key on close-vs-open, so the bars are split into four style groups.
        GREEN, RED, HOLLOW = "#5ec45e", "#d83c34", "rgba(0,0,0,0)"
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
            # pin the price pane to the VISIBLE window's range and clip every level to it.
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
                    # right-edge volume-at-price bars on an overlaying, reversed x-axis.
                    # Axis id x9 is deliberately clear of the subplot rows' x2/x3/x4.
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
            # upcoming events as dashed vlines; an invisible marker at the furthest date pulls
            # the x-range forward. Weekend dates snapped to the next trading day — the weekend
            # rangebreak below would hide them.
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
        # collapse non-trading gaps (S54): hide weekends + missing weekdays inside the bar
        # span (holidays). Only dates WITHIN the data span count as holidays — future weekdays
        # (the event-marker extension) must survive. Applied to every subplot row's date axis;
        # x9 (the numeric volume-profile overlay) is excluded: rangebreaks are a date-axis feature.
        rb = [dict(bounds=["sat", "mon"])]
        holidays = pd.bdate_range(df.index[0], df.index[-1]).difference(df.index.normalize())
        if len(holidays):
            rb.append(dict(values=[d.strftime("%Y-%m-%d") for d in holidays]))
        fig.update_layout(**{f"xaxis{i + 1 if i else ''}": dict(rangebreaks=rb)
                             for i in range(rows)})
        if price_line is not None:
            # NB: no explicit xref — add_hline appends " domain" to the annotation xref itself;
            # setting it manually produced "x domain domain" and a ValueError
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


def fig_dict(fig):
    """Figure → JSON-safe dict via plotly's own encoder (numpy/NaN/Timestamp-aware —
    NEVER json.dumps a fig directly; NaN would reach the browser as invalid JSON)."""
    if fig is None:
        return None
    return json.loads(pio.to_json(fig))


def build_chart(ticker, payload=None, as_of=None, start=None, live=False,
                overlays=DEFAULT_OVERLAYS, aspects=VP_ASPECTS):
    """Ports draw_chart's compute: frame + optional live bar + overlays/RSI/MACD on the
    warm-up frame, sliced to the view, then candle_fig. Returns
    {fig, range52, live: {found, hhmm, in_progress, close, chg} | None}.
    `payload` (the ticker's latest generated report) supplies profile/events/GEX levels."""
    on = set(overlays)
    # Normalize as_of to the payload's canonical YYYY-MM-DD (payload["as_of_mode"] is stamped
    # asof_ts.date().isoformat()). _check_date accepts non-canonical-but-valid dates ("2025-3-5",
    # ISO-with-time), so comparing the raw string would spuriously null the payload on those.
    if as_of:
        live = False
        try:
            as_of_key = pd.Timestamp(as_of).date().isoformat()
        except (ValueError, TypeError):
            as_of_key = as_of          # upstream _check_date should prevent this
    else:
        as_of_key = None
    if payload is not None and payload.get("as_of_mode") != as_of_key:
        # data-vintage mismatch: LATEST may hold an as-of (backtest) payload while this is a
        # current-mode chart request, or vice versa — drawing the other mode's GEX walls/
        # profile/event markers on these candles would be silent lookahead/staleness. Degrade
        # to an undecorated chart instead.
        payload = None
    df, n_view = chart_frame(ticker, as_of, start)
    df = df.copy()
    live_info = None
    live_last = None
    if live:
        # One Tradier quote per tick for the provisional session bar. The after-hours read used
        # to ride this tick too, which coupled it to `found` — and `fetch_live_bar` returns None
        # overnight/pre-market (trade_date isn't today), so the client's miss-counter killed the
        # poll after ~30s and froze the AH tile. AH now has its own endpoint (S64 fix).
        bar = None
        try:
            from modules.tradier import get_daily_quote
            bar = fetch_live_bar(ticker, quote=get_daily_quote(ticker))
        except Exception:
            pass
        if bar:
            df, _ = append_live_bar(df, bar)
            live_last = float(bar["Close"])
            prev = float(df["Close"].iloc[-2]) if len(df) > 1 else live_last
            live_info = {"found": True, "hhmm": bar.get("hhmm"),
                         "in_progress": bool(bar.get("in_progress")),
                         "close": live_last, "prev_close": prev,
                         "chg": (live_last / prev - 1) if prev else 0.0,
                         "open": bar.get("Open"), "high": bar.get("High"),
                         "low": bar.get("Low")}
        else:
            live_info = {"found": False}

    close = df["Close"]
    ov = []
    if "ma20" in on:
        ov.append(("MA20", close.rolling(20).mean(), "#d6ba2e", "solid"))
    if "ma50" in on:
        ov.append(("MA50", close.rolling(50).mean(), "#4ea3d8", "solid"))
    if "ma200" in on:
        ov.append(("MA200", close.rolling(200).mean(), "#b070d0", "solid"))
    if "ema9" in on:
        ov.append(("EMA9", close.ewm(span=9, adjust=False).mean(), "#cfcfcf", "dot"))
    if "bb" in on:
        # ddof=0 (population std) — the ta library's Bollinger convention, matching the
        # report's Bollinger–Keltner squeeze (structure.read_squeeze)
        m, s = close.rolling(20).mean(), close.rolling(20).std(ddof=0)
        ov.append(("BB upper", m + 2 * s, "#7f8ea3", "dash"))
        ov.append(("BB lower", m - 2 * s, "#7f8ea3", "dash"))

    rsi_s = macd_t = None
    if "rsi" in on:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rsi_s = (100 - 100 / (1 + gain / loss)).tail(n_view)
    if "macd" in on:
        m = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        sig = m.ewm(span=9, adjust=False).mean()
        macd_t = (m.tail(n_view), sig.tail(n_view), (m - sig).tail(n_view))

    vprofile = None
    if "vp" in on:
        prof = (payload or {}).get("profile")
        if prof:
            vprofile = dict(prof)
            vprofile["aspects"] = set(aspects or [])

    view = df.tail(n_view)
    price = live_last if live_last is not None else float(view["Close"].iloc[-1])
    fig = candle_fig(view, overlays=[(n, s.tail(n_view), c, d) for n, s, c, d in ov],
                     show_volume="volume" in on,
                     price_line=price if "pline" in on else None,
                     vprofile=vprofile, events=event_markers(payload),
                     glevels=gex_levels(payload) if "gex" in on else [],
                     rsi=rsi_s, macd=macd_t,
                     prev_close=df["Close"].shift(1).tail(n_view))
    if fig is not None:
        # stable per-view uirevision: plotly preserves the user's zoom/pan across live ticks
        # and overlay toggles, resetting only when the ticker or the date window changes
        fig.update_layout(uirevision=f"{ticker}|{as_of or ''}|{start or ''}")
    return {"fig": fig_dict(fig), "range52": range52(df), "live": live_info,
            "as_of": str(df.index[-1].date())}
