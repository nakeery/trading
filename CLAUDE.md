# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Pipeline

Daily workflow:

```bash
# 1. Refresh data + indicators + harvest today's options chain snapshot from Massive
python indicators.py

# 2. Get entry decision — SIGNAL + POSITION SIZING (reads IV from indicators CSV)
python entry.py

# 3. If signal is actionable: get live options chain sizing via Tradier
python sizing.py
```

`indicators.py` requires a Massive API key for the chain harvest. The key is currently HARDCODED
in `modules/massive.py:16` (regression — see Known Issues). Once the env-var pattern is restored,
set `$env:MASSIVE_API_KEY` and add it to `$PROFILE` for persistence across PowerShell sessions.
If the env var ever goes unset and the hardcode is removed, IV columns are written as NaN and
`entry.py` warns to re-run.

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

`indicators.py` must run first — all downstream scripts depend on its CSV output.

| Script | Purpose | Output |
|---|---|---|
| `indicators.py` | Fetch OHLCV, compute 30+ indicators, harvest today's chain summary from Massive | `data/{ticker}_indicators.csv` (with IV cols), `data/{ticker}_dashboard.png` |
| `direction.py` | Direction ML models (Phase 2 + 2B) | `data/{ticker}_ml_features.csv`, `data/{ticker}_ml_results.png` |
| `volatility.py` | IV expansion ML model (Phase 3) | `data/{ticker}_phase3_features.csv`, `data/{ticker}_phase3_results.png` |
| `entry.py` | Combines all models → SIGNAL + POSITION SIZING (reads IV from CSV — no live API) | Console only |
| `backtest.py` | Walk-forward backtest + 6-month forward return table (53 windows QQQ; 91 AMD; 53 NVDA; 31y SPY; 17 CRSP) | `data/{ticker}_backtest.png`, `data/{ticker}_backtest_results.csv` |
| `sizing.py` | Live options chain sizing via Tradier API | Console only |
| `backfill_iv.py` | Standalone 2-year historical IV backfill via BS-inversion (one-off per ticker) | Updates `data/{ticker}_indicators.csv` in place; checkpointed |
| `modules/features.py` | Shared feature engineering (HV, VIX, earnings, normalize, vol thresholds, IV imputation) + constants (S14/S16) | Imported by direction/volatility/entry/backtest |
| `modules/benchmarks.py` | Sector benchmarks, macro features, catalyst proximity | Imported by direction/entry/backtest/volatility |
| `modules/massive.py` | Massive.com API client + `get_chain_summary()` + `get_historical_iv_snapshot()`; exports `IV_COLS`, `IV_FEATURE_COLS`, `IV_META_COLS` | Imported by `indicators.py` (harvest), `backfill_iv.py` (history), and 5 ML scripts (exclude from features) |
| `modules/bs_invert.py` | Black-Scholes implied-vol solver (Newton-Raphson + bisection fallback) — used by `backfill_iv.py` | Imported by `modules/massive.py` |
| `modules/tradier.py` | Tradier API client + `get_atm_iv()` | Imported by `sizing.py` only |

All CSVs and PNGs are written to the `data/` subdirectory (must exist — create manually if missing).

## Decision Framework

`entry.py` and `backtest.py` use a unified five-label SIGNAL output:

| Signal | Conditions | Position Sizing |
|---|---|---|
| **STRONG ENTRY** | 15d WIN + 63d WIN + Phase 3 EXPANSION | FULL |
| **CAUTION** | 15d WIN + 63d WIN + Phase 3 CONTRACTION | REDUCED |
| **SHORT-TERM ONLY** | 15d WIN + 63d NO SIGNAL (any Phase 3) | REDUCED |
| **LEAPS ONLY** | 15d NO SIGNAL + 63d WIN | LEAPS (6–9mo expiries) |
| **STAY OUT** | 15d NO SIGNAL + 63d NO SIGNAL | N/A |

- Phase 2 (15d) drives ENTER vs STAY OUT for short-DTE setups
- Phase 2B (63d) confirms or rejects medium-term thesis (LEAPS-aligned)
- Phase 3 (IV expansion) modulates sizing — not a go/no-go gate
- **IV/HV gate (`entry.py` only)**: ATM IV (~30 DTE) read from `atm_iv_30d` column in indicators
  CSV (harvested by `indicators.py` from Massive) and compared to HV-20. If `signal == STRONG ENTRY`
  and `IV/HV >= 1.40`, downgrade to `CAUTION`. The ratio + label (cheap/fair/rich/very rich) prints
  regardless of signal. If `atm_iv_30d` is NaN (Massive harvest failed or never ran), prints a
  warning to re-run `indicators.py` and skips the gate.
- **Term structure** (`entry.py` display only — not yet a feature): printed with 5-band label.
  `< 0.95` contango → `0.95–0.98` slight contango → `0.98–1.02` noise → `1.02–1.05` slight
  backwardation → `> 1.05` backwardation. Treat `> 1.05` as a stress signal (trust contraction
  signals less; weight options-market-implied tail risk higher).
- **6-month forward return table** (`backtest.py`, S15): printed after the 15d table. For QQQ,
  `STRONG ENTRY` is the only signal with edge on both 15d (+1.9%) and 6mo (+10.6%) horizons.
  Use the 15d table to decide whether to enter; use the 6mo table to decide DTE.
  `LEAPS ONLY` does NOT outperform `ALL DAYS` at 6mo for QQQ — informational only at index level.

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
- **IV harvest in `indicators.py`** (S10) — daily chain summary written to today's row of
  indicators CSV. Two-call pattern in `modules/massive.py`: front tenor (target_dte ± 7d, wide
  strikes) for ATM IV + 25Δ skew + P/C OI; back tenor (55–90 DTE, narrow ATM strikes) for term
  structure. Avoids hitting the 1250-contract pagination cap.
- **CSV merge preserves IV history** — `harvest_iv_snapshot()` reads existing CSV and merges
  prior IV via `combine_first` before writing today's. Without this, every `indicators.py` re-run
  would wipe accumulated IV data because the CSV is regenerated from scratch.
- **`IV_COLS` exclusion required in all ML scripts** — the 7 IV columns are NaN for pre-backfill
  rows. Every `train()` / `train_model()` must include `*IV_COLS` in its exclude set (or
  `*IV_META_COLS` if `--iv-features` is on), or `dropna()` removes the entire training set.
  Applied in entry/direction/volatility/backtest/calibrate_multipliers.
- **Today-row addition in `indicators.py`** (S16) — when today is a weekday and yfinance hasn't
  returned today's bar yet (yfinance `end` is exclusive), `harvest_iv_snapshot` appends a today-row
  with NaN OHLCV so the IV stamp lands on today's date instead of overwriting yesterday's IV.
  Side effect: each `indicators.py` run grows the df by 1 row, shifting the 80/20 split forward
  by 1 sample. Daily probabilities can drift run-to-run (observed +16pp shift in QQQ Phase 3
  expansion prob during S16 verification). Expected behavior, not a bug — but worth knowing if
  comparing run-to-run probabilities.
- **Shared feature engineering** (`modules/features.py`, S14/S16) — `compute_hv_features`,
  `compute_vix_features`, `add_earnings_proximity`, `normalize_features`, `compute_vol_thresholds`,
  `impute_iv_features`, plus all phase constants. Used by direction/volatility/entry/backtest.
  `direction.py` and `volatility.py` still wrap `compute_vix_features` and the benchmarks loop
  with thin local helpers (`add_vix`, `add_benchmarks`) — refactor incomplete.

## Model Details

All models: `LogisticRegression(C=0.1, class_weight="balanced")`, 80/20 time-based split, `RANDOM_STATE=42`.

| | Phase 2 (15d) | Phase 2B (63d) | Phase 3 (IV) |
|---|---|---|---|
| Target | Vol-adjusted gain in 15d | Vol-adjusted gain in 63d | HV expansion in 10d |
| Threshold | 0.55 | 0.55 | 0.60 |

Volatility is more predictable than direction — Phase 3 has roughly 3× the edge of either direction model
(QQQ: Phase 2 +1.5pt edge, Phase 2B +6.3pt, Phase 3 +27pt at production thresholds).

Threshold sweep auto-marks optimal using `max(precision - base_rate) × log(signals)` — rewards edge
above base rate and signal volume simultaneously.

CLI flags (default OFF on all three; available on direction/entry/backtest):
- `--calibrate` — isotonic Phase 2 (Decision 1, S11). Reverted to default OFF after NVDA regression
  (STRONG ENTRY 4.4% → -0.4%). Calibrated mode uses P2_THRESHOLD=0.50 instead of 0.55.
- `--iv-features` — Phase 3 uses real Massive IV (`atm_iv_30d`, `iv_skew_25d`, `term_structure`)
  with HV-based imputation for pre-backfill rows. Default uses HV proxy (full price history).
  Validated on QQQ (75.0% expansion precision, +0.8pp over HV proxy).

## Sizing Config (`sizing.py`)

- `TRADIER_TOKEN` — brokerage token required (not sandbox; sandbox uses simulated data)
- `MIN_DTE = 180`, `MAX_DTE = 365` — targets 6–12 month expiries
- `DEFAULT_STRIKE_RANGE = 10` strikes above/below ATM
- IV source: `smv_vol` (smoothed model vol — matches Tradier app display)
- ATM anchor: nearest real ATM strike, not exact stock price
- All strikes shown including "over budget" ones (not silently filtered)
- IV/HV ratio shown via `^` (>120%, expensive) and `v` (<80%, cheap) markers — useful for assessing whether option premium is rich relative to realized vol

## Massive Config (`modules/massive.py`)

- ⚠️ **`MASSIVE_API_KEY` is currently HARDCODED** at `modules/massive.py:16` (regression — was
  env-var-only by design). Active security risk: file is in git. Restore env-var pattern + rotate
  the key as part of the fix. The commented-out env-var line is preserved on line 15 for the fix.
- Plan tier: Options Starter (15-min delayed snapshots, 2yr historical, unlimited rate limit)
- `MASSIVE_URL = https://api.massive.com` — surface is functionally identical to Polygon.io
- `get_chain_summary(ticker, underlying_price, target_dte=30)` returns:
  `atm_iv_30d`, `atm_strike`, `atm_expiry`, `atm_dte`, `iv_skew_25d`, `term_structure`, `put_call_oi_ratio`
- Two-call daily harvest (avoids pagination cap):
  - Front: `dte=target±7`, strikes `spot×0.85` to `×1.15` → ATM IV + 25Δ skew + P/C OI
  - Back: `dte=55-90`, strikes `spot×0.97` to `×1.03` → back-month ATM for term structure
- Filters out `iv=20` placeholder (Massive returns this for deep ITM/OTM with empty greeks)
- Snapshot endpoint is current-only — `expired=true` is ignored on `/v3/snapshot/options/`
  (only honored on `/v3/reference/options/contracts`). Historical IV uses BS-inversion in
  `get_historical_iv_snapshot()` + `backfill_iv.py` + `modules/bs_invert.py` (contracts reference +
  per-contract aggregates + Newton-Raphson invert). Fill rate is capped at ~2yr by the plan limit.

### IV column structure
- `IV_FEATURE_COLS = [atm_iv_30d, iv_skew_25d, term_structure]` — usable as ML features after backfill
- `IV_META_COLS = [atm_strike, atm_expiry, atm_dte, put_call_oi_ratio]` — always excluded from features
- `IV_COLS = IV_FEATURE_COLS + IV_META_COLS` — full list for CSV column management

### Backfill quality filters (post-S13/S14 hardening)
- `MIN_OPTION_VOLUME = 5` — rejects single-trade artifacts in `_fetch_agg_price`
- `MIN_OPTION_TRADES = 5` — rejects block-trade artifacts (n < 5)
- `0.05 ≤ iv ≤ 2.0` bounds in `get_historical_iv_snapshot` — rejects implausible inversions
- Monthly-expiry preference (3rd Friday) over weeklies — fixes weekly-heavy tickers (QQQ)
- Near-ATM delta filter `0.30 ≤ delta ≤ 0.70` for ATM IV — rejects deep-ITM time-premium artifacts
- Two-call corroboration required (≥ 2 ATM calls must invert before trusting)
- `FAST_FAIL_MISSES = 5` — early termination when consecutive aggregates calls return empty

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

- ⚠️ `modules/massive.py:16`: `MASSIVE_API_KEY` is HARDCODED (regression — was env-var-only by design).
  File is in git. Restore env-var pattern + rotate the key. The commented-out env-var line is
  preserved on line 15 as a one-line revert path.
- `modules/tradier.py`: `TRADIER_TOKEN` reads `$env:TRADIER_TOKEN` if set, else falls back to hardcoded
  constant. Set the env var to keep the token out of git.
- `direction.py` + `volatility.py`: still have inline `add_vix()` and `add_benchmarks()` wrappers
  (~30 LOC each, duplicated between the two files). S14/S16 refactor incomplete — pending follow-up.
- `direction.py`: dead `N_ESTIMATORS = 200` constant (Random Forest leftover)
- `indicators.py`: unused `import mdates`
- `diag/_diag_*.py`: 6 diagnostic files in workspace root, flagged for removal in S12, never deleted.
- `data/iv_log.csv` (deprecated as of S10): file preserved on disk as historical record but no new rows
  are written. IV history now lives in `data/{ticker}_indicators.csv`.
- AAPL backfill is partial (180 IV rows since 2025-07-24 — interrupted run, restartable).
- NVDA has only 2 IV rows (no backfill run yet) — blocks `--iv-features` validation on the
  best-validated individual stock.

## Important Warnings

- **NEVER name a script `signal.py`** — it shadows Python's built-in `signal` module and causes `AttributeError: partially initialized module 'subprocess'`. The original `entry_signal.py` was renamed to `entry.py` to resolve this.
- **`backtest.py` is self-contained** relative to `direction.py` / `volatility.py` (only imports from `modules/features.py`). If feature engineering changes outside `modules/features.py` (e.g. add_benchmarks loop bodies), `backtest.py` must be manually updated to match.
- **Today-row in `indicators.py`** (S16) — re-running `indicators.py` mid-day appends a today-row with NaN OHLCV so the IV harvest stamps onto today's date. This grows the df by 1, shifting train/test splits in downstream scripts. Today's HV/indicators come from yesterday's bar (the latest non-NaN row), today's IV is from a fresh Massive snapshot.
- **`data/` directory must exist** before running any script — create it manually if missing.
- **`modules/` directory** holds `features.py`, `benchmarks.py`, `massive.py`, `bs_invert.py`, `tradier.py`, and `catalysts.csv`. Catalyst CSV path is `data_dir`-relative; the `csv_path = os.path.join(data_dir, "catalysts.csv")` fix in Session 7 is required for catalyst loading to work.
- **`trade/` subdirectory** is the Python virtual environment — do not delete. Use `.\trade\Scripts\python.exe -X utf8` explicitly; Claude Code's shell doesn't inherit venv activation.
- **`memory/` subdirectory** is Claude's auto-memory system.
- **`$env:MASSIVE_API_KEY` does not persist across PowerShell sessions** — once env-var pattern is restored, add to `$PROFILE` for permanence.
- **yfinance `.info` returns 401 errors** — `TICKER_BENCHMARK` dict in `benchmarks.py` bypasses this entirely for known tickers.
- **ETFs have no earnings** — yfinance "may be delisted" warning is harmless; `Days_to_earnings` defaults to 45 (neutral).
- **`data/catalysts.csv`** must have no commas in description field (use dashes instead) — pandas reads ragged CSV otherwise.
- **Unicode arrow (`->`)**: not a problem in VS Code/Windows Terminal; only affects cmd.exe with cp1252 encoding.

## Tech Stack

`yfinance`, `pandas`, `numpy`, `ta`, `matplotlib`, `scikit-learn` (LogisticRegression, StandardScaler, precision_score, CalibratedClassifierCV, brier_score_loss), `lxml` (earnings dates), `requests` (Tradier API via `modules/tradier.py` + Massive API via `modules/massive.py`)

## Ticker Suitability Notes

- **QQQ**: framework reference baseline; 53 windows (2001–2026); clean hierarchy. Post-S15 STRONG ENTRY 1.9% / 63.3% win at 15d, +10.6% / 77.3% at 6mo.
- **AMD**: well-suited; 91 windows (2000–2026); STRONG ENTRY 3.9% / 57.0% win, AvgWin/AvgLoss 13.0% / -8.3% supports FULL sizing. **Only trade STRONG ENTRY** — CAUTION ≈ STAY OUT (Phase 3 HV proxy doesn't discriminate at AMD's vol scale), SHORT-TERM ONLY is a hard NO (-1.4% / 44.5% — 63d confirmation is load-bearing). AMD IV backfill complete; Phase 3 retrain with `--iv-features` not yet run.
- **NVDA**: well-suited in RAW mode; 53 windows; STRONG ENTRY 4.4% / 65.5% — best in project. ⚠️ CALIBRATED mode COLLAPSES this to -0.4% / 52% (S11 regression — drove the default-revert decision). Edge lives in the high-confidence probability tail.
- **SOFI**: marginal — short history (2021 IPO); rate features wired but need more rate-regime variation.
- **AAPL**: backfill partial (180 IV rows since 2025-07-24); backtest not yet run.
- **LYFT**: backfill complete (439 IV rows); backtest not yet run.
- **CRSP**: unsuitable for direction (binary FDA/trial events dominate); Phase 3 viable for vol plays — consider straddles/strangles around PDUFA dates rather than directional calls. Catalyst feature is automatically neutralized in direction models via `EVENT_DRIVEN_TICKERS = {"CRSP"}`.
- **SPY**: structurally UNSUITABLE — 0.1pp edge over base, hierarchy broken. Framework's price-action lens vs SPY's macro-driven moves don't match.

Cross-ticker findings:
- **STRONG ENTRY win rate ~65%** reproduces across QQQ/NVDA — use as suitability test. New ticker that can't hit ~60%+ STRONG win rate is probably unsuitable.
- **CAUTION avg loss 3–4pt worse than STRONG ENTRY** consistently across AMD/NVDA/SOFI — validates REDUCED sizing for IV-contraction signals.
- **Phase 2B (63d) edge stronger than Phase 2 (15d)** on AMD (+8.5pt) and CRSP (+22.5pt — longer horizon filters binary event noise).
- **Edge concentrates in high-confidence tail for individual stocks**; index ETFs distribute edge uniformly. Any regularization that compresses extremes (isotonic calibration, heavy L2) destroys individual-stock tail edge.
- **Cross-ticker validation required for any framework change**: QQQ alone is INSUFFICIENT. Always co-validate on QQQ + NVDA minimum before adopting as production default.