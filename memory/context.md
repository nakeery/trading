Session Context Summary

Project Overview
AMD Options Swing Trading ML Pipeline — a 6-script system that supplements a Webull chart-based strategy for AMD 6-12 month call options with ML-derived entry signals and options position sizing.

Pipeline Architecture
Scripts run sequentially. indicators.py must run first to generate the CSV that all downstream scripts depend on.

Script          Purpose                                              Output
indicators.py   Fetch OHLCV, compute 30+ indicators                 data/{ticker}_indicators.csv, data/{ticker}_dashboard.png
direction.py    Direction ML model (>=5% gain in 15d?)              data/{ticker}_ml_features.csv, data/{ticker}_ml_results.png
volatility.py   IV expansion ML model (HV >=10% higher in 10d?)    data/{ticker}_phase3_features.csv, data/{ticker}_phase3_results.png
entry.py        Combines both models -> single recommendation        Console output only
backtest.py     Walk-forward backtest of combined signal             data/{ticker}_backtest.png, data/{ticker}_backtest_results.csv
sizing.py       Live options chain sizing via Tradier API            Console output only
benchmarks.py   Shared module — benchmark detection (no output)     Imported by direction.py, entry.py, backtest.py

Primary daily-use script: entry.py
Run after ENTER signal: sizing.py

Workflow
1. indicators.py  — refresh data daily
2. entry.py      — get entry decision and sizing recommendation (ENTER/STAY OUT, FULL/REDUCED)
3. sizing.py      — when signal says ENTER, get contract sizing from live Tradier options chain
4. direction.py   — as needed for deeper direction model analysis
5. volatility.py  — as needed for deeper IV analysis
6. backtest.py    — periodically to verify model performance

Script Renames (from original entry_phase*.py naming)
- entry_phase1.py  -> indicators.py
- entry_phase2.py  -> direction.py
- entry_phase3.py  -> volatility.py
- entry_signal.py  -> entry.py (NOTE: caused circular import — "signal" shadows Python stdlib module)
- entry_backtest.py -> backtest.py
- NEW: sizing.py (Phase 4)
IMPORTANT: Do NOT name any script "signal.py" — it shadows Python's built-in signal module and causes
AttributeError: partially initialized module 'subprocess'. User renamed to something else to resolve.

Decision Framework (updated after backtest findings)
- Phase 2 fires (direction) = ENTER decision
- Phase 3 (IV expansion) = position SIZING, not go/no-go gate
  - Phase 3 expansion -> FULL size
  - Phase 3 contraction -> REDUCED size
- STAY OUT (Phase 2 doesn't fire) -> no entry regardless of Phase 3

Work Done — Original Device
1. Analyzed entry.py and identified 5 issues, implemented fixes:
   - Staleness warning in load_indicators()
   - Precision over accuracy in train()
   - Feature attribution via get_top_contributors()
   - Base rate context alongside probabilities
   - CAUTION case now shows contraction probability
2. Added data/ directory routing across all scripts
   - User manually created data/ directory in project root
   - All file I/O updated to use os.path.join(DATA_DIR, ...)

Work Done — Current Device (Session 2)
6. Fixed sizing.py ATM marker
   - Was marking all strikes within ±2% of current price as ATM (caused dual markers)
   - Fixed: store actual nearest ATM strike per expiry in each row; mark only that one
   - Added atm_strike column to rows dict; marker uses row["strike"] == row["atm_strike"]
7. Added dynamic sector benchmark detection (benchmarks.py)
   - New shared module: benchmarks.py — single source of truth for all benchmark mappings
   - Three-tier lookup: TICKER_BENCHMARK (no network call) → yfinance sector/industry → SPX fallback
   - TICKER_BENCHMARK: AMD/NVDA → SOX+XLK, CRSP → IBB+XLV, SOFI → KBE+XLF,
     RIVN → XLY, EVGO → XLU, RGTI → XLK, QQQ → SPX
   - INDUSTRY_BENCHMARK: Semiconductors→^SOX, Biotechnology→IBB, Banks-Regional→KRE, etc.
   - SECTOR_BENCHMARK: Technology→XLK, Financial Services→XLF, Healthcare→XLV, etc.
   - direction.py: add_sox() renamed to add_benchmarks(df, benchmarks); prompts for benchmark after ticker
   - entry.py: build_features(df, benchmarks) — benchmarks passed as parameter
   - backtest.py: same as entry.py; cache filename dynamic: {bench_name.lower()}_cache.csv
   - Feature names: {bench_name}_RS_5d, {bench_name}_RS_20d (e.g. SOX_RS_5d, XLK_RS_5d)
   - AMD now gets 4 benchmark features: SOX_RS_5d, SOX_RS_20d, XLK_RS_5d, XLK_RS_20d
   - yfinance .info endpoint returns 401 errors — TICKER_BENCHMARK bypasses this entirely
8. Updated threshold sweep marker in direction.py and volatility.py
   - Was: max precision (picked 0.60 — high precision but only 58 signals)
   - Now: max (precision - base_rate) × log(signals) — rewards edge above base rate AND signal volume
   - Metric label: "optimal"
   - For AMD test set: picks 0.55 (score 0.377) over 0.60 (0.353) — better balance

Work Done — Previous Device
3. Built backtest.py — walk-forward backtest (13 windows, 2020-2026)
   - Expanding window: trains from 2018 to cutoff, tests next 6 months
   - Caches VIX/SOX downloads (data/vix_cache.csv, data/sox_cache.csv)
   - Cache invalidates automatically when indicators CSV is newer
   - Dynamic marker on best avg return row
4. Refactored entry.py recommendation framework based on backtest findings
   - Replaced STRONG ENTRY/CAUTION with ENTER + FULL/REDUCED sizing model
   - Phase 3 repurposed from hard gate to position sizing input
5. Built sizing.py (Phase 4) — live options chain via Tradier
   - Requires Tradier brokerage account and API token (TRADIER_TOKEN in config)
   - Tradier brokerage token required — sandbox token uses simulated data
   - Inputs: ticker, budget ($), strikes above/below ATM (default 10)
   - Strike selection anchored to nearest real ATM strike, not exact stock price
   - Uses smv_vol (smoothed model vol) for IV to match Tradier app display
   - Shows all strikes including "over budget" ones (not silently filtered)
   - ATM strike marked with "<-- ATM" in output
   - Loss scenario table: 10%, 15%, 20%, 100% of budget
   - Greeks (delta, theta) come directly from Tradier — no Black-Scholes needed

Troubleshooting History
- yfinance options chain returns empty tuple for AMD: resolved by switching to Tradier
  - pip install curl_cffi helped but didn't fully fix it
  - requests.Session() workaround rejected by newer yfinance ("requires curl_cffi session")
  - Final solution: Tradier API entirely replaces yfinance for options data
- lxml not installed: earnings dates fell back to 45-day neutral value; fixed with pip install lxml
- UserWarning "X does not have valid feature names": fixed by wrapping latest row in pd.DataFrame before scaler.transform()
- UserWarning "X has feature names but StandardScaler fitted without feature names": fixed in backtest.py by fitting scaler on DataFrame not .values
- Deep ITM strikes missing from sizing output: caused by contracts=0 filter silently dropping unaffordable rows; fixed by keeping all rows and showing "over budget" instead
- Strike range was dollar-based; changed to count-based (N strikes above/below ATM) for consistency across price levels
- IV values didn't match Tradier app: fixed by switching from mid_iv to smv_vol in greeks response
- sizing.py dual ATM markers: both $350 and $360 marked as ATM when price fell between them; fixed by storing actual nearest ATM strike in each row and marking only that one
- yfinance .info 401 errors: Yahoo Finance restricts quoteSummary endpoint; fixed by adding TICKER_BENCHMARK dict as primary lookup in benchmarks.py (no network call required)
- Benchmark was hardcoded to ^SOX (AMD-specific); generalized via benchmarks.py with per-ticker, industry, and sector dicts

Backtest Results (AMD, 2020-2026, 13 walk-forward windows)
  Signal          Count   Avg Ret   Strong Win%
  STRONG ENTRY      173     2.9%       39.9%
  CAUTION           303     3.7%       38.6%   <- best avg return
  STAY OUT         1100     2.3%       36.5%
  ALL DAYS         1576     2.6%       37.3%

Key Findings
- Direction filter (Phase 2) works: STAY OUT consistently underperforms benchmark
- IV gate as hard filter hurts: CAUTION outperformed STRONG ENTRY
- Best use: veto mechanism (stay out when flagged) not entry trigger
- Phase 2 Win signals combined avg ~3.4% vs 2.6% benchmark
- Volatility more predictable than direction: Phase 3 ~31pt edge vs Phase 2 ~12pt edge

Important Notes
- backtest.py is SELF-CONTAINED — does NOT import from direction.py or volatility.py
  If feature engineering changes in those scripts, backtest.py must be manually updated
- data/ directory must exist before running any script (user created manually)
- trade/ subdirectory is the Python virtual environment — do not delete
- memory/ subdirectory in project root is Claude's auto-memory system
- Unicode arrow issue (→): not a problem in VS Code/Windows Terminal; only affects cmd.exe cp1252

Tech Stack
yfinance, pandas, numpy, ta, matplotlib, scikit-learn (LogisticRegression, StandardScaler,
precision_score), lxml (for earnings dates), requests (for Tradier API in sizing.py)

Model Details
Both models: Logistic Regression (C=0.1, class_weight="balanced", 80/20 time-based split)
Direction threshold: P2_THRESHOLD = 0.55 (~50.4% precision vs 37.8% base rate)
IV expansion threshold: P3_THRESHOLD = 0.60 (~59% precision vs 27.8% base rate)
Training history: 2018-present (~1,600 rows)
Threshold sweep marker: auto-marks best precision threshold (not hardcoded)

Sizing.py Config Notes
TRADIER_TOKEN = brokerage token (not sandbox)
MIN_DTE = 180, MAX_DTE = 365 (6-12 month expiries)
DEFAULT_STRIKE_RANGE = 10 strikes above/below ATM
IV source: smv_vol (smoothed model vol, matches Tradier app display)
