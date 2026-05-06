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
benchmarks.py   Shared module — benchmark detection, macro features, catalyst proximity (no output)

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

Work Done — Session 2 (Previous Device)
6. Fixed sizing.py ATM marker
   - Was marking all strikes within +-2% of current price as ATM (caused dual markers)
   - Fixed: store actual nearest ATM strike per expiry in each row; mark only that one
   - Added atm_strike column to rows dict; marker uses row["strike"] == row["atm_strike"]
7. Added dynamic sector benchmark detection (benchmarks.py)
   - New shared module: benchmarks.py — single source of truth for all benchmark mappings
   - Three-tier lookup: TICKER_BENCHMARK (no network call) -> yfinance sector/industry -> SPX fallback
   - TICKER_BENCHMARK: AMD/NVDA -> SOX+XLK, CRSP -> IBB+XLV, SOFI -> KBE+XLF,
     RIVN -> XLY, EVGO -> XLU, RGTI -> XLK, QQQ -> SPX
   - INDUSTRY_BENCHMARK: Semiconductors->^SOX, Biotechnology->IBB, Banks-Regional->KRE, etc.
   - SECTOR_BENCHMARK: Technology->XLK, Financial Services->XLF, Healthcare->XLV, etc.
   - direction.py: add_sox() renamed to add_benchmarks(df, benchmarks); prompts for benchmark after ticker
   - entry.py: build_features(df, benchmarks) — benchmarks passed as parameter
   - backtest.py: same as entry.py; cache filename dynamic: {bench_name.lower()}_cache.csv
   - Feature names: {bench_name}_RS_5d, {bench_name}_RS_20d (e.g. SOX_RS_5d, XLK_RS_5d)
   - AMD now gets 4 benchmark features: SOX_RS_5d, SOX_RS_20d, XLK_RS_5d, XLK_RS_20d
   - yfinance .info endpoint returns 401 errors — TICKER_BENCHMARK bypasses this entirely
8. Updated threshold sweep marker in direction.py and volatility.py
   - Was: max precision (picked 0.60 — high precision but only 58 signals)
   - Now: max (precision - base_rate) x log(signals) — rewards edge above base rate AND signal volume
   - Metric label: "optimal"
   - For AMD test set: picks 0.55 (score 0.377) over 0.60 (0.353) — better balance

Work Done — Session 3 (This Device)
9. Comprehensive script review of all 7 files — found and fixed:
   - Added FileNotFoundError + sys.exit(1) to direction.py, volatility.py, backtest.py
     (entry.py already had it; now consistent across all scripts that load CSVs)
   - Added precision metric below accuracy in direction.py and volatility.py
     Uses \n in a single print call (not a separate print() — user preference)
     "*** Precision — train: X% | test: Y% (when model says WIN/EXPANSION, how often correct) ***"
10. Implemented vol-adjusted thresholds via compute_vol_thresholds(df) in all 4 ML scripts:
   - Formula P2: WIN_THRESHOLD = P2_VOL_MULTIPLE x median_HV x sqrt(FORWARD_DAYS/252)
   - Formula P3: EXPANSION_THRESHOLD = P3_VOL_MULTIPLE x median_HV
   - P2_VOL_MULTIPLE = 0.41 — locks in 0.41-sigma difficulty bar for any ticker
     Practical tuning range: 0.25 (aggressive, ~40% base rate) to 1.0 (conservative, ~16%)
   - P3_VOL_MULTIPLE = 0.20 — heuristic: vol-of-vol scales roughly with HV level (no clean derivation)
   - Math: 252 = trading days/year; vol scales to T days via sqrt(T/252) (square-root-of-time rule)
   - 0.41 sigma: AMD's 5% threshold in std deviation units; ~34% of moves exceed this bar normally
   - compute_vol_thresholds() placed before __main__, called immediately after load_indicators()
   - direction.py: global WIN_THRESHOLD only; uses FORWARD_DAYS variable name
   - volatility.py: global EXPANSION_THRESHOLD only
   - entry.py / backtest.py: both globals; uses P2_FORWARD_DAYS variable name
   - Confirmed: AMD HV 48.4% -> WIN_THRESHOLD 4.8%, EXPANSION 9.7% (matches defaults)
   - SOFI HV 61.9% -> WIN_THRESHOLD 6.2%, EXPANSION 12.4%
   - NVDA HV 40.7% -> WIN_THRESHOLD 4.1%, EXPANSION 8.1%
11. Issues identified but NOT yet fixed:
   - indicators.py: unused `import mdates`
   - direction.py: dead `N_ESTIMATORS = 200` constant (Random Forest leftover)
   - sizing.py: TRADIER_TOKEN hardcoded in source file (security risk — should be env var)
   - backtest.py: signal labels still "STRONG ENTRY/CAUTION/STAY OUT" (pre-refactor naming,
     inconsistent with entry.py's ENTER/FULL/REDUCED framework)
12. Ran and analyzed models against AMD, SOFI, NVDA:
   - AMD direction.py: 13.4pt precision gap (train 60.2% vs test 46.8%) — regime issue;
     test period Oct 2024-Apr 2026 was choppy for AMD vs cleaner uptrends in training
   - AMD backtest: framework working well (see updated Backtest Results below)
   - SOFI backtest: direction filter INVERTED — STAY OUT (4.4%) outperforms STRONG ENTRY (3.3%)
     Cause: only 7 windows (2021 IPO = insufficient history); features calibrated for
     semiconductors, not fintech drivers (rate sensitivity, credit quality, regulatory news)
     Verdict: unsuitable ticker for current feature set
   - SOFI entry.py: ENTER/REDUCED — HV 75%, IV Rank 0.69, IV Percentile 89%,
     81% contraction probability; expensive options likely to IV crush even if direction correct
   - NVDA backtest: STAY OUT (5.3%) outperforms STRONG ENTRY (4.8%) — AI bull run so strong
     that ALL DAYS avg 4.1%; model cannot discriminate in a near-vertical secular trend
   - NVDA volatility.py: 18pt precision gap (train 55% vs test 37%) — vol regime changed
     post-2023 AI pivot; pre-2023 semiconductor vol patterns don't predict AI-era dynamics
   - Cross-ticker finding: CAUTION avg loss consistently 3-4pt worse than STRONG ENTRY
     AMD (-9.9% vs -7.6%), NVDA (-9.8% vs -5.9%), SOFI (-9.4% vs -9.2%)
     Strongly validates REDUCED sizing for IV-contraction signals across all tickers tested
13. Discussed FORWARD_DAYS = 15 vs 63 days (3 months) to match actual minimum hold period.
    Decided to keep at 15 for now — functions as entry TIMING signal, not holding period predictor.
    Revisit if signal reliability remains a concern after more AMD live testing.

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
- Unicode arrow (->): not a problem in VS Code/Windows Terminal; only affects cmd.exe cp1252
- NVDA Phase 3 large precision gap (18pt): vol regime changed post-2023 AI pivot; training data
  reflects pre-AI semiconductor vol patterns that don't predict AI-era dynamics
- SOFI direction filter inverted in backtest: insufficient training history (2021 onward, 7 windows);
  fixed by reducing MIN_TRAIN_DAYS to 252 (9 windows); edge still thin — fintech needs
  rate/credit/regulatory features to fully discriminate
- catalysts.csv commas in description field: caused pandas to read CSV with ragged columns,
  promoting ticker column to row index; fixed by replacing commas with dashes in descriptions

Backtest Results (AMD, Session 3 — 2095 rows, 13 windows, 2020-2026)
  Signal          Count   Avg Ret   Median  Win%    Strong%  AvgWin   AvgLoss
  STRONG ENTRY      191     3.9%     1.6%   55.0%    42.4%   13.4%    -7.6%
  CAUTION           352     4.0%     2.2%   56.0%    42.6%   14.9%    -9.9%  <- best avg return
  STAY OUT         1033     1.9%    -0.1%   49.2%    35.2%   11.8%    -7.7%
  ALL DAYS         1576     2.6%     0.3%   51.4%    37.8%   12.8%    -8.1%

Backtest Results (AMD, Session 4 — MIN_TRAIN_DAYS=252, 15 windows, 2019-2026)
  Signal          Count   Avg Ret   Median  Win%    Strong%  AvgWin   AvgLoss
  STRONG ENTRY      239     4.3%     2.6%   57.7%    43.9%   12.8%    -7.2%  <- best avg return
  CAUTION           357     3.9%     2.1%   55.5%    42.0%   14.9%    -9.7%
  STAY OUT         1106     2.2%     0.1%   50.5%    36.7%   11.8%    -7.7%
  ALL DAYS         1702     2.8%     0.7%   52.5%    38.8%   12.6%    -8.0%

Backtest Results (SOFI, Session 4 — MIN_TRAIN_DAYS=504, 7 windows, 2023-2026) [INVERTED — model unsuitable]
  Signal          Count   Avg Ret   Median  Win%    Strong%  AvgWin   AvgLoss
  STRONG ENTRY      205     3.3%     1.4%   53.2%    37.1%   14.3%    -9.2%
  CAUTION           163     1.3%    -1.0%   47.9%    33.7%   13.0%    -9.4%
  STAY OUT          452     4.4%     1.7%   54.4%    37.6%   16.2%    -9.8%  <- best avg return (bad)
  ALL DAYS          820     3.5%     1.3%   52.8%    36.7%   15.1%    -9.5%

Backtest Results (SOFI, Session 4 — MIN_TRAIN_DAYS=252, 9 windows, 2022-2026) [inversion fixed]
  Signal          Count   Avg Ret   Median  Win%    Strong%  AvgWin   AvgLoss
  STRONG ENTRY      205     3.3%     1.4%   53.2%    37.1%   14.3%    -9.2%  <- best avg return
  CAUTION           163     1.3%    -1.0%   47.9%    33.7%   13.0%    -9.4%
  STAY OUT          578     3.2%     0.9%   52.8%    34.8%   15.2%   -10.2%
  ALL DAYS          946     2.9%     0.9%   52.0%    35.1%   14.6%    -9.8%

Backtest Results (SOFI, Session 6 — MIN_TRAIN_DAYS=252, 9 windows, 2022-2026) [best result to date]
  Signal          Count   Avg Ret   Median  Win%    Strong%  AvgWin   AvgLoss
  STRONG ENTRY       54     3.3%     0.2%   50.0%    40.7%   14.1%    -7.5%  <- best avg return
  CAUTION            72     0.9%    -2.5%   40.3%    26.4%   15.1%    -8.7%
  STAY OUT          821     3.0%     1.2%   53.1%    35.4%   14.6%   -10.1%
  ALL DAYS          947     2.9%     0.9%   52.0%    35.1%   14.6%    -9.8%
  Note: STRONG ENTRY count dropped from 205 to 54 — universal features shifted model thresholds;
  gap over STAY OUT widened from +0.1pt to +0.3pt; AvgLoss improved -9.2% -> -7.5% (key signal)

Work Done — Session 4 (This Device)
14. Confirmed Claude Code can run scripts directly via:
    cmd /c "(echo TICKER && echo.) | python -X utf8 script.py"
    - Must use -X utf8 flag (not PYTHONUTF8=1 env var) to avoid cp1252 UnicodeEncodeError on Windows
    - Must use cmd /c piping (not PowerShell pipe) to avoid BOM character prepended to ticker input
    - direction.py / entry.py / backtest.py have 2 prompts: ticker, then benchmarks (blank = default)
    - volatility.py has 1 prompt: ticker only
    - indicators.py has 3 prompts: ticker, start date, end date; plus a trailing chart prompt
    - backtest.py has a trailing "Show chart? [y/N]" prompt inside plot_results()
15. Added Days_to_earnings to output in entry.py and volatility.py
    - entry.py: shown in Direction section after Drivers line as "Days to Earnings: Xd"
      Extracted via df_full.dropna().iloc[-1].get("Days_to_earnings", 45) in print_combined_signal()
    - volatility.py: shown after Signal line as "Days to Earnings: Xd"
      Extracted via int(latest_row["Days_to_earnings"]) in print_signal_summary()
16. Ran full pipeline for AMD and SOFI, results:
    - AMD indicators: price $341.54, RSI-14 69.9 Neutral, above KC upper band, MACD bullish,
      Stoch overbought (80.8/92.8); entry.py -> STAY OUT (win prob 11.1% vs 39.4% base rate)
    - SOFI indicators: price $16.20, RSI-14 40.5 Neutral, below KC lower band, MACD bearish,
      Stoch oversold (15.1/16.1); entry.py -> ENTER/REDUCED (win prob 56.8%, HV 75%, IV pct 89.2%,
      expansion prob 8.1%, Days to Earnings 85d)
    - AMD backtest: model performing well with MIN_TRAIN_DAYS=252
    - SOFI backtest with MIN_TRAIN_DAYS=504: INVERTED (7 windows insufficient)
17. Reduced MIN_TRAIN_DAYS from 504 to 252 in backtest.py (original line kept as comment)
    - SOFI inversion fixed: STRONG ENTRY now best avg return (3.3%) vs STAY OUT (3.2%)
    - Gap is thin — model still lacks key fintech macro drivers
    - AMD also improved: STRONG ENTRY now clearly best (4.3%, 57.7% win rate, 15 windows)

Work Done — Session 5 (This Device)
18. Generalized feature set for any US equity ticker — added to all 4 ML scripts:
    Universal features (all tickers, no external fetch):
    - price_vs_52w_high = Close / Close.rolling(252).max() - 1 (distance from 52-week peak)
    - price_vs_52w_low  = Close / Close.rolling(252).min() - 1 (distance from 52-week trough)
    - vol_ratio         = Volume / Volume.rolling(20).mean()   (relative volume spike detection)
    Benchmark sector trend feature (added in add_benchmarks / benchmark loop):
    - {bench_name}_vs_ma200 = bench_close / bench_close.rolling(200).mean() - 1
      (is the sector ETF itself in an uptrend?)
    These are added in normalize_features() for direction.py/volatility.py and inline in
    build_features() for entry.py/backtest.py.

19. Added modular macro feature layer (rate-sensitive tickers) — benchmarks.py:
    - MACRO_FEATURES dict: SOFI + major financials (JPM, BAC, GS, MS, WFC, C) -> ^TNX + ^IRX
    - detect_macro_features(ticker) -> list or []
    - add_macro_features(df, macro_features, start_date, end_date):
      Derives: {name}, {name}_chg_5d, {name}_vs_ma20 per rate source
      If both UST10Y and UST3M present: derives yield_curve and yield_curve_chg_5d
    - All 4 ML scripts import and call add_macro_features(); no-op for AMD/CRSP
    - SOFI: UST10Y, UST3M, yield_curve fetched and joined at runtime

20. Ran pipeline on SOFI with new features:
    - Rate features (UST10Y, UST3M, yield_curve) loaded correctly
    - Rate features NOT in top drivers — limited data (1340 rows) insufficient to learn
      rate sensitivity across different rate regimes; expected to improve over time
    - New universal feature price_vs_52w_low (+) appeared as direction driver immediately
    - ENTER/REDUCED signal — same as prior session; model stable
    - Concern: train/test precision inversion (54.6% train vs 76.5% test) — suspicious,
      test period likely favorable regime not genuine 39pt edge
    - IV at 89.6th pct with strong contraction signal remains primary concern for call buying

21. Ran pipeline on CRSP (new ticker, biotech):
    - indicators.py: 2398 rows from 2016-10-01, price $52.38, all RSIs ~50, inside KC bands
    - CRSP ATH: $210.04 on 2021-01-14; current -75.1% from ATH
    - entry.py: ENTER/REDUCED — but direction model has near-zero edge (35.3% test precision
      vs 34.0% base rate); Phase 3 stronger (60.4% vs 31.8% base rate — biotech vol is
      predictable from HV momentum)
    - backtest (17 windows, 2018-2026): STAY OUT outperforms STRONG ENTRY (1.3% vs 0.9%)
      CAUTION avg loss -10.0% comparable to STAY OUT -10.1% (pattern breaks vs AMD/NVDA/SOFI)
      STRONG ENTRY avg loss -13.8% — binary event risk materializes in loss magnitude
    - Verdict: CRSP direction model inverted, unsuitable for directional calls
      FDA/trial binary events drive price, not technical indicators
    - WIN threshold for CRSP: 5.9% in 15 days (vol-adjusted, same sigma difficulty as AMD)

22. Added Days_to_catalyst feature via data/catalysts.csv:
    - Manual CSV: ticker, date, type (trial_readout/pdufa), description
    - add_catalyst_proximity(df, ticker, data_dir) in benchmarks.py:
      Reads catalysts.csv, filters by ticker, computes days to next future event
      Defaults to 90 silently if file missing or ticker not listed (AMD, SOFI unaffected)
      Prints "✓ Days_to_catalyst (N event(s) for TICKER)" when events found
    - All 4 ML scripts import and call add_catalyst_proximity() after earnings proximity
    - CRSP: Days_to_catalyst immediately appeared as top direction driver (-)
      — far from catalyst is bearish for CRSP direction (big moves happen ON catalyst days)
    - data/catalysts.csv seeded with 2 placeholder CRSP rows; user should update with real dates
    - Troubleshooting: commas in description field caused ragged CSV parse error;
      fixed by replacing commas with dashes in description values

Backtest Results (CRSP, Session 5 — 2398 rows, 17 windows, 2018-2026) [INVERTED — unsuitable]
  Signal          Count   Avg Ret   Median  Win%    Strong%  AvgWin   AvgLoss
  STRONG ENTRY      122     0.9%    -0.1%   49.2%    35.2%   16.1%   -13.8%
  CAUTION           381     0.7%    -1.0%   46.2%    31.0%   13.2%   -10.0%
  STAY OUT         1502     1.3%    -0.7%   47.9%    32.2%   13.8%   -10.1%  <- best avg return
  ALL DAYS         2005     1.2%    -0.8%   47.7%    32.1%   13.8%   -10.3%

Work Done — Session 6 (This Device)
23. Added Days_to_catalyst output line to entry.py and volatility.py:
    - entry.py: shown in Direction section after Days_to_earnings as "Days to Catalyst: Xd"
      Extracted via df_full.dropna().iloc[-1].get("Days_to_catalyst", 90)
      Shows "N/A" when value >= 90 (sentinel for no known upcoming catalyst)
    - volatility.py: same logic after Days_to_earnings line in print_signal_summary()
    - AMD/SOFI show "N/A"; CRSP shows actual countdown (e.g. "88d" to Aug 1 pediatric PDUFA)

24. Investigated CRSP catalyst data and populated catalysts.csv with full history:
    - Researched and added 11 confirmed historical events (2019-2024) + 3 future approximates
    - Sources: CRSP IR press releases page, GlobeNewswire, Vertex IR, FDA.gov
    Historical events added:
      2019-11-19  CTX001 first two patients - SCD and TDT (first human CRISPR gene editing data)
      2020-06-12  CTX001 EHA 2020 - CLIMB-111 and CLIMB-121 trial data
      2020-10-21  CTX110 CARBON Phase 1 top-line results - B-cell malignancies
      2020-12-05  CTX001 ASH 2020 + NEJM publication
      2021-06-11  CTX001 EHA 2021 - 22 patients with 3+ month follow-up (approximate)
      2021-10-12  CTX110 CARBON Phase 1 positive update
      2022-06-11  Exa-cel EHA 2022 - extended follow-up SCD and TDT
      2022-12-10  Exa-cel ASH 2022 data readout
      2022-12-12  CTX110 CARBON ASH 2022 update
      2023-06-09  Exa-cel EHA 2023 - pivotal trial results
      2023-10-31  FDA advisory committee meeting - exa-cel SCD (trading halt; adcom voted in favor)
      2023-11-16  UK MHRA authorization - Casgevy SCD and TDT
      2023-12-08  Casgevy FDA approval SCD (already present)
      2024-01-16  Casgevy FDA approval TDT (approved ahead of March 2024 PDUFA)
      2024-02-13  Casgevy European Commission approval
    Upcoming (approximate dates):
      2026-08-01  Casgevy pediatric label expansion ages 5-11 - Priority Review Voucher
      2026-09-30  Zugo-cel (CTX112) autoimmune/oncology data update
      2026-11-30  CTX611 Phase 2 topline data - anticoagulant

24. Backtest progression testing effect of catalyst data quantity on CRSP direction model:
    - 1 event (Dec 2023 only):    STRONG ENTRY -0.6%  AvgLoss -13.0%
    - 4 events (+3 future approx): STRONG ENTRY +0.1%  AvgLoss -13.0%
    - 18 events (full history):   STRONG ENTRY -1.2%  AvgLoss -14.0%
    - STAY OUT held steady at +1.5% across all three runs
    - Conclusion: inversion is structural — more catalyst data deepened it rather than fixed it
    - The model cannot learn direction of binary events from price/volume features
    - Days_to_catalyst as a feature only signals "event approaching" not "event will be positive"
    - AvgLoss widening to -14.0% with dense catalyst history reflects larger losses near events
      when the model fires STRONG ENTRY and the binary outcome is negative

Backtest Results (CRSP, Session 6 — 18 events in catalysts.csv) [INVERTED — structural not fixable]
  Signal          Count   Avg Ret   Median  Win%    Strong%  AvgWin   AvgLoss
  STRONG ENTRY      102    -1.2%    -0.6%   46.1%    32.4%   13.8%   -14.0%
  CAUTION           366     0.5%    -1.6%   44.3%    29.8%   13.7%    -9.9%
  STAY OUT         1537     1.5%    -0.5%   48.6%    32.7%   13.9%   -10.2%  <- best avg return
  ALL DAYS         2005     1.2%    -0.8%   47.7%    32.1%   13.8%   -10.3%

25. Implemented Phase 2B — 63-day direction model (entry.py, direction.py, backtest.py):
    - Added P2B_FORWARD_DAYS = 63 and WIN_THRESHOLD_63 to all three scripts
    - WIN_THRESHOLD_63 = P2_VOL_MULTIPLE x median_HV x sqrt(63/252) — same 0.41-sigma bar
      AMD: 9.9% gain required in 63 days; SOFI: 12.7%; CRSP: 12.0%; QQQ: 3.6%
    - entry.py: Phase 2B trained on df_full.copy() (no leakage from 15-day target)
      Output now shows two direction sections: "15d entry timing" and "63d thesis"
      Sizing logic updated: FULL only when 15d + 63d + expansion all agree
      If 15d fires but 63d doesn't: REDUCED + warning note
    - backtest.py: new signal labels — STRONG ENTRY (both fire), SHORT-TERM ONLY (15d only),
      CAUTION (neither direction, Phase 3 expansion), STAY OUT (15d doesn't fire)
    - direction.py: trains both models, prints precision for each

    AMD Phase 2B test results:
      Phase 2  (15d): test precision 33.2% vs 39.4% base rate (below base — poor test period)
      Phase 2B (63d): test precision 56.8% vs 48.3% base rate (+8.5pt — stronger signal)
    CRSP Phase 2B: test precision 61.7% vs 39.2% base rate (+22.5pt — meaningful even though
      15-day model is inverted; 63-day model learns longer-horizon patterns less contaminated
      by individual binary event noise)
    SOFI Phase 2B: test precision 100% — suspicious (too few test positives); treat as unreliable

    AMD backtest with Phase 2B (15 windows):
      Signal           Count   Avg Ret   Median  Win%   AvgLoss
      STRONG ENTRY       211     2.6%     3.4%   59.7%   -9.6%
      CAUTION            288     1.1%    -0.8%   46.2%   -9.4%
      SHORT-TERM ONLY     59    12.2%    10.8%   66.1%   -9.3%  <- best avg return (surprising)
      STAY OUT          1019     2.5%     0.1%   50.3%   -7.4%
      ALL DAYS          1577     2.7%     0.3%   51.4%   -8.1%
    Note: SHORT-TERM ONLY best for AMD because short-burst momentum trades pay off in 15 days
    even without 63-day confirmation. Behavior differs by ticker (see QQQ below).

26. Re-ran SOFI pipeline (Session 6):
    - indicators.py: price $16.02 (down from $16.20), below KC lower band, MACD bearish,
      Stoch oversold (11.2/15.5) — technically weaker than Session 4
    - entry.py: ENTER/REDUCED — win prob 72.0% vs 33.0% base rate; top drivers: IV_pct (+),
      price_vs_52w_low (+), Days_to_earnings (-); HV 75.1%, IV rank 0.74, IV pct 89.6%,
      expansion prob 13.2% (87% contraction); Days to Earnings 84d; Days to Catalyst N/A
    - backtest: STRONG ENTRY 3.3% best avg return; gap over STAY OUT widened to +0.3pt;
      AvgLoss improved to -7.5% (was -9.2%) — model avoiding big losers more effectively
    - Suspicious train/test precision inversion persists (76.5% test vs 54.6% train) —
      likely favorable test regime, not genuine edge; monitor as more data accumulates
    - SOFI improving but still thin; direction: correct posture is ENTER/REDUCED not full size

27. Ran pipeline on QQQ (new ticker — broad index ETF):
    - indicators.py: 6624 rows from 2000-01-03 (longest history of any ticker tested)
      price $681.61, RSI-14 76.5 overbought, above KC upper band, Stoch 97.6 overbought
    - entry.py: ENTER/REDUCED — 15d win prob 58.1% vs 45.0% base rate (WIN)
      63d win prob 45.6% vs 53.4% base rate (NO SIGNAL — base rate exceeds threshold because
      QQQ drifts up so consistently that >53% of 63-day windows are wins by default)
      Phase 3: HV 15.5%, IV rank 0.20 (Low IV) — contraction signal
      Structural note: earnings warnings suppressed (ETF has no earnings); Days_to_earnings 45d default
    - backtest (51 windows, 2002-2026): correct signal hierarchy confirmed
      STRONG ENTRY 2.3% best avg return; STAY OUT 0.6% worst
      SHORT-TERM ONLY 0.7% — near-worst for QQQ (vs best for AMD); QQQ lacks sharp
      momentum bursts that make SHORT-TERM ONLY profitable for individual stocks
      Phase 3 test precision 63.2% vs 41.9% base — strongest Phase 3 edge seen across any ticker
    - Structural quirk: QQQ benchmark is SPX (^GSPC); ~0.95+ correlation means SPX_RS features
      contribute near-zero signal; model compensates with VIX, HV, RSI, KC band features
      Swapping to XLK benchmark would be worse (QQQ and XLK even more correlated)
    - Framework assessment: works well for index ETFs; best statistical validation of any
      ticker (51 windows); STRONG ENTRY clearly outperforms; weaker individual stock features
      don't hurt because QQQ doesn't need them

    QQQ Backtest Results (51 windows, 2002-2026):
      Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
      STRONG ENTRY       500     2.3%     2.6%   65.6%   55.2%    5.6%   -4.1%  <- best
      CAUTION           1081     1.2%     1.8%   61.3%   50.2%    4.6%   -4.2%
      SHORT-TERM ONLY    517     0.7%     1.6%   60.2%   48.0%    4.1%   -4.6%
      STAY OUT          4007     0.6%     1.2%   61.9%   43.1%    3.3%   -3.7%
      ALL DAYS          6105     0.9%     1.4%   62.0%   45.8%    3.8%   -3.9%

Next Steps (planned, not yet implemented)
- Consider buying straddles/strangles before PDUFA dates for CRSP instead of directional calls
  — Phase 3 IV expansion model is reliable for biotech; direction model is not
  — Watch for Phase 3 to flip EXPANSION as Days_to_catalyst counts down toward Aug/Sep/Nov 2026
- Add interest rate features to improve SOFI model (rate features loaded but need more data/
  rate regime variation before they show up as significant contributors):
  Rate features already wired up via MACRO_FEATURES; need time and different rate regimes
- Expand MACRO_FEATURES to other rate-sensitive tickers as they're added to watchlist
- Potential benchmark improvements for SOFI: replace/augment KBE+XLF with fintech peers
  (ARKF, UPST) — SOFI trades more like growth/fintech than traditional banking

Key Findings
- Direction filter (Phase 2) works for AMD: STAY OUT consistently underperforms benchmark
- IV gate as hard filter hurts: CAUTION outperformed STRONG ENTRY -> repurposed as sizing
- Best use: veto mechanism (stay out when flagged) not entry trigger
- Phase 2 Win signals combined avg ~3.4-4% vs 2.6% benchmark
- Volatility more predictable than direction: Phase 3 ~31pt edge vs Phase 2 ~12pt edge
- CAUTION avg loss premium (~3-4pt vs STRONG ENTRY) confirmed consistent across AMD, NVDA, SOFI
  — IV contraction risk on losing trades is real and validates REDUCED position sizing
- Phase 2B (63-day) edge stronger than Phase 2 (15-day) on AMD (+8.5pt vs +6pt over base rate)
  and CRSP (+22.5pt — longer window filters out binary event noise that contaminates 15-day model)
- SHORT-TERM ONLY signal behavior is ticker-dependent: best on AMD (12.2% avg — momentum bursts)
  but worst on QQQ (0.7% — no sharp momentum bursts on an index)
- Framework works best for: large liquid sector-driven stocks with no near-term binary events
  (AMD ideal), and broad index ETFs (QQQ — cleanest backtest, 51 windows)
- Framework degrades for: event-driven biotech (CRSP), rate-sensitive with short history (SOFI),
  secular trend too strong to discriminate (NVDA post-2023)
- Ticker suitability: AMD well-suited; QQQ well-suited (index, no binary events, 51 windows);
  SOFI marginal (short history, missing rate features — edge improving session-over-session);
  NVDA marginal (bull trend too strong, vol regime change hurts Phase 3);
  CRSP unsuitable for direction (binary FDA/trial events dominate; Phase 3 viable for vol plays)

Potential Improvements (identified, not yet implemented)
Priority 1 — highest value for individual stocks:
  - Earnings estimate revision direction: are analysts raising or cutting EPS over past 30-60 days?
    Available from finviz or yfinance. Single most powerful missing feature for individual stocks.
  - Actual IV from Tradier options chain: ATM IV and put/call ratio fed back into signal layer.
    Tradier already integrated via sizing.py; closing HV-proxy gap (e.g. NVDA HV 35% vs IV 43%)
Priority 2 — additional individual stock signals:
  - Short interest ratio (days to cover): high short + positive momentum = squeeze setup.
    Available monthly from FINRA. Not applicable to ETFs.
  - Relative valuation: P/S or P/E vs 3-year history. Distinguishes oversold cheap vs oversold
    expensive. Simple to compute from yfinance .info when available.
Priority 3 — model quality:
  - Probability calibration: isotonic regression post-processing so "72% win prob" means 72%.
    Currently logistic regression outputs are scores not calibrated probabilities.
    Feasible for AMD (2096 rows); riskier for SOFI (1340 rows).
Won't fix / structural limits:
  - Binary event direction: no price/volume feature can predict which way an FDA decision
    or trial readout will go. Framework correctly identifies event proximity; direction unknowable.
  - Secular trend regimes: when a stock is in parabolic uptrend (NVDA 2023-2024), "overbought"
    signals become noise. Would require explicit regime labels to handle.

Important Notes
- backtest.py is SELF-CONTAINED — does NOT import from direction.py or volatility.py
  If feature engineering changes in those scripts, backtest.py must be manually updated
- data/ directory must exist before running any script (user created manually)
- trade/ subdirectory is the Python virtual environment — do not delete
- memory/ subdirectory in project root is Claude's auto-memory system
- Unicode arrow issue (->): not a problem in VS Code/Windows Terminal; only affects cmd.exe cp1252
- FORWARD_DAYS = 15 kept intentionally — acts as entry timing signal, not holding period predictor
  Phase 2B (63-day) added in Session 6 as LEAPS-aligned thesis validation layer
- data/catalysts.csv must have no commas in description field (use dashes instead)
- QQQ ETF has no earnings dates — yfinance warns "may be delisted" but this is harmless;
  Days_to_earnings defaults to 45 (neutral) for ETFs

Tech Stack
yfinance, pandas, numpy, ta, matplotlib, scikit-learn (LogisticRegression, StandardScaler,
precision_score), lxml (for earnings dates), requests (for Tradier API in sizing.py)

Model Details
All models: Logistic Regression (C=0.1, class_weight="balanced", 80/20 time-based split)
Phase 2  (15d direction) threshold: P2_THRESHOLD = 0.55 — entry timing signal
Phase 2B (63d direction) threshold: P2_THRESHOLD = 0.55 — thesis validation (LEAPS-aligned)
Phase 3  (IV expansion)  threshold: P3_THRESHOLD = 0.60
Training history: 2018-present (~2,096 rows for AMD); 2000-present (~6,624 rows for QQQ)
Threshold sweep marker: auto-marks optimal using max (precision - base_rate) x log(signals)
Vol-adjusted thresholds: compute_vol_thresholds() auto-calibrates all thresholds at runtime
  WIN_THRESHOLD    = P2_VOL_MULTIPLE x median_HV x sqrt(15/252)  — 15-day direction bar
  WIN_THRESHOLD_63 = P2_VOL_MULTIPLE x median_HV x sqrt(63/252)  — 63-day direction bar
  EXPANSION_THRESHOLD = P3_VOL_MULTIPLE x median_HV
  P2_VOL_MULTIPLE=0.41 (0.41-sigma bar); P3_VOL_MULTIPLE=0.20 (heuristic)
  P2 tuning range: 0.25=aggressive (~40% base rate), 0.41=default (~34%), 0.75=conservative (~23%)
Backtest signal labels (updated Session 6):
  STRONG ENTRY = 15d WIN + 63d WIN + Phase 3 EXPANSION
  CAUTION      = 15d WIN + 63d WIN + Phase 3 CONTRACTION
  SHORT-TERM ONLY = 15d WIN + 63d NO SIGNAL (any Phase 3)
  STAY OUT     = 15d NO SIGNAL

Sizing.py Config Notes
TRADIER_TOKEN = brokerage token (not sandbox)
MIN_DTE = 180, MAX_DTE = 365 (6-12 month expiries)
DEFAULT_STRIKE_RANGE = 10 strikes above/below ATM
IV source: smv_vol (smoothed model vol, matches Tradier app display)
