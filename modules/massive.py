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

# IV columns split by downstream usage:
#   IV_FEATURE_COLS — backfill targets; usable as ML features after backfill_iv.py run.
#                     Include via --iv-features flag in volatility/entry/backtest.
#   IV_META_COLS    — always excluded from feature_cols (non-numeric string, or
#                     requires months of daily accumulation to be useful as a feature).
#   IV_COLS         — full list for CSV column management; kept for backward compat.
IV_FEATURE_COLS = ["atm_iv_30d", "iv_skew_25d", "term_structure"]
IV_META_COLS    = ["atm_strike", "atm_expiry", "atm_dte", "put_call_oi_ratio"]
IV_COLS         = IV_FEATURE_COLS + IV_META_COLS

FRONT_MONTH_MIN_DTE = 25    # back-month term-structure pivot — anything < 25d counts as "near"
BACK_MONTH_MIN_DTE  = 55    # back-month tenor for term-structure denominator
MAX_PAGES                = 5     # cap pagination — 5 × 250 = 1250 contracts per call
PAGE_LIMIT               = 250
# MAX_INVERT_PER_CATEGORY removed — all contracts are tried (no cap)


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


# ─────────────────────────────────────────────────────────────────────────────
# HISTORICAL IV SNAPSHOT  (Black-Scholes inversion via reference + aggs)
# Used by backfill_iv.py to populate indicators CSV with 2 years of real IV.
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_historical_contracts(ticker, date, dte_min, dte_max,
                                strike_min, strike_max, contract_type=None):
    """
    Fetch option contract metadata for a historical date via the reference endpoint.

    Unlike _fetch_chain() (snapshot, current-only), the reference endpoint supports
    as_of=DATE and expired=true for historical data.  Returns metadata only — prices
    are fetched separately via _fetch_agg_price().
    """
    params = {
        "underlying_ticker":   ticker,
        "expired":             "true",
        "expiration_date.gte": (date + datetime.timedelta(days=dte_min)).isoformat(),
        "expiration_date.lte": (date + datetime.timedelta(days=dte_max)).isoformat(),
        "strike_price.gte":    round(float(strike_min), 2),
        "strike_price.lte":    round(float(strike_max), 2),
        "limit":               1000,
    }
    if contract_type:
        params["contract_type"] = contract_type

    rows = []
    data = _get(f"{MASSIVE_URL}/v3/reference/options/contracts", params)
    rows.extend(data.get("results") or [])
    next_url = data.get("next_url")
    pages = 1
    while next_url and pages < MAX_PAGES:
        data = _get(next_url)
        rows.extend(data.get("results") or [])
        next_url = data.get("next_url")
        pages += 1
    return rows


def _fetch_agg_price(contract_ticker, date):
    """
    Fetch 1-day OHLCV bar for an option contract on a specific historical date.

    Returns the closing price (falling back to VWAP), or None if no data
    was recorded for that contract on that date (no trades / contract inactive).
    """
    date_str = date.isoformat()
    url = (f"{MASSIVE_URL}/v2/aggs/ticker/{contract_ticker}"
           f"/range/1/day/{date_str}/{date_str}")
    try:
        data = _get(url)
        results = data.get("results") or []
        if results:
            r = results[0]
            price = r.get("c") or r.get("vw")
            if price and float(price) > 0:
                return float(price)
    except Exception:
        pass
    return None


def get_historical_iv_snapshot(ticker, date, spot, r, target_dte=30, q=0.0):
    """
    Compute IV snapshot for a historical date via Black-Scholes inversion.

    Fetches option contract metadata (reference endpoint, as_of=date, expired=true)
    and historical closing prices (aggregates endpoint), then inverts to IV using
    Newton-Raphson.  Mirrors the structure of get_chain_summary() for daily snapshot.

    Args:
        ticker:     underlying symbol (e.g. "QQQ")
        date:       datetime.date to compute IV for
        spot:       underlying closing price on that date
        r:          risk-free rate for that date (annual decimal, e.g. 0.05)
        target_dte: target days-to-expiry for ATM IV (default 30)
        q:          continuous dividend yield (default 0)

    Returns dict on success, None on failure. Keys:
        atm_iv_30d, atm_strike, atm_expiry, atm_dte  — ATM IV stats
        iv_skew_25d                                   — 25-delta put IV minus 25-delta call IV
        term_structure                                — front ATM IV / back ATM IV
        (put_call_oi_ratio omitted — historical OI not available via Massive)
    """
    try:
        from modules.bs_invert import implied_vol, implied_vol_put, bs_delta
    except ImportError:
        raise RuntimeError(
            "modules/bs_invert.py not found — create it before running backfill_iv.py"
        )

    dte_min_front = max(1, target_dte - 7)
    dte_max_front = target_dte + 7

    try:
        # Stage A: front-month calls (ATM region) and puts (25-delta region)
        front_calls_meta = _fetch_historical_contracts(
            ticker, date, dte_min_front, dte_max_front,
            spot * 0.90, spot * 1.10, contract_type="call",
        )
        front_puts_meta = _fetch_historical_contracts(
            ticker, date, dte_min_front, dte_max_front,
            spot * 0.88, spot * 1.02, contract_type="put",
        )
        # Stage B: back-month calls for term-structure denominator (narrow strike band)
        back_calls_meta = _fetch_historical_contracts(
            ticker, date, BACK_MONTH_MIN_DTE, BACK_MONTH_MIN_DTE + 35,
            spot * 0.97, spot * 1.03, contract_type="call",
        )
    except Exception:
        return None

    if not front_calls_meta:
        return None

    def parse_meta(c):
        """Extract (opt_ticker, strike, expiry_date, dte) from reference contract dict."""
        opt_ticker = c.get("ticker")
        strike_raw = c.get("strike_price")
        expiry_str = c.get("expiration_date")
        if not (opt_ticker and strike_raw and expiry_str):
            return None
        try:
            expiry = datetime.date.fromisoformat(expiry_str)
        except ValueError:
            return None
        dte = (expiry - date).days
        if dte <= 0:
            return None
        return (opt_ticker, float(strike_raw), expiry, dte)

    parsed_front_calls = [p for p in (parse_meta(c) for c in front_calls_meta) if p]
    parsed_front_puts  = [p for p in (parse_meta(c) for c in front_puts_meta)  if p]
    parsed_back_calls  = [p for p in (parse_meta(c) for c in back_calls_meta)  if p]

    if not parsed_front_calls:
        return None

    # Sort by combined expiry + strike distance (normalized by spot so both terms
    # are percentage-scale).  No cap — try all contracts; most will return NO PRICE
    # quickly, and capping risks missing the one liquid contract on a thin day.
    def meta_atm_score(p):
        return abs(p[3] - target_dte) * 10 + abs(p[1] - spot) / spot * 100

    parsed_front_calls.sort(key=meta_atm_score)
    # Sort puts toward ~5% OTM (approximate 25-delta region at 30 DTE / 20% vol)
    parsed_front_puts.sort(key=lambda p: abs(p[3] - target_dte) * 10 + abs(p[1] - spot * 0.95) / spot * 100)
    parsed_back_calls.sort(key=lambda p: abs(p[1] - spot) / spot * 100)

    front_calls_cands = parsed_front_calls
    front_puts_cands  = parsed_front_puts
    back_calls_cands  = parsed_back_calls

    def invert_call(p):
        """Fetch price and BS-invert to (strike, expiry, dte, iv, delta) or None."""
        opt_ticker, strike, expiry, dte = p
        T = dte / 252.0
        price = _fetch_agg_price(opt_ticker, date)
        if price is None:
            return None
        try:
            iv = implied_vol(price, spot, strike, r, T, q)
        except (ValueError, Exception):
            return None
        if not (0.01 <= iv <= 5.0):  # reject implausible inversions
            return None
        delta = bs_delta(spot, strike, r, T, iv, q, contract_type="call")
        return (strike, expiry, dte, iv, delta)

    def invert_put(p):
        """Fetch price and BS-invert (via put-call parity) to (strike, expiry, dte, iv, delta) or None."""
        opt_ticker, strike, expiry, dte = p
        T = dte / 252.0
        price = _fetch_agg_price(opt_ticker, date)
        if price is None:
            return None
        try:
            iv = implied_vol_put(price, spot, strike, r, T, q)
        except (ValueError, Exception):
            return None
        if not (0.01 <= iv <= 5.0):
            return None
        delta = bs_delta(spot, strike, r, T, iv, q, contract_type="put")
        return (strike, expiry, dte, iv, delta)

    # Invert front-month calls; need at least one for ATM IV
    inverted_calls = [r for r in (invert_call(p) for p in front_calls_cands) if r is not None]
    if not inverted_calls:
        return None

    # ATM call: combined expiry-distance + strike-distance score (strike normalized by spot)
    def inv_atm_score(p):
        strike, expiry, dte, iv, delta = p
        return abs(dte - target_dte) * 10 + abs(strike - spot) / spot * 100

    atm = min(inverted_calls, key=inv_atm_score)
    atm_strike, atm_expiry, atm_dte, atm_iv, _ = atm

    # 25-delta skew at the same expiry tenor
    skew = None
    inverted_puts = [r for r in (invert_put(p) for p in front_puts_cands) if r is not None]
    near_calls = [p for p in inverted_calls if abs(p[2] - atm_dte) <= 7]
    near_puts  = [p for p in inverted_puts  if abs(p[2] - atm_dte) <= 7]
    if near_calls and near_puts:
        c25 = min(near_calls, key=lambda p: abs(p[4] - 0.25))
        p25 = min(near_puts,  key=lambda p: abs(abs(p[4]) - 0.25))
        skew = float(p25[3]) - float(c25[3])  # put_iv - call_iv

    # Term structure: front ATM IV / back-month ATM IV  (>1 = backwardation)
    term = None
    inverted_back = [r for r in (invert_call(p) for p in back_calls_cands) if r is not None]
    if inverted_back:
        back_atm = min(inverted_back, key=lambda p: abs(p[0] - spot))
        back_iv = back_atm[3]
        if back_iv > 0:
            term = atm_iv / back_iv

    return {
        "atm_iv_30d":     atm_iv,
        "atm_strike":     atm_strike,
        "atm_expiry":     atm_expiry.isoformat(),
        "atm_dte":        atm_dte,
        "iv_skew_25d":    skew,
        "term_structure": term,
    }
