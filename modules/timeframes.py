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
            return df[_OHLCV].sort_index()
    raw = yf.download(ticker, period="max", interval="1d", progress=False, auto_adjust=True)
    if raw is None or len(raw) == 0:
        raise FileNotFoundError(f"no indicators CSV and no yfinance daily data for {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw[_OHLCV].dropna(how="all").sort_index()


def _load_intraday(ticker, ttl_hours=3):
    """1h bars from yfinance (~3y), cached with a TTL. Returns a tz-naive (US/Eastern) OHLCV frame."""
    os.makedirs(INTRADAY_DIR, exist_ok=True)
    cache = os.path.join(INTRADAY_DIR, f"{ticker.lower()}_1h.csv")
    if os.path.exists(cache) and (time.time() - os.path.getmtime(cache)) < ttl_hours * 3600:
        return pd.read_csv(cache, index_col=0, parse_dates=True)
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


def build_timeframes(ticker, data_dir=DATA_DIR, include_intraday=True, intraday_ttl_hours=3):
    """{tf: ohlcv_df} for the available timeframes, plus a list of notes about anything omitted."""
    daily = _load_daily(ticker, data_dir)
    frames = {
        "1D": daily,
        "1W": _resample(daily, "W-FRI"),
        "1M": _resample(daily, "ME"),
    }
    notes = []
    if include_intraday:
        try:
            h1 = _load_intraday(ticker, intraday_ttl_hours)
            frames["1h"] = h1
            frames["4h"] = _resample(h1, "4h")
        except Exception as e:
            notes.append(f"intraday (1h/4h) unavailable ({type(e).__name__}) — showing 1D/1W/1M only.")
    present = [tf for tf in TF_ORDER if tf in frames]
    return {tf: frames[tf] for tf in present}, notes


if __name__ == "__main__":
    import sys
    t = (sys.argv[1] if len(sys.argv) > 1 else "QQQ").upper()
    tfs, notes = build_timeframes(t)
    for tf, df in tfs.items():
        print(f"{tf:>3}: {len(df):>5} bars  {df.index.min()} -> {df.index.max()}  "
              f"last close {df['Close'].iloc[-1]:.2f}")
    for n in notes:
        print("note:", n)
