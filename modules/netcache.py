"""Shared freshness + JSON helpers for the per-run network-call caches (S70).

The lens re-fetched several daily-granularity yfinance datasets on EVERY gather_report run
(VIX complex, SKEW/VVIX, RS/beta closes, earnings dates, ex-div calendar). These helpers give
every such cache the same two freshness conventions already used across the project:

- session-stale (`session_fresh`) — valid until the next market close, the pc_oi convention
- wall-clock TTL (`fresh_hours`) — the breadth/fng/street ~6h/24h convention

`most_recent_close` deliberately DUPLICATES pc_oi._most_recent_close (10 lines) rather than
importing modules.pc_oi into features.py's import chain (pc_oi pulls tradier). A smoke-test
drift guard pins the two equal.
"""

import json
import os
import time

import pandas as pd


def most_recent_close():
    """Most recent weekday 16:00 ET already in the past (mirror of pc_oi._most_recent_close)."""
    now = pd.Timestamp.now(tz="America/New_York")
    close = now.normalize() + pd.Timedelta(hours=16)          # today 16:00 ET
    if now < close or close.weekday() >= 5:                   # before today's close, or weekend
        close -= pd.Timedelta(days=1)
        while close.weekday() >= 5:                           # land on a weekday
            close -= pd.Timedelta(days=1)
    return close


def session_fresh(as_of):
    """True while no market close has occurred since `as_of` (epoch). False on any error."""
    try:
        return float(as_of) >= most_recent_close().timestamp()
    except Exception:
        return False


def fresh_hours(as_of, hours):
    """True while `as_of` (epoch) is younger than `hours`. False on any error."""
    try:
        return (time.time() - float(as_of)) < hours * 3600.0
    except Exception:
        return False


def load_json(path):
    """Cached dict at `path` or None. Never raises."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_json(path, obj):
    """Write `obj` as JSON at `path` (makedirs). Never raises."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)
    except Exception:
        pass
