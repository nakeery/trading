Session Context Summary

Project Overview
Multi-Ticker Options Swing Trading ML Pipeline — 7-script system that supplements a Webull
chart-based strategy for 6-12 month call options with ML-derived entry signals and live
options sizing. Originally AMD-specific; now generalized for any liquid US equity or index ETF.

Pipeline Architecture
Scripts run sequentially. indicators.py must run first to generate the CSV that all
downstream scripts depend on.

Script          Purpose                                              Output
indicators.py   Fetch OHLCV, compute 30+ indicators                 data/{ticker}_indicators.csv, data/{ticker}_dashboard.png
direction.py    Direction ML model (Phase 2 + 2B)                   data/{ticker}_ml_features.csv, data/{ticker}_ml_results.png
volatility.py   IV expansion ML model (Phase 3)                    data/{ticker}_phase3_features.csv, data/{ticker}_phase3_results.png
entry.py        Combines models -> single SIGNAL recommendation      Console output only
backtest.py     Walk-forward backtest of combined signal             data/{ticker}_backtest.png, data/{ticker}_backtest_results.csv
sizing.py       Live options chain sizing via Tradier API            Console output only
modules/benchmarks.py  Shared module — benchmarks, macro features, catalyst proximity (no output)

Primary daily-use script: entry.py
Run after entry signal is actionable: sizing.py

Workflow
1. indicators.py  — refresh data daily
2. entry.py       — get SIGNAL + POSITION SIZING
3. sizing.py      — when signal is actionable, get contract sizing from live Tradier options chain
4. direction.py   — as needed for deeper direction model analysis
5. volatility.py  — as needed for deeper IV analysis
6. backtest.py    — periodically to verify model performance

Decision Framework
- Phase 2 (15d direction) fires = entry timing signal
- Phase 2B (63d direction) confirms or rejects medium-term thesis
- Phase 3 (IV expansion) = position SIZING input, not go/no-go gate

Backtest Signal Labels (used in both entry.py and backtest.py)
  STRONG ENTRY    = 15d WIN + 63d WIN + Phase 3 EXPANSION
  CAUTION         = 15d WIN + 63d WIN + Phase 3 CONTRACTION
  SHORT-TERM ONLY = 15d WIN + 63d NO SIGNAL (any Phase 3)
  STAY OUT        = 15d NO SIGNAL

Position Sizing
  STRONG ENTRY    -> FULL
  CAUTION         -> REDUCED
  SHORT-TERM ONLY -> REDUCED
  STAY OUT        -> N/A

IMPORTANT: Do NOT name any script "signal.py" — it shadows Python's built-in signal module
and causes AttributeError: partially initialized module 'subprocess'.

Sessions 1-6 — Summary

Session 1-2 (Original/Previous Devices)
- Initial pipeline build; 5-issue review of entry.py with fixes
- data/ directory routing across all scripts
- Built backtest.py walk-forward framework (cached VIX/SOX downloads)
- Built sizing.py via Tradier API; replaced yfinance options (was returning empty tuples)
- Refactored from STRONG ENTRY/CAUTION binary to ENTER + FULL/REDUCED sizing
- Dynamic sector benchmark detection: TICKER_BENCHMARK dict bypasses 401-prone yfinance .info
- Threshold sweep marker: max(precision - base_rate) × log(signals) — rewards edge AND volume

Session 3 — 7-script Review
- Added FileNotFoundError + sys.exit(1) consistency across CSV-loading scripts
- Implemented vol-adjusted thresholds via compute_vol_thresholds(df) in all 4 ML scripts
  - WIN_THRESHOLD = P2_VOL_MULTIPLE × median_HV × sqrt(FORWARD_DAYS/252)
  - EXPANSION_THRESHOLD = P3_VOL_MULTIPLE × median_HV
  - P2_VOL_MULTIPLE = 0.41 (0.41-sigma bar; range 0.25 aggressive to 1.0 conservative)
  - P3_VOL_MULTIPLE = 0.20 (heuristic — vol-of-vol scales with HV level)
- Cross-ticker validated: AMD HV 48.4% -> WIN 4.8%, EXPANSION 9.7%; SOFI HV 61.9% -> 6.2%/12.4%

Session 4 — Operational Fixes
- Confirmed Claude Code piped run pattern: cmd /c "(echo TICKER && echo.) | python -X utf8 script.py"
  - -X utf8 required (avoids cp1252 UnicodeEncodeError); cmd /c required (PowerShell prepends BOM)
- Added Days_to_earnings output to entry.py and volatility.py
- Reduced MIN_TRAIN_DAYS from 504 to 252 in backtest.py — unlocked SOFI
  (7 windows insufficient -> 9-15 windows acceptable)
- Confirmed: AMD STRONG ENTRY 4.3% (15 windows); SOFI STRONG ENTRY 3.3% (9 windows, thin edge)

Session 5 — Ticker Generalization
- Universal features in all ML scripts: price_vs_52w_high, price_vs_52w_low, vol_ratio
- Per-benchmark sector trend: {bench_name}_vs_ma200
- Macro feature layer (rate-sensitive tickers): SOFI/JPM/BAC/GS/MS/WFC/C -> ^TNX + ^IRX
  - Derives: {name}, {name}_chg_5d, {name}_vs_ma20, yield_curve, yield_curve_chg_5d
- Catalyst proximity feature: data/catalysts.csv -> Days_to_catalyst (defaults 90 sentinel)
- Added CRSP — biotech, IBB+XLV benchmark
- Verdict: CRSP direction model inverted (binary FDA/trial events); Phase 3 viable for vol plays

Session 6 — Phase 2B + QQQ Validation
- Phase 2B (63-day direction model) added to entry.py, direction.py, backtest.py
  - WIN_THRESHOLD_63 = P2_VOL_MULTIPLE × median_HV × sqrt(63/252) (same 0.41-sigma bar)
- Days_to_catalyst output line added to entry.py and volatility.py
- Populated catalysts.csv with 18 CRSP events (2019-2026)
  - Tested CRSP backtest with 1, 4, 18 events: inversion deepens with more catalyst data
  - Conclusion: structural — model can't predict direction of binary events from price/volume
- New backtest signal labels: STRONG ENTRY / CAUTION / SHORT-TERM ONLY / STAY OUT
- QQQ backtest validated framework: 51 windows (2002-2026), best statistical case
  - STRONG ENTRY 2.3%, CAUTION 1.2%, SHORT-TERM ONLY 0.7%, STAY OUT 0.6%

Session 7 — Catalyst Fix + Output Polish + Geopolitical Awareness (current device, 2026-05-07)

1. Catalyst loading bug found and fixed
   - benchmarks.py:126 had csv_path = "catalysts.csv" — ignored the data_dir parameter
   - All callers passed data_dir="modules" but the function looked in project root
   - Fixed: csv_path = os.path.join(data_dir, "catalysts.csv")
   - Result: CRSP Days_to_catalyst now correctly resolves (88d to Aug 2026 PDUFA)
   - Last commit message ("may not be pulling catalysts as intended") was diagnosing this

2. for_direction parameter on add_catalyst_proximity()
   - Once catalysts loaded correctly, 63d direction model boosted to 80.7% win prob (inflated)
   - Days_to_catalyst (+) appeared as top driver — model fitting to historical positive outcomes
     (CRSP's past catalysts: FDA approvals, EHA wins) — spurious "near catalyst -> bullish"
   - Solution: EVENT_DRIVEN_TICKERS = {"CRSP"} in benchmarks.py
     When for_direction=True AND ticker in EVENT_DRIVEN_TICKERS, fills 90 sentinel (constant)
     Phase 3 (volatility.py) keeps real catalyst data — IV expansion near events IS real signal
   - direction.py, entry.py, backtest.py call with for_direction=True
   - volatility.py call left default (for_direction=False)
   - CRSP backtest after fix: STRONG ENTRY 3.8% (best avg return) vs prior -1.2% (inverted)
     But sample is thin (45 STRONG ENTRY signals across 17 windows); CRSP still marginal

3. Output language alignment
   - entry.py: ENTRY DECISION line renamed to SIGNAL
   - SIGNAL values now match backtest.py: STRONG ENTRY / CAUTION / SHORT-TERM ONLY / STAY OUT
   - POSITION SIZING line preserved (FULL / REDUCED / N/A)

4. Ticker input loops with KeyboardInterrupt/EOFError handling
   - indicators.py: re-prompts on empty (no default ticker)
   - direction.py, volatility.py, entry.py, backtest.py, sizing.py:
     accept default on empty (TICKER pre-set), break loop, exit cleanly on Ctrl+C/EOF

5. sizing.py NameError fix
   - Line 33: INDICATORS_CSV = os.path.join(DATA_DIR, f"{TICKER.lower()}_indicators.csv")
     referenced TICKER which was commented out at line 31
   - Same pattern as other scripts — commented the line out; INDICATORS_CSV set in main loop

6. backtest.py print fix
   - Line 495 said "Min training window: 252 days (~2 years)" — incorrect, 252 = ~1 year
   - Was a copy-paste artifact from when MIN_TRAIN_DAYS = 504

7. Documented Bash tool quirk
   - Bash tool drops Python stdout from cmd /c subprocesses on Windows (script runs but no output)
   - PowerShell tool captures output correctly via cmd /c "(echo TICKER && echo.) | python -X utf8 script.py" 2>&1
   - Pattern saved to memory: feedback_running_scripts.md

8. QQQ full pipeline run — 2026-05-07 baseline
   - 6625 rows (2000-01-03 to 2026-05-06); price $695.77; all RSIs overbought; above KC upper
   - Phase 2 (15d): 57.2% vs 45.0% base — WIN
   - Phase 2B (63d): 42.3% vs 53.4% base — NO SIGNAL (below base, model bearish medium-term)
   - Phase 3: HV 14.2%, IV rank 0.17 (Low IV), expansion prob 45.6% — CONTRACTION
   - SIGNAL: SHORT-TERM ONLY / POSITION SIZING: REDUCED
   - Backtest 51 windows (2002-2026): matches Session 6 baseline (no regression)
     STRONG ENTRY 2.3%, CAUTION 1.2%, SHORT-TERM ONLY 0.7%, STAY OUT 0.6%
   - sizing.py at $5K budget: only deep OTM (715-745) fits at 1 contract per expiry;
     IV/HV ratio 1.6-1.8x (every row marked ^ = IV expensive vs HV)

Backtest Results (Most Recent / Representative)

QQQ (51 windows, 2002-2026) — best statistical validation in project
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY       501     2.3%     2.5%   65.5%   55.1%    5.6%   -4.1%   <- best
  CAUTION           1082     1.2%     1.8%   61.4%   50.3%    4.6%   -4.2%
  SHORT-TERM ONLY    518     0.7%     1.6%   60.2%   48.1%    4.1%   -4.6%
  STAY OUT          4005     0.6%     1.2%   61.9%   43.1%    3.3%   -3.7%
  ALL DAYS          6106     0.9%     1.4%   62.0%   45.8%    3.8%   -3.9%

AMD (15 windows, 2019-2026) — well-suited; baseline ticker
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgLoss
  STRONG ENTRY       211     2.6%     3.4%   59.7%   46.0%    -9.6%
  CAUTION            288     1.1%    -0.8%   46.2%   32.6%    -9.4%
  SHORT-TERM ONLY     59    12.2%    10.8%   66.1%   62.7%    -9.3%   <- best (momentum bursts)
  STAY OUT          1018     2.5%     0.1%   50.3%   36.1%    -7.4%

CRSP (17 windows, 2018-2026, post-Session 7 fix) — inversion fixed but sample thin
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY        45     3.8%     0.2%   51.1%   42.2%   18.9%  -12.1%   <- best
  CAUTION            246     0.6%    -1.6%   45.5%   32.1%   13.9%  -10.4%
  SHORT-TERM ONLY    147     2.9%     0.5%   52.4%   34.7%   13.9%   -9.3%
  STAY OUT          1441     1.4%    -0.7%   48.0%   32.1%   13.6%   -9.9%
  Note: 45 STRONG ENTRY signals over 17 windows is too thin for confident trading;
  AvgLoss -12.1% reflects binary event risk on directional calls

Geopolitical Risk Limitation (Session 7 — Iran war context, May 2026)

The framework is reactive, not predictive, of exogenous shocks. All inputs are derived
from price/volume/HV history; the model cannot detect geopolitical events before they
affect prices. The classification report directly evidences this:

  Phase 3 test set:
    Contraction:  precision 0.79  ← model predicts calm-continues well
    Expansion:    precision 0.64  ← much weaker on shock-driven vol spikes

The asymmetry is structural: contraction events are mean-reversion driven and learnable
from HV history; expansion events are often exogenous (CPI prints, Fed surprises, war
escalation) and unlearnable from price/vol features alone.

Key tell during stress: the IV/HV gap encodes information the model can't see.
QQQ on 2026-05-07 showed HV 14.2% but option IV at 22-26% (60-80% premium). That gap
IS the options market pricing in tail risk Phase 3 doesn't pick up. During known
geopolitical crises:
  - Trust contraction signals less when binary catalysts loom
  - Weight options-market-implied tail risk (the IV/HV ratio) higher than Phase 3 output
  - Don't size like the SHORT-TERM ONLY backtest avg return (0.7%) — those windows
    don't include "Iran-war-2026" type events

Potential Mitigations (not yet implemented)
- VIX term structure feature: VIX9D/VIX or VIX/VIX3M ratio — captures dealer hedging
  and near-term shock pricing in a way HV-derived features cannot
- Put/call ratio or skew metric from Tradier — direct options-market positioning signal
- News/sentiment feature scoped to conflict-related keywords (e.g. NewsAPI integration)
- Manual "elevated tail risk" override flag in entry.py — switch to conservative
  thresholds when user knows a binary catalyst (Fed week, war escalation) is pending
- Replace HV proxy with actual ATM IV from Tradier in Phase 3 — already integrated
  via sizing.py; closing the HV-proxy gap is Priority 1

Known Issues (not yet fixed)
- indicators.py: unused `import mdates`
- direction.py: dead `N_ESTIMATORS = 200` constant (Random Forest leftover)
- sizing.py: TRADIER_TOKEN hardcoded in source (security risk — should be env var)

Improvements (Identified, Not Yet Implemented)

Priority 1 — close the HV/IV proxy gap and add macro tail risk visibility
  - Actual IV from Tradier options chain fed back into Phase 3 (closes HV-proxy gap)
  - VIX term structure + put/call ratio for dealer hedging visibility
  - Earnings estimate revision direction (finviz/yfinance) for individual stocks
Priority 2 — additional individual stock signals
  - Short interest ratio (FINRA monthly): high short + positive momentum = squeeze setup
  - Relative valuation (P/S, P/E vs 3-year history) — distinguishes oversold cheap vs
    oversold expensive
Priority 3 — model quality
  - Probability calibration (isotonic regression) so "72% win prob" actually means 72%
  - Currently logistic regression outputs are scores not calibrated probabilities
Won't fix / structural
  - Binary event direction (FDA decisions, trial readouts) — direction unknowable from
    price/volume features
  - Geopolitical shocks — see Geopolitical Risk Limitation above
  - Secular trend regimes (NVDA 2023-2024 parabolic) — would require explicit regime labels

Important Notes
- Use the PowerShell tool (NOT Bash) for piped script execution on Windows.
  Pattern: cmd /c "(echo TICKER && echo.) | python -X utf8 script.py" 2>&1
  Bash tool drops Python stdout from cmd /c subprocesses; PowerShell captures correctly.
- backtest.py is SELF-CONTAINED — does NOT import from direction.py or volatility.py.
  If feature engineering changes there, backtest.py must be manually updated.
- data/ directory must exist before running any script (user created manually)
- modules/ contains benchmarks.py and catalysts.csv (the catalyst event ledger)
- trade/ subdirectory is the Python virtual environment — do not delete
- memory/ subdirectory in project root is Claude's auto-memory system
- FORWARD_DAYS = 15 kept intentionally — entry timing signal, not holding period predictor
  Phase 2B (63-day) is the LEAPS-aligned thesis validation layer
- data/catalysts.csv must have no commas in description field (use dashes instead)
- ETFs (QQQ) have no earnings dates — yfinance "may be delisted" warning is harmless;
  Days_to_earnings defaults to 45 (neutral)

Tech Stack
yfinance, pandas, numpy, ta, matplotlib, scikit-learn (LogisticRegression, StandardScaler,
precision_score), lxml (earnings dates), requests (Tradier API in sizing.py)

Model Details
All models: Logistic Regression (C=0.1, class_weight="balanced", 80/20 time-based split)
Phase 2  (15d direction) threshold: P2_THRESHOLD = 0.55 — entry timing signal
Phase 2B (63d direction) threshold: P2_THRESHOLD = 0.55 — thesis validation (LEAPS-aligned)
Phase 3  (IV expansion)  threshold: P3_THRESHOLD = 0.60
Threshold sweep: auto-marks optimal using max(precision - base_rate) × log(signals)
Vol-adjusted thresholds: compute_vol_thresholds() auto-calibrates at runtime
  WIN_THRESHOLD    = P2_VOL_MULTIPLE × median_HV × sqrt(15/252)   — 15-day direction bar
  WIN_THRESHOLD_63 = P2_VOL_MULTIPLE × median_HV × sqrt(63/252)   — 63-day direction bar
  EXPANSION_THRESHOLD = P3_VOL_MULTIPLE × median_HV
  P2_VOL_MULTIPLE=0.41; P3_VOL_MULTIPLE=0.20

Sizing.py Config
TRADIER_TOKEN = brokerage token (not sandbox)
MIN_DTE = 180, MAX_DTE = 365 (6-12 month expiries)
DEFAULT_STRIKE_RANGE = 10 strikes above/below ATM
IV source: smv_vol (smoothed model vol, matches Tradier app display)

Ticker Suitability (current understanding)
- AMD:  well-suited; 15 walk-forward windows; STRONG ENTRY 2.6%/59.7% win rate
- QQQ:  best statistical case; 51 windows; clean signal hierarchy; framework reference
- SOFI: marginal — short history (2021 IPO); rate features need more rate-regime variation
- NVDA: marginal — bull trend too strong post-2023 AI pivot; vol regime change hurts Phase 3
- CRSP: unsuitable for direction (binary FDA/trial events); Phase 3 viable for vol plays
        (consider straddle/strangle around PDUFA dates rather than directional calls)

Cross-Ticker Findings
- Direction filter (Phase 2) works: STAY OUT consistently underperforms benchmark
- IV gate as hard filter hurts: CAUTION outperformed STRONG ENTRY in early backtests
  -> repurposed Phase 3 as sizing input
- Volatility more predictable than direction: Phase 3 ~22pt edge (QQQ) vs Phase 2 ~7pt
- CAUTION avg loss premium (~3-4pt vs STRONG ENTRY) confirmed across AMD, NVDA, SOFI
  — IV contraction risk on losing trades is real (validates REDUCED sizing)
- Phase 2B (63-day) edge stronger than Phase 2 (15-day) on AMD (+8.5pt) and CRSP (+22.5pt
  — longer horizon filters out binary event noise)
- SHORT-TERM ONLY ticker-dependent: best on AMD (12.2% — momentum bursts) but worst on
  QQQ (0.7% — no sharp momentum bursts on an index)