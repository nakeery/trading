"""
Universe data layer (S33 cross-sectional rebuild — Stage 0).

A FIXED, liquid, sector-diverse universe of large-cap US names with long history. Bulk-downloads
adjusted daily closes via yfinance and caches them as one wide frame (dates × tickers).

⚠ SURVIVORSHIP: this is a *current* universe (names that exist today), so the backtest implicitly
excludes companies that delisted/failed. That biases results optimistically. True point-in-time
membership + delisting data is the known-hard part of free data and is deferred (see plan S33).
Stage-1 gate results must be read with this caveat in mind.
"""

import os
import pandas as pd
import yfinance as yf

# ~45 liquid large caps spanning sectors, most with pre-2005 history (cross-sectional dispersion
# needs sector diversity, not an all-tech basket). A few newer names (GOOGL'04, META'12) carry
# NaNs early — handled naturally by per-date cross-sections (a name simply isn't ranked until it
# has data).
UNIVERSE = [
    # Tech / semis
    "AAPL", "MSFT", "INTC", "CSCO", "ORCL", "IBM", "QCOM", "TXN", "NVDA", "AMD",
    # Communication
    "GOOGL", "META", "DIS", "CMCSA", "VZ", "T",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP",
    # Healthcare
    "JNJ", "PFE", "MRK", "UNH", "ABT", "BMY",
    # Energy
    "XOM", "CVX", "COP", "SLB",
    # Consumer staples
    "KO", "PEP", "PG", "WMT", "MCD", "COST",
    # Consumer discretionary
    "HD", "NKE", "LOW", "SBUX",
    # Industrials
    "CAT", "BA", "HON", "UPS", "MMM",
]

DATA_DIR = os.path.join("data", "universe")
CACHE = os.path.join(DATA_DIR, "prices_close.csv")


def load_universe_prices(start="2000-01-01", end=None, refresh=False, tickers=None):
    """Wide DataFrame of adjusted daily closes (index=dates, columns=tickers).

    Cached to data/universe/prices_close.csv; re-downloads if missing, stale, or refresh=True.
    """
    tickers = tickers or UNIVERSE
    end = end or pd.Timestamp.today().strftime("%Y-%m-%d")
    os.makedirs(DATA_DIR, exist_ok=True)

    if os.path.exists(CACHE) and not refresh:
        df = pd.read_csv(CACHE, index_col=0, parse_dates=True)
        have = set(df.columns)
        if set(tickers).issubset(have) and df.index.max() >= pd.Timestamp(end) - pd.Timedelta(days=5):
            return df[tickers].sort_index()

    print(f"Downloading {len(tickers)} names {start}..{end} (adjusted close)...")
    raw = yf.download(tickers, start=start, end=end, progress=False, auto_adjust=True)
    # yfinance returns MultiIndex columns (field, ticker); grab Close cross-section.
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    close = close.dropna(how="all").sort_index()
    close.to_csv(CACHE)
    print(f"  cached -> {CACHE}  ({close.shape[0]} dates × {close.shape[1]} names)")
    return close


if __name__ == "__main__":
    px = load_universe_prices(refresh=True)
    print(px.tail(3))
    print(f"\nCoverage: {px.shape[0]} dates, {px.shape[1]} names, "
          f"{px.index.min().date()} -> {px.index.max().date()}")
    print("Names with full history:",
          int((px.notna().mean() > 0.99).sum()), "/", px.shape[1])
