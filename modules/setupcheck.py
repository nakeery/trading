"""
Setup-quality checklist (S41) — a default-on lens block.

A transparent ✓/✗/– COMPLETENESS check over reads the lens already computes (plus one new
relative-strength-vs-benchmark row). It does NOT score edge or probability — the S32 lesson stands
(free-data prediction is marginal); what a checklist CAN do is catch blind spots and disqualifiers
before the user takes their own chart-based entry: trading against the higher timeframe, buying an
unconfirmed rally, paying very-rich vol, or sitting on an earnings print unintentionally.

Marks: ✓ favorable · ✗ against · – flagged/neutral/unavailable. Every row carries its reading.
"""

import os
import time

import pandas as pd

from modules import netcache

TIER1_MACRO = {"FOMC", "CPI", "NFP", "PCE"}   # mirror econ_calendar Tier-1 (display-only here)
RS_HORIZONS = (20, 63)                        # sessions — classic momentum/RS lookbacks
EARN_FLAG_DAYS = 7                            # earnings inside this window = flagged (not failed)
IV_HV_RICH = 1.40                             # mirror sentiment.IV_HV_RICH


def rel_strength(closes, bench_closes, horizons=RS_HORIZONS):
    """Ticker return minus benchmark return per horizon (pure). {h: diff} or None if too short."""
    out = {}
    c = pd.Series(closes).dropna()
    b = pd.Series(bench_closes).dropna()
    for h in horizons:
        if len(c) > h and len(b) > h:
            out[h] = float(c.iloc[-1] / c.iloc[-1 - h] - 1) - float(b.iloc[-1] / b.iloc[-1 - h] - 1)
    return out or None


def _cached_closes(syms, data_dir="data"):
    """Per-symbol 6mo daily closes behind a session-stale disk cache (S70) —
    data/rs_cache/{sym}.json {as_of, close}. Stale/missing symbols batch into ONE
    yf.download; per-symbol stale fallback when the download misses. SPY dedupes across
    fetch_rs, fetch_beta, and tickers sharing a benchmark. Returns a close DataFrame
    (one column per resolved symbol) or None. Never raises."""
    try:
        import yfinance as yf
        syms = list(dict.fromkeys(syms))

        def _path(s):
            return os.path.join(data_dir, "rs_cache", f"{s.strip('^').lower()}.json")

        def _ser(c):
            s = pd.Series({pd.Timestamp(k): float(v) for k, v in (c.get("close") or {}).items()})
            return s.sort_index()

        series, stale = {}, []
        for s in syms:
            c = netcache.load_json(_path(s))
            if c and netcache.session_fresh(c.get("as_of")) and c.get("close"):
                series[s] = _ser(c)
            else:
                stale.append((s, c))
        if stale:
            close = None
            try:
                raw = yf.download([s for s, _ in stale], period="6mo", interval="1d",
                                  progress=False, auto_adjust=True)
                if raw is not None and len(raw):
                    # per-symbol Close columns in both shapes (the S61 _close_frame lesson): a
                    # list download returns MultiIndex (field, symbol); yfinance flattens to
                    # single-level columns when exactly one symbol survives
                    if isinstance(raw.columns, pd.MultiIndex):
                        close = raw["Close"]
                    else:
                        close = raw[["Close"]].rename(columns={"Close": stale[0][0]})
            except Exception:
                close = None
            for s, c in stale:
                ser = close[s].dropna() if (close is not None and s in close.columns) else None
                if ser is not None and len(ser):
                    idx = (ser.index.tz_convert(None)
                           if getattr(ser.index, "tz", None) is not None else ser.index)
                    netcache.save_json(_path(s), {
                        "as_of": time.time(),
                        "close": {d.strftime("%Y-%m-%d"): float(v)
                                  for d, v in zip(idx.normalize(), ser)}})
                    series[s] = ser
                elif c and c.get("close"):              # stale fallback — old rows beat no rows
                    series[s] = _ser(c)
        if not series:
            return None
        return pd.concat(series, axis=1)
    except Exception:
        return None


def fetch_rs(ticker, daily, data_dir="data", extra=None):
    """Best-effort relative strength vs the ticker's sector benchmark (TICKER_BENCHMARK first
    entry; SPY fallback). One yfinance daily fetch; returns {bench, rs:{h: diff}} or None.
    `extra` (S67) = optional list of (sym, label) comparators — e.g. the equal-weight twin from
    sectors.ew_comparator — that ride the SAME single download by passing a symbol LIST; each
    that computes lands in out["extra"][sym] = {"label", "rs": {h: diff}}. With extra=None the
    return shape and the benchmark math are unchanged (no "extra" key)."""
    try:
        from modules.benchmarks import TICKER_BENCHMARK
        pairs = TICKER_BENCHMARK.get(ticker.upper())
        sym, name = (pairs[0] if pairs else ("SPY", "SPY"))
        extras = [(s, lbl) for s, lbl in (extra or []) if s != sym]
        syms = [sym] + [s for s, _ in extras]
        close = _cached_closes(syms, data_dir)          # session-stale cache (S70)
        if close is None or len(close) == 0:
            return None

        def _rs_vs(s):
            if s not in close.columns:
                return None
            ser = close[s].dropna()
            if not len(ser):
                return None
            # align both series to the common last date — the bench can carry a fresher (or
            # partial-today) bar than the ticker's CSV series, which would skew the short horizon
            last = min(daily.index[-1], ser.index[-1])
            return rel_strength(daily.loc[:last, "Close"], ser.loc[:last])

        rs = _rs_vs(sym)
        if not rs:
            return None
        out = {"bench": name, "rs": rs}
        for s, lbl in extras:
            rs_e = _rs_vs(s)
            if rs_e:
                out.setdefault("extra", {})[s] = {"label": lbl, "rs": rs_e}
        return out
    except Exception:
        return None


def beta_corr(closes, bench_closes, window=60):
    """PURE (S46): trailing OLS beta (cov/var of daily returns) + Pearson correlation vs the
    benchmark over the last `window` aligned sessions. {beta, corr, n} or None when too short
    (<20 returns) or the benchmark is degenerate (zero variance)."""
    c = pd.Series(closes, dtype=float).dropna().pct_change()
    b = pd.Series(bench_closes, dtype=float).dropna().pct_change()
    df = pd.concat([c, b], axis=1, join="inner", keys=["s", "m"]).dropna().iloc[-window:]
    if len(df) < 20:
        return None
    var = float(df["m"].var())
    if not var:
        return None
    return {"beta": float(df["s"].cov(df["m"]) / var),
            "corr": float(df["s"].corr(df["m"])), "n": len(df)}


def fetch_beta(ticker, daily, window=60, data_dir="data"):
    """Best-effort 60d beta/corr vs SPY (S46) — how much the MARKET BACKDROP applies to THIS name.
    SPY closes come from the shared session-stale rs_cache (S70) — a pure cache hit whenever
    fetch_rs already pulled SPY this session. Aligned to the common last date like fetch_rs;
    None on any failure."""
    try:
        close = _cached_closes(("SPY",), data_dir)
        if close is None or "SPY" not in close.columns:
            return None
        ser = close["SPY"].dropna()
        if not len(ser):
            return None
        last = min(daily.index[-1], ser.index[-1])
        return beta_corr(daily.loc[:last, "Close"], ser.loc[:last], window=window)
    except Exception:
        return None


def _gauge(ctx, name):
    for g in (ctx or {}).get("gauges", []):
        if g.get("name") == name:
            return g.get("value")
    return None


def setup_check(reads, profile=None, ctx=None, earn=None, macro_tier1_days=None, rs=None,
                beta=None, ex_div=None):
    """Build the checklist. `reads` = lens per-TF reads (needs '1D'; uses 1W/1M when present);
    `profile` = volume_profile dict; `ctx` = gather_context result; `earn` = next_earnings dict;
    `macro_tier1_days` = days to the nearest Tier-1 release (None = unknown); `rs` = fetch_rs
    result; `beta` = beta_corr/fetch_beta result (S46 — informational, never ✓/✗); `ex_div` =
    features.next_ex_dividend result (S46 — appended to the catalyst row). Pure — all inputs
    injectable. Returns {rows: [(label, mark, detail)], net, footer}."""
    rows = []

    # 1. higher-timeframe alignment
    tfs = [t for t in ("1D", "1W", "1M") if t in (reads or {})]
    if tfs:
        trends = {t: reads[t].get("trend") for t in tfs}
        desc = "/".join(f"{t} {v}" for t, v in trends.items())
        if all(v == "up" for v in trends.values()):
            rows.append(("HTF alignment", "✓", f"all up ({desc})"))
        elif all(v == "down" for v in trends.values()):
            rows.append(("HTF alignment", "✗", f"aligned DOWN ({desc}) — that's a short-side tape"))
        elif "down" in trends.values():
            rows.append(("HTF alignment", "✗", f"opposed ({desc})"))
        else:
            rows.append(("HTF alignment", "–", f"mixed ({desc})"))
    else:
        rows.append(("HTF alignment", "–", "n/a (no daily reads)"))

    # 2. daily momentum room
    r1d = (reads or {}).get("1D") or {}
    rsi, state = r1d.get("rsi"), r1d.get("rsi_state")
    if rsi is not None:
        if state == "overbought":
            rows.append(("Momentum room", "✗", f"1D RSI {rsi:.0f} overbought — chasing"))
        elif state == "oversold":
            rows.append(("Momentum room", "✓", f"1D RSI {rsi:.0f} oversold — room (falling-knife check: HTF row)"))
        else:
            rows.append(("Momentum room", "✓", f"1D RSI {rsi:.0f} — room either way"))
    else:
        rows.append(("Momentum room", "–", "n/a"))

    # 3. volume confirmation
    tag = (r1d.get("_vol") or {}).get("tag")
    if tag == "up-confirmed":
        rows.append(("Volume confirms", "✓", "1D up-move on expanding volume"))
    elif tag == "up-WEAK":
        rows.append(("Volume confirms", "✗", "1D rally on falling volume — unconfirmed"))
    elif tag == "dn-distrib":
        rows.append(("Volume confirms", "✗", "1D distribution (down on rising volume)"))
    elif tag == "dn-exhaust":
        rows.append(("Volume confirms", "–", "1D downtrend exhausting (watch for the turn)"))
    else:
        rows.append(("Volume confirms", "–", "n/a"))

    # 4. relative strength vs benchmark
    if rs and rs.get("rs"):
        vals = rs["rs"]
        detail = " / ".join(f"{v:+.1%} {h}d" for h, v in sorted(vals.items()))
        if all(v > 0 for v in vals.values()):
            rows.append(("Relative strength", "✓", f"leading {rs['bench']} ({detail})"))
        elif all(v < 0 for v in vals.values()):
            rows.append(("Relative strength", "✗", f"lagging {rs['bench']} ({detail})"))
        else:
            rows.append(("Relative strength", "–", f"mixed vs {rs['bench']} ({detail})"))
    else:
        rows.append(("Relative strength", "–", "n/a (benchmark data unavailable)"))

    # 4b. market coupling (S46) — how much the MARKET BACKDROP applies to THIS name. Always
    # informational ("–"): high or low coupling is neither favorable nor against by itself.
    if beta and beta.get("corr") is not None:
        bc = f"β {beta['beta']:.2f} / corr {beta['corr']:.2f} vs SPY ({beta.get('n', 60)}d)"
        if beta["corr"] >= 0.6:
            rows.append(("Market beta", "–", f"{bc} — backdrop applies"))
        elif beta["corr"] < 0.3:
            rows.append(("Market beta", "–", f"{bc} — largely idiosyncratic; backdrop matters less"))
        else:
            rows.append(("Market beta", "–", f"{bc} — moderate coupling"))
    else:
        rows.append(("Market beta", "–", "n/a"))

    # 5. location vs volume structure
    if profile:
        loc = profile.get("price_location")
        sup = profile.get("near_hvn_below")           # proximity-filtered (±HVN_NEAR_PCT, S43)
        sup_s = f"; HVN support {sup:.2f} below" if sup else "; no HVN support nearby"
        if loc == "in_value":
            rows.append(("Location", "✓", f"inside value area{sup_s}"))
        elif loc == "above_value":
            rows.append(("Location", "–", f"extended above value (chase risk){sup_s}"))
        else:
            rows.append(("Location", "–", f"below value (discount, but out of favor){sup_s}"))
    else:
        rows.append(("Location", "–", "n/a (no volume profile)"))

    # 6. vol regime
    iv_hv = _gauge(ctx, "IV/HV ratio")
    regime = (ctx or {}).get("regime")
    if iv_hv is not None or regime not in (None, "n/a"):
        if iv_hv is not None and iv_hv >= IV_HV_RICH:
            rows.append(("Vol regime", "✗", f"IV/HV {iv_hv:.2f} very rich — long-premium entries handicapped"))
        elif regime == "stress":
            rows.append(("Vol regime", "–", "VIX stress — historically contrarian-BUY here (S21), but size sanely"))
        else:
            iv_s = f"IV/HV {iv_hv:.2f}, " if iv_hv is not None else ""
            rows.append(("Vol regime", "✓", f"{iv_s}VIX regime {regime or 'n/a'}"))
    else:
        rows.append(("Vol regime", "–", "n/a"))

    # 7. catalyst timing — flagged, not failed: sitting on a print may be intentional (vol plays)
    parts, mark = [], "✓"
    if earn and earn.get("days") is not None:
        if earn.get("est"):
            # S74: the date is a cadence ESTIMATE — yfinance has no future date but the past
            # prints say one is due. Near the estimate (incl. slightly past — the grace window)
            # this is exactly the blind spot the row exists to catch; never a confident ✓.
            if earn["days"] <= EARN_FLAG_DAYS:
                mark = "–"
                last = (f"last confirmed print {earn['last_days']}d ago, "
                        if earn.get("last_days") is not None else "")
                parts.append(f"earnings date unavailable — {last}next ~{earn.get('date')} (est)")
            else:
                parts.append(f"earnings ~{earn['days']}d out (est)")
        elif 0 <= earn["days"] <= EARN_FLAG_DAYS:
            mark = "–"
            parts.append(f"earnings in {earn['days']}d ({earn.get('date')}) — inside the holding window")
        else:
            parts.append(f"earnings {earn['days']}d out")
    else:
        parts.append("no earnings date")
    if macro_tier1_days is not None and macro_tier1_days <= 1:
        mark = "–"
        parts.append("Tier-1 macro ≤1d (FOMC/CPI/NFP/PCE)")
    if ex_div and ex_div.get("days") is not None and 0 <= ex_div["days"] <= 45:
        # informational (mark unchanged): a long call doesn't earn the dividend, and deep-ITM
        # calls face early-exercise into ex-div (S46)
        pre = "~" if ex_div.get("est") else ""
        parts.append(f"ex-div {pre}{ex_div['date']} ({ex_div['days']}d) — calls don't earn it; "
                     f"deep-ITM early-exercise risk")
    rows.append(("Catalyst timing", mark, "; ".join(parts)))

    n_ok = sum(1 for _, m, _ in rows if m == "✓")
    n_flag = sum(1 for _, m, _ in rows if m == "–")
    n_bad = sum(1 for _, m, _ in rows if m == "✗")
    net = f"{n_ok}/{len(rows)} favorable · {n_flag} flagged · {n_bad} against"
    footer = "completeness check, not a probability — the entry edge is yours; this catches blind spots"
    return {"rows": rows, "net": net, "footer": footer,
            "n_ok": n_ok, "n_flag": n_flag, "n_bad": n_bad}
