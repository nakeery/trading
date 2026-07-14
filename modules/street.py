"""
Street expectations + news (S58) — analyst context for `lens.py --street`.

Answers "what does the street expect, which way are expectations moving, and why is it moving
today?" — the one report axis that was price/flow-only before. Four yfinance endpoints (probed
live 2026-07-14; these are quoteSummary/news endpoints, NOT the 401-prone `.info`):
`analyst_price_targets` (spot + mean/median/high/low target), `upgrades_downgrades` (grade +
price-target actions; trailing-90d counts), `eps_trend` (current vs 30d-ago estimates per
period — revision momentum, the researched factor), `news` (recent headlines). ETFs return
empty analyst frames and degrade to a headlines-only section (QQQ probed).

CONTEXT only, never a model feature. Cached ~6h per ticker (data/street_cache/{T}.json —
news wants fresher than session-stale); best-effort: never raises, stale cache on failure,
None when nothing is available. Caveat printed by the lens: targets follow price — a wide
"upside" right after a selloff is stale ink, not a signal.
"""

import json
import logging
import os
import time

import pandas as pd

CACHE_DIR = "street_cache"
TTL_HOURS = 6
NEWS_N = 6
UD_LOOKBACK_DAYS = 90
REV_DEAD = 0.005                 # |30d estimate revision| ≤ 0.5% reads flat
PERIOD_LABELS = {"0q": "this qtr", "+1q": "next qtr", "0y": "this yr", "+1y": "next yr"}


def street_read(pt, ud_rows, eps, now=None):
    """PURE: plain-dict endpoint shapes → the analyst read. `pt` = analyst_price_targets dict
    (yfinance keys: current=SPOT, mean/median/high/low = targets); `ud_rows` =
    [{date, firm, to_grade, action, pt_action}]; `eps` = {period: {current, 30daysAgo, ...}}.
    Returns {} for an ETF/uncovered name (all inputs empty). Offline-testable."""
    out = {}
    if pt and pt.get("mean") and pt.get("current"):
        spot, mean = float(pt["current"]), float(pt["mean"])
        out["pt"] = {"spot": spot, "mean": mean, "median": pt.get("median"),
                     "high": pt.get("high"), "low": pt.get("low"),
                     "upside_mean": mean / spot - 1 if spot else None}
    revs = []
    for period in ("0q", "+1q", "0y", "+1y"):
        d = (eps or {}).get(period) or {}
        cur, ago = d.get("current"), d.get("30daysAgo")
        if cur is None or not ago or pd.isna(cur) or pd.isna(ago):
            continue
        chg = float(cur) / float(ago) - 1
        revs.append({"period": period, "label": PERIOD_LABELS[period], "chg30": chg,
                     "tag": "up" if chg > REV_DEAD else "down" if chg < -REV_DEAD else "flat"})
    if revs:
        out["revisions"] = revs
        ups = sum(r["tag"] == "up" for r in revs)
        dns = sum(r["tag"] == "down" for r in revs)
        out["rev_net"] = ("estimates drifting UP" if ups > dns
                          else "estimates drifting DOWN" if dns > ups else "estimates flat")
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.today()
    cutoff = now - pd.Timedelta(days=UD_LOOKBACK_DAYS)
    rows = [r for r in (ud_rows or []) if pd.Timestamp(r["date"]) >= cutoff]
    if rows:
        act = [str(r.get("action", "")).lower() for r in rows]
        pta = [str(r.get("pt_action", "")).lower() for r in rows]
        out["ud"] = {"n": len(rows), "window_days": UD_LOOKBACK_DAYS,
                     "n_up": sum(a == "up" for a in act),
                     "n_down": sum(a == "down" for a in act),
                     "n_init": sum(a == "init" for a in act),
                     "pt_raises": sum(p == "raises" for p in pta),
                     "pt_lowers": sum(p == "lowers" for p in pta),
                     "latest": rows[:5]}
    return out


def _plain_news(items):
    """yfinance news list → [{when, title, provider, url}] (newest first, ≤NEWS_N)."""
    out = []
    for it in items or []:
        c = (it or {}).get("content") or {}
        title = c.get("title")
        if not title:
            continue
        when = str(c.get("pubDate") or c.get("displayTime") or "")
        out.append({"when": when[5:10] if len(when) >= 10 else when,   # MM-DD
                    "title": title,
                    "provider": ((c.get("provider") or {}).get("displayName")) or "?",
                    "url": ((c.get("canonicalUrl") or {}).get("url"))})
        if len(out) >= NEWS_N:
            break
    return out


def fetch_street(ticker, data_dir="data", ttl_hours=TTL_HOURS):
    """Street read + headlines for `ticker`, cached ~6h under data/street_cache/. Never
    raises; stale cache on failure, else None. ETF/uncovered → headlines-only dict."""
    cdir = os.path.join(data_dir, CACHE_DIR)
    path = os.path.join(cdir, f"{ticker.upper()}.json")
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl_hours * 3600:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    try:
        import yfinance as yf
        lg = logging.getLogger("yfinance")
        prev_level = lg.level
        lg.setLevel(logging.CRITICAL)      # ETFs 404 the quoteSummary endpoints — expected noise
        try:
            t = yf.Ticker(ticker)
            try:
                pt = t.analyst_price_targets or {}
            except Exception:
                pt = {}
            ud_rows = []
            try:
                ud = t.upgrades_downgrades
                if ud is not None and len(ud):
                    for when, r in ud.iterrows():
                        ud_rows.append({"date": str(when)[:10], "firm": r.get("Firm"),
                                        "to_grade": r.get("ToGrade"),
                                        "action": r.get("Action"),
                                        "pt_action": r.get("priceTargetAction")})
            except Exception:
                pass
            eps = {}
            try:
                et = t.eps_trend
                if et is not None and len(et):
                    eps = {str(p): {"current": _f(r.get("current")),
                                    "30daysAgo": _f(r.get("30daysAgo"))}
                           for p, r in et.iterrows()}
            except Exception:
                pass
            try:
                news = _plain_news(t.news)
            except Exception:
                news = []
        finally:
            lg.setLevel(prev_level)
        if pt or ud_rows or eps or news:
            out = street_read(pt, ud_rows, eps)
            out["news"] = news
            out["as_of_str"] = time.strftime("%Y-%m-%d %H:%M")
            try:
                os.makedirs(cdir, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(out, f)
            except Exception:
                pass
            return out
    except Exception:
        pass
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)                    # stale fallback beats nothing
    except Exception:
        return None


def _f(v):
    """float or None (NaN-safe) — keeps the cached JSON clean of NaNs."""
    try:
        v = float(v)
        return None if pd.isna(v) else v
    except Exception:
        return None
