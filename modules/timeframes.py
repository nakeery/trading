"""
Per-timeframe OHLCV builder (S34 — multi-timeframe Lens; S63 — day-trader frames).

Returns aligned OHLCV frames so the structure/momentum/volume reads can run natively on each
timeframe (a name can be oversold on the daily yet overbought on the weekly). Two groups:

  TREND         1M / 1W / 1D / 4h / 2h / 1h — what the swing structure is doing.
  ENTRY TIMING  30m / 15m / 5m (`INTRADAY_TFS`) — S63, LIVE SESSION ONLY. Display-only: every
                consumer whitelists the trend group, so these never touch the alignment
                synthesis, the risk scorecard or the setup check.

Sourcing:
  - 1D/1W/1M: resample the daily OHLCV already in data/{ticker}_indicators.csv (decades of history).
  - 1h:       yfinance interval=60m (~3y lookback); cached to data/intraday/ with a short TTL.
  - 4h/2h:    resampled from the 1h series (more reliable than yfinance's native 4h).
  - 5m:       Tradier timesales (real-time — the point of a session-only block), yfinance 5m/60d
              fallback; cached with a 2-minute TTL. 15m/30m resample off it, so one fetch feeds
              all three rows.

Intraday is best-effort: on any failure the intraday frames are omitted and a note is returned, so the
daily/weekly/monthly read always works.
"""

import os
import time

import numpy as np
import pandas as pd
import yfinance as yf

DATA_DIR = "data"
INTRADAY_DIR = os.path.join(DATA_DIR, "intraday")
_OHLCV = ["Open", "High", "Low", "Close", "Volume"]
_AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}

# Display order, longest → shortest for the multi-TF table. build_timeframes DROPS any frame whose
# key is absent here, and every renderer (CLI, React) iterates the dict in insertion order — so this
# list is the single source of truth for row order across the whole stack.
TF_ORDER = ["1M", "1W", "1D", "4h", "2h", "1h", "30m", "15m", "5m"]

# Sub-hourly entry-timing frames (S63). Display-only: the alignment summary, the risk scorecard, the
# setup check, the squeeze line and the thesis blind spots all exclude these keys.
INTRADAY_TFS = ("30m", "15m", "5m")

# Bar length per timeframe — used to spot a still-forming intraday bar (the `*` mark).
TF_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240}

RTH_OPEN = (9, 30)          # regular trading hours, ET — the window in which the entry-timing
RTH_CLOSE = (16, 0)         # frames are meaningful (outside it they are stale by definition)


def _resample(df, rule, offset=None):
    kw = {"offset": offset} if offset else {}
    out = df[_OHLCV].resample(rule, **kw).agg(_AGG)
    return out.dropna(subset=["Close"])


def session_open(now=None):
    """True during regular US trading hours (weekday, 09:30 ≤ ET < 16:00). Holidays are approximated
    as weekdays — the same convention `_last_completed_session` already uses. `now` (tz-aware or ET-
    naive) is injectable for testing."""
    if now is None:
        now = pd.Timestamp.now(tz="America/New_York")
    now = pd.Timestamp(now)
    if now.tz is not None:
        now = now.tz_convert("America/New_York")
    if now.weekday() >= 5:
        return False
    hm = (now.hour, now.minute)
    return RTH_OPEN <= hm < RTH_CLOSE


def _load_daily(ticker, data_dir):
    """Daily OHLCV from the indicators CSV if present (so we reuse the harvested history), else fetch
    from yfinance — the Lens works for any ticker (incl. SPY backdrop) without requiring indicators.py."""
    path = os.path.join(data_dir, f"{ticker.lower()}_indicators.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if all(c in df.columns for c in _OHLCV):
            # drop indicators.py's NaN-OHLCV "today-row" (appended for the IV stamp) so the daily
            # frame never ends on a NaN bar — that crashed read_timeframe (price=None) for e.g. RIVN
            return df[_OHLCV].dropna(subset=["Close"]).sort_index()
    raw = yf.download(ticker, period="max", interval="1d", progress=False, auto_adjust=True)
    if raw is None or len(raw) == 0:
        raise FileNotFoundError(f"no indicators CSV and no yfinance daily data for {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw[_OHLCV].dropna(subset=["Close"]).sort_index()


def _cache_path(ticker, label):
    return os.path.join(INTRADAY_DIR, f"{ticker.lower()}_{label}.csv")


def _to_et_naive(raw):
    """yfinance intraday frame → tz-naive (US/Eastern) OHLCV, columns flattened."""
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw[_OHLCV].copy()
    if raw.index.tz is not None:
        raw.index = raw.index.tz_convert("America/New_York").tz_localize(None)
    return raw


def _load_intraday(ticker, ttl_hours=3, notes=None, interval="60m", label="1h", period="730d"):
    """Intraday bars from yfinance, cached with a TTL. Returns a tz-naive (US/Eastern) OHLCV frame.
    When the download fails (Yahoo throttles intraday requests intermittently) but a cache exists,
    falls back to the stale cache with a note rather than dropping the rows entirely.
    `interval`/`label`/`period` are parameterised (S63) so the same path serves the 60m trend frame
    and the 5m entry-timing frame — each gets its own cache file."""
    os.makedirs(INTRADAY_DIR, exist_ok=True)
    cache = _cache_path(ticker, label)
    if os.path.exists(cache) and (time.time() - os.path.getmtime(cache)) < ttl_hours * 3600:
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    try:
        raw = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
        if raw is None or len(raw) == 0:
            raise RuntimeError("empty intraday download")
        raw = _to_et_naive(raw)
        raw.to_csv(cache)
        return raw
    except Exception:
        if os.path.exists(cache):
            if notes is not None:
                age_h = (time.time() - os.path.getmtime(cache)) / 3600
                notes.append(f"intraday refresh failed — using cached {label} bars ({age_h:.1f}h old).")
            return pd.read_csv(cache, index_col=0, parse_dates=True)
        raise


def _tradier_5m(ticker, days=20):
    """5-minute RTH bars from Tradier timesales (real-time with a brokerage token). Returns a
    tz-naive ET OHLCV frame or None. Same conversion recipe as `_topup_intraday`."""
    from modules.tradier import get_timesales
    now = pd.Timestamp.now(tz="America/New_York").tz_localize(None)
    bars = get_timesales(ticker, interval="5min",
                         start=(now - pd.Timedelta(days=days)).strftime("%Y-%m-%d %H:%M"),
                         end=now.strftime("%Y-%m-%d %H:%M"))
    if not bars:
        return None
    ts = pd.DataFrame(bars)
    ts.index = pd.to_datetime(ts["timestamp"], unit="s", utc=True).dt.tz_convert(
        "America/New_York").dt.tz_localize(None)
    return ts.rename(columns={"open": "Open", "high": "High", "low": "Low",
                              "close": "Close", "volume": "Volume"})[_OHLCV].astype(float)


def _load_ltf(ticker, ttl_min=2, notes=None):
    """(S63) 5-minute bars for the entry-timing block. Tradier FIRST — a block that only exists
    while the session is live wants the real-time source (~4s; yfinance intraday is delayed and
    throttled) — with yfinance 5m/60d as the fallback. Cached with a short TTL since a 5m bar goes
    stale in minutes; `ttl_min=0` under --live forces a refetch every run."""
    os.makedirs(INTRADAY_DIR, exist_ok=True)
    cache = _cache_path(ticker, "5m")
    if os.path.exists(cache) and (time.time() - os.path.getmtime(cache)) < ttl_min * 60:
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    try:
        m5 = _tradier_5m(ticker)
        if m5 is not None and len(m5):
            m5.to_csv(cache)
            return m5
    except Exception:
        pass
    # Tradier unavailable (no token / failure) → yfinance, which caps 5m at ~60 days.
    if notes is not None:
        notes.append("entry-timing 5m bars from yfinance (Tradier unavailable) — delayed, not real-time.")
    return _load_intraday(ticker, ttl_hours=ttl_min / 60, notes=notes,
                          interval="5m", label="5m", period="60d")


def merge_intraday_topup(h1, topup):
    """Merge real-time top-up 1h bars into the cached yfinance 1h frame (pure — unit-testable).
    Top-up bars REPLACE any overlapping cached hours (the cached tail may be a partial hour written
    mid-session) and extend past the cached end. Bars must share the tz-naive ET, session-anchored
    (09:30/10:30/…) hourly grid. Returns (df, n_new_or_replaced)."""
    if topup is None or len(topup) == 0:
        return h1, 0
    if h1 is None or len(h1) == 0:
        return topup, len(topup)
    keep = h1[~h1.index.isin(topup.index)]
    merged = pd.concat([keep, topup]).sort_index()
    return merged, len(topup)


def _topup_intraday(h1, ticker, notes):
    """(S40 --live) Bring the 1h frame up to the current session with Tradier timesales (real-time;
    ~40 days of 15min history). Fetches 15min bars from the start of the last cached hour, resamples
    to the yfinance 60m grid (session-anchored :30 offset), and merges. Best-effort: on any failure
    the yfinance frame is returned untouched."""
    try:
        from modules.tradier import get_timesales
        now = pd.Timestamp.now(tz="America/New_York").tz_localize(None)
        start = (h1.index[-1] if len(h1) else now.normalize() - pd.Timedelta(days=5))
        if start >= now:
            return h1
        bars = get_timesales(ticker, interval="15min",
                             start=start.strftime("%Y-%m-%d %H:%M"),
                             end=now.strftime("%Y-%m-%d %H:%M"))
        if not bars:
            return h1
        ts = pd.DataFrame(bars)
        ts.index = pd.to_datetime(ts["timestamp"], unit="s", utc=True).dt.tz_convert(
            "America/New_York").dt.tz_localize(None)
        ts = ts.rename(columns={"open": "Open", "high": "High", "low": "Low",
                                "close": "Close", "volume": "Volume"})[_OHLCV].astype(float)
        # 15min → the yfinance 60m grid: hourly bars anchored at the 09:30 session open.
        ts60 = ts.resample("60min", offset="30min").agg(_AGG).dropna(subset=["Close"])
        merged, n = merge_intraday_topup(h1, ts60)
        if n:
            notes.append(f"1h topped up live from Tradier ({n} bar{'s' if n != 1 else ''}).")
        return merged
    except Exception:
        return h1


def build_timeframes(ticker, data_dir=DATA_DIR, include_intraday=True, intraday_ttl_hours=3,
                     live=False, as_of=None, ltf=False):
    """{tf: ohlcv_df} for the available timeframes, plus a list of notes about anything omitted.
    `live=True` (lens --live) tops the 1h frame up to the current session via Tradier timesales,
    so the 1h/4h rows stay current even when the yfinance intraday download is stale or refused.
    `ltf=True` (S63, lens --ltf) adds the sub-hourly entry-timing frames — but ONLY while the
    session is live: outside RTH they describe a market that stopped moving hours ago, so they are
    skipped with a note instead. Never in as-of mode (no historical sub-hourly source).
    `as_of` (S57 — historical/backtest mode): truncate the SOURCE frames to that date BEFORE
    resampling, so the forming week/month as of that date is exactly what a viewer saw then —
    truncating the resampled frames by label would instead drop the forming period (a W-FRI
    label is the period-END Friday, which sits past a mid-week as-of)."""
    daily = _load_daily(ticker, data_dir)
    if as_of is not None:
        cutoff = pd.Timestamp(as_of).normalize()
        daily = daily.loc[:cutoff]
        if len(daily) == 0:
            raise FileNotFoundError(f"no {ticker} data on/before {cutoff.date()}")
    frames = {
        "1D": daily,
        "1W": _resample(daily, "W-FRI"),
        "1M": _resample(daily, "ME"),
    }
    notes = []
    if include_intraday:
        try:
            h1 = _load_intraday(ticker, intraday_ttl_hours, notes=notes)
            if live:
                h1 = _topup_intraday(h1, ticker, notes)
            if as_of is not None:
                # intraday timestamps run through the session — keep the whole as-of day
                h1 = h1[h1.index < pd.Timestamp(as_of).normalize() + pd.Timedelta(days=1)]
                if len(h1) == 0:
                    raise RuntimeError("intraday history does not reach the as-of date")
            frames["1h"] = h1
            frames["4h"] = _resample(h1, "4h")
            # 2h rides the same cached 1h frame — free, so it is default-on. Session-anchored
            # (09:30/11:30/13:30/15:30) rather than the wall-clock bins 4h uses. pandas anchors
            # bins at midnight+offset, and 09:30 sits 90min past a 2h boundary — NOT 30min.
            frames["2h"] = _resample(h1, "2h", offset="90min")
        except Exception as e:
            notes.append(f"intraday (1h/4h/2h) unavailable ({type(e).__name__}) — showing 1D/1W/1M only.")
    if ltf:
        if as_of is not None:
            pass                                        # caller already notes the as-of suppressions
        elif not session_open():
            notes.append("entry-timing frames (5m/15m/30m) hidden — market closed.")
        else:
            try:
                m5 = _load_ltf(ticker, ttl_min=0 if live else 2, notes=notes)
                # 5m bars sit on the :30 session grid, and both 15 and 30 divide it evenly, so the
                # default midnight-anchored bins already land on 09:30/09:45/… — no offset needed.
                frames["5m"] = m5
                frames["15m"] = _resample(m5, "15min")
                frames["30m"] = _resample(m5, "30min")
            except Exception as e:
                notes.append(f"entry-timing frames (5m/15m/30m) unavailable ({type(e).__name__}).")
    present = [tf for tf in TF_ORDER if tf in frames]
    return {tf: frames[tf] for tf in present}, notes


# ── Live provisional session bar (S40 --live) ────────────────────────────────
def fetch_live_bar(ticker):
    """Today's session bar, live from the Tradier quote (real-time with a brokerage token; measured
    ~4s delay). Returns {"ts", "Open","High","Low","Close","Volume", "in_progress", "hhmm"} or None
    when the market hasn't traded today / Tradier is unavailable. Close = live last while the
    session is open (quote `close` is null until the bell → in_progress). DISPLAY-ONLY: never
    written to the CSV — the next indicators.py run replaces it with the adjusted yfinance bar.
    NB Tradier prices are unadjusted (same convention as the S30 post-close stamp)."""
    try:
        from modules.tradier import get_daily_quote
        q = get_daily_quote(ticker)
        if not q or not q.get("trade_date"):
            return None
        now_et = pd.Timestamp.now(tz="America/New_York")
        traded = pd.Timestamp(int(q["trade_date"]), unit="ms", tz="UTC").tz_convert("America/New_York")
        if traded.normalize() != now_et.normalize():
            return None                                   # closed day / no trades today
        o, h, l, last = q.get("open"), q.get("high"), q.get("low"), q.get("last")
        if any(v is None for v in (o, h, l, last)):
            return None
        # post-bell the quote carries the OFFICIAL close — use it, not `last`, which keeps
        # updating on after-hours prints (an AH move would otherwise contaminate a bar
        # presented as the completed session, and can sit outside the session high/low)
        official = q.get("close")
        return {"ts": now_et.normalize().tz_localize(None),
                "Open": float(o), "High": float(h), "Low": float(l),
                "Close": float(official) if official is not None else float(last),
                "Volume": float(q.get("volume") or 0),
                "in_progress": official is None,
                "hhmm": now_et.strftime("%H:%M")}
    except Exception:
        return None


def append_live_bar(daily, bar):
    """Append the live provisional session bar to a daily OHLCV frame (pure — unit-testable).
    Returns (df, appended_bool): left untouched when the frame already covers the bar's date
    (post-close stamp / refresh already ran) or inputs are missing."""
    if bar is None or daily is None or len(daily) == 0:
        return daily, False
    if daily.index[-1] >= bar["ts"]:
        return daily, False
    row = pd.DataFrame([[bar["Open"], bar["High"], bar["Low"], bar["Close"], bar["Volume"]]],
                       columns=_OHLCV, index=pd.DatetimeIndex([bar["ts"]]))
    return pd.concat([daily, row]), True


def apply_live_bar(frames, bar):
    """Inject the live session bar into the 1D frame and re-derive 1W/1M so the forming week/month
    absorb it. Returns True when applied."""
    if "1D" not in frames:
        return False
    d2, ok = append_live_bar(frames["1D"], bar)
    if not ok:
        return False
    frames["1D"] = d2
    frames["1W"] = _resample(d2, "W-FRI")
    frames["1M"] = _resample(d2, "ME")
    return True


# Rules mirror the resample bins in build_timeframes — used to spot an in-progress final bar.
_PARTIAL_RULES = {"1W": "W-FRI", "1M": "ME"}


def _last_completed_session():
    """Most recent COMPLETED daily session (naive date): today if a weekday past 4 PM ET, else the
    prior weekday. Holidays approximated as weekdays — same convention as lens._expected_last_session."""
    now_et = pd.Timestamp.now(tz="America/New_York")
    d = pd.Timestamp(now_et.date())
    if not (now_et.weekday() < 5 and now_et.hour >= 16):
        d -= pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d


def last_bar_partial(daily, tf, frac=0.7, now_session=None):
    """True when the most recent resampled bar for `tf` is still forming. Two checks (S43):
    (1) CALENDAR — the last period's end (its resample label, rolled back to a weekday) is after the
        most recent completed session, i.e. the period can still grow. This catches a Thu/Fri forming
        week or a late-month forming month that the count heuristic misses (frac=0.7 exists so a
        complete 4-day holiday week isn't misflagged — but that tolerance left late-period forming
        bars unmarked, quietly understating W/M volume reads).
    (2) COUNT — the last period holds < frac × the typical bar count: catches a dataset that simply
        ends mid-period (stale data), where the calendar check can't fire.
    `now_session` overrides the wall clock for testing. Only the D→W/M timeframes can be partial
    here; intraday and 1D return False (their freshness is handled upstream)."""
    rule = _PARTIAL_RULES.get(tf)
    if rule is None or daily is None or len(daily) < 60:
        return False
    counts = daily["Close"].resample(rule).count()
    counts = counts[counts > 0]
    if len(counts) < 4:
        return False
    end = counts.index[-1]                      # period end: the Friday (W-FRI) / month-end (ME)
    while end.weekday() >= 5:                   # a weekend month-end resolves to its last weekday
        end -= pd.Timedelta(days=1)
    sess = now_session if now_session is not None else _last_completed_session()
    if end > sess:
        return True
    typical = counts.iloc[:-1].median()
    return bool(typical and counts.iloc[-1] < frac * typical)


if __name__ == "__main__":
    import sys
    t = (sys.argv[1] if len(sys.argv) > 1 else "QQQ").upper()
    tfs, notes = build_timeframes(t)
    for tf, df in tfs.items():
        print(f"{tf:>3}: {len(df):>5} bars  {df.index.min()} -> {df.index.max()}  "
              f"last close {df['Close'].iloc[-1]:.2f}")
    for n in notes:
        print("note:", n)
