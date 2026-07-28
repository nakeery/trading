"""
lens_score — score the lens' OWN reads against realized forward returns (S65).

score_ledger.py scores the archived entry.py ML signals; nothing scored the lens itself. The
web app's day-over-day snapshots (data/payload_history/{ticker}/{date}.json — setup marks,
rally/drawdown factor lists, trend-regime label, close; written on every report run since S56)
are exactly a dated record of what the lens said. This joins each snapshot to the realized
15d/63d forward return off the indicators CSV closes and aggregates three ways:

    setup band    ≥6 ✓ / 4–5 ✓ / ≤3 ✓         (completeness score at the time)
    regime        ESTABLISHED UPTREND / DOWNTREND / none
    risk lean     dd>rally / rally>dd / balanced

    python lens_score.py --ticker QQQ

HONESTY CONTRACT (printed on every run): snapshots exist only for sessions the lens was run;
N is small and sessions are NOT independent (adjacent runs share most of their forward
window); averages/medians only — no win thresholds, NO significance claims. This scores
report-completeness vs forward drift, not an edge. Descriptive only — never a model input.

Reusable: `score(ticker, data_dir)` returns a status dict (score_ledger pattern, never
raises); the web LensScore expander renders it zero-network via /api/lens_score.
"""

import argparse
import json
import os

import pandas as pd

HORIZONS = (15, 63)                    # sessions — mirror score_ledger / the risk windows
SCORE_BANDS = ((6, 99, "≥6 ✓"), (4, 5, "4–5 ✓"), (0, 3, "≤3 ✓"))


def load_snapshots(ticker, data_dir="data"):
    """All stored payload snapshots for `ticker`, sorted by as_of date. [] when none."""
    d = os.path.join(data_dir, "payload_history", ticker.lower())
    out = []
    try:
        for fname in sorted(f for f in os.listdir(d) if f.endswith(".json")):
            try:
                with open(os.path.join(d, fname), encoding="utf-8") as f:
                    snap = json.load(f)
                if isinstance(snap, dict) and snap.get("as_of"):
                    out.append(snap)
            except Exception:
                continue
    except Exception:
        return []
    return out


def snapshot_row(snap):
    """PURE: one snapshot → the scoreable row {as_of, ok, total, n_dd, n_rally, regime}."""
    marks = list((snap.get("setup") or {}).values())
    return {"as_of": snap.get("as_of"),
            "ok": sum(1 for m in marks if m == "✓"), "total": len(marks),
            "n_dd": len(snap.get("dd") or []), "n_rally": len(snap.get("rally") or []),
            "regime": snap.get("regime")}


def _fwd(close, i, n):
    """Return over n SESSIONS from position i, or None past the data (score_ledger convention)."""
    if i + n >= len(close):
        return None
    base = float(close.iloc[i])
    return float(close.iloc[i + n]) / base - 1 if base else None


def score_snapshots(rows, close):
    """PURE: rows + a datetime-indexed Close series → rows + fwd15/fwd63 (None = pending)."""
    close = close.dropna().sort_index()
    out = []
    for r in rows:
        pos = close.index.searchsorted(pd.Timestamp(r["as_of"]).normalize())
        fwd15 = _fwd(close, pos, 15) if pos < len(close) else None
        fwd63 = _fwd(close, pos, 63) if pos < len(close) else None
        out.append({**r, "fwd15": fwd15, "fwd63": fwd63})
    return out


def _band(ok):
    for lo, hi, label in SCORE_BANDS:
        if lo <= ok <= hi:
            return label
    return SCORE_BANDS[-1][2]


def _lean(r):
    if r["n_dd"] > r["n_rally"]:
        return "dd>rally"
    if r["n_rally"] > r["n_dd"]:
        return "rally>dd"
    return "balanced"


def _regime_key(r):
    reg = r.get("regime")
    if not reg:
        return "no regime"
    return "UPTREND" if "UP" in reg else "DOWNTREND"


def aggregate(scored):
    """PURE: scored rows → {'bands': {...}, 'regimes': {...}, 'leans': {...}} — per cell
    {n, scored15, avg15, med15, scored63, avg63, med63}. Averages/medians ONLY (no win
    thresholds, no significance). Empty cells are absent, never zero-filled."""
    def cell(sub):
        s15 = [x["fwd15"] for x in sub if x["fwd15"] is not None]
        s63 = [x["fwd63"] for x in sub if x["fwd63"] is not None]
        def med(v):
            return float(pd.Series(v).median()) if v else None
        return {"n": len(sub),
                "scored15": len(s15), "avg15": sum(s15) / len(s15) if s15 else None,
                "med15": med(s15),
                "scored63": len(s63), "avg63": sum(s63) / len(s63) if s63 else None,
                "med63": med(s63)}

    def group(keyfn, order=None):
        keys = list(dict.fromkeys(keyfn(r) for r in scored))
        if order:
            keys = [k for k in order if k in keys] + [k for k in keys if k not in order]
        return {k: cell([r for r in scored if keyfn(r) == k]) for k in keys}

    return {"bands": group(lambda r: _band(r["ok"]),
                           order=[b[2] for b in SCORE_BANDS]),
            "regimes": group(_regime_key, order=["UPTREND", "DOWNTREND", "no regime"]),
            "leans": group(_lean, order=["rally>dd", "balanced", "dd>rally"])}


def score(ticker, data_dir="data"):
    """Orchestrator (never raises): {'status': 'ok'|'no_snapshots'|'no_csv'|'error:…',
    'ticker', 'rows', 'bands', 'regimes', 'leans', 'n', 'first', 'last',
    'pending15', 'pending63', 'note'}."""
    try:
        snaps = load_snapshots(ticker, data_dir)
        if not snaps:
            return {"status": "no_snapshots", "ticker": ticker}
        cpath = os.path.join(data_dir, f"{ticker.lower()}_indicators.csv")
        if not os.path.exists(cpath):
            return {"status": "no_csv", "ticker": ticker}
        close = pd.read_csv(cpath, index_col=0, parse_dates=True)["Close"]
        scored = score_snapshots([snapshot_row(s) for s in snaps], close)
        agg = aggregate(scored)
        note = (f"{len(scored)} snapshots since {scored[0]['as_of']} — only sessions the lens "
                f"was run; small N, sessions are NOT independent, and NO significance is "
                f"claimed. This scores report-completeness vs forward drift, not an edge.")
        return {"status": "ok", "ticker": ticker, "rows": scored, **agg,
                "n": len(scored), "first": scored[0]["as_of"], "last": scored[-1]["as_of"],
                "pending15": sum(1 for r in scored if r["fwd15"] is None),
                "pending63": sum(1 for r in scored if r["fwd63"] is None),
                "note": note}
    except Exception as e:
        return {"status": f"error:{type(e).__name__}", "ticker": ticker}


def _pct(v):
    return "—" if v is None else f"{v:+.1%}"


def print_scorecard(res):
    t = res.get("ticker", "?")
    if res.get("status") != "ok":
        print(f"  {t}: lens self-score unavailable ({res.get('status')} — snapshots "
              f"accumulate under data/payload_history/ as reports run)")
        return
    print(f"\n  LENS SELF-SCORE — {t}  ({res['n']} snapshots, {res['first']} → {res['last']};"
          f" {res['pending15']} pending 15d, {res['pending63']} pending 63d)")
    for title, key in (("setup band", "bands"), ("trend regime", "regimes"),
                       ("risk lean", "leans")):
        print(f"\n  {title:<14} {'n':>4}  {'avg 15d':>8} {'med 15d':>8}  "
              f"{'avg 63d':>8} {'med 63d':>8}")
        for k, c in res[key].items():
            print(f"  {k:<14} {c['n']:>4}  {_pct(c['avg15']):>8} {_pct(c['med15']):>8}  "
                  f"{_pct(c['avg63']):>8} {_pct(c['med63']):>8}")
    print(f"\n  · {res['note']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Score the lens' own snapshots vs realized forward returns.")
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
