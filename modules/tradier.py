"""
Tradier API helpers — shared module for sizing.py and entry.py.

Provides:
  - Authenticated REST client (get_current_price, get_expirations, get_chain)
  - get_atm_iv() — fetches the closest-to-target-DTE ATM call IV in one call

Auth: brokerage token (not sandbox). Reads TRADIER_TOKEN env var if set,
otherwise falls back to the hardcoded constant below. Set
$env:TRADIER_TOKEN = "..."  to keep it out of source control.
"""

import os
import datetime
import requests
import pandas as pd

TRADIER_TOKEN = os.environ.get("TRADIER_TOKEN", "Bu4Zf6XIUJT7fC08NxopO5JDdh6I")
TRADIER_URL   = "https://api.tradier.com/v1"


def _get(endpoint, params=None):
    headers = {
        "Authorization": f"Bearer {TRADIER_TOKEN}",
        "Accept":        "application/json",
    }
    resp = requests.get(f"{TRADIER_URL}{endpoint}", headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_current_price(ticker):
    data = _get("/markets/quotes", {"symbols": ticker})
    return float(data["quotes"]["quote"]["last"])


def get_daily_quote(ticker):
    """Full session quote dict for ticker (open/high/low/close/volume/trade_date...).

    The 'close' field is null while the session is open and populates at the
    bell — callers can use it as a completed-session latch. Returns None on
    any failure."""
    try:
        data = _get("/markets/quotes", {"symbols": ticker})
        quote = (data.get("quotes") or {}).get("quote")
        return quote if isinstance(quote, dict) else None
    except Exception:
        return None


def get_daily_history(ticker, start, end):
    """Official daily OHLCV bars from Tradier, start/end inclusive (YYYY-MM-DD).

    NOTE: prices are split/dividend-UNADJUSTED (yfinance closes are adjusted).
    Returns a list of {date, open, high, low, close, volume} dicts; [] on failure."""
    try:
        data = _get("/markets/history", {
            "symbol": ticker, "interval": "daily", "start": start, "end": end,
        })
        days = (data.get("history") or {}).get("day", [])
        return [days] if isinstance(days, dict) else (days or [])
    except Exception:
        return []


def get_timesales(ticker, interval="15min", start=None, end=None, session_filter="open"):
    """Intraday bars from Tradier (real-time with a brokerage token). `interval` ∈ tick/1min/5min/
    15min; start/end are 'YYYY-MM-DD HH:MM' (ET). Availability: ~20 days back for 1min, ~40 days
    for 15min.

    `session_filter` (probed live 2026-07-27):
      "open" (default) → regular-hours bars only, matching yfinance's 60m series — what the 1h
             top-up and the 5m entry-timing frames want, so their grids stay RTH-aligned.
      "all"  → INCLUDES pre/post-market bars. This is the ONLY way to see extended-hours trades:
             /markets/quotes latches `last` to the official close at the bell (S64 fix) and the
             quote therefore cannot report an after-hours move.
    Returns a list of {time, timestamp, open, high, low, close, volume, ...} dicts; [] on failure."""
    try:
        params = {"symbol": ticker, "interval": interval, "session_filter": session_filter}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        data = _get("/markets/timesales", params)
        bars = (data.get("series") or {}).get("data", [])
        return [bars] if isinstance(bars, dict) else (bars or [])
    except Exception:
        return []


def get_expirations(ticker):
    data = _get("/markets/options/expirations", {"symbol": ticker})
    return data["expirations"]["date"]


def get_chain(ticker, expiration):
    data = _get("/markets/options/chains", {
        "symbol":     ticker,
        "expiration": expiration,
        "greeks":     "true",
    })
    options = data.get("options") or {}
    if not options.get("option"):
        return pd.DataFrame()
    return pd.DataFrame(options["option"])


def get_atm_iv(ticker, target_dte=30, current_price=None):
    """
    Returns ATM call IV at the closest available expiry to target_dte (default 30 days).
    30 days matches HV-20 in tenor — apples-to-apples for IV/HV comparison.
    Returns None if no expiry/chain available or API fails.

    Returns: dict with keys:
        price, iv, expiry, dte, atm_strike  — or None on failure
    """
    if current_price is None:
        current_price = get_current_price(ticker)

    today = datetime.date.today()
    expirations = get_expirations(ticker)
    if not expirations:
        return None

    # Find the expiry closest to target_dte
    candidates = [(e, (datetime.date.fromisoformat(e) - today).days) for e in expirations]
    candidates = [(e, d) for e, d in candidates if d > 0]  # future expiries only
    if not candidates:
        return None
    expiry, dte = min(candidates, key=lambda x: abs(x[1] - target_dte))

    chain = get_chain(ticker, expiry)
    if chain.empty:
        return None

    chain = chain[chain["option_type"] == "call"].copy()
    if chain.empty:
        return None

    # Pick the strike nearest current price
    chain["dist"] = (chain["strike"] - current_price).abs()
    atm_row = chain.sort_values("dist").iloc[0]

    greeks = atm_row.get("greeks") or {}
    if not isinstance(greeks, dict):
        return None
    iv = greeks.get("smv_vol") or greeks.get("mid_iv")
    if iv is None:
        return None

    return {
        "price":      current_price,
        "iv":         float(iv),
        "expiry":     expiry,
        "dte":        int(dte),
        "atm_strike": float(atm_row["strike"]),
    }
