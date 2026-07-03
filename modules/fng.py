"""
CNN Fear & Greed gauge (S41) — market-level sentiment context for lens.py + market_context.py.

Unofficial endpoint (418s without a browser UA + Referer; probed live 2026-07-02): one JSON with
the current score/rating plus ~1y of history — enough for a sentiment.percentile_of read. CONTEXT
only, never a model feature. Cached ~6h (data/fng_cache.json, mirrors geocontext); best-effort:
never raises, stale cache served on failure, None when nothing is available.

Framework note (S21): for this framework's signals, fear/stress readings have historically been
contrarian-BUY conditions, not sell triggers — the label is printed with that framing in mind.
"""

import json
import os
import time

import requests

from modules.sentiment import percentile_of

FNG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CACHE_FILE = "fng_cache.json"
TTL_HOURS = 6
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
           "Accept": "application/json", "Referer": "https://edition.cnn.com/"}


def parse_fng(payload):
    """CNN graphdata JSON → {score, rating, prev, pct} or None (pure — unit-testable).
    pct = trailing percentile of the current score within the payload's own history."""
    cur = (payload or {}).get("fear_and_greed") or {}
    score = cur.get("score")
    if score is None:
        return None
    hist = ((payload.get("fear_and_greed_historical") or {}).get("data")) or []
    scores = [p.get("y") for p in hist if isinstance(p, dict) and p.get("y") is not None]
    return {"score": float(score), "rating": str(cur.get("rating") or "").strip(),
            "prev": cur.get("previous_close"),
            "pct": percentile_of(scores, float(score)) if scores else None}


def fetch_fng(data_dir="data", ttl_hours=TTL_HOURS):
    """Current Fear & Greed read, cached. Never raises; stale cache on failure, else None."""
    path = os.path.join(data_dir, CACHE_FILE)
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl_hours * 3600:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    try:
        r = requests.get(FNG_URL, headers=HEADERS, timeout=10)
        r.raise_for_status()
        out = parse_fng(r.json())
        if out:
            try:
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
