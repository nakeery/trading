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
entry.py        Combines models -> SIGNAL + IV/HV gate              Console + data/iv_log.csv (append-only)
backtest.py     Walk-forward backtest of combined signal             data/{ticker}_backtest.png, data/{ticker}_backtest_results.csv
sizing.py       Live options chain sizing via Tradier API            Console output only
modules/benchmarks.py  Shared module — benchmarks, macro features, catalyst proximity
modules/tradier.py     Shared Tradier API client + get_atm_iv()    (no output; imported by sizing/entry)
calibrate_multipliers.py  One-off P2/P3 multiplier sweep tool       data/{ticker}_multiplier_sweep.csv, data/multiplier_calibration.png

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
- [S8] IV/HV gate (entry.py): live ATM IV from Tradier, downgrades STRONG ENTRY -> CAUTION
  if IV/HV >= 1.40. Surfaces options-market info the HV-only model can't see.

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

Session 8 — Multiplier Validation, New Features, Tradier IV Gate (2026-05-07, same day as S7)

1. Multiplier sweep tooling
   - calibrate_multipliers.py: classification-edge sweep over P2_VOL_MULTIPLE (0.20-1.80) and
     P3_VOL_MULTIPLE (0.10-0.40); outputs CSV per ticker + combined PNG
   - backtest.py MULTIPLIER_SWEEP config (list of (p2,p3) tuples; empty=default behavior):
     iterates over combinations, prints comparison table sorted by STRONG ENTRY avg return,
     flags hierarchy-monotonic combos
   - Both tools self-contained; production multipliers untouched unless deliberately changed

2. Multiplier validation: 0.41 / 0.20 are correct
   - Classification sweep on QQQ suggested P2 optimum at 0.90 (edge 11.6pp vs 6.6pp at 0.41)
     and SPY at 1.50 (edge 16.6pp vs 10.6pp at 0.41) — looked like big improvement
   - But the trading-metric backtest sweep (QQQ, P2 in {0.25, 0.41, 0.90} × P3=0.20):
     STRONG ENTRY avg ~2.3-2.5% across all three values (statistically identical),
     0.90 BROKE the signal hierarchy (SHORT-TERM ONLY 1.6% > CAUTION 1.4%)
   - Lesson: classification edge ≠ trading P&L. Strict labels lower base rates,
     inflating "edge" in the score formula without improving real returns.
   - 0.41 / 0.20 stay as production constants. Multiplier sweep tool is for future
     ticker-specific calibration if needed.

3. Two new feature additions to the model
   - Gap features in indicators.py:
       gap_pct    = (Open - prev_Close) / prev_Close
       gap_ma_5d  = 5-day rolling mean of gap_pct (directional drift from overnight news)
       gap_vol_5d = 5-day rolling mean of |gap_pct| (recent gap activity / news velocity)
     Computed once in indicators.py; flows into all downstream CSVs automatically.
     backtest.py computes them inline as fallback if CSV is stale (self-containment preserved).
   - VIX term structure in direction.py / volatility.py / entry.py / backtest.py:
       VIX9D_VIX_ratio = ^VIX9D / ^VIX  (>1 = near-term fear elevated)
       VIX_VIX3M_ratio = ^VIX / ^VIX3M  (<1 = backwardation = stress regime)
     Neutral fill (1.0) for dates before VIX9D/VIX3M history starts (~2011-2013).
     This addresses the "VIX term structure feature" mitigation listed in S7.

4. Pipeline run on QQQ / SPY / NVDA (May 6 close) — current state assessment
   - All three: STAY OUT (Phase 2 below 55% threshold; markets extended at RSI 60-80, above KC)
   - Backtests with new features (no regression vs S6 baseline):
     QQQ  (2001-2026, 53 windows): STRONG ENTRY 2.0% / 65% win  (was 2.3% S6; -0.3pp explained
            by 2 extra 2026 windows including geopolitical-stress period)
     SPY  (1995-2026, 31y): STRONG ENTRY 0.8% / 64% — barely above ALL DAYS 0.7%; CAUTION
            (0.9%) actually beats STRONG. Hierarchy broken. Framework finds no edge on SPY.
     NVDA (2001-2026, 25y): STRONG ENTRY 4.4% / 65% win — BEST result in project. Decisively
            beats AMD (2.6%) and QQQ (2.0%). Reclassify NVDA from "marginal" to "well-suited".
   - Cross-ticker pattern: STRONG ENTRY win rate ≈ 65% across all three. That's a
     reproducible framework property (tunable target for new tickers — if backtest <60%,
     ticker is probably unsuitable).
   - SPY finding is structural: broad-market efficiency dampens signal below noise threshold.
     Framework's lens (price-action, momentum, sector RS) is wrong for macro-driven SPY.
     Not a tuning problem.

5. Tradier IV gate in entry.py — Priority 1 step shipped
   - New module: modules/tradier.py — extracted shared API client (was in sizing.py).
     Includes get_atm_iv(ticker, target_dte=30) → {price, iv, expiry, dte, atm_strike}.
     TRADIER_TOKEN reads $env:TRADIER_TOKEN if set, else hardcoded fallback (security improvement).
   - sizing.py refactored to import from modules/tradier — behavior unchanged.
   - entry.py:
       After signal computation, fetches ATM call IV at ~30 DTE (apples-to-apples with HV-20).
       Computes IV/HV ratio with labels: cheap (<0.85) / fair / rich (>=1.20) / very rich (>=1.40).
       Gate: if signal == STRONG ENTRY AND IV/HV >= IV_HV_GATE_RICH (1.40), downgrade to
              CAUTION + REDUCED with explanatory note.
       Displays the IV section regardless of signal — informative on STAY OUT too.
       Graceful fallback: any Tradier error prints "IV check unavailable: ..." and continues.
   - Forward-accumulating dataset: data/iv_log.csv appends one row per entry.py run with
     date, ticker, price, atm_iv, expiry, dte, hv_20, iv_hv_ratio, label, signal_pre, signal_post.
     After ~3-6 months: enough history to feature-engineer real IV into Phase 3 retraining.
   - First QQQ snapshot (2026-05-06): ATM IV 20.6% / HV 14.2% / ratio 1.46 = "very rich".
     Signal was STAY OUT so gate didn't fire, but the snapshot validates the documented
     "options market sees what HV-based Phase 3 cannot" gap from S7.

Session 9 — Probability Calibration Diagnostic (2026-05-07, same day as S7+S8)

Context: discussion explored two next-step options — put/call ratio + skew (extends S8
IV/HV gate) vs probability calibration (model-quality polish). Chose calibration as the
lowest-risk path: existing models are untouched, only diagnostic output added. Decision
on whether to switch the production model deferred until after seeing the diagnostic data.

1. Diagnostic-only addition (no production changes)
   - Added print_calibration_diagnostic() helper to direction.py and volatility.py
   - Added calibration block at end of train_model() in both files
   - Compares raw LR vs CalibratedClassifierCV (isotonic, 5-fold CV) on the test set
   - Outputs per model: Brier score, ECE, 10-bin reliability table (N / Pred / Actual / Gap)
   - Production model RETURNED is still the raw LR — diagnostic does not flip any switch
   - New imports: sklearn.calibration.CalibratedClassifierCV, sklearn.metrics.brier_score_loss

2. QQQ findings — direction models are miscalibrated, Phase 3 already OK
   Phase 2  (15d direction):  Raw ECE 6.99% -> Calibrated 1.56%   (4.5x improvement)
                              Raw Brier 0.2547 -> 0.2491
                              Pattern: overconfident at 0.5-0.7 bins
                              (raw 55% predicted = 47% actual; raw 64% = 51% actual)
                              Range compression after calibration: minimal — still 0.4-0.6 spread

   Phase 2B (63d direction):  Raw ECE 9.75% -> Calibrated 6.40%   (1.5x improvement)
                              Raw Brier 0.2600 -> 0.2500
                              Pattern: severely overconfident at high end
                              (raw 74% predicted = 41% actual — 33pp gap)
                              Also underconfident at low end (raw 46% = 61% actual)
                              Range compression: SIGNIFICANT — 1002/1304 test samples
                              concentrated in 0.6-0.7 bin after isotonic calibration
                              (loss of discriminative power partially offsets calibration gain)

   Phase 3  (IV expansion):   Raw ECE 4.95% -> Calibrated 3.35%   (1.5x, low base)
                              Raw Brier 0.1789 -> 0.1759
                              Pattern: already well-calibrated; one bad bin at 0.4-0.5
                              (raw 45% predicted = 24% actual)
                              Calibration provides modest improvement only

3. Root cause: class_weight="balanced" inflates confidence
   - LR is trained on artificially balanced classes (each contributes equal loss weight)
   - Scores reflect odds vs a 50/50 base rate, not the true ~45% WIN base rate
   - Raw scores are ranking scores not calibrated probabilities — "57.2% win prob"
     in entry.py output corresponds to ~48% actual win frequency on Phase 2
   - Phase 3 has less miscalibration because its base rate (~42%) is closer to balanced

4. Backtest baseline confirmed unchanged after S9 changes
   - Ran backtest.py on QQQ post-edit (53 windows, 2001-2026)
   - Numbers match S8 baseline exactly: STRONG ENTRY 2.0% / 64.9% win, hierarchy intact
   - Confirms diagnostic-only addition didn't accidentally alter production behavior

5. Pending decision: whether/how to switch production model
   Direction 1 (recommended): Switch Phase 2 ONLY to calibrated
     - Cleanest case (4.5x ECE drop, minimal compression)
     - Phase 2 is the gateway gate (ENTER vs STAY OUT) — best leverage point
     - Single-model change is isolatable for regression diagnosis
     - Downstream task: re-tune P2_THRESHOLD on calibrated scale, re-run backtest, confirm hierarchy
   Direction 2: Try Platt scaling on Phase 2B
     - Phase 2B has worst miscalibration but isotonic compressed too aggressively
     - Platt (sigmoid fit) compresses less; better fit for sigmoid-shaped miscalibration
     - Best as follow-up after Direction 1 validates that calibration helps in this framework

Backtest Results (Most Recent / Representative)

QQQ (53 windows, 2001-2026, post-S8 features) — framework reference baseline
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY       619     2.0%     2.4%   64.9%   53.3%    5.4%   -4.1%   <- best
  CAUTION           1364     1.1%     1.8%   62.1%   50.1%    4.4%   -4.3%
  SHORT-TERM ONLY    558     0.3%     0.8%   56.5%   43.4%    4.1%   -4.6%
  STAY OUT          3772     0.6%     1.2%   61.5%   42.6%    3.5%   -3.9%
  Note: -0.3pp vs S6 baseline (was 2.3%) explained by 2 extra 2026 windows in stress period

NVDA (25 windows, 2001-2026, post-S8 features) — RECLASSIFIED well-suited (was marginal)
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY       392     4.4%     4.9%   65.3%   52.8%   14.4%  -14.5%   <- BEST in project
  CAUTION           1269     1.7%     2.4%   56.4%   45.0%   11.2%  -10.8%
  SHORT-TERM ONLY    323     4.1%     3.0%   60.7%   44.6%   12.7%   -9.3%
  STAY OUT          4361     2.5%     2.0%   58.5%   40.6%   10.0%   -8.0%
  S7 said "marginal — bull trend too strong"; data contradicts that. STRONG ENTRY 4.4% beats AMD.
  Long history dilutes the recent-regime objection; new gap+VIX9D features may also help.

SPY (31 years, 1995-2026, post-S8 features) — UNSUITABLE for this framework
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY       898     0.8%     1.1%   63.6%   47.1%    3.6%   -4.1%
  CAUTION           1189     0.9%     1.2%   61.9%   48.6%    3.4%   -3.1%   <- inverted!
  SHORT-TERM ONLY    724     0.2%     0.8%   58.7%   43.6%    3.1%   -3.8%
  STAY OUT          5044     0.7%     1.2%   65.6%   47.3%    2.6%   -3.0%
  ALL DAYS          7855     0.7%     1.1%   64.2%   47.2%    2.9%   -3.2%
  STRONG ENTRY beats ALL DAYS by 0.1pp = noise. Hierarchy broken (CAUTION>STRONG).
  Structural: SPY moves are macro-driven (Fed, GDP, geopolitics); framework's price-action
  + momentum + sector-RS lens is the wrong tool. Don't use as primary ticker.

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

Potential Mitigations
- [DONE S8] VIX term structure features (VIX9D_VIX_ratio, VIX_VIX3M_ratio) added to all
  ML scripts — captures dealer hedging and near-term shock pricing
- [DONE S8] Live ATM IV gate at entry time — IV/HV ratio computed; STRONG ENTRY -> CAUTION
  if ratio >= 1.40 (very rich). Forward-accumulating data/iv_log.csv builds historical
  IV dataset for eventual Phase 3 retraining (~3-6 months out)
- [TODO] Put/call ratio or skew metric from Tradier — direct options-market positioning signal
- [TODO] News/sentiment feature scoped to conflict-related keywords (NewsAPI integration)
- [TODO] Manual "elevated tail risk" override flag in entry.py — conservative thresholds
  when user knows a binary catalyst (Fed week, war escalation) is pending
- [TODO/Phase 2] Once iv_log.csv has 3-6 months of history, retrain Phase 3 with real IV
  features instead of HV proxy. Considering paid options history (ORATS/CBOE) to backfill
  if real-IV results justify the cost.

Known Issues (not yet fixed)
- indicators.py: unused `import mdates`
- direction.py: dead `N_ESTIMATORS = 200` constant (Random Forest leftover)
- modules/tradier.py: TRADIER_TOKEN now reads $env:TRADIER_TOKEN if set; hardcoded
  fallback still in source. Set the env var to keep token out of git.

Improvements (Identified, Not Yet Implemented)

Priority 1 — close the HV/IV proxy gap and add macro tail risk visibility
  - [DONE S8] VIX term structure features (VIX9D_VIX_ratio, VIX_VIX3M_ratio)
  - [DONE S8] Live ATM IV gate at entry time + forward IV history accumulation
  - [TODO] Put/call ratio or skew metric from Tradier
  - [TODO/Phase 2] Phase 3 retraining on real IV history (after iv_log.csv accumulates ~3-6mo)
  - [TODO] Earnings estimate revision direction (finviz/yfinance) for individual stocks
Priority 2 — additional individual stock signals
  - Short interest ratio (FINRA monthly): high short + positive momentum = squeeze setup
  - Relative valuation (P/S, P/E vs 3-year history) — distinguishes oversold cheap vs
    oversold expensive
  - Macro feature layer for indexes (yield curve, credit spread, DXY) — only worth it
    if SPY tuning is wanted; current verdict says SPY is structurally unsuitable
Priority 3 — model quality
  - [DIAGNOSTIC DONE S9] Probability calibration via isotonic regression
    - Diagnostic added to direction.py + volatility.py train_model() — compares raw LR
      vs CalibratedClassifierCV side-by-side via Brier/ECE/reliability bins
    - QQQ results: Phase 2 ECE 6.99% -> 1.56% (4.5x); Phase 2B 9.75% -> 6.40% (1.5x);
      Phase 3 4.95% -> 3.35% (already low base)
    - Raw scores systematically overconfident — root cause is class_weight="balanced"
    - Production model unchanged; diagnostic only at this stage
  - [PENDING DECISION S9] Switch Phase 2 to calibrated production model (Direction 1)
    - Cleanest improvement; Phase 2 is the gateway gate so leverage is highest
    - Phase 2B isotonic compresses 1002/1304 samples into one bin — defer until Platt tested
    - Phase 3 already well-calibrated; not essential to switch
  - [TODO follow-up] Try Platt scaling on Phase 2B (Direction 2)
    - Sigmoid-fit alternative; less compression than isotonic, may fit
      sigmoid-shaped miscalibration well
Won't fix / structural
  - Binary event direction (FDA decisions, trial readouts) — direction unknowable from
    price/volume features
  - Geopolitical shocks — see Geopolitical Risk Limitation above
  - SPY edge — broad-market efficiency dampens framework lens below noise threshold
    (verified S8: 0.1pp edge over base, broken hierarchy across 31 years)

Important Notes
- Use the PowerShell tool (NOT Bash) for piped script execution on Windows.
  Pattern: cmd /c "(echo TICKER && echo.) | python -X utf8 script.py" 2>&1
  Bash tool drops Python stdout from cmd /c subprocesses; PowerShell captures correctly.
- backtest.py is SELF-CONTAINED — does NOT import from direction.py or volatility.py.
  If feature engineering changes there, backtest.py must be manually updated.
- data/ directory must exist before running any script (user created manually)
- modules/ contains benchmarks.py (sector + macro + catalysts), tradier.py (S8 — shared
  Tradier API client used by sizing.py and entry.py), and catalysts.csv (catalyst event ledger)
- data/iv_log.csv (S8) is append-only — every entry.py run adds one row. Used to build
  forward-looking IV history for eventual Phase 3 retraining on real IV (not HV proxy)
- trade/ subdirectory is the Python virtual environment — do not delete
- memory/ subdirectory in project root is Claude's auto-memory system
- FORWARD_DAYS = 15 kept intentionally — entry timing signal, not holding period predictor
  Phase 2B (63-day) is the LEAPS-aligned thesis validation layer
- data/catalysts.csv must have no commas in description field (use dashes instead)
- ETFs (QQQ) have no earnings dates — yfinance "may be delisted" warning is harmless;
  Days_to_earnings defaults to 45 (neutral)

Tech Stack
yfinance, pandas, numpy, ta, matplotlib, scikit-learn (LogisticRegression, StandardScaler,
precision_score), lxml (earnings dates), requests (Tradier API via modules/tradier.py)

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

Tradier Config (modules/tradier.py + sizing.py)
TRADIER_TOKEN = $env:TRADIER_TOKEN if set, else hardcoded fallback (S8 refactor)
MIN_DTE = 180, MAX_DTE = 365 (6-12 month expiries) — sizing.py default
DEFAULT_STRIKE_RANGE = 10 strikes above/below ATM
IV source: smv_vol (smoothed model vol, matches Tradier app display) — fallback: mid_iv
get_atm_iv(ticker, target_dte=30) — picks closest-to-30-DTE expiry, returns ATM call IV

Entry.py IV/HV Gate (S8)
IV_HV_FAIR_LOW = 0.85   — below: premium cheap vs realized (favorable for buyers)
IV_HV_FAIR_HIGH = 1.20  — above: premium rich
IV_HV_GATE_RICH = 1.40  — above: STRONG ENTRY downgrades to CAUTION (REDUCED sizing)
IV_TARGET_DTE = 30      — ATM IV expiry tenor (matches HV-20 timeframe)
data/iv_log.csv columns: log_time, signal_date, ticker, price, atm_iv, iv_expiry,
                         iv_dte, hv_20, iv_hv_ratio, iv_hv_label, signal_pre_gate, signal_post_gate

Ticker Suitability (post-S8)
- QQQ:  best statistical case; 53 windows; clean hierarchy; framework reference baseline
        STRONG ENTRY 2.0% / 65% win
- NVDA: WELL-SUITED (was "marginal" in S7) — STRONG ENTRY 4.4% / 65% win, BEST in project.
        Long history dilutes the post-2023 regime-change concern.
- AMD:  well-suited; 15 walk-forward windows; STRONG ENTRY 2.6%/59.7% win rate
- SOFI: marginal — short history (2021 IPO); rate features need more rate-regime variation
- CRSP: unsuitable for direction (binary FDA/trial events); Phase 3 viable for vol plays
        (consider straddle/strangle around PDUFA dates rather than directional calls)
- SPY:  UNSUITABLE — 0.1pp edge over base rate, hierarchy broken (S8 finding).
        Structural mismatch: framework is price-action/momentum, SPY is macro-driven.
        Don't use as primary ticker.

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
- [S8] STRONG ENTRY win rate ≈ 65% across QQQ/NVDA/SPY — reproducible framework property.
  Use as suitability test: if a new ticker can't hit ~60%+ STRONG win rate, probably unsuitable.
- [S8] Framework's edge concentrates where micro-inefficiencies exist:
  individual stocks (NVDA 4.4%, AMD 2.6%) > tech-heavy index (QQQ 2.0%) > broad index (SPY 0.8%).
  Lens is wrong for macro-driven tickers; correct for momentum/growth-driven tickers.
- [S8] Classification edge ≠ trading P&L. Multiplier sweep on classification metric suggested
  P2_VOL_MULTIPLE=0.90 was 4× better than 0.41; trading-metric backtest sweep showed
  identical STRONG ENTRY returns (~2.4% across 0.25/0.41/0.90) and 0.90 broke hierarchy.
  Always validate threshold-tuning ideas via backtest STRONG ENTRY avg return, not via
  precision-edge metrics.