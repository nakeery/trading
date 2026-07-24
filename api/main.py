"""LENS FastAPI backend (S60) — serves the gather_report payload + chart figures to the
React frontend in web/.

Dev:   .\\trade\\Scripts\\python.exe -m uvicorn api.main:app --port 8000 --reload --reload-dir api
       (reload-dir MUST stay restricted to api/ — a generate writes CSVs/JSON caches under
       data/, and an unrestricted --reload would restart the server mid-generate)
Prod:  npm run build in web/, then this app serves web/dist at / (same origin — no CORS).

Run from the repo root: DATA_DIR="data" is cwd-relative, exactly like the CLI and Streamlit.
"""

import asyncio
import os

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from api import charts, loaders, reportgen
from api.cache import evict_ticker, report_cache
from api.sanitize import sanitize

DATA_DIR = "data"
WEB_DIST = os.path.join("web", "dist")

app = FastAPI(title="LENS API", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.get("/api/health")
def health():
    return {"status": "ok"}


def _check_date(name: str, val: str | None, allow_future: bool = True) -> None:
    """422 on an unparseable date query param, and (for as_of) on a future date — a
    future as-of would produce a current report wearing a historical banner."""
    if not val:
        return
    try:
        ts = pd.Timestamp(val)
    except Exception:
        raise HTTPException(422, f"invalid {name} date: {val!r}")
    if not allow_future and ts.normalize() > pd.Timestamp.today().normalize():
        raise HTTPException(422, f"{name} is in the future: {val!r}")


@app.get("/api/tickers")
def tickers():
    """Every ticker with an indicators CSV on disk (ports lens_web.known_tickers)."""
    try:
        names = sorted(f[:-len("_indicators.csv")].upper()
                       for f in os.listdir(DATA_DIR) if f.endswith("_indicators.csv"))
    except Exception:
        names = []
    return sanitize({"tickers": names})


@app.get("/api/report/{ticker}")
async def report(ticker: str,
                 vol: bool = False, call: bool = False, gex: bool = False,
                 squeeze: bool = False, insider: bool = False, street: bool = False,
                 movers: bool = False, geo: bool = False, live: bool = False,
                 pc_oi: str = Query("off", pattern="^(off|all|near|leaps|monthly)$"),
                 thesis: str | None = Query(None, pattern="^(bullish|bearish)$"),
                 level: float | None = None, as_of: str | None = None,
                 force: bool = False):
    """The report bundle: {payload, preamble, ansi_html, diff}.

    Serialized under GENERATE_LOCK — gather_report captures stdout via a process-global
    redirect, so generates must never run concurrently (keep this endpoint `async def`).
    Cached 120s per (ticker, flags); `force` (the Run button) and live mode always refetch.
    On success: LATEST[ticker] updated (the chart's payload source), per-ticker caches
    evicted (the generate may have restamped the indicators CSV — data-vintage match), and
    a day-over-day snapshot is saved + diffed (skipped in as-of mode: a backtest rerun must
    not overwrite that date's real end-of-day snapshot)."""
    t = ticker.strip().upper()
    _check_date("as_of", as_of, allow_future=False)
    flags = {"vol": vol, "call": call, "gex": gex, "squeeze": squeeze, "insider": insider,
             "street": street, "movers": movers, "geo": geo,
             "live": live and not as_of, "pc_oi": pc_oi,
             "thesis": thesis, "level": level or None, "as_of": as_of or None}
    key = (t, reportgen.flags_key(flags))
    async with reportgen.GENERATE_LOCK:
        if force or flags["live"]:
            report_cache.pop(key, None)
        if key in report_cache:
            bundle = report_cache[key]
        else:
            bundle = await asyncio.to_thread(reportgen.generate, t, flags)
            if bundle["payload"] is not None:
                report_cache[key] = bundle
                evict_ticker(t)
        if bundle["payload"] is not None:
            # LATEST must track the report the client is actually looking at — on cache HITS
            # too, or a flag toggle within the TTL leaves /api/chart drawing the OTHER flag
            # combo's GEX levels/profile/markers under this report's sections
            reportgen.LATEST[t] = bundle["payload"]
    diff = None
    payload = bundle["payload"]
    if payload is not None and payload.get("as_of_mode") is None:
        diff = loaders.snapshot_and_diff(t, payload)
    return sanitize({"payload": payload, "preamble": bundle["preamble"],
                     "ansi_html": bundle["ansi_html"], "diff": diff})


@app.get("/api/chart/{ticker}")
def chart(ticker: str, as_of: str | None = None, start: str | None = None,
          live: bool = False,
          overlays: str = ",".join(charts.DEFAULT_OVERLAYS),
          aspects: str = ",".join(charts.VP_ASPECTS)):
    """Candlestick figure for the ticker: {fig, range52, live, as_of}. `overlays` /
    `aspects` are comma-separated tokens (see charts.OVERLAY_TOKENS / VP_ASPECTS) — the
    fig is rebuilt server-side per combination; the daily frame underneath is cached.
    Profile/events/GEX levels come from the ticker's LATEST generated payload (S54)."""
    t = ticker.strip().upper()
    _check_date("as_of", as_of, allow_future=False)
    _check_date("start", start)  # a future start just yields an empty window — parse-only
    ov = tuple(x for x in (s.strip() for s in overlays.split(","))
               if x in charts.OVERLAY_TOKENS)
    asp = tuple(x for x in (s.strip() for s in aspects.split(",")) if x in charts.VP_ASPECTS)
    try:
        out = charts.build_chart(t, payload=reportgen.LATEST.get(t),
                                 as_of=as_of or None, start=start or None,
                                 live=live, overlays=ov, aspects=asp)
    except Exception as e:
        # no CSV and no yfinance data for the name — the sibling loaders swallow this
        # internally; here it must not surface as a 500 traceback
        raise HTTPException(404, f"no daily data for {t}: {type(e).__name__}")
    return sanitize(out)


@app.get("/api/iv_history/{ticker}")
def iv_history(ticker: str, asof: str | None = None):
    """IV-vs-HV trailing-year figure (S50) — zero network, indicators CSV only.
    {fig, caption} or {fig: None} for tickers without harvested IV columns."""
    t = ticker.strip().upper()
    hist = charts.load_iv_history(t, asof=asof or None)
    fig = charts.iv_fig(hist) if hist else None
    if fig is None:
        return {"fig": None}
    fig.update_layout(uirevision=f"{t}|{asof or ''}")   # keep zoom across refetches
    cap = ("ATM IV (30d, harvested) vs HV-20 (realized) · shaded spans = pre-earnings "
           "event-IV stamp windows (S44) · gaps = sessions with no harvest")
    if any(v is not None for v in (hist.get("skew") or [])):
        cap += (" · lower pane: 25Δ skew, put IV − call IV (rising = downside protection "
                "getting bid)")
    return sanitize({"fig": charts.fig_dict(fig), "caption": cap})


@app.get("/api/tile/{ticker}")
def tile(ticker: str):
    """Watchlist-tile data (CSV-only, zero network): sparkline closes, Δ%, MA arrows,
    latest snapshot's setup score. {tile: null} when too thin/unreadable."""
    return sanitize({"tile": loaders.load_tile(ticker.strip().upper())})


@app.get("/api/econ_calendar")
async def econ_calendar(refresh: bool = False):
    """Two-month FRED release grid (zero network). `refresh=1` is the ONLY network path:
    force-refreshes dates + headline prints from FRED first (needs $env:FRED_API_KEY).
    The refresh runs under GENERATE_LOCK: it captures stdout via the process-global
    redirect_stdout, and overlapping a generate's capture can permanently swap sys.stdout
    onto a dead buffer (LIFO restore across threads)."""
    result = None
    if refresh:
        async with reportgen.GENERATE_LOCK:
            result = await asyncio.to_thread(loaders.refresh_econ_calendar)
    cal = await asyncio.to_thread(loaders.load_econ_calendar)
    return sanitize({"calendar": cal, "refresh": result})


@app.get("/api/ledger/{ticker}")
def ledger(ticker: str):
    """entry.py's forward signal ledger tail + realized-return scoring (S30/S56).
    {ledger: null} when the ticker has no ledger yet."""
    return sanitize({"ledger": loaders.load_ledger(ticker.strip().upper())})


@app.get("/api/seasonality/{ticker}")
def seasonality(ticker: str, asof: str | None = None):
    """Monthly base rates over full history (S53) — display-only forever (the S31 leak
    class); {status: 'ok'|'insufficient', ...} or {status: 'unavailable'}."""
    out = loaders.load_seasonality(ticker.strip().upper(), asof=asof or None)
    return sanitize(out if out is not None else {"status": "unavailable"})


@app.get("/api/earnings_reactions/{ticker}")
def earnings_reactions(ticker: str, asof: str | None = None):
    """Realized post-print reactions (S53); {rows: null} for ETFs / no usable prints."""
    out = loaders.load_earnings_reactions(ticker.strip().upper(), asof=asof or None)
    return sanitize(out if out is not None else {"rows": None})


# Production-ish single-command mode: after `npm run build`, the built frontend is served
# from the same origin. Mounted LAST so /api/* routes always win; harmless no-op when
# web/dist is absent (dev mode — Vite on :5173 proxies /api here instead).
if os.path.isdir(WEB_DIST):
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
