# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Pipeline

Daily workflow:

```bash
# 1. Refresh data + indicators (run daily)
python indicators.py

# 2. Get entry decision — ENTER/STAY OUT + FULL/REDUCED sizing
python entry.py

# 3. If ENTER: get live options chain sizing via Tradier
python sizing.py
```

As-needed analysis:

```bash
# Direction model detail
python direction.py

# IV expansion model detail
python volatility.py

# Walk-forward backtest (periodic validation)
python backtest.py
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### Prompt counts per script (for piped input via Claude Code)

| Script | Prompts |
|---|---|
| indicators.py | 3 (ticker, start date, end date) + trailing chart prompt |
| direction.py | 2 (ticker, benchmarks — blank = default) |
| volatility.py | 1 (ticker) |
| entry.py | 2 (ticker, benchmarks — blank = default) |
| backtest.py | 2 (ticker, benchmarks) + trailing chart prompt |
| sizing.py | interactive (ticker, budget, strikes) |

### Running scripts via Claude Code on Windows

```bash
cmd /c "(echo TICKER && echo.) | python -X utf8 script.py"
```

- `-X utf8` is required — avoids cp1252 UnicodeEncodeError on Windows
- `cmd /c` pipe is required — PowerShell prepends a BOM character to the ticker input

## Architecture

Seven scripts run sequentially. `indicators.py` must run first — all downstream scripts depend on its CSV output.

| Script | Purpose | Output |
|---|---|---|
| `indicators.py` | Fetch OHLCV, compute 30+ indicators | `data/{ticker}_indicators.csv`, `data/{ticker}_dashboard.png` |
| `direction.py` | Direction ML model (≥5% gain in 15d?) | `data/{ticker}_ml_features.csv`, `data/{ticker}_ml_results.png` |
| `volatility.py` | IV expansion ML model (HV ≥10% higher in 10d?) | `data/{ticker}_phase3_features.csv`, `data/{ticker}_phase3_results.png` |
| `entry.py` | Combines both models → ENTER/STAY OUT + FULL/REDUCED | Console only |
| `backtest.py` | Walk-forward backtest (13–15 windows, 2019–present) | `data/{ticker}_backtest.png`, `data/{ticker}_backtest_results.csv` |
| `sizing.py` | Live options chain sizing via Tradier API | Console only |
| `benchmarks.py` | Shared sector benchmark detection — no output | Imported by direction.py, entry.py, backtest.py |

All CSVs and PNGs are written to the `data/` subdirectory (must exist — create manually if missing).

## Decision Framework

- **Phase 2 fires (direction model ≥ threshold)** → ENTER
  - **Phase 3 expansion** → FULL position size
  - **Phase 3 contraction** → REDUCED position size
- **Phase 2 doesn't fire** → STAY OUT (regardless of Phase 3)

Phase 3 (IV expansion) is a **sizing input**, not a go/no-go gate.

## Key Design Decisions

- **Logistic regression only** — intentional for interpretability; black-box models avoided
- **Time-based train/test split** (not random) — avoids lookahead bias in time series
- **Price-level features normalized** to ratios/pct_change — ticker-agnostic and scale-invariant
- **Earnings proximity capped** at 45–90 days, defaults to neutral when earnings data unavailable
- **IV proxied from HV-20** — approximates IV rank/percentile without a paid options feed
- **Vol-adjusted thresholds** via `compute_vol_thresholds()` — auto-calibrates WIN_THRESHOLD and EXPANSION_THRESHOLD to each ticker's median HV at runtime
  - `P2_VOL_MULTIPLE = 0.41` (0.41-sigma difficulty bar; tuning range 0.25–1.0)
  - `P3_VOL_MULTIPLE = 0.20` (heuristic; validate via backtest for new tickers)
  - Math: `sqrt(FORWARD_DAYS/252)` scales volatility to the forward window (square-root-of-time rule)
- **Benchmarks via `benchmarks.py`** — 3-tier lookup: `TICKER_BENCHMARK` dict (no network) → yfinance sector/industry → SPX fallback
  - AMD/NVDA → SOX + XLK; SOFI → KBE + XLF; RIVN → XLY; QQQ → SPX
  - Feature names: `{bench_name}_RS_5d`, `{bench_name}_RS_20d`
- **`FORWARD_DAYS = 15`** kept intentionally — functions as entry timing signal, not holding period predictor

## Model Details

Both models: `LogisticRegression(C=0.1, class_weight="balanced")`, 80/20 time-based split.

| | Direction (Phase 2) | IV Expansion (Phase 3) |
|---|---|---|
| Target | ≥5% gain in 15 days | HV ≥10% higher in 10 days |
| Threshold | 0.55 | 0.60 |
| Precision vs base rate | ~50.4% vs 37.8% | ~59% vs 27.8% |

Threshold sweep auto-marks optimal using `max(precision - base_rate) × log(signals)` — rewards edge above base rate and signal volume simultaneously.

## Sizing Config (`sizing.py`)

- `TRADIER_TOKEN` — brokerage token required (not sandbox; sandbox uses simulated data)
- `MIN_DTE = 180`, `MAX_DTE = 365` — targets 6–12 month expiries
- `DEFAULT_STRIKE_RANGE = 10` strikes above/below ATM
- IV source: `smv_vol` (smoothed model vol — matches Tradier app display)
- ATM anchor: nearest real ATM strike, not exact stock price
- All strikes shown including "over budget" ones (not silently filtered)

## Known Issues (not yet fixed)

- `indicators.py`: unused `import mdates`
- `direction.py`: dead `N_ESTIMATORS = 200` constant (Random Forest leftover)
- `sizing.py`: `TRADIER_TOKEN` hardcoded in source (should be env var)
- `backtest.py`: signal labels still "STRONG ENTRY/CAUTION/STAY OUT" (pre-refactor naming, inconsistent with entry.py's ENTER/FULL/REDUCED)

## Important Warnings

- **NEVER name a script `signal.py`** — it shadows Python's built-in `signal` module and causes `AttributeError: partially initialized module 'subprocess'`. The original `entry_signal.py` was renamed to `entry.py` to resolve this.
- **`backtest.py` is self-contained** — does NOT import from `direction.py` or `volatility.py`. If feature engineering changes in those scripts, `backtest.py` must be manually updated to match.
- **`data/` directory must exist** before running any script — create it manually if missing.
- **`trade/` subdirectory** is the Python virtual environment — do not delete.
- **yfinance `.info` returns 401 errors** — `TICKER_BENCHMARK` dict in `benchmarks.py` bypasses this entirely for known tickers.
- **Unicode arrow (`->`)**: not a problem in VS Code/Windows Terminal; only affects cmd.exe with cp1252 encoding.

## Tech Stack

`yfinance`, `pandas`, `numpy`, `ta`, `matplotlib`, `scikit-learn` (LogisticRegression, StandardScaler, precision_score), `lxml` (earnings dates), `requests` (Tradier API in sizing.py)

## Ticker Suitability Notes

- **AMD**: well-suited; model validated across 15 walk-forward windows (2019–2026)
- **NVDA**: marginal — bull trend too strong (all days avg high), vol regime changed post-2023 AI pivot
- **SOFI**: marginal — short history (2021 IPO), missing rate/credit features; STAY OUT can outperform on thin edge
- Cross-ticker finding: CAUTION avg loss is consistently 3–4pt worse than STRONG ENTRY (validates REDUCED sizing for IV-contraction signals)
