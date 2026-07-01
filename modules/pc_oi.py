"""
Options Trading — Put/Call OI + Volume Viewer
==============================================
Ad-hoc lookup of put/call OPEN-INTEREST and VOLUME by expiration date, read off the live
Tradier options chain. Run as needed — NOT part of the daily pipeline and NOT a model
feature. Also imported by lens.py (`--pc-oi`) for an in-lens by-expiry positioning block.

  P/C OI    (per expiry) = sum(put open interest) / sum(call open interest)  (positioning)
  P/C Vol   (per expiry) = sum(put volume)        / sum(call volume)         (latest session)
  Call Vol / Put Vol     = raw latest-session volume (contracts traded each side)

Reading the ratios:
  < 1.0  -> more calls than puts  -> call-leaning / bullish positioning
  > 1.0  -> more puts than calls   -> put-leaning  / hedging or bearish positioning

OI is a STOCK (cumulative positioning; updates once/day at the prior close). Volume is a
FLOW (latest-session activity; resets each session; outside market hours it shows the last
completed session). Seeing both shows whether an OI reading is being actively traded or is
stale. Both are point-in-time snapshots of the CURRENT chain — future expiries are fully
visible because those contracts already trade today. (Arbitrary PAST dates are not
available — vendors don't serve historical OI.)

Usage (interactive, matches sizing.py) — run as a module from the project root:
    python -X utf8 -m modules.pc_oi
      Ticker: QQQ
      Expiry filter (YYYY-MM-DD, blank = all): 2026-12-18

  - Blank expiry filter -> full term structure across every future expiry (+ TOTAL).
  - A date              -> just that expiry.

Piped (Windows — see CLAUDE.md):
    cmd /c "(echo QQQ && echo.) | python -X utf8 -m modules.pc_oi"             # all expiries
    cmd /c "(echo QQQ && echo 2026-12-18) | python -X utf8 -m modules.pc_oi"   # one expiry

Requirements: pandas, requests; a Tradier brokerage token (TRADIER_TOKEN env var or the
fallback in modules/tradier.py).
"""

import sys
import json
import os
import time
import datetime

import pandas as pd

from modules.tradier import (
    TRADIER_TOKEN,
    get_current_price,
    get_expirations,
    get_chain,
)

# LEAPS tenor the framework actually trades (6-12 months). Rows in this window are
# flagged so positioning at the real holding horizon stands out from near-term weeklies.
LEAPS_MIN_DTE = 180
LEAPS_MAX_DTE = 365
NEAR_MAX_DTE  = 45      # "near" tenor preset — front weeklies/monthlies (event / short-dated)

# Named tenor presets -> (dte_min, dte_max). Consumed by gather_pc_oi / lens.py --pc-oi.
TENOR_PRESETS = {
    "all":   (None, None),
    "near":  (None, NEAR_MAX_DTE),
    "leaps": (LEAPS_MIN_DTE, LEAPS_MAX_DTE),
}


# ─────────────────────────────────────────
# CACHE — per (ticker, scope), session-stale
# ─────────────────────────────────────────
# OI settles once/day at the close and doesn't move intraday (volume is the only intraday-changing
# column), so we cache each scope's fetched rows and only re-hit Tradier once a new market close has
# occurred since the cache was written. Mirrors modules/geocontext.py's JSON-cache pattern.
CACHE_SUBDIR = "pc_oi_cache"


def _scopekey(preset, monthly):
    return preset + ("_monthly" if monthly else "")


def _cache_path(ticker, scopekey, data_dir):
    return os.path.join(data_dir, CACHE_SUBDIR, f"{ticker.lower()}_{scopekey}.json")


def _most_recent_close():
    """Most recent weekday 16:00 ET already in the past — the last OI-settlement boundary
    (mirrors lens._expected_last_session's weekday / 4 PM-ET convention)."""
    now = pd.Timestamp.now(tz="America/New_York")
    close = now.normalize() + pd.Timedelta(hours=16)          # today 16:00 ET
    if now < close or close.weekday() >= 5:                   # before today's close, or weekend
        close -= pd.Timedelta(days=1)
        while close.weekday() >= 5:                           # land on a weekday
            close -= pd.Timedelta(days=1)
    return close


def _hhmm(as_of):
    return datetime.datetime.fromtimestamp(as_of).strftime("%H:%M")


def _cache_age(as_of):
    """'YYYY-MM-DD HH:MM (Nh/Nm ago)' for a cache as_of epoch."""
    ts   = datetime.datetime.fromtimestamp(as_of).strftime("%Y-%m-%d %H:%M")
    mins = (time.time() - as_of) / 60.0
    age  = f"{mins/60:.0f}h ago" if mins >= 60 else f"{max(mins, 0):.0f}m ago"
    return f"{ts} ({age})"


def load_cache(ticker, scopekey, data_dir):
    """Cached dict for (ticker, scope) or None. Never raises."""
    try:
        with open(_cache_path(ticker, scopekey, data_dir), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def cache_stale(cache):
    """True if a market close has occurred since the cache's as_of (session-based)."""
    try:
        return float(cache["as_of"]) < _most_recent_close().timestamp()
    except Exception:
        return True


def save_cache(ticker, scopekey, data_dir, price, rows):
    """Write {as_of, price, rows} JSON. Never raises."""
    path = _cache_path(ticker, scopekey, data_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"as_of": time.time(), "price": price, "rows": rows}, f)
    except Exception:
        pass


def _rehydrate(rows):
    """Recompute each cached row's dte from its expiry vs today (OI/vol stay as cached)."""
    today = datetime.date.today()
    out = []
    for r in rows:
        r = dict(r)
        try:
            r["dte"] = (datetime.date.fromisoformat(r["expiry"]) - today).days
        except Exception:
            pass
        out.append(r)
    return out


# ─────────────────────────────────────────
# LABEL — same bands as entry.py OPTIONS-MARKET CHECK
# ─────────────────────────────────────────
def pc_label(pc):
    if pc is None:
        return "n/a"
    return ("heavy call interest" if pc < 0.70
            else "call-leaning"    if pc < 1.00
            else "put-leaning"     if pc < 1.30
            else "heavy put interest")


def is_monthly_expiry(d):
    """True when `d` (a date) is a standard monthly expiry — the 3rd Friday of its month
    (weekday Friday, day-of-month 15-21). Keeps monthlies / quarterlies / LEAPS; filters out
    the weeklies and any odd EOM/daily expiries. Per-expiry ratios are unaffected by this
    filter (each is self-contained); only the aggregate TOTAL's scope narrows."""
    return d.weekday() == 4 and 15 <= d.day <= 21


# ─────────────────────────────────────────
# FETCH — sum put/call OI and volume per future expiry off the live chain
# ─────────────────────────────────────────
def pc_by_expiry(ticker, date_filter=None, dte_min=None, dte_max=None,
                 monthly_only=False, quiet=False):
    """
    Returns a list of dicts sorted by DTE:
      {expiry, dte, call_oi, put_oi, pc, call_vol, put_vol, pc_vol}
    One Tradier chain call per expiry. Narrowing (date_filter / dte range / monthly_only) is
    applied to the expiry list BEFORE fetching, so it also cuts the number of network calls.
    `quiet` suppresses the per-expiry progress prints (used by lens.py).
    """
    today = datetime.date.today()

    expirations = get_expirations(ticker)
    if isinstance(expirations, str):       # Tradier returns a bare string for 1 expiry
        expirations = [expirations]

    future = sorted(
        (e, (datetime.date.fromisoformat(e) - today).days) for e in expirations
    )
    future = [(e, d) for e, d in future if d > 0]          # future expiries only

    if date_filter:
        match = [(e, d) for e, d in future if e == date_filter]
        if not match:
            if not quiet:
                print(f"  No future expiry on {date_filter}. Available future expiries:")
                print("    " + ", ".join(e for e, _ in future))
            return []
        future = match
    else:
        if dte_min is not None:
            future = [(e, d) for e, d in future if d >= dte_min]
        if dte_max is not None:
            future = [(e, d) for e, d in future if d <= dte_max]
        if monthly_only:
            future = [(e, d) for e, d in future
                      if is_monthly_expiry(datetime.date.fromisoformat(e))]

    rows = []
    for exp, dte in future:
        if not quiet:
            print(f"  Fetching {exp} ({dte} DTE)...")
        try:
            chain = get_chain(ticker, exp)
        except Exception as e:
            if not quiet:
                print(f"  Skipping {exp}: {e}")
            continue
        if chain.empty or "open_interest" not in chain.columns or "option_type" not in chain.columns:
            continue

        is_call = chain["option_type"] == "call"
        is_put  = chain["option_type"] == "put"

        oi  = pd.to_numeric(chain["open_interest"], errors="coerce").fillna(0)
        vol = (pd.to_numeric(chain["volume"], errors="coerce").fillna(0)
               if "volume" in chain.columns else pd.Series(0, index=chain.index))

        call_oi  = float(oi[is_call].sum())
        put_oi   = float(oi[is_put].sum())
        call_vol = float(vol[is_call].sum())
        put_vol  = float(vol[is_put].sum())

        # Ratio guards: only the DENOMINATOR (call side) can break the division.
        # call_vol == 0 is a real state (illiquid / far-dated / untraded this session),
        # so emit None -> "n/a" rather than 0.0 (which would falsely read as call-heavy).
        # A zero NUMERATOR with calls > 0 is fine: ratio 0.0 = genuinely all-call activity.
        # The raw Call Vol / Put Vol columns still show the counts when the ratio is n/a.
        pc     = (put_oi  / call_oi)  if call_oi  > 0 else None
        pc_vol = (put_vol / call_vol) if call_vol > 0 else None

        rows.append({"expiry": exp, "dte": dte,
                     "call_oi": call_oi, "put_oi": put_oi, "pc": pc,
                     "call_vol": call_vol, "put_vol": put_vol, "pc_vol": pc_vol})
    return rows


def totals(rows):
    """Aggregate OI/volume across `rows` -> {call_oi, put_oi, pc, call_vol, put_vol, pc_vol}.
    Same guard as per-expiry: a zero call side -> None ('n/a')."""
    tot_call     = sum(r["call_oi"]  for r in rows)
    tot_put      = sum(r["put_oi"]   for r in rows)
    tot_call_vol = sum(r["call_vol"] for r in rows)
    tot_put_vol  = sum(r["put_vol"]  for r in rows)
    return {
        "call_oi":  tot_call,
        "put_oi":   tot_put,
        "pc":       (tot_put / tot_call) if tot_call > 0 else None,
        "call_vol": tot_call_vol,
        "put_vol":  tot_put_vol,
        "pc_vol":   (tot_put_vol / tot_call_vol) if tot_call_vol > 0 else None,
    }


def gather_pc_oi(ticker, preset="all", monthly=False, interactive=False, data_dir="data", quiet=True):
    """Resolve a tenor preset and return {ticker, price, rows, total, scope, as_of, as_of_str,
    age_str, stale, cached} — or None on no token / no data. Cached per (ticker, scope) under
    data/pc_oi_cache/; re-fetches only when a market close has occurred since the cache
    (session-stale). When stale: prompts to refresh if `interactive` (a TTY), else serves the cached
    rows with stale=True. Best-effort: never raises; a fetch failure falls back to any cache."""
    if not TRADIER_TOKEN or TRADIER_TOKEN == "YOUR_TOKEN_HERE":
        return None
    scope    = " · ".join([preset] + (["monthly"] if monthly else []))
    scopekey = _scopekey(preset, monthly)
    cache    = load_cache(ticker, scopekey, data_dir)
    stale    = cache is not None and cache_stale(cache)

    def _result(price, rows, as_of, is_stale, cached):
        return {"ticker": ticker, "price": price, "rows": rows, "total": totals(rows),
                "scope": scope, "as_of": as_of, "as_of_str": _hhmm(as_of),
                "age_str": _cache_age(as_of), "stale": is_stale, "cached": cached}

    refresh = cache is None                                # first time → must fetch (no prompt)
    if cache is not None and stale:
        if interactive:
            try:
                ans = input(f"  {ticker} put/call OI cached {_cache_age(cache['as_of'])}; a market "
                            f"close has passed — refresh from Tradier? [y/N]: ")
                refresh = ans.strip().lower().startswith("y")
            except EOFError:
                refresh = False
        else:
            refresh = False                                # piped → serve cached (stale flag set)

    if not refresh and cache is not None:
        return _result(cache.get("price"), _rehydrate(cache["rows"]), cache["as_of"], stale, True)

    dte_min, dte_max = TENOR_PRESETS.get(preset, (None, None))
    print(f"  ↻ put/call OI: fetching {scope} from Tradier…")
    try:
        price = get_current_price(ticker)
        rows  = pc_by_expiry(ticker, dte_min=dte_min, dte_max=dte_max,
                             monthly_only=monthly, quiet=quiet)
    except Exception:
        if cache is not None:                              # fetch failed → fall back to cache
            return _result(cache.get("price"), _rehydrate(cache["rows"]), cache["as_of"], stale, True)
        return None
    if not rows:
        return None
    save_cache(ticker, scopekey, data_dir, price, rows)
    return _result(price, rows, time.time(), False, False)


# ─────────────────────────────────────────
# PRINT  (standalone full-width table)
# ─────────────────────────────────────────
def print_table(rows, ticker, current_price):
    w   = 114
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'═'*w}")
    print(f"  PUT/CALL — {ticker}  |  Price: ${current_price:.2f}  |  as of {now}")
    print(f"  P/C OI = put OI / call OI (positioning)   P/C Vol = put vol / call vol (latest session)")
    print(f"{'─'*w}")
    print(f"  {'Expiry':>10}  {'DTE':>4}  {'Call OI':>12}  {'Put OI':>12}  {'P/C OI':>6}  "
          f"{'Call Vol':>12}  {'Put Vol':>12}  {'P/C Vol':>7}  Positioning")
    print(f"  {'─'*110}")

    for r in rows:
        pc_str  = f"{r['pc']:.2f}"     if r["pc"]     is not None else "n/a"
        pcv_str = f"{r['pc_vol']:.2f}" if r["pc_vol"] is not None else "n/a"
        leaps   = " *" if LEAPS_MIN_DTE <= r["dte"] <= LEAPS_MAX_DTE else ""
        print(f"  {r['expiry']:>10}  {r['dte']:>4}  {int(r['call_oi']):>12,}  "
              f"{int(r['put_oi']):>12,}  {pc_str:>6}  {int(r['call_vol']):>12,}  "
              f"{int(r['put_vol']):>12,}  {pcv_str:>7}  {pc_label(r['pc'])}{leaps}")

    if len(rows) > 1:
        t = totals(rows)
        tot_pc_str  = f"{t['pc']:.2f}"     if t["pc"]     is not None else "n/a"
        tot_pcv_str = f"{t['pc_vol']:.2f}" if t["pc_vol"] is not None else "n/a"
        print(f"  {'─'*110}")
        print(f"  {'TOTAL':>10}  {'':>4}  {int(t['call_oi']):>12,}  {int(t['put_oi']):>12,}  "
              f"{tot_pc_str:>6}  {int(t['call_vol']):>12,}  {int(t['put_vol']):>12,}  "
              f"{tot_pcv_str:>7}  {pc_label(t['pc'])}")

    print(f"\n  {'─'*110}")
    print(f"  Bands (Positioning uses P/C OI):  < 0.70 heavy call | < 1.00 call-leaning | "
          f"< 1.30 put-leaning | >= 1.30 heavy put")
    print(f"  * = LEAPS tenor ({LEAPS_MIN_DTE}-{LEAPS_MAX_DTE} DTE) — the framework's target horizon")
    print(f"  Call Vol / Put Vol = raw latest-session volume (contracts traded).  P/C Vol 'n/a' = zero call volume.")
    print(f"  OI = cumulative positioning; Volume = latest-session flow (resets each session, partial intraday).")
    print(f"{'═'*w}\n")


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    if TRADIER_TOKEN == "YOUR_TOKEN_HERE":
        print("  Set TRADIER_TOKEN (env var or modules/tradier.py) before running.")
        sys.exit(1)

    try:
        ticker = input("  Ticker [XYZ]: ").strip().upper()
    except KeyboardInterrupt:
        print()
        sys.exit(0)
    if not ticker:
        print("  No ticker entered.")
        sys.exit(1)

    date_filter = input("  Expiry filter (YYYY-MM-DD, blank = all): ").strip()
    if date_filter:
        try:
            datetime.date.fromisoformat(date_filter)
        except ValueError:
            print(f"  Invalid date '{date_filter}' — use YYYY-MM-DD.")
            sys.exit(1)
        # Single expiry → one cheap Tradier call; not worth caching.
        print(f"\n  Fetching {ticker} from Tradier...")
        try:
            current_price = get_current_price(ticker)
            print(f"  Current price: ${current_price:.2f}")
        except Exception as e:
            print(f"  Error fetching price: {e}")
            sys.exit(1)
        rows = pc_by_expiry(ticker, date_filter)
        if not rows:
            print("  No open-interest data found.")
            sys.exit(0)
        print_table(rows, ticker, current_price)
    else:
        # All expiries (the expensive case) → cached per scope, session-stale refresh prompt.
        data = gather_pc_oi(ticker, preset="all", interactive=sys.stdin.isatty(), quiet=False)
        if not data:
            print("  No open-interest data found (or no Tradier token).")
            sys.exit(0)
        tag = "stale cache" if data["stale"] else "cached" if data["cached"] else "refreshed"
        print(f"  ({tag} {data['age_str']})")
        print_table(data["rows"], ticker, data["price"])
