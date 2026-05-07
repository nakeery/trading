# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Pipeline

Daily workflow:

```bash
# 1. Refresh data + indicators (run daily)
python indicators.py

# 2. Get entry decision — SIGNAL + POSITION SIZING
python entry.py

# 3. If signal is actionable: get live options chain sizing via Tradier
python sizing.py
```

As-needed analysis:

```bash
# Direction model detail (Phase 2 + 2B)
python direction.py

# IV expansion model detail (Phase 3)
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

Use the **PowerShell tool** (not Bash) with the cmd /c echo pipe:

```powershell
cmd /c "(echo TICKER && echo.) | python -X utf8 script.py" 2>&1
```

- `-X utf8` is required — avoids cp1252 UnicodeEncodeError on Windows
- `cmd /c` echo pipe is required — PowerShell's native `|` prepends a BOM to stdin
- **Bash tool does not capture Python stdout from cmd /c subprocesses** — script runs but output is dropped. Always use the PowerShell tool.

## Architecture

Seven scripts. `indicators.py` must run first — all downstream scripts depend on its CSV output.

| Script | Purpose | Output |
|---|---|---|
| `indicators.py` | Fetch OHLCV, compute 30+ indicators | `data/{ticker}_indicators.csv`, `data/{ticker}_dashboard.png` |
| `direction.py` | Direction ML models (Phase 2 + 2B) | `data/{ticker}_ml_features.csv`, `data/{ticker}_ml_results.png` |
| `volatility.py` | IV expansion ML model (Phase 3) | `data/{ticker}_phase3_features.csv`, `data/{ticker}_phase3_results.png` |
| `entry.py` | Combines all models → SIGNAL + POSITION SIZING | Console only |
| `backtest.py` | Walk-forward backtest (51 windows for QQQ; 15 for AMD; 17 for CRSP) | `data/{ticker}_backtest.png`, `data/{ticker}_backtest_results.csv` |
| `sizing.py` | Live options chain sizing via Tradier API | Console only |
| `modules/benchmarks.py` | Shared sector benchmarks, macro features, catalyst proximity | Imported by direction/entry/backtest/volatility |

All CSVs and PNGs are written to the `data/` subdirectory (must exist — create manually if missing).

## Decision Framework

`entry.py` and `backtest.py` use a unified four-label SIGNAL output:

| Signal | Conditions | Position Sizing |
|---|---|---|
| **STRONG ENTRY** | 15d WIN + 63d WIN + Phase 3 EXPANSION | FULL |
| **CAUTION** | 15d WIN + 63d WIN + Phase 3 CONTRACTION | REDUCED |
| **SHORT-TERM ONLY** | 15d WIN + 63d NO SIGNAL (any Phase 3) | REDUCED |
| **STAY OUT** | 15d NO SIGNAL | N/A |

- Phase 2 (15d) drives ENTER vs STAY OUT
- Phase 2B (63d) confirms or rejects medium-term thesis
- Phase 3 (IV expansion) modulates sizing — not a go/no-go gate

## Key Design Decisions

- **Logistic regression only** — intentional for interpretability; black-box models avoided
- **Time-based train/test split** (not random) — avoids lookahead bias in time series
- **Price-level features normalized** to ratios/pct_change — ticker-agnostic and scale-invariant
- **Earnings proximity capped** at 45–90 days, defaults to neutral when earnings data unavailable
- **IV proxied from HV-20** — approximates IV rank/percentile without a paid options feed
- **Vol-adjusted thresholds** via `compute_vol_thresholds()` — auto-calibrates per ticker:
  - `WIN_THRESHOLD = P2_VOL_MULTIPLE × median_HV × sqrt(15/252)` (Phase 2)
  - `WIN_THRESHOLD_63 = P2_VOL_MULTIPLE × median_HV × sqrt(63/252)` (Phase 2B)
  - `EXPANSION_THRESHOLD = P3_VOL_MULTIPLE × median_HV` (Phase 3)
  - `P2_VOL_MULTIPLE = 0.41` (0.41-sigma difficulty bar; tuning range 0.25–1.0)
  - `P3_VOL_MULTIPLE = 0.20` (heuristic; validate via backtest for new tickers)
- **Benchmarks via `modules/benchmarks.py`** — 3-tier lookup: `TICKER_BENCHMARK` dict (no network) → yfinance sector/industry → SPX fallback
  - AMD/NVDA → SOX + XLK; SOFI → KBE + XLF; CRSP → IBB + XLV; RIVN → XLY; QQQ → SPX
  - Feature names: `{bench_name}_RS_5d`, `{bench_name}_RS_20d`, `{bench_name}_vs_ma200`
- **Macro features** (`MACRO_FEATURES` in benchmarks.py) — opt-in for rate-sensitive tickers
  - SOFI/JPM/BAC/GS/MS/WFC/C → ^TNX (UST10Y) + ^IRX (UST3M); derives yield_curve
- **Catalyst proximity** (`add_catalyst_proximity` in benchmarks.py) — reads `data/catalysts.csv`
  - `for_direction=True` flag neutralizes catalyst feature for `EVENT_DRIVEN_TICKERS = {"CRSP"}`
  - Reason: catalyst proximity creates spurious "near event → bullish" association in
    direction models for binary-event biotechs (FDA decisions, trial readouts unpredictable)
  - Phase 3 (`volatility.py`) uses default `for_direction=False` — IV expansion near events is real signal
- **`FORWARD_DAYS = 15`** kept intentionally — entry timing signal, not holding period predictor
  - Phase 2B (63-day) added as LEAPS-aligned thesis validation layer

## Model Details

All models: `LogisticRegression(C=0.1, class_weight="balanced")`, 80/20 time-based split.

| | Phase 2 (15d) | Phase 2B (63d) | Phase 3 (IV) |
|---|---|---|---|
| Target | Vol-adjusted gain in 15d | Vol-adjusted gain in 63d | HV expansion in 10d |
| Threshold | 0.55 | 0.55 | 0.60 |

QQQ test (Session 7 baseline): Phase 2 +7.7pt edge, Phase 2B +6.3pt, Phase 3 +22.5pt.
Volatility is more predictable than direction — Phase 3 has roughly 3× the edge of either direction model.

Threshold sweep auto-marks optimal using `max(precision - base_rate) × log(signals)` — rewards edge above base rate and signal volume simultaneously.

## Sizing Config (`sizing.py`)

- `TRADIER_TOKEN` — brokerage token required (not sandbox; sandbox uses simulated data)
- `MIN_DTE = 180`, `MAX_DTE = 365` — targets 6–12 month expiries
- `DEFAULT_STRIKE_RANGE = 10` strikes above/below ATM
- IV source: `smv_vol` (smoothed model vol — matches Tradier app display)
- ATM anchor: nearest real ATM strike, not exact stock price
- All strikes shown including "over budget" ones (not silently filtered)
- IV/HV ratio shown via `^` (>120%, expensive) and `v` (<80%, cheap) markers — useful for assessing whether option premium is rich relative to realized vol

## Geopolitical / Exogenous Shock Limitation

The framework is **reactive, not predictive** of shocks. All inputs are derived from price/volume/HV history; the model cannot detect war escalations, central bank surprises, or other exogenous events before they affect prices.

Phase 3 classification report directly evidences this:
- Contraction precision: ~79% (calm regimes mean-revert reliably)
- Expansion precision: ~64% (shocks are structurally unlearnable from price history)

During known geopolitical crises (e.g. Iran war, May 2026):
- The IV/HV ratio gap is itself information about tail risk — the options market sees what the model doesn't
- Trust contraction signals less when binary catalysts loom
- Weight options-market-implied premium higher than Phase 3's HV-based output

See `memory/context.md` "Geopolitical Risk Limitation" for proposed mitigations (VIX term structure, put/call ratio, etc.).

## Known Issues (not yet fixed)

- `indicators.py`: unused `import mdates`
- `direction.py`: dead `N_ESTIMATORS = 200` constant (Random Forest leftover)
- `sizing.py`: `TRADIER_TOKEN` hardcoded in source (security risk — should be env var)

## Important Warnings

- **NEVER name a script `signal.py`** — it shadows Python's built-in `signal` module and causes `AttributeError: partially initialized module 'subprocess'`. The original `entry_signal.py` was renamed to `entry.py` to resolve this.
- **`backtest.py` is self-contained** — does NOT import from `direction.py` or `volatility.py`. If feature engineering changes in those scripts, `backtest.py` must be manually updated to match.
- **`data/` directory must exist** before running any script — create it manually if missing.
- **`modules/` directory** holds `benchmarks.py` and `catalysts.csv`. Catalyst CSV path is `data_dir`-relative; the `csv_path = os.path.join(data_dir, "catalysts.csv")` fix in Session 7 is required for catalyst loading to work.
- **`trade/` subdirectory** is the Python virtual environment — do not delete.
- **`memory/` subdirectory** is Claude's auto-memory system.
- **yfinance `.info` returns 401 errors** — `TICKER_BENCHMARK` dict in `benchmarks.py` bypasses this entirely for known tickers.
- **ETFs have no earnings** — yfinance "may be delisted" warning is harmless; `Days_to_earnings` defaults to 45 (neutral).
- **`data/catalysts.csv`** must have no commas in description field (use dashes instead) — pandas reads ragged CSV otherwise.
- **Unicode arrow (`->`)**: not a problem in VS Code/Windows Terminal; only affects cmd.exe with cp1252 encoding.

## Tech Stack

`yfinance`, `pandas`, `numpy`, `ta`, `matplotlib`, `scikit-learn` (LogisticRegression, StandardScaler, precision_score), `lxml` (earnings dates), `requests` (Tradier API in sizing.py)

## Ticker Suitability Notes

- **AMD**: well-suited; 15 walk-forward windows (2019–2026); STRONG ENTRY 2.6% avg / 59.7% win rate
- **QQQ**: best statistical validation; 51 windows (2002–2026); clean signal hierarchy; framework reference baseline
- **SOFI**: marginal — short history (2021 IPO); rate features wired but need more rate-regime variation
- **NVDA**: marginal — bull trend too strong post-2023 AI pivot; vol regime change hurts Phase 3
- **CRSP**: unsuitable for direction (binary FDA/trial events dominate); Phase 3 viable for vol plays — consider straddles/strangles around PDUFA dates rather than directional calls. Catalyst feature is automatically neutralized in direction models via `EVENT_DRIVEN_TICKERS`.

Cross-ticker finding: CAUTION avg loss is consistently 3–4pt worse than STRONG ENTRY (validates REDUCED sizing for IV-contraction signals). SHORT-TERM ONLY behavior is ticker-dependent: best on AMD (12.2% — momentum bursts) but near-worst on QQQ (0.7% — no sharp momentum bursts on an index).