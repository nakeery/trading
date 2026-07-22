"""TTL caches for the FastAPI backend (S60) — the st.cache_data replacement.

Same cadences as lens_web.py's @st.cache_data decorators; `force=True` evicts the entry
before recomputing (the Run button / live mode, mirroring generate_payload.clear).
evict_ticker() mirrors lens_web.py's post-generate clears — a generate may have auto-refreshed
the indicators CSV, so every per-ticker cache must drop that ticker or the chart shows a stale
data vintage vs the report.
"""

from cachetools import TTLCache

report_cache = TTLCache(maxsize=64, ttl=120)       # (ticker, flags_key) → report bundle
frame_cache = TTLCache(maxsize=64, ttl=600)        # ticker → full daily frame
iv_cache = TTLCache(maxsize=64, ttl=600)           # (ticker, asof) → iv history dict
tile_cache = TTLCache(maxsize=256, ttl=600)        # ticker → watchlist tile
ledger_cache = TTLCache(maxsize=64, ttl=600)       # ticker → merged ledger rows
season_cache = TTLCache(maxsize=64, ttl=3600)      # (ticker, asof) → seasonality
reactions_cache = TTLCache(maxsize=64, ttl=3600)   # (ticker, asof) → earnings reactions
econ_cache = TTLCache(maxsize=2, ttl=86400)        # () → econ calendar (manual refresh evicts)

_PER_TICKER = (frame_cache, iv_cache, tile_cache, ledger_cache, season_cache, reactions_cache)


def cached(cache, key, fn, force=False):
    """Memoize fn() under `key` in `cache`; `force` evicts first (fresh compute)."""
    if force:
        cache.pop(key, None)
    if key in cache:
        return cache[key]
    val = fn()
    cache[key] = val
    return val


def evict_ticker(ticker):
    """Drop every per-ticker cache entry after a successful generate (data-vintage match —
    mirrors the load_*.clear() block in lens_web.py)."""
    t = ticker.upper()
    for cache in _PER_TICKER:
        for k in [k for k in list(cache) if (k[0] if isinstance(k, tuple) else k) == t]:
            cache.pop(k, None)
