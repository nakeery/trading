"""
score_ledger — the forward signal-ledger scorer (S56; the S30 standing TODO).

Joins `data/{ticker}_signal_ledger.csv` (one row per entry.py as-of run date) to REALIZED
forward returns off the indicators CSV closes — the first true out-of-sample read on the ML
layer. Each ledger row is scored against ITS OWN stamped thresholds (`win_threshold` /
`win_threshold_63`, the vol-adjusted bars computed at signal time — same bar as backtest.py),
so a threshold recalibration later never rewrites history.

    python score_ledger.py --ticker QQQ        # or bare → ticker prompt

Reusable: `score(ticker, data_dir)` returns a status dict (no sys.exit) — lens_web.py's
signal-ledger expander renders it zero-network. Rows younger than the horizon are "pending".
Descriptive only — nothing here feeds a model.
"""

import argparse
import os

import pandas as pd

HORIZONS = (15, 63)          # sessions — Phase 2 / Phase 2B forward windows
MIN_SCORED_NOTE = 10         # below this many scored rows, print the small-sample caveat


def _thresh(v):
    """Stamped threshold cell → positive float, or None when missing/NaN/0 (row scores as
    unscored '—', never a fake loss — float('nan' or 0) is NaN and NaN comparisons are False)."""
    try:
        if v is None or pd.isna(v):
            return None
        f = float(v)
        return f if f else None
    except (TypeError, ValueError):
        return None


def _fwd(close, i, n):
    """Return over n SESSIONS from position i (close-to-close), or None when the window
    extends past the data."""
    if i + n >= len(close):
        return None
    base = float(close.iloc[i])
    return float(close.iloc[i + n]) / base - 1 if base else None


def score(ticker, data_dir="data"):
    """Score every ledger row with realized 15d/63d forward returns + WIN tags vs the row's
    own stamped thresholds. Returns a dict:
      {status: 'ok'|'no_ledger'|'no_csv'|'empty',
       rows: [{date, signal, fwd15, win15, fwd63, win63}, …] (newest first),
       summary: {signal: {n, scored15, avg15, win15, scored63, avg63, win63}},
       baseline: same-shape aggregate over ALL rows, n_rows, pending15, pending63}
    Never raises."""
    try:
        lpath = os.path.join(data_dir, f"{ticker.lower()}_signal_ledger.csv")
        if not os.path.exists(lpath):
            return {"status": "no_ledger", "ticker": ticker}
        ledger = pd.read_csv(lpath, parse_dates=["date"])
        if not len(ledger):
            return {"status": "empty", "ticker": ticker}
        cpath = os.path.join(data_dir, f"{ticker.lower()}_indicators.csv")
        if not os.path.exists(cpath):
            return {"status": "no_csv", "ticker": ticker}
        close = (pd.read_csv(cpath, index_col=0, parse_dates=True)["Close"]
                 .dropna().sort_index())

        rows = []
        for _, r in ledger.iterrows():
            d = pd.Timestamp(r["date"]).normalize()
            pos = close.index.searchsorted(d)
            # score from the as-of session itself; a ledger date missing from the CSV
            # (e.g. pre-close run stamped a NaN-OHLCV row) snaps to the next session
            if pos >= len(close):
                fwd15 = fwd63 = None
            else:
                fwd15, fwd63 = _fwd(close, pos, 15), _fwd(close, pos, 63)
            th15 = _thresh(r.get("win_threshold"))
            th63 = _thresh(r.get("win_threshold_63"))
            rows.append({
                "date": d.date().isoformat(), "signal": str(r.get("signal", "")),
                "fwd15": fwd15, "win15": (fwd15 >= th15) if (fwd15 is not None and th15) else None,
                "fwd63": fwd63, "win63": (fwd63 >= th63) if (fwd63 is not None and th63) else None,
            })
        rows.sort(key=lambda x: x["date"], reverse=True)

        def agg(sub):
            s15 = [x for x in sub if x["fwd15"] is not None]
            s63 = [x for x in sub if x["fwd63"] is not None]
            w15 = [x for x in s15 if x["win15"] is not None]
            w63 = [x for x in s63 if x["win63"] is not None]
            return {"n": len(sub),
                    "scored15": len(s15),
                    "avg15": sum(x["fwd15"] for x in s15) / len(s15) if s15 else None,
                    "win15": sum(x["win15"] for x in w15) / len(w15) if w15 else None,
                    "scored63": len(s63),
                    "avg63": sum(x["fwd63"] for x in s63) / len(s63) if s63 else None,
                    "win63": sum(x["win63"] for x in w63) / len(w63) if w63 else None}

        summary = {sig: agg([x for x in rows if x["signal"] == sig])
                   for sig in sorted({x["signal"] for x in rows})}
        baseline = agg(rows)
        return {"status": "ok", "ticker": ticker, "rows": rows, "summary": summary,
                "baseline": baseline, "n_rows": len(rows),
                "pending15": sum(1 for x in rows if x["fwd15"] is None),
                "pending63": sum(1 for x in rows if x["fwd63"] is None)}
    except Exception as e:
        return {"status": f"error:{type(e).__name__}", "ticker": ticker}


def _pct(v, signed=True):
    if v is None:
        return "pending"
    return f"{v:+.1%}" if signed else f"{v:.0%}"


def print_scorecard(res):
    t = res.get("ticker", "?")
    if res.get("status") != "ok":
        print(f"  {t}: ledger not scoreable ({res.get('status')})")
        return
    print(f"\n  SIGNAL LEDGER SCORECARD — {t}  ({res['n_rows']} rows; "
          f"{res['pending15']} pending 15d, {res['pending63']} pending 63d)")
    print(f"  {'Date':>10}  {'Signal':<16} {'fwd 15d':>8} {'win':>4}  {'fwd 63d':>8} {'win':>4}")
    for r in res["rows"]:
        w15 = "—" if r["win15"] is None else ("✓" if r["win15"] else "✗")
        w63 = "—" if r["win63"] is None else ("✓" if r["win63"] else "✗")
        print(f"  {r['date']:>10}  {r['signal']:<16} {_pct(r['fwd15']):>8} {w15:>4}"
              f"  {_pct(r['fwd63']):>8} {w63:>4}")
    print(f"\n  {'Signal':<16} {'n':>3}  {'avg 15d':>8} {'win15':>6}  {'avg 63d':>8} {'win63':>6}")
    for sig, a in res["summary"].items():
        print(f"  {sig:<16} {a['n']:>3}  {_pct(a['avg15']):>8} "
              f"{_pct(a['win15'], signed=False) if a['win15'] is not None else '—':>6}"
              f"  {_pct(a['avg63']):>8} "
              f"{_pct(a['win63'], signed=False) if a['win63'] is not None else '—':>6}")
    b = res["baseline"]
    print(f"  {'ALL ROWS':<16} {b['n']:>3}  {_pct(b['avg15']):>8} "
          f"{_pct(b['win15'], signed=False) if b['win15'] is not None else '—':>6}"
          f"  {_pct(b['avg63']):>8} "
          f"{_pct(b['win63'], signed=False) if b['win63'] is not None else '—':>6}")
    print(f"\n  · win = fwd return ≥ the row's own vol-adjusted threshold (the backtest bar), "
          f"for EVERY tier — on a STAY OUT row a ✗ means staying out was right")
    scored = res["n_rows"] - res["pending15"]
    if scored < MIN_SCORED_NOTE:
        print(f"  · only {scored} scored rows — directional read only; the ledger matures "
              f"with each entry.py run")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Score the forward signal ledger against realized returns.")
    ap.add_argument("--ticker", help="Ticker (skips the prompt).")
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()
    ticker = args.ticker
    if not ticker:
        try:
            ticker = input("  Ticker [QQQ]: ").strip().upper() or "QQQ"
        except EOFError:
            ticker = "QQQ"
    print_scorecard(score(ticker.upper(), args.data_dir))
