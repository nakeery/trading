"""Data loaders + snapshot/diff for the FastAPI backend (S60) — ports lens_web.py's
non-chart loaders. M1 ships the day-over-day snapshot machinery (the /api/report response
carries the diff); the watchlist/econ-calendar/ledger/seasonality loaders join in M3.

Snapshots share data/payload_history/ with the Streamlit app — same format, same pruning —
so history accumulated there keeps working while both UIs run in parallel.
"""

import json
import os
import time

import pandas as pd

from api.cache import cached, ledger_cache, reactions_cache, season_cache, tile_cache

DATA_DIR = "data"
HISTORY_DIR = os.path.join(DATA_DIR, "payload_history")
SNAP_KEEP = 90            # snapshots kept per ticker
GAUGE_MOVE_PP = 0.10      # gauge percentile move worth surfacing (10 points)


# ── day-over-day snapshots + diff (ports lens_web.py S56) ────────────────────
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
            "regime": (risk.get("regime") or {}).get("label")}   # S57 trend regime


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
    # trend-regime flip (S57) — only when the prior snapshot carries the key (pre-S57
    # snapshots don't; a missing→labeled transition would otherwise read as a day-one flip)
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


# ── watchlist tiles (ports lens_web.py load_tile + the snapshot setup chip) ──
def load_tile(ticker):
    """Watchlist-tile data off the indicators CSV — zero network. None when the file is
    unreadable/too thin. Adds the latest snapshot's setup score when one exists."""
    def _load():
        path = os.path.join(DATA_DIR, f"{ticker.lower()}_indicators.csv")
        try:
            c = pd.read_csv(path, index_col=0, parse_dates=True)["Close"].dropna()
            if len(c) < 21:
                return None
            last, prev = float(c.iloc[-1]), float(c.iloc[-2])
            ma20 = float(c.rolling(20).mean().iloc[-1])
            ma50 = float(c.rolling(50).mean().iloc[-1]) if len(c) >= 50 else None
            out = {"ticker": ticker.upper(),
                   "closes": [float(v) for v in c.tail(60)], "last": last,
                   "chg": last / prev - 1 if prev else 0.0,
                   "ma20_up": bool(last >= ma20),
                   "ma50_up": bool(last >= ma50) if ma50 is not None else None,
                   "as_of": c.index[-1].date().isoformat(), "setup": None}
            try:
                d = os.path.join(HISTORY_DIR, ticker.lower())
                snaps = sorted(f for f in os.listdir(d) if f.endswith(".json"))
                if snaps:
                    with open(os.path.join(d, snaps[-1]), encoding="utf-8") as f:
                        marks = list((json.load(f).get("setup") or {}).values())
                    if marks:
                        out["setup"] = {"ok": sum(1 for m in marks if m == "✓"),
                                        "total": len(marks)}
            except Exception:
                pass
            return out
        except Exception:
            return None
    return cached(tile_cache, ticker.upper(), _load)


# ── econ calendar (ports lens_web.py load_econ_calendar — structured for React) ──
def load_econ_calendar():
    """Two-month econ-release window + per-series coverage + cache age — ZERO network
    (reads data/econ_calendar.csv + econ_results.json). None when unavailable."""
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
            # chip → the FRED GRAPH of the headline data series; release page only as a
            # fallback for series without a headline mapping
            url = (f"https://fred.stlouisfed.org/series/{HEADLINE_SERIES[s][0]}"
                   if s in HEADLINE_SERIES
                   else f"https://fred.stlouisfed.org/release?rid={rid[s]}" if s in rid
                   else None)
            res = headline_result(s, d, results.get(s) or [])
            events.append({"date": d.date().isoformat(), "series": s, "tier": int(t),
                           "url": url, "result": res, "release_name": str(rn)})
        cov = {k: (v.date().isoformat() if v is not None else None)
               for k, v in coverage_end_per_series().items()}
        path = os.path.join(DATA_DIR, "econ_calendar.csv")
        mtime = os.path.getmtime(path) if os.path.exists(path) else None
        months = [{"year": int(m.year), "month": int(m.month)}
                  for m in (start, start + pd.offsets.MonthBegin(1))]
        return {"events": events, "coverage": cov,
                "age_days": (time.time() - mtime) / 86400 if mtime else None,
                "months": months, "today": today.date().isoformat(),
                "grid_end": end.date().isoformat()}
    except Exception:
        return None


def refresh_econ_calendar():
    """The ONLY network path for the calendar: force-refresh release dates + headline
    results from FRED (never raises, never overwrites a good cache with a worse one)."""
    import contextlib
    import io
    try:
        from modules.econ_calendar import fetch_release_results, refresh_if_stale
    except Exception:
        return {"status": "unavailable", "message": "econ_calendar module import failed"}
    # stdout captured: the module prints per-series ✓ progress lines
    with contextlib.redirect_stdout(io.StringIO()):
        status, msg = refresh_if_stale(max_age_days=-1)     # -1 = TRUE force
        _r_status, r_msg = fetch_release_results(DATA_DIR)
    return {"status": status, "message": f"{msg} · {r_msg}"}


# ── signal ledger (ports lens_web.py load_ledger + load_ledger_score, merged) ──
def load_ledger(ticker, rows=30):
    """Tail of entry.py's forward signal ledger with realized-return scoring merged in
    (score_ledger.score — zero network). None when the ticker has no ledger yet."""
    def _load():
        path = os.path.join(DATA_DIR, f"{ticker.lower()}_signal_ledger.csv")
        if not os.path.exists(path):
            return None
        try:
            df = pd.read_csv(path)
            if not len(df):
                return None
            df = df.tail(rows)
            out = {"columns": list(df.columns),
                   "rows": df.where(pd.notna(df), None).to_dict("records"),
                   "score": None}
            try:
                from score_ledger import score
                res = score(ticker, DATA_DIR)
                if res.get("status") == "ok":
                    out["score"] = {"rows": res["rows"], "summary": res["summary"],
                                    "pending15": res["pending15"],
                                    "pending63": res["pending63"]}
            except Exception:
                pass
            return out
        except Exception:
            return None
    return cached(ledger_cache, ticker.upper(), _load)


# ── seasonality + earnings reactions (ports lens_web.py S53 loaders) ─────────
def load_seasonality(ticker, asof=None):
    """Monthly seasonality base rates — needs the FULL daily history (decades). `asof`
    truncates so post-as-of months can't leak into a backtest view. None on failure."""
    def _load():
        try:
            from api.charts import load_daily_full
            from modules.seasonality import monthly_seasonality
            close = load_daily_full(ticker)["Close"]
            if asof:
                close = close.loc[:pd.Timestamp(asof)]
            return monthly_seasonality(close)
        except Exception:
            return None
    return cached(season_cache, (ticker.upper(), asof), _load)


def load_earnings_reactions(ticker, n=10, asof=None):
    """Realized post-print reactions: gap/1d/5d + pre-print IV per past earnings —
    indicators CSV + the yfinance earnings-dates call (cached ~1h). None for ETFs /
    no CSV / no usable prints."""
    def _load():
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
    return cached(reactions_cache, (ticker.upper(), asof), _load)


def snapshot_and_diff(ticker, payload):
    """Save today's snapshot and return the diff vs the prior stored session (the data
    behind the 'Δ what changed' panel): {prev_as_of, prev_close, close, changes} — changes
    None when nothing notable moved; the whole thing None with no history. Callers must
    skip this in as-of mode (a backtest rerun must not overwrite that date's REAL
    end-of-day snapshot)."""
    cur = snap_from_payload(payload)
    if not cur["as_of"]:
        return None
    save_snapshot(ticker, payload)
    prev = load_prev_snapshot(ticker, cur["as_of"])
    if not prev:
        return None
    return {"prev_as_of": prev.get("as_of"), "prev_close": prev.get("close"),
            "close": cur.get("close"), "changes": diff_snapshots(prev, cur)}
