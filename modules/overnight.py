"""
Overnight & extended-hours context (S64) — index futures + after-hours ticker quote for lens.py.

The whole stack is RTH-gated (session_open) and daily-bar based, so a pre-market or evening lens
run describes a market that stopped moving hours ago. Two off-hours reads close that blind spot:

  1. FUTURES — ES=F / NQ=F latest price vs the prior daily settle, from one batched yfinance
     daily download (futures trade ~23h on Globex, so the in-progress daily row's Close IS the
     live overnight print; probed live 2026-07-27 — the last row's Close equals
     fast_info.last_price, and fast_info.previous_close matches NO settle, so the prior settle
     must come from the daily history itself, never fast_info).
  2. AFTER-HOURS PRINT — the ticker's own extended-hours move, read off the Tradier TIMESALES
     tape with session_filter="all". **Not the quote.** The original S64 implementation assumed
     `/markets/quotes` `last` keeps updating on AH/pre-market prints while official `close`
     latches at the bell; that is FALSE and made the tile structurally unable to move. Probed
     live 2026-07-27 16:34 ET on SOFI, 34 minutes after the bell and ~130k AH shares in:
         last 16.88 == close 16.88, trade_date frozen at 16:00:00.153
         bid 16.89 / ask 16.90, bid_date 16:33:56  ← quotes DO stay live off-hours
         timesales session_filter="all" → 16.92 @ 16:35  ← the actual print
     So `last` latches to the official close exactly like `close` does, and any read derived
     from it can only ever say +0.00%. The tape is the only source of a real AH trade; the quote
     is still used for the REFERENCE price (`close`/`prevclose`), which was never wrong.
     Equities only; degrades silently without a token.

DISPLAY-ONLY context, never a model feature (S20/S31 lessons) and NOT a risk-scorecard factor
(S43 — and an overnight print is exactly the kind of near-always-on noise the tally must not
absorb). Both surfaces are rendered only when the market is CLOSED — during RTH the SPY tide and
the live bar already cover direction, so lens.py gates the calls on `not session_open()`.

Cache: data/futures_cache.json, TTL 20 MINUTES — a deliberate deviation from the ~6h module
convention (breadth/fng/etc.): overnight tape decays in minutes, and a 6h-stale futures print is
worse than none. The segment carries its fetch timestamp so staleness is always visible. The
after-hours read is deliberately UNCACHED here (two real-time Tradier calls, only made off-hours;
the /api/afterhours endpoint puts a ~10s TTL in front of it so multiple tabs don't multiply them).
Best-effort throughout: never raises, stale cache served on failure, None when nothing exists.
When there is no extended-hours print at all, the read is None and the caller shows NOTHING —
never a 0.00% placeholder, which is precisely the failure this module shipped with.
"""

import json
import os
import time

import pandas as pd

CACHE_FILE = "futures_cache.json"
FUT_TTL_MINUTES = 20            # overnight data is only useful fresh — see module docstring
FUT_SYMBOLS = {"ES": "ES=F", "NQ": "NQ=F"}   # keep minimal — more symbols ≠ more information
# 1min, not 5min: the window is only ever a few hours (last close → now), so the row count is
# trivial either way, but a 5min bar leaves the tile's timestamp frozen for up to five minutes
# at a time — on a surface whose entire job is "has it moved since the bell", that reads as
# broken. Tradier keeps ~20 days of 1min, far more than this window needs.
EXT_INTERVAL = "1min"


def read_futures(close_map):
    """PURE: {label: Close Series (daily, last row = in-progress Globex session)} →
    {label: {last, settle, chg, bar_date}}. chg = last row vs prior row ("vs prior settle").
    Labels with < 2 rows are omitted; empty result → None. Offline-testable."""
    out = {}
    for label, closes in (close_map or {}).items():
        try:
            s = pd.Series(closes, dtype=float).dropna()
        except Exception:
            continue
        if len(s) < 2:
            continue
        last, settle = float(s.iloc[-1]), float(s.iloc[-2])
        if settle <= 0:
            continue
        entry = {"last": last, "settle": settle, "chg": last / settle - 1.0}
        try:
            entry["bar_date"] = pd.Timestamp(s.index[-1]).date().isoformat()
        except Exception:
            entry["bar_date"] = None
        out[label] = entry
    return out or None


def fetch_futures(data_dir="data", ttl_minutes=FUT_TTL_MINUTES):
    """Current ES/NQ overnight read, cached ttl_minutes. One batched yfinance daily download.
    Never raises; stale cache on failure, else None. Returns {"fut": {...}, "as_of_str": "HH:MM"}."""
    path = os.path.join(data_dir, CACHE_FILE)
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl_minutes * 60:
            with open(path, encoding="utf-8") as f:
                cached = json.load(f)
            if isinstance(cached, dict):
                return cached
    except Exception:
        pass
    try:
        import yfinance as yf
        raw = yf.download(list(FUT_SYMBOLS.values()), period="5d", interval="1d",
                          progress=False, auto_adjust=False)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        close_map = {lbl: close[sym] for lbl, sym in FUT_SYMBOLS.items()
                     if sym in close.columns}
        read = read_futures(close_map)
        if read:                                     # never rewrite the cache on an all-fail —
            out = {"fut": read,                      # the mtime bump would suppress the retry
                   "as_of_str": pd.Timestamp.now(tz="America/New_York").strftime("%H:%M")}
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
            return json.load(f)                      # stale fallback beats nothing
    except Exception:
        return None


def _expected_session_date(now_et):
    """Most recent COMPLETED session's date for a given ET timestamp — same convention as
    lens._expected_last_session (holidays approximated as weekdays), replicated locally so this
    module stays lens-independent."""
    d = pd.Timestamp(now_et.date())
    if not (now_et.weekday() < 5 and now_et.hour >= 16):
        d -= pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d.date()


def _to_et(ts):
    """Any timestamp-ish → tz-aware ET. Naive values are assumed to already be ET (Tradier
    timesales `time` strings are ET wall-clock)."""
    t = pd.Timestamp(ts)
    return t.tz_localize("America/New_York") if t.tz is None else t.tz_convert("America/New_York")


def _ext_window_start(now):
    """PURE: the moment the extended-hours window opened for `now` — the most recent completed
    session's 16:00 ET close. One rule covers every off-hours case: an evening run (prints from
    16:00 tonight), an overnight run, and a pre-market run (last night's post-market AND this
    morning's pre-market are both 'since that close'). Avoids an arbitrary max-age cutoff."""
    return _to_et(pd.Timestamp(_expected_session_date(_to_et(now)))) + pd.Timedelta(hours=16)


def afterhours_read(quote, ext=None, now=None):
    """PURE: (raw Tradier quote, last extended-hours print) → {last, ref, chg_pct, label, hhmm}
    or None. `now` is injectable for testing (tz-aware or ET-naive), mirroring
    timeframes.session_open.

    `ext` = {"price": float, "ts": <ET timestamp>} — the last trade OUTSIDE regular hours, from
    the timesales tape (see the module docstring: the quote's `last` latches to the official
    close at the bell, so it can never carry an AH move). **No `ext` → None**, deliberately: the
    caller then renders nothing, instead of a price that is pinned to +0.00% forever.

    ref = official `close` when present (post-bell), else `prevclose` (Tradier nulls `close`
    intraday/pre-open). The print must land inside the current extended-hours window
    (`_ext_window_start`) — anything older is weekend-stale/halted and drops silently.
    `hhmm` is the PRINT's time, not the wall clock, so a stale tape is visible rather than
    masquerading as current. label: weekday before 09:30 ET → 'pre-mkt', else 'AH'. Never raises."""
    if not isinstance(quote, dict) or not isinstance(ext, dict):
        return None
    try:
        ref = quote.get("close")
        if ref is None:
            ref = quote.get("prevclose")
        last = ext.get("price")
        if last is None or ref is None:
            return None
        last, ref = float(last), float(ref)
        if ref <= 0 or last <= 0:
            return None
        if now is None:
            now = pd.Timestamp.now(tz="America/New_York")
        now = _to_et(now)
        ts = _to_et(ext["ts"])
        if ts <= _ext_window_start(now) or ts > now + pd.Timedelta(minutes=5):
            return None                       # stale (prior session) or implausibly future
        label = "pre-mkt" if (now.weekday() < 5 and (now.hour, now.minute) < (9, 30)) else "AH"
        return {"last": last, "ref": ref, "chg_pct": (last / ref - 1.0) * 100.0,
                "label": label, "hhmm": ts.strftime("%H:%M")}
    except Exception:
        return None


def fetch_ext_print(ticker, now=None):
    """The ticker's most recent EXTENDED-HOURS trade: {"price", "ts"} or None. One Tradier
    timesales call with session_filter="all" (the only source that carries pre/post-market
    prints), windowed from the last close. Bars inside regular hours are dropped, so a name with
    no off-hours activity returns None rather than the RTH close. Never raises."""
    try:
        from modules.tradier import get_timesales
        now = _to_et(now if now is not None else pd.Timestamp.now(tz="America/New_York"))
        start = _ext_window_start(now)
        bars = get_timesales(ticker, interval=EXT_INTERVAL,
                             start=start.strftime("%Y-%m-%d %H:%M"),
                             end=now.strftime("%Y-%m-%d %H:%M"),
                             session_filter="all")
        best = None
        for b in bars or []:
            try:
                ts = _to_et(b.get("time"))
                price = b.get("close")
            except Exception:
                continue
            if price is None or ts <= start or ts > now + pd.Timedelta(minutes=5):
                continue
            # session_filter="all" returns RTH bars too — keep only genuinely off-hours prints
            if ts.weekday() < 5 and (9, 30) <= (ts.hour, ts.minute) < (16, 0):
                continue
            if best is None or ts > best["ts"]:
                best = {"price": float(price), "ts": ts}
        return best
    except Exception:
        return None


def fetch_afterhours(ticker, now=None):
    """Extended-hours read for `ticker`: one Tradier quote (for the reference close) + one
    timesales call (for the actual print). Uncached here — the caller only invokes it off-hours
    and the API layer puts a short TTL in front. Never raises; None without a token, on any
    fetch failure, or when there is no extended-hours print."""
    try:
        from modules.tradier import get_daily_quote
        q = get_daily_quote(ticker)
        if not q:
            return None
        return afterhours_read(q, ext=fetch_ext_print(ticker, now=now), now=now)
    except Exception:
        return None
