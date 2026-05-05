"""
Benchmark detection — shared module for all ML pipeline scripts.
Maps ticker sector/industry to the appropriate market benchmark(s).

Lookup order:
  1. TICKER_BENCHMARK   — direct per-ticker mapping (no network call, fastest)
  2. INDUSTRY_BENCHMARK — yfinance sector/industry lookup (requires working .info API)
  3. SECTOR_BENCHMARK   — broad SPDR ETF fallback via yfinance
  4. FALLBACK_BENCHMARK — S&P 500 if everything else fails

To add a ticker: add an entry to TICKER_BENCHMARK.
"""

import yfinance as yf

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
