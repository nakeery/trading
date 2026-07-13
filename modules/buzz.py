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


def _load_results(data_dir, ttl_hours):
    path = os.path.join(data_dir, CACHE_FILE)
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl_hours * 3600:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
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
        results = results or None
    if results:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(results, f)
        except Exception:
            pass
        return results
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)                      # stale fallback beats nothing
    except Exception:
        return None


def fetch_buzz(ticker, data_dir="data", ttl_hours=TTL_HOURS):
    """Retail-buzz read for `ticker`, or None when unranked / feed unavailable.
    One cached feed fetch (~6h) serves every ticker. Never raises."""
    try:
        results = _load_results(data_dir, ttl_hours)
        return buzz_read(results, ticker)
    except Exception:
        return None
