"""TTL caches for the FastAPI backend (S60) — the st.cache_data replacement.

Same cadences as lens_web.py's @st.cache_data decorators — EXCEPT report_cache, which is
session-stale since S70 (see below); `force=True` evicts the entry
before recomputing (the Run button / live mode, mirroring generate_payload.clear).
evict_ticker() mirrors lens_web.py's post-generate clears — a generate may have auto-refreshed
the indicators CSV, so every per-ticker cache must drop that ticker or the chart shows a stale
data vintage vs the report.
"""

import threading
import time

from cachetools import TTLCache

from modules import netcache

# (ticker, flags_key) → (as_of_epoch, bundle). SESSION-STALE (S70), not a short TTL: a report
# generated today is valid until the next market close — switching CRSP → SOFI → CRSP within a
# day serves the morning's report instantly. The Run button (force) and live mode still bypass
# via the /api/report endpoint; the boundary matches the pc_oi/gex/volquote chain caches.
report_cache = {}
_REPORT_MAX = 64
frame_cache = TTLCache(maxsize=64, ttl=600)        # ticker → full daily frame
iv_cache = TTLCache(maxsize=64, ttl=600)           # (ticker, asof) → iv history dict
tile_cache = TTLCache(maxsize=256, ttl=600)        # ticker → watchlist tile
ledger_cache = TTLCache(maxsize=64, ttl=600)       # ticker → merged ledger rows
season_cache = TTLCache(maxsize=64, ttl=3600)      # (ticker, asof) → seasonality
reactions_cache = TTLCache(maxsize=64, ttl=3600)   # (ticker, asof) → earnings reactions
# S64 fix: the AH tile polls every ~30s off-hours. A short TTL keeps N open tabs from
# multiplying Tradier calls without letting the print visibly lag its own poll interval.
afterhours_cache = TTLCache(maxsize=64, ttl=10)    # ticker → after-hours read
lens_score_cache = TTLCache(maxsize=64, ttl=600)   # ticker → lens self-score (S65)

_PER_TICKER = (frame_cache, iv_cache, tile_cache, ledger_cache, season_cache, reactions_cache,
               lens_score_cache)

# cachetools caches are NOT thread-safe, and the sync `def` endpoints run concurrently in
# FastAPI's threadpool (the watchlist alone fires N parallel /api/tile calls) while
# evict_ticker runs on the event-loop thread — one lock covers every mutation.
_LOCK = threading.Lock()


def get_report(key):
    """Session-fresh report bundle for `key`, or None. Stale entries (a market close has
    occurred since their generate) are pruned on sight."""
    with _LOCK:
        entry = report_cache.get(key)
        if entry is None:
            return None
        as_of, bundle = entry
        if not netcache.session_fresh(as_of):
            report_cache.pop(key, None)
            return None
        return bundle


def put_report(key, bundle):
    """Store `bundle` stamped now; evict the oldest entries beyond _REPORT_MAX."""
    with _LOCK:
        report_cache[key] = (time.time(), bundle)
        while len(report_cache) > _REPORT_MAX:
            oldest = min(report_cache, key=lambda k: report_cache[k][0])
            report_cache.pop(oldest, None)


def cached(cache, key, fn, force=False):
    """Memoize fn() under `key` in `cache`; `force` evicts first (fresh compute).
    The compute itself runs outside the lock (fn can be slow — a full yfinance download);
    a concurrent duplicate compute is acceptable, a corrupted cache is not."""
    with _LOCK:
        if force:
            cache.pop(key, None)
        elif key in cache:
            return cache[key]
    val = fn()
    with _LOCK:
        cache[key] = val
    return val


def evict_ticker(ticker):
    """Drop every per-ticker cache entry after a successful generate (data-vintage match —
    mirrors the load_*.clear() block in lens_web.py)."""
    t = ticker.upper()
    with _LOCK:
        for cache in _PER_TICKER:
            for k in [k for k in list(cache) if (k[0] if isinstance(k, tuple) else k) == t]:
                cache.pop(k, None)
