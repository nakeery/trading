# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Pipeline

All scripts prompt for ticker (default: AMD) and run interactively:

```bash
# Phase 1 — fetch data & compute technical indicators → {ticker}_indicators.csv
python entry_phase1.py

# Phase 2 — direction ML model (will gain ≥5% in 15d?) → {ticker}_ml_features.csv + chart
python entry_phase2.py

# Phase 3 — IV expansion ML model (HV ≥10% higher in 10d?) → {ticker}_phase3_features.csv + chart
python entry_phase3.py

# Combined signal — runs Phase 2 & 3 fresh, prints STRONG ENTRY / CAUTION / STAY OUT
python entry_signal.py
```

Install dependencies:
```bash
pip install -r requirements.txt
```

## Architecture

This is a 3-phase options entry signal system built around AMD (but works for any yfinance ticker):

**Phase 1 → Phase 2/3 → Signal** — scripts are sequential. Phase 2, 3, and the signal script all depend on the CSV output from Phase 1.

**Phase 1 (`entry_phase1.py`):** Downloads OHLCV from yfinance, computes 30+ technical indicators via the `ta` library (RSI-6/14/23, MA-20/50/100/200, EMA-8/21/34/55/89, Keltner Channels, OBV, MACD, Stochastic), and saves `{ticker}_indicators.csv`.

**Phase 2 (`entry_phase2.py`):** Loads the Phase 1 CSV, fetches VIX (^VIX), SOX (^SOX), and earnings dates from yfinance. Engineers features: HV-20, IV rank/percentile (derived from HV), VIX changes, SOX relative strength, days-to-earnings. Trains a logistic regression (C=0.1, balanced class weights, 80/20 time split) to predict ≥5% gain in 15 days.

**Phase 3 (`entry_phase3.py`):** Same data loading pattern. Target is HV expansion ≥10% in 10 days. Features emphasize volatility dynamics: HV changes, IV rank/percentile trends, VIX momentum.

**Signal (`entry_signal.py`):** Trains both models, applies thresholds (direction ≥0.55, expansion ≥0.60), and outputs the recommendation. This is the primary production entry point.

## Key Design Decisions

- **Logistic regression only** — intentional for interpretability; user prefers practical/interpretable models over black-box approaches
- **Time-based train/test split** (not random) — avoids lookahead bias in time series
- **Price-level features normalized** to ratios/pct_change — makes features ticker-agnostic and scale-invariant
- **Earnings proximity capped** at 45–90 days and defaulted to neutral when earnings data is unavailable
- **IV proxied from HV** — the system uses historical volatility (HV-20) to approximate IV rank/percentile since real IV data requires a paid options feed
- All outputs (CSVs, PNGs) are written to the project root, named `{ticker}_*`
