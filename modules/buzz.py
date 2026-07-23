"""
ApeWisdom retail-attention gauge (S56) — crowd-buzz context for the lens `--squeeze` block.

Keyless public API (probed live 2026-07-12): ticker mention ranks across the stock boards
(r/wallstreetbets, r/stocks, r/options, …), refreshed every few minutes upstream. We cache the
top pages ~6h (data/buzz_cache.json — one fetch serves every ticker) and look the ticker up.
Mentions are ATTENTION, not sentiment or direction — a crowded name gaps on headlines both
ways; in the squeeze block, buzz is the ignition-attention counterpart to the fuel metrics.
CONTEXT only, never a model feature. Best-effort: never raises, stale cache on failure.
"""

import json
import os
import time

import requests

BUZZ_URL = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}"
CACHE_FILE = "buzz_cache.json"
HISTORY_FILE = "buzz_history.csv"   # S58 — daily (date,ticker,rank,mentions) accumulation
HISTORY_KEEP_DAYS = 400             # ~1y of trading attention is plenty for a percentile
HIST_MIN_OBS = 10                   # prior days needed before a mentions percentile prints
HISTORY_TAIL = 60                   # rows returned for the web sparkline
TTL_HOURS = 6
PAGES = 4                 # 100/page — past rank ~400 the tail is noise
TIMEOUT = 15


def buzz_read(results, ticker):
    """Find `ticker` in an ApeWisdom results list → {rank, mentions, upvotes, rank_prev,
    mentions_prev, chg} or None when unranked. `chg` = mentions change vs 24h ago (None when
    the prior count is 0/absent). Pure — unit-testable."""
    t = ticker.upper()
    for r in results or []:
        if str(r.get("ticker", "")).upper() != t:
            continue
        mentions = int(r.get("mentions") or 0)
        prev = r.get("mentions_24h_ago")
        prev = int(prev) if prev not in (None, "") else None
        return {"rank": int(r.get("rank") or 0), "mentions": mentions,
                "upvotes": int(r.get("upvotes") or 0),
                "rank_prev": int(r["rank_24h_ago"]) if r.get("rank_24h_ago") else None,
                "mentions_prev": prev,
                "chg": (mentions / prev - 1) if prev else None}
    return None


def record_history(results, data_dir, today=None):
    """Append today's (date,ticker,rank,mentions) rows for every ranked ticker to
    data/buzz_history.csv — dedupe on (date,ticker) keeping the day's FIRST snapshot, prune
    beyond HISTORY_KEEP_DAYS. One row set per feed refresh (~daily at the 6h TTL) is what
    powers the mentions percentile + web sparkline. Best-effort, never raises."""
    try:
        import pandas as pd
        path = os.path.join(data_dir, HISTORY_FILE)
        today = today or time.strftime("%Y-%m-%d")
        new = pd.DataFrame([{"date": today,
                             "ticker": str(r.get("ticker", "")).upper(),
                             "rank": int(r.get("rank") or 0),
                             "mentions": int(r.get("mentions") or 0)}
                            for r in (results or []) if r.get("ticker")])
        if new.empty:
            return
        if os.path.exists(path):
            old = pd.read_csv(path, dtype={"date": str})
            new = pd.concat([old, new], ignore_index=True)
        new = new.drop_duplicates(subset=["date", "ticker"], keep="first")
        cutoff = (pd.Timestamp(today) - pd.Timedelta(days=HISTORY_KEEP_DAYS)).strftime("%Y-%m-%d")
        new = new[new["date"] >= cutoff]
        new.to_csv(path, index=False)
    except Exception:
        pass


def ticker_history(ticker, data_dir, tail=HISTORY_TAIL):
    """This ticker's accumulated buzz history, oldest→newest: [{date, rank, mentions}] (last
    `tail` rows; tail=None = full retained history) or None when nothing recorded yet.
    Never raises."""
    try:
        import pandas as pd
        path = os.path.join(data_dir, HISTORY_FILE)
        if not os.path.exists(path):
            return None
        df = pd.read_csv(path, dtype={"date": str})
        df = df[df["ticker"] == (ticker or "").upper()].sort_values("date")
        if df.empty:
            return None
        if tail:
            df = df.tail(tail)
        return df[["date", "rank", "mentions"]].to_dict("records")
    except Exception:
        return None


def mentions_pct(history, current, today=None):
    """PURE: fraction of PRIOR days' mentions below `current` — None until ≥HIST_MIN_OBS prior
    observations (buzz history accumulates ~1/day; sentiment.percentile_of's 63-obs floor is a
    daily-price convention, too strict here). Today's own row is excluded."""
    if current is None:
        return None
    today = today or time.strftime("%Y-%m-%d")
    vals = [h["mentions"] for h in (history or []) if h.get("date") != today]
    if len(vals) < HIST_MIN_OBS:
        return None
    return float(sum(v < current for v in vals) / len(vals))


def _load_results(data_dir, ttl_hours):
    path = os.path.join(data_dir, CACHE_FILE)
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl_hours * 3600:
            mtime = os.path.getmtime(path)
            with open(path, encoding="utf-8") as f:
                results = json.load(f)
            # stamp under the FETCH date (file mtime), not the read date: a post-midnight
            # read of yesterday-evening's cache would otherwise bank stale counts under
            # today, and keep="first" would then block the day's real snapshot
            record_history(results, data_dir,
                           today=time.strftime("%Y-%m-%d", time.localtime(mtime)))
            return results                     # a day served from cache still gets its row
    except Exception:
        pass
    results = []
    try:
        for page in range(1, PAGES + 1):
            r = requests.get(BUZZ_URL.format(page=page), timeout=TIMEOUT)
            r.raise_for_status()
            batch = (r.json() or {}).get("results") or []
            results.extend(batch)
            if len(batch) < 100:
                break
    except Exception:
        # a mid-pagination failure leaves a TRUNCATED list — caching it would serve a partial
        # feed for 6h and manufacture false "unranked" reads for tickers on the missing pages;
        # discard and fall through to the stale cache instead
        results = None
    if results:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(results, f)
        except Exception:
            pass
        record_history(results, data_dir)          # S58 — fresh feed → stamp today's history
        return results
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)                      # stale fallback beats nothing
    except Exception:
        return None


def fetch_buzz(ticker, data_dir="data", ttl_hours=TTL_HOURS):
    """Retail-buzz read for `ticker`: the buzz_read dict (+ `history` rows and a `pct`
    mentions percentile once enough days have accumulated) when ranked, `{"unranked": True}`
    when the feed loaded but the ticker isn't in the top ~400 (S58 — so "quiet" is visible
    instead of silent), None when the feed is unavailable. One cached feed fetch (~6h) serves
    every ticker. Never raises."""
    try:
        results = _load_results(data_dir, ttl_hours)
        if results is None:
            return None
        read = buzz_read(results, ticker)
        if read is None:
            return {"unranked": True}
        read["history"] = ticker_history(ticker, data_dir)
        # percentile over the FULL retained history (~400d) — the 60-row sparkline tail
        # would cap the window at ~59 prior days and read "100th" after any quiet spell
        read["pct"] = mentions_pct(ticker_history(ticker, data_dir, tail=None),
                                   read["mentions"])
        return read
    except Exception:
        return None
