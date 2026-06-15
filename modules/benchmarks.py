"""
Benchmark detection and macro feature engineering — shared module for all ML pipeline scripts.
Maps ticker sector/industry to the appropriate market benchmark(s).

Lookup order:
  1. TICKER_BENCHMARK   — direct per-ticker mapping (no network call, fastest)
  2. INDUSTRY_BENCHMARK — yfinance sector/industry lookup (requires working .info API)
  3. SECTOR_BENCHMARK   — broad SPDR ETF fallback via yfinance
  4. FALLBACK_BENCHMARK — S&P 500 if everything else fails

To add a ticker: add an entry to TICKER_BENCHMARK.
To add macro features for a ticker: add an entry to MACRO_FEATURES.
"""

import os
import numpy as np
import yfinance as yf
import pandas as pd

# Direct per-ticker mapping — checked first, no network call required.
# Format: "TICKER": [(yf_ticker, display_name), ...]
TICKER_BENCHMARK = {
    # Semiconductors
    "AMD":   [("^SOX", "SOX"), ("XLK", "XLK")],
    "NVDA":  [("^SOX", "SOX"), ("XLK", "XLK")],
    # Biotech
    "CRSP":  [("IBB",  "IBB"), ("XLV", "XLV")],
    # Fintech / digital bank
    "SOFI":  [("KBE",  "KBE"), ("XLF", "XLF")],
    # EV / Consumer Discretionary
    "RIVN":  [("XLY",  "XLY")],
    # EV charging infrastructure / Utilities
    "EVGO":  [("XLU",  "XLU")],
    # Quantum computing / broad tech
    "RGTI":  [("XLK",  "XLK")],
    # Broad market ETF — benchmark against S&P 500
    "QQQ":   [("^GSPC", "SPX")],
}

# Sub-sector → specific index (takes priority over sector fallback)
INDUSTRY_BENCHMARK = {
    "Semiconductors":              ("^SOX",  "SOX"),
    "Biotechnology":               ("IBB",   "IBB"),
    "Drug Manufacturers—General":  ("XPH",   "XPH"),
    "Banks—Regional":              ("KRE",   "KRE"),
    "Banks—Diversified":           ("KBE",   "KBE"),
    "Oil & Gas E&P":               ("XOP",   "XOP"),
    "Oil & Gas Integrated":        ("XOP",   "XOP"),
    "Airlines":                    ("JETS",  "JETS"),
    "Homebuilding & Construction":  ("XHB",  "XHB"),
}

# Sector → SPDR ETF fallback
SECTOR_BENCHMARK = {
    "Technology":             ("XLK",  "XLK"),
    "Financial Services":     ("XLF",  "XLF"),
    "Healthcare":             ("XLV",  "XLV"),
    "Consumer Cyclical":      ("XLY",  "XLY"),
    "Consumer Defensive":     ("XLP",  "XLP"),
    "Energy":                 ("XLE",  "XLE"),
    "Utilities":              ("XLU",  "XLU"),
    "Industrials":            ("XLI",  "XLI"),
    "Basic Materials":        ("XLB",  "XLB"),
    "Real Estate":            ("XLRE", "XLRE"),
    "Communication Services": ("XLC",  "XLC"),
}

FALLBACK_BENCHMARK = ("^GSPC", "SPX")

# Tickers where catalyst proximity is noise in direction models (binary events dominate).
# Days_to_catalyst is neutralized (set to 90 sentinel) when for_direction=True.
# Phase 3 / volatility models are unaffected — IV expansion near events is real signal.
EVENT_DRIVEN_TICKERS = {"CRSP"}

# Opt-in macro features for rate/commodity-sensitive tickers.
# Format: "TICKER": [(yf_symbol, feature_name), ...]
# Add new tickers as needed; tickers not listed get no macro features.
MACRO_FEATURES = {
    "SOFI": [("^TNX", "UST10Y"), ("^IRX", "UST3M")],
    "JPM":  [("^TNX", "UST10Y"), ("^IRX", "UST3M")],
    "BAC":  [("^TNX", "UST10Y"), ("^IRX", "UST3M")],
    "GS":   [("^TNX", "UST10Y"), ("^IRX", "UST3M")],
    "MS":   [("^TNX", "UST10Y"), ("^IRX", "UST3M")],
    "WFC":  [("^TNX", "UST10Y"), ("^IRX", "UST3M")],
    "C":    [("^TNX", "UST10Y"), ("^IRX", "UST3M")],
}


def detect_macro_features(ticker):
    """Returns list of (yf_symbol, feature_name) pairs for ticker, or [] if none defined."""
    return MACRO_FEATURES.get(ticker, [])


def add_macro_features(df, macro_features, start_date, end_date):
    """
    Fetch and join macro features (rate data, etc.) into df.
    No-op if macro_features is empty — safe to call for any ticker.
    Derives per-source: raw value, 5d change, vs 20d MA.
    If both UST10Y and UST3M present, also derives yield_curve and yield_curve_chg_5d.
    """
    if not macro_features:
        return df

    fetched = {}
    macro_cols = []
    for symbol, name in macro_features:
        raw = yf.download(symbol, start=start_date, end=end_date, progress=False)
        raw.columns = raw.columns.get_level_values(0)
        series = raw[["Close"]].rename(columns={"Close": name})
        series[f"{name}_chg_5d"]  = series[name].pct_change(5)
        series[f"{name}_vs_ma20"] = series[name] / series[name].rolling(20).mean() - 1
        df = df.join(series, how="left")
        ff_cols = [name, f"{name}_chg_5d", f"{name}_vs_ma20"]
        df[ff_cols] = df[ff_cols].ffill()
        macro_cols += ff_cols
        fetched[name] = True
        print(f"  ✓ {name}, {name}_chg_5d, {name}_vs_ma20")

    if "UST10Y" in fetched and "UST3M" in fetched:
        df["yield_curve"]        = df["UST10Y"] - df["UST3M"]
        # diff(5), not pct_change(5): the 10Y-3M spread crosses zero at curve inversions
        # (e.g. 2007-08-10), so a percentage change divides by ~0 and explodes to +inf
        # (crashes StandardScaler). An absolute 5-day spread change (pp) is well-defined.
        df["yield_curve_chg_5d"] = df["yield_curve"].diff(5)
        macro_cols += ["yield_curve", "yield_curve_chg_5d"]
        print("  ✓ yield_curve, yield_curve_chg_5d")

    # Defensive: near-zero / negative short rates (^IRX during ZIRP and the 2008 panic)
    # can still make a pct_change/ratio feature non-finite; convert any inf to NaN so the
    # affected row drops out cleanly rather than crashing the model.
    if macro_cols:
        df[macro_cols] = df[macro_cols].replace([np.inf, -np.inf], np.nan)

    return df


def add_catalyst_proximity(df, ticker, data_dir="modules", for_direction=False):
    """
    Joins Days_to_catalyst from data/catalysts.csv — days until the next known binary event
    (PDUFA date or clinical trial readout) for the given ticker.
    Silent no-op (fills 90) when file missing or ticker not in file.
    Populate catalysts.csv manually; columns: ticker, date, type, description.
    for_direction=True neutralizes event-driven tickers (EVENT_DRIVEN_TICKERS) by filling 90 —
    catalyst proximity is noise for direction models when events are binary and unpredictable.
    """
    if for_direction and ticker.upper() in EVENT_DRIVEN_TICKERS:
        df["Days_to_catalyst"] = 90
        return df
    csv_path = os.path.join(data_dir, "catalysts.csv")
    if not os.path.exists(csv_path):
        df["Days_to_catalyst"] = 90
        return df

    cats = pd.read_csv(csv_path)
    cats["date"] = pd.to_datetime(cats["date"])
    cats = cats[cats["ticker"].str.upper() == ticker.upper()]

    if cats.empty:
        df["Days_to_catalyst"] = 90
        return df

    dates = sorted(cats["date"].dt.normalize().unique())

    def _days_to_next(date):
        # Cap at 90 (S31): mirrors add_earnings_proximity. Without it, a ticker whose
        # history predates its first catalyst date gets a calendar-time ramp for old rows
        # (the same leak fixed in earnings). Dormant today — catalysts.csv is CRSP-only and
        # CRSP is direction-neutralized — but capped defensively against future additions.
        future = [d for d in dates if d >= date]
        return min(int((future[0] - date).days), 90) if future else 90

    df["Days_to_catalyst"] = [_days_to_next(d) for d in df.index]
    print(f"  ✓ Days_to_catalyst ({len(dates)} event(s) for {ticker})")
    return df


def detect_benchmarks(ticker):
    """
    Returns a list of (yf_ticker, display_name) benchmark tuples for the given ticker.
    Checks TICKER_BENCHMARK first (no network call), then falls back to yfinance
    sector/industry lookup, then SPX if everything fails.
    """
    if ticker in TICKER_BENCHMARK:
        return TICKER_BENCHMARK[ticker]

    benchmarks = []
    try:
        info     = yf.Ticker(ticker).info
        industry = info.get("industry", "")
        sector   = info.get("sector",   "")
        if industry in INDUSTRY_BENCHMARK:
            benchmarks.append(INDUSTRY_BENCHMARK[industry])
        if sector in SECTOR_BENCHMARK:
            sector_bench = SECTOR_BENCHMARK[sector]
            if sector_bench not in benchmarks:
                benchmarks.append(sector_bench)
    except Exception:
        pass
    return benchmarks or [FALLBACK_BENCHMARK]
