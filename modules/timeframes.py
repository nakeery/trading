"""
Per-timeframe OHLCV builder (S34 — multi-timeframe Lens).

Returns aligned OHLCV frames for {1h, 4h, 1D, 1W, 1M} so the structure/momentum/volume reads can run
natively on each timeframe (a name can be oversold on the daily yet overbought on the weekly).

Sourcing:
  - 1D/1W/1M: resample the daily OHLCV already in data/{ticker}_indicators.csv (decades of history).
  - 1h:       yfinance interval=60m (~3y lookback); cached to data/intraday/ with a short TTL.
  - 4h:       resampled from the 1h series (more reliable than yfinance's native 4h).

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

# Display order, longest → shortest for the multi-TF table.
TF_ORDER = ["1M", "1W", "1D", "4h", "1h"]


def _resample(df, rule):
    out = df[_OHLCV].resample(rule).agg(_AGG)
    return out.dropna(subset=["Close"])


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


def _load_intraday(ticker, ttl_hours=3, notes=None):
    """1h bars from yfinance (~3y), cached with a TTL. Returns a tz-naive (US/Eastern) OHLCV frame.
    When the download fails (Yahoo throttles intraday requests intermittently) but a cache exists,
    falls back to the stale cache with a note rather than dropping the 1h/4h rows entirely."""
    os.makedirs(INTRADAY_DIR, exist_ok=True)
    cache = os.path.join(INTRADAY_DIR, f"{ticker.lower()}_1h.csv")
    if os.path.exists(cache) and (time.time() - os.path.getmtime(cache)) < ttl_hours * 3600:
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    try:
        raw = yf.download(ticker, period="730d", interval="60m", progress=False, auto_adjust=True)
        if raw is None or len(raw) == 0:
            raise RuntimeError("empty intraday download")
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        raw = raw[_OHLCV].copy()
        # tz-aware UTC → US/Eastern, then drop tz for clean resampling/printing.
        if raw.index.tz is not None:
            raw.index = raw.index.tz_convert("America/New_York").tz_localize(None)
        raw.to_csv(cache)
        return raw
    except Exception:
        if os.path.exists(cache):
            if notes is not None:
                age_h = (time.time() - os.path.getmtime(cache)) / 3600
                notes.append(f"intraday refresh failed — using cached 1h bars ({age_h:.1f}h old).")
            return pd.read_csv(cache, index_col=0, parse_dates=True)
        raise


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
                     live=False):
    """{tf: ohlcv_df} for the available timeframes, plus a list of notes about anything omitted.
    `live=True` (lens --live) tops the 1h frame up to the current session via Tradier timesales,
    so the 1h/4h rows stay current even when the yfinance intraday download is stale or refused."""
    daily = _load_daily(ticker, data_dir)
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
            frames["1h"] = h1
            frames["4h"] = _resample(h1, "4h")
        except Exception as e:
            notes.append(f"intraday (1h/4h) unavailable ({type(e).__name__}) — showing 1D/1W/1M only.")
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
        return {"ts": now_et.normalize().tz_localize(None),
                "Open": float(o), "High": float(h), "Low": float(l), "Close": float(last),
                "Volume": float(q.get("volume") or 0),
                "in_progress": q.get("close") is None,
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


def last_bar_partial(daily, tf, frac=0.7):
    """True when the most recent resampled bar for `tf` is still forming — it holds fewer source
    (daily) bars than a typical complete period. Counts daily bars per period from the daily frame,
    so it catches BOTH an in-progress current period AND a dataset that simply ends mid-period (stale
    data), without relying on the wall clock. Only the D→W/M timeframes can be partial here; intraday
    and 1D return False (their freshness is handled upstream)."""
    rule = _PARTIAL_RULES.get(tf)
    if rule is None or daily is None or len(daily) < 60:
        return False
    counts = daily["Close"].resample(rule).count()
    counts = counts[counts > 0]
    if len(counts) < 4:
        return False
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
