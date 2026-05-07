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
