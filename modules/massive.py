"""
Massive.com options data API helpers — used by indicators.py for the daily
chain snapshot harvest. Builds richer IV/skew/term-structure features than
Tradier's ATM-IV-only call so Phase 3 can be retrained on real options
data once enough history accumulates.

Auth: paid API key. Reads MASSIVE_API_KEY env var; calls fail clearly if
unset. Set $env:MASSIVE_API_KEY = "..." in your shell profile.
"""

import os
import datetime
import requests

# MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY", "")
MASSIVE_API_KEY = "T7TSg1ASBMXeGvCea9XRfUyJ9Mmm2Gzd"
MASSIVE_URL     = "https://api.massive.com"

# Canonical list of columns added to indicators CSV by harvest_iv_snapshot().
# ML scripts (entry/direction/volatility/backtest) must EXCLUDE these from
# feature_cols until S11 backfills historical values — otherwise dropna()
# in train() removes every pre-today row.
IV_COLS = [
    "atm_iv_30d", "atm_strike", "atm_expiry", "atm_dte",
    "iv_skew_25d", "term_structure", "put_call_oi_ratio",
]

FRONT_MONTH_MIN_DTE = 25    # back-month term-structure pivot — anything < 25d counts as "near"
BACK_MONTH_MIN_DTE  = 55    # back-month tenor for term-structure denominator
MAX_PAGES           = 5     # cap pagination — 5 × 250 = 1250 contracts per call
PAGE_LIMIT          = 250


def _get(url, params=None):
    if not MASSIVE_API_KEY:
        raise RuntimeError("MASSIVE_API_KEY env var not set — cannot call Massive API")
    p = {"apiKey": MASSIVE_API_KEY}
    if params:
        p.update(params)
    resp = requests.get(url, params=p, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _fetch_chain(ticker, dte_min, dte_max, strike_min=None, strike_max=None):
    """Fetch chain snapshot filtered to expiries in [today+dte_min, today+dte_max]
    and optionally a strike range. Strike filters keep result counts under the
    pagination cap when many weekly expiries crowd the window."""
    today = datetime.date.today()
    params = {
        "expiration_date.gte": (today + datetime.timedelta(days=dte_min)).isoformat(),
        "expiration_date.lte": (today + datetime.timedelta(days=dte_max)).isoformat(),
        "limit":               PAGE_LIMIT,
    }
    if strike_min is not None:
        params["strike_price.gte"] = strike_min
    if strike_max is not None:
        params["strike_price.lte"] = strike_max

    rows = []
    data = _get(f"{MASSIVE_URL}/v3/snapshot/options/{ticker}", params)
    rows.extend(data.get("results") or [])
    next_url = data.get("next_url")
    pages = 1
    while next_url and pages < MAX_PAGES:
        data = _get(next_url)  # next_url already encodes filters + cursor
        rows.extend(data.get("results") or [])
        next_url = data.get("next_url")
        pages += 1
    return rows


def get_chain_summary(ticker, underlying_price, target_dte=30):
    """
    Fetch options chain and derive summary stats for downstream features.

    Args:
        ticker:           underlying symbol (e.g. "QQQ")
        underlying_price: latest spot price — used to find ATM strike
                          (caller passes it to avoid an extra quote call)
        target_dte:       target days-to-expiry for ATM IV (default 30, matches HV-20)

    Returns dict on success, or None on failure / empty chain. Keys:
        atm_iv_30d         — ATM call IV at closest-to-target_dte expiry (decimal)
        atm_strike         — strike used for ATM IV
        atm_expiry         — YYYY-MM-DD of that expiry
        atm_dte            — days to that expiry
        iv_skew_25d        — 25Δ put IV − 25Δ call IV (positive = put-side fear)
        term_structure     — front-month ATM IV / back-month ATM IV (>1 = backwardation)
        put_call_oi_ratio  — sum(put OI) / sum(call OI) across queried expiries
    """
    try:
        # Front tenor: ATM IV + 25Δ skew + P/C OI. Wide strike range covers
        # 25Δ wings (~7% OTM at typical equity-index IV).
        front_rows = _fetch_chain(
            ticker,
            dte_min=max(0, target_dte - 7),
            dte_max=target_dte + 7,
            strike_min=underlying_price * 0.85,
            strike_max=underlying_price * 1.15,
        )
        # Back month: ATM only for term-structure denominator. Narrow strike
        # range keeps the result count small.
        back_rows = _fetch_chain(
            ticker,
            dte_min=BACK_MONTH_MIN_DTE,
            dte_max=BACK_MONTH_MIN_DTE + 35,
            strike_min=underlying_price * 0.97,
            strike_max=underlying_price * 1.03,
        )
        rows = front_rows + back_rows
    except Exception as e:
        print(f"  Massive chain fetch failed: {e}")
        return None
    if not rows:
        return None

    today = datetime.date.today()

    def parse_row(r):
        d = r.get("details") or {}
        g = r.get("greeks") or {}
        try:
            exp = datetime.date.fromisoformat(d.get("expiration_date"))
        except (TypeError, ValueError):
            return None
        return {
            "type":   d.get("contract_type"),
            "strike": float(d.get("strike_price")),
            "expiry": exp,
            "dte":    (exp - today).days,
            "iv":     r.get("implied_volatility"),
            "delta":  g.get("delta"),
            "oi":     r.get("open_interest") or 0,
        }

    parsed_all = [p for p in (parse_row(r) for r in rows) if p]
    calls_all = [p for p in parsed_all if p["type"] == "call"]
    puts_all  = [p for p in parsed_all if p["type"] == "put"]

    # Filter for IV-based stats: drop the iv=20 placeholder Massive returns when
    # it can't compute (deep ITM/OTM with empty greeks).
    def has_real_iv(p):
        return p["iv"] is not None and p["iv"] != 20 and p["delta"] is not None

    calls = [p for p in calls_all if has_real_iv(p)]
    puts  = [p for p in puts_all  if has_real_iv(p)]
    if not calls:
        return None

    # ATM call: minimize a combined score of expiry distance and strike distance.
    # The ×10 weight on dte keeps strike adjustments from dominating expiry choice.
    def atm_score(p):
        return abs(p["dte"] - target_dte) * 10 + abs(p["strike"] - underlying_price)
    atm = min(calls, key=atm_score)

    # 25Δ skew at the same expiry tenor as ATM (±7d window for liquidity)
    skew = None
    near_calls = [p for p in calls if abs(p["dte"] - atm["dte"]) <= 7]
    near_puts  = [p for p in puts  if abs(p["dte"] - atm["dte"]) <= 7]
    if near_calls and near_puts:
        c25 = min(near_calls, key=lambda p: abs(p["delta"] - 0.25))
        p25 = min(near_puts,  key=lambda p: abs(abs(p["delta"]) - 0.25))
        skew = float(p25["iv"]) - float(c25["iv"])

    # Front / back month ATM IV → term structure ratio (>1 = backwardation)
    def find_atm_at(min_dte):
        cands = [p for p in calls if p["dte"] >= min_dte]
        if not cands:
            return None
        return min(cands, key=lambda p: (abs(p["dte"] - min_dte), abs(p["strike"] - underlying_price)))
    front = find_atm_at(FRONT_MONTH_MIN_DTE)
    back  = find_atm_at(BACK_MONTH_MIN_DTE)
    term  = (float(front["iv"]) / float(back["iv"])) if (front and back and back["iv"]) else None

    # Put/call OI ratio uses ALL contracts (placeholder IV doesn't affect OI)
    call_oi = sum(p["oi"] for p in calls_all)
    put_oi  = sum(p["oi"] for p in puts_all)
    pc_oi   = (put_oi / call_oi) if call_oi > 0 else None

    return {
        "atm_iv_30d":        float(atm["iv"]),
        "atm_strike":        atm["strike"],
        "atm_expiry":        atm["expiry"].isoformat(),
        "atm_dte":           atm["dte"],
        "iv_skew_25d":       skew,
        "term_structure":    term,
        "put_call_oi_ratio": pc_oi,
    }
