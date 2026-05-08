Session Context Summary

Project Overview
Multi-Ticker Options Swing Trading ML Pipeline — 7-script system that supplements a Webull
chart-based strategy for 6-12 month call options with ML-derived entry signals and live
options sizing. Originally AMD-specific; now generalized for any liquid US equity or index ETF.

Pipeline Architecture
Scripts run sequentially. indicators.py must run first to generate the CSV that all
downstream scripts depend on.

Script          Purpose                                              Output
indicators.py   Fetch OHLCV, compute 30+ indicators, harvest         data/{ticker}_indicators.csv (now with IV cols),
                today's options chain summary from Massive            data/{ticker}_dashboard.png
direction.py    Direction ML model (Phase 2 + 2B)                   data/{ticker}_ml_features.csv, data/{ticker}_ml_results.png
volatility.py   IV expansion ML model (Phase 3)                    data/{ticker}_phase3_features.csv, data/{ticker}_phase3_results.png
entry.py        Combines models -> SIGNAL + IV/HV gate              Console (reads IV from indicators CSV — no live API call)
backtest.py     Walk-forward backtest of combined signal             data/{ticker}_backtest.png, data/{ticker}_backtest_results.csv
sizing.py       Live options chain sizing via Tradier API            Console output only
modules/benchmarks.py  Sector benchmarks + macro + catalyst proximity
modules/tradier.py     Shared Tradier API client (used by sizing.py)
modules/massive.py     Massive.com options API client + get_chain_summary (S10)
calibrate_multipliers.py  One-off P2/P3 multiplier sweep tool       data/{ticker}_multiplier_sweep.csv, data/multiplier_calibration.png

Primary daily-use script: entry.py (after indicators.py refresh)
Run after entry signal is actionable: sizing.py

Workflow
1. indicators.py  — refresh data daily (downloads OHLCV + harvests options chain snapshot)
2. entry.py       — get SIGNAL + POSITION SIZING (reads IV from indicators CSV)
3. sizing.py      — when signal is actionable, get contract sizing from live Tradier options chain
4. direction.py   — as needed for deeper direction model analysis
5. volatility.py  — as needed for deeper IV analysis
6. backtest.py    — periodically to verify model performance

Decision Framework
- Phase 2 (15d direction) fires = entry timing signal
- Phase 2B (63d direction) confirms or rejects medium-term thesis
- Phase 3 (IV expansion) = position SIZING input, not go/no-go gate
- IV/HV gate (entry.py): live ATM IV from Massive chain snapshot (harvested by indicators.py),
  downgrades STRONG ENTRY -> CAUTION if IV/HV >= 1.40

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

────────────────────────────────────────────────────────────────────────

Sessions 1-6 — Foundational Build (consolidated)

- S1-S2: 7-script pipeline assembled; data/ CSV routing; backtest.py walk-forward framework
  (cached VIX/SOX); sizing.py via Tradier (yfinance options chain returned empty tuples);
  refactor from binary STRONG ENTRY/CAUTION to ENTER + FULL/REDUCED sizing; dynamic sector
  benchmark detection bypassing 401-prone yfinance .info; threshold sweep marker
  max(precision - base_rate) × log(signals)
- S3: Vol-adjusted thresholds via compute_vol_thresholds() in all 4 ML scripts.
  P2_VOL_MULTIPLE = 0.41 (0.41-sigma bar; range 0.25 aggressive to 1.0 conservative)
  P3_VOL_MULTIPLE = 0.20 (heuristic; vol-of-vol scales with HV level)
- S4: Confirmed Claude Code piped run pattern for Windows
  (cmd /c echo pipe + python -X utf8); MIN_TRAIN_DAYS reduced 504 -> 252 (unlocked SOFI)
- S5: Universal price features (price_vs_52w_high/low, vol_ratio); per-benchmark sector
  trend; macro features for rate-sensitive tickers (SOFI/banks -> ^TNX + ^IRX);
  catalyst proximity feature from data/catalysts.csv; CRSP added (biotech, IBB+XLV)
- S6: Phase 2B (63-day direction) added; data/catalysts.csv populated with 18 CRSP events;
  4-label SIGNAL output finalized (STRONG ENTRY / CAUTION / SHORT-TERM ONLY / STAY OUT);
  QQQ backtest validated as framework reference baseline (51 windows, 2002-2026)

Session 7 — Catalyst Fix + Output Polish + Geopolitical Awareness (2026-05-07)

1. benchmarks.py:126 csv_path bug fixed — function ignored data_dir parameter, now resolves
   correctly to data/catalysts.csv. CRSP Days_to_catalyst now resolves (88d to Aug PDUFA).
2. EVENT_DRIVEN_TICKERS = {"CRSP"} added — when for_direction=True, fills 90 sentinel
   (constant). Phase 3 keeps real catalyst data (IV expansion near events IS real signal).
   Direction.py/entry.py/backtest.py call with for_direction=True; volatility.py default.
   CRSP backtest after fix: STRONG ENTRY 3.8% (best avg) vs prior -1.2% (inverted).
3. SIGNAL terminology unified across entry.py and backtest.py.
4. Ticker input loops with KeyboardInterrupt/EOFError handling across all scripts.
5. sizing.py NameError fix; backtest.py print fix (252 days = ~1 year, not 2).
6. Documented Bash tool quirk: drops Python stdout from cmd /c subprocesses on Windows.
7. QQQ baseline re-validated (51 windows): no regression vs S6.

Session 8 — Multiplier Validation, New Features, Tradier IV Gate (2026-05-07)

1. calibrate_multipliers.py — classification-edge sweep over P2 (0.20-1.80) and
   P3 (0.10-0.40); backtest.py MULTIPLIER_SWEEP config for trading-metric sweep.
2. Multiplier validation: 0.41 / 0.20 stay as production. Classification sweep
   suggested P2=0.90 was 4× better than 0.41; trading backtest showed identical
   STRONG ENTRY returns (~2.4% across 0.25/0.41/0.90) and 0.90 BROKE hierarchy.
   Lesson: classification edge ≠ trading P&L.
3. Two new feature additions:
   - Gap features in indicators.py: gap_pct, gap_ma_5d, gap_vol_5d
   - VIX term structure: VIX9D_VIX_ratio, VIX_VIX3M_ratio (>1 = backwardation = stress)
     Neutral fill (1.0) for dates before VIX9D/VIX3M history (~2011-2013)
4. Pipeline run on QQQ/SPY/NVDA: all STAY OUT. Backtests with new features no regression.
   NVDA reclassified WELL-SUITED (was "marginal") — STRONG ENTRY 4.4% / 65% win, BEST
   in project. SPY reclassified UNSUITABLE — 0.1pp edge over base, broken hierarchy.
   Cross-ticker pattern: STRONG ENTRY win rate ≈ 65% — reproducible framework property.
5. Tradier IV gate in entry.py — Priority 1 step shipped (later replaced in S10):
   modules/tradier.py extracted; get_atm_iv() returns ATM call IV at ~30 DTE; entry.py
   computes IV/HV ratio with cheap/fair/rich/very rich labels; STRONG ENTRY downgraded
   to CAUTION at IV/HV >= 1.40. iv_log.csv built forward-accumulating IV history.

Session 9 — Probability Calibration Diagnostic (2026-05-07)

Diagnostic-only addition (no production change). print_calibration_diagnostic() in
direction.py and volatility.py compares raw LR vs CalibratedClassifierCV (isotonic, 5-fold)
on test set. Outputs Brier, ECE, 10-bin reliability table.

QQQ findings — direction models miscalibrated, Phase 3 already OK
- Phase 2  (15d): Raw ECE 6.99% -> Calibrated 1.56%   (4.5x improvement, minimal compression)
- Phase 2B (63d): Raw ECE 9.75% -> Calibrated 6.40%   (1.5x; SIGNIFICANT compression — 1002/1304
                                                       samples in one bin after isotonic)
- Phase 3:        Raw ECE 4.95% -> Calibrated 3.35%   (already low base — modest gain)

Root cause: class_weight="balanced" inflates LR confidence (scores reflect odds vs 50/50,
not true ~45% WIN base rate). Raw "57.2% win prob" corresponds to ~48% actual.

Backtest baseline confirmed unchanged after S9 changes (53 windows match S8 exactly).

PENDING DECISION (carried into S10+): switch Phase 2 to calibrated (Direction 1,
recommended — cleanest, highest leverage) vs try Platt scaling on Phase 2B (Direction 2,
follow-up after Direction 1 validates calibration helps in this framework).

Session 10 — Massive.com Options Data Integration (2026-05-07/05-08)

User signed up for Massive.com Options Starter ($subscription). Replaces Tradier IV gate
and the iv_log.csv accumulation pattern with a richer daily chain harvest written into
the indicators CSV. Sets up the data layer for S11 (BS-inversion historical IV backfill)
and S12 (Phase 3 retraining on real IV).

1. Massive API exploration — findings worth recording
   - The API surface is functionally identical to Polygon.io: same endpoint paths
     (/v3/snapshot/options/, /v3/reference/options/contracts, /v2/aggs/ticker/...),
     same OPRA ticker format (O:QQQ261218C00500000), same as_of semantics.
   - /v3/snapshot/options/{underlyingAsset} returns IV, Greeks, OI, bid/ask, OHLCV but
     is CURRENT-ONLY. Tested with expiration_date.lte=PAST_DATE + expired=true:
     returns empty array even for contracts that expired one month ago. The expired
     flag is ignored on the snapshot endpoint (only honored on contracts reference).
   - /v2/aggs/ticker/O:CONTRACT/range/... returns historical OHLCV bars for expired
     contracts but NO IV/Greeks.
   - /v3/reference/options/contracts?as_of=DATE&expired=true returns expired contract
     metadata (strike, expiry, type) but no pricing.
   - Chain snapshot returns IV=20 (placeholder) with empty greeks {} for deep ITM/OTM
     contracts (documented behavior). Real ATM contracts populate IV (~0.22) and full
     Greeks correctly.
   - Implication: historical IV is NOT a first-class product. To get a historical IV
     time series for Phase 3 retraining, we must build a BS-inversion pipeline (S11):
       contracts reference (as_of) -> aggregates (OHLC) -> Black-Scholes invert -> IV

2. modules/massive.py (new) — chain snapshot client
   - MASSIVE_API_KEY = $env:MASSIVE_API_KEY (no hardcoded fallback by design — empty
     string default; calls fail with "MASSIVE_API_KEY env var not set" if unset)
   - get_chain_summary(ticker, underlying_price, target_dte=30) returns dict:
       atm_iv_30d, atm_strike, atm_expiry, atm_dte,
       iv_skew_25d, term_structure, put_call_oi_ratio
   - Two-call pattern (avoids pagination cap losing back-month data):
       Call A: dte=target±7, strike=spot×0.85 to ×1.15  (ATM IV + 25Δ skew + P/C OI)
       Call B: dte=55-90,    strike=spot×0.97 to ×1.03  (back-month ATM for term structure)
   - IV_COLS canonical list exported (atm_iv_30d, atm_strike, atm_expiry, atm_dte,
     iv_skew_25d, term_structure, put_call_oi_ratio) — imported by indicators.py
     and the 5 ML scripts that exclude it from feature_cols
   - Filters out placeholder IV=20 with `iv != 20 and delta is not None` for IV-based
     stats; uses ALL contracts (with or without IV) for OI counting

3. indicators.py — daily IV harvest
   - harvest_iv_snapshot(df, ticker, csv_path) writes today's chain summary to today's row
   - CRITICAL bug discovered + fixed: each indicators.py run regenerated the CSV from
     scratch, wiping prior days' IV. Fix: harvest_iv_snapshot reads existing CSV first
     and merges any prior IV via combine_first before writing today's. Forward IV
     accumulation now works as designed.
   - Graceful degradation: if Massive API fails or key not set, prints warning,
     leaves IV columns NaN. Does not break indicators run.

4. entry.py — read IV from CSV, gate logic preserved
   - Removed: from modules.tradier import get_atm_iv (only sizing.py still uses tradier)
   - Removed: check_atm_iv() — replaced with read_iv_from_csv()
   - Removed: log_iv_observation() and iv_log.csv writes (data is now in indicators CSV)
   - read_iv_from_csv: reads atm_iv_30d from latest row of df_full; if NaN, prints
     "WARNING: atm_iv_30d is NaN for {date} — re-run indicators.py to refresh the IV
     snapshot." and returns None (gate skipped, signal still computed)
   - print_combined_signal: drops IV_COLS before its dropna() (today's row has NaN in
     some IV cols when harvest fails — would otherwise lose the entire latest row)
   - Display: OPTIONS-MARKET CHECK section shows ATM IV, IV/HV ratio, 25Δ skew,
     term structure (5-band label), put/call OI ratio
   - Term structure 5-band labels (added by user post-implementation):
       < 0.95               -> contango
       0.95 ≤ x ≤ 0.98      -> slight contango
       0.98 < x < 1.02      -> noise
       1.02 ≤ x ≤ 1.05      -> slight backwardation  (boundary fix: 1.05 included here)
       > 1.05               -> backwardation
   - Note: matches Geopolitical Risk Limitation heuristic (>1.05 = trust contractions less)

5. IV_COLS exclusion preventive fix in 5 scripts
   - The mostly-NaN IV columns (only today populated) destroyed train()'s dropna()
   - Fixed in entry.py, direction.py, volatility.py, backtest.py, calibrate_multipliers.py
   - Pattern: exclude = {"Open", "High", "Low", "Close", "Volume", target_col, *IV_COLS}
   - When BS-inversion backfill (S11) populates historical IV, can revisit including
     IV columns as features (likely Phase 3 retrain in S12)

6. iv_log.csv (S8) — deprecated, file preserved on disk as historical record
   - Last 24h of writes were the only entries; not enough data to be useful by itself
   - Indicators CSV now serves as the forward-accumulating IV history

7. Pipeline run verification on QQQ (2026-05-07/08):
   - ATM IV (~28d): 22.0% (matches Massive chain output)
   - IV/HV ratio: 1.52 (very rich) — would gate STRONG ENTRY -> CAUTION when Phase 2 fires
   - 25Δ skew: +0.037 (modest put-side fear)
   - Term structure: 1.02 (slight backwardation — front-month IV ticked above back month
     in last 24h, suggesting near-term stress entering the chain)
   - Put/Call OI: 0.66 (slight call bias near ATM)
   - SIGNAL: STAY OUT (Phase 2 at 53.3% < 0.55 threshold; gate did not fire)

8. Operational note: $env:MASSIVE_API_KEY does not persist across PowerShell sessions.
   Add to $PROFILE for permanence:
     notepad $PROFILE
     # Add: $env:MASSIVE_API_KEY = "<your-key>"
   Otherwise indicators.py harvest writes NaN whenever the env var isn't set.

────────────────────────────────────────────────────────────────────────

Backtest Results (Most Recent / Representative)

QQQ (53 windows, 2001-2026, post-S8 features) — framework reference baseline
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY       619     2.0%     2.4%   64.9%   53.3%    5.4%   -4.1%   <- best
  CAUTION           1364     1.1%     1.8%   62.1%   50.1%    4.4%   -4.3%
  SHORT-TERM ONLY    558     0.3%     0.8%   56.5%   43.4%    4.1%   -4.6%
  STAY OUT          3772     0.6%     1.2%   61.5%   42.6%    3.5%   -3.9%

NVDA (25 windows, 2001-2026, post-S8 features) — RECLASSIFIED well-suited (was marginal)
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY       392     4.4%     4.9%   65.3%   52.8%   14.4%  -14.5%   <- BEST in project
  CAUTION           1269     1.7%     2.4%   56.4%   45.0%   11.2%  -10.8%
  SHORT-TERM ONLY    323     4.1%     3.0%   60.7%   44.6%   12.7%   -9.3%
  STAY OUT          4361     2.5%     2.0%   58.5%   40.6%   10.0%   -8.0%

SPY (31 years, 1995-2026, post-S8 features) — UNSUITABLE for this framework
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY       898     0.8%     1.1%   63.6%   47.1%    3.6%   -4.1%
  CAUTION           1189     0.9%     1.2%   61.9%   48.6%    3.4%   -3.1%   <- inverted!
  SHORT-TERM ONLY    724     0.2%     0.8%   58.7%   43.6%    3.1%   -3.8%
  STAY OUT          5044     0.7%     1.2%   65.6%   47.3%    2.6%   -3.0%
  STRONG ENTRY beats ALL DAYS (0.7%) by 0.1pp = noise. Hierarchy broken (CAUTION>STRONG).
  Structural mismatch: framework's price-action lens vs SPY's macro-driven moves.

AMD (15 windows, 2019-2026) — well-suited; baseline ticker
  STRONG ENTRY 2.6% / 59.7% win | CAUTION 1.1% / 46.2% | SHORT-TERM ONLY 12.2% / 66.1% (best)

CRSP (17 windows, 2018-2026, post-S7 fix) — inversion fixed but sample thin
  STRONG ENTRY 3.8% / 51.1% win | only 45 STRONG signals — too thin for confident trading
  AvgLoss -12.1% reflects binary event risk on directional calls

────────────────────────────────────────────────────────────────────────

Geopolitical Risk Limitation

The framework is reactive, not predictive, of exogenous shocks. All inputs are derived
from price/volume/HV history; the model cannot detect geopolitical events before they
affect prices. The classification report directly evidences this:

  Phase 3 test set:
    Contraction:  precision 0.79  ← model predicts calm-continues well
    Expansion:    precision 0.64  ← much weaker on shock-driven vol spikes

The asymmetry is structural: contraction events are mean-reversion driven and learnable
from HV history; expansion events are often exogenous (CPI prints, Fed surprises, war
escalation) and unlearnable from price/vol features alone.

Key tells during stress:
- IV/HV gap encodes information the model can't see (e.g., QQQ on 2026-05-07: HV 14.2%
  but option IV at 22-26%, 60-80% premium — that gap IS the options market pricing in
  tail risk Phase 3 doesn't pick up)
- Per-ticker term structure (S10) — backwardation (term > 1.05) signals near-term stress
- 25Δ skew (S10) — elevated put-side IV signals tail-risk hedging demand
- VIX9D_VIX_ratio + VIX_VIX3M_ratio (S8) — market-wide near-term fear proxy

During known geopolitical crises:
- Trust contraction signals less when binary catalysts loom or term > 1.05
- Weight options-market-implied tail risk (IV/HV ratio + skew) higher than Phase 3 output
- Don't size like the SHORT-TERM ONLY backtest avg return (0.7%) — those windows
  don't include "Iran-war-2026" type events

────────────────────────────────────────────────────────────────────────

Improvements (status as of S10)

DONE
- [S8] VIX term structure (VIX9D_VIX_ratio, VIX_VIX3M_ratio) in all ML scripts
- [S8] Tradier IV gate in entry.py (replaced in S10 by Massive)
- [S10] Massive.com Options Starter integration:
    - modules/massive.py with two-call chain harvest
    - indicators.py daily harvest into indicators CSV (with merge to preserve history)
    - entry.py reads IV from CSV (no live Tradier call); same gate logic
    - 25Δ skew, term structure, put/call OI ratio captured per ticker per day
    - 5-band term structure labels in entry.py output

PENDING DECISIONS
- [S9 carryover] Switch Phase 2 to calibrated production model (Direction 1)
    Cleanest improvement; Phase 2 is the gateway gate so leverage is highest
    Required: re-tune P2_THRESHOLD on calibrated scale + backtest regression check
- [S9 carryover] Try Platt scaling on Phase 2B (Direction 2)
    Sigmoid-fit alternative; less compression than isotonic
    Defer until Direction 1 validates that calibration helps in this framework

NEXT MAJOR WORK
- [S11/TODO] Black-Scholes inversion pipeline for historical IV backfill
    Use /v3/reference/options/contracts (as_of) + /v2/aggs/... to get historical option
    OHLC, then BS-invert with risk-free rate + dividends to recover ATM IV per ticker
    per day. Output: 2 years of historical IV in indicators CSV (per ticker).
    Dependencies: scipy.optimize (brentq), FRED ^IRX for risk-free rate, yfinance
    dividend yield.
- [S12/TODO] Phase 3 retraining on real IV (depends on S11)
    Replace HV-derived target with actual ATM IV expansion in next 10 days; use real
    IV rank/percentile as features. Should sharpen Phase 3 expansion precision (0.64).

OTHER TODO (lower priority)
- Earnings estimate revision direction (finviz/yfinance) for individual stocks
- Short interest ratio (FINRA monthly) for squeeze-setup detection
- Relative valuation (P/S, P/E vs 3-year history)
- Macro feature layer for indexes (yield curve, credit spread, DXY) — only worth it if
  SPY tuning is wanted; current verdict says SPY is structurally unsuitable

WON'T FIX / STRUCTURAL
- Binary event direction (FDA decisions, trial readouts) — direction unknowable from
  price/volume features
- Geopolitical shocks — see Geopolitical Risk Limitation above
- SPY edge — broad-market efficiency dampens framework lens below noise threshold

────────────────────────────────────────────────────────────────────────

Known Issues (not yet fixed)
- indicators.py: unused `import mdates`, `import datetime` patterns ok
- direction.py: dead `N_ESTIMATORS = 200` constant (Random Forest leftover)
- modules/tradier.py: TRADIER_TOKEN reads $env:TRADIER_TOKEN if set; hardcoded fallback
  still in source. Set the env var to keep token out of git.
- modules/massive.py: MASSIVE_API_KEY uses empty-string default (no hardcoded fallback by
  design — calls fail clearly if env var unset)

Important Notes
- Use the PowerShell tool (NOT Bash) for piped script execution on Windows.
  Pattern: cmd /c "(echo TICKER && echo.) | python -X utf8 script.py" 2>&1
- backtest.py is SELF-CONTAINED — does NOT import from direction.py or volatility.py.
  If feature engineering changes there, backtest.py must be manually updated.
- IV_COLS exclusion pattern: any new ML script reading the indicators CSV must add
  *IV_COLS to its train()/train_model() exclude set, otherwise dropna() destroys
  training data (until S11 backfill populates historical values).
- harvest_iv_snapshot must read existing CSV before writing — preserves prior IV
  history that would otherwise be wiped by indicators.py's full CSV regen.
- $env:MASSIVE_API_KEY does NOT persist across PowerShell sessions — add to $PROFILE.
- data/ directory must exist before running any script (user created manually)
- modules/ contains benchmarks.py, tradier.py, massive.py, catalysts.csv
- data/iv_log.csv (S8) deprecated — file preserved as historical record, no new writes
- trade/ subdirectory is the Python virtual environment — do not delete
- memory/ subdirectory in project root is Claude's auto-memory system
- FORWARD_DAYS = 15 kept intentionally — entry timing signal, not holding period predictor
- data/catalysts.csv must have no commas in description field (use dashes instead)
- ETFs (QQQ) have no earnings dates — Days_to_earnings defaults to 45 (neutral)

Tech Stack
yfinance, pandas, numpy, ta, matplotlib, scikit-learn (LogisticRegression, StandardScaler,
precision_score, CalibratedClassifierCV, brier_score_loss), lxml (earnings dates),
requests (Tradier API via modules/tradier.py + Massive API via modules/massive.py)

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

Massive Config (modules/massive.py)
MASSIVE_API_KEY = $env:MASSIVE_API_KEY (no hardcoded fallback — must be set in environment)
MASSIVE_URL     = https://api.massive.com
Two-call chain harvest:
  Front: dte=target±7,  strike=spot×0.85 to ×1.15  -> ATM IV + 25Δ skew + P/C OI
  Back:  dte=55-90,     strike=spot×0.97 to ×1.03  -> back-month ATM for term structure
FRONT_MONTH_MIN_DTE = 25, BACK_MONTH_MIN_DTE = 55
MAX_PAGES = 5, PAGE_LIMIT = 250 (1250 contracts/call cap)
Filters out IV=20 placeholder (Massive returns this for deep ITM/OTM with empty greeks)
Plan tier: Options Starter — 15-min delayed, 2yr historical, unlimited rate (paid tier)
Endpoints used: /v3/snapshot/options/{ticker} (filtered chain) — current data only
Endpoints planned for S11: /v3/reference/options/contracts (as_of) + /v2/aggs/ticker/...

IV columns added to indicators CSV (canonical list in modules/massive.py:IV_COLS)
  atm_iv_30d, atm_strike, atm_expiry, atm_dte,
  iv_skew_25d, term_structure, put_call_oi_ratio
All 5 ML scripts (entry/direction/volatility/backtest/calibrate_multipliers) exclude
*IV_COLS from feature_cols — required until S11 backfill.

Entry.py IV/HV Gate (S8 logic, S10 data source change)
IV_HV_FAIR_LOW = 0.85   — below: premium cheap vs realized (favorable for buyers)
IV_HV_FAIR_HIGH = 1.20  — above: premium rich
IV_HV_GATE_RICH = 1.40  — above: STRONG ENTRY downgrades to CAUTION (REDUCED sizing)
IV_TARGET_DTE = 30      — ATM IV expiry tenor (matches HV-20 timeframe)
Source: today's row of indicators CSV (atm_iv_30d column written by indicators.py)
Failure mode: NaN warning printed, gate skipped, signal still computed

Term Structure 5-Band Label (entry.py output)
  term < 0.95             -> contango
  0.95 ≤ term ≤ 0.98      -> slight contango
  0.98 < term < 1.02      -> noise (dead zone — normal regime)
  1.02 ≤ term ≤ 1.05      -> slight backwardation
  term > 1.05             -> backwardation (treat as stress signal)

────────────────────────────────────────────────────────────────────────

Ticker Suitability (post-S8)
- QQQ:  best statistical case; 53 windows; clean hierarchy; framework reference baseline
        STRONG ENTRY 2.0% / 65% win
- NVDA: WELL-SUITED (was "marginal" in S7) — STRONG ENTRY 4.4% / 65% win, BEST in project.
        Long history dilutes the post-2023 regime-change concern.
- AMD:  well-suited; 15 walk-forward windows; STRONG ENTRY 2.6% / 59.7% win
- SOFI: marginal — short history (2021 IPO); rate features need more rate-regime variation
- CRSP: unsuitable for direction (binary FDA/trial events); Phase 3 viable for vol plays
        (consider straddle/strangle around PDUFA dates rather than directional calls)
- SPY:  UNSUITABLE — 0.1pp edge over base, hierarchy broken (S8 finding).
        Structural mismatch: framework is price-action/momentum, SPY is macro-driven.

Cross-Ticker Findings
- Direction filter (Phase 2) works: STAY OUT consistently underperforms benchmark
- IV gate as hard filter hurts (CAUTION outperformed STRONG ENTRY in early backtests);
  repurposed Phase 3 as sizing input
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
  individual stocks (NVDA 4.4%, AMD 2.6%) > tech-heavy index (QQQ 2.0%) > broad index (SPY 0.8%)
- [S8] Classification edge ≠ trading P&L. Validate threshold-tuning ideas via backtest
  STRONG ENTRY avg return, not via precision-edge metrics.
