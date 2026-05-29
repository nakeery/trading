Session Context Summary
=======================

Project Overview
----------------
Multi-Ticker Options Swing Trading ML Pipeline — supplements a Webull chart-based
strategy for 6-12 month call options with ML-derived entry signals and live
options sizing. Originally AMD-specific; now generalized for any liquid US equity
or index ETF.

Daily flow (see CLAUDE.md for commands):
  indicators.py → entry.py → sizing.py
Diagnostic scripts (as needed): direction.py, volatility.py, backtest.py
Shared modules: modules/{features, benchmarks, massive, tradier, bs_invert}.py

────────────────────────────────────────────────────────────────────────

Decision Framework
------------------

Five-label SIGNAL output (entry.py + backtest.py):

  STRONG ENTRY     15d WIN + 63d WIN + Phase 3 EXPANSION         FULL sizing
  CAUTION          15d WIN + 63d WIN + Phase 3 CONTRACTION       REDUCED sizing
  SHORT-TERM ONLY  15d WIN + 63d NO SIGNAL                       REDUCED sizing
  LEAPS ONLY       15d NO SIGNAL + 63d WIN                       LEAPS (6-9mo)
  STAY OUT         15d NO SIGNAL                                 N/A

Phase 2 (15d) drives ENTER vs STAY OUT.
Phase 2B (63d) confirms or rejects medium-term thesis.
Phase 3 (IV expansion) modulates sizing — not a go/no-go gate.

IV/HV gate (entry.py): IV/HV >= 1.40 downgrades STRONG ENTRY → CAUTION.
  IV/HV bands: < 0.85 cheap | 0.85-1.20 fair | 1.20-1.40 rich | > 1.40 very rich

Term structure 5-band (entry.py display only):
  < 0.95 contango | 0.95-0.98 slight contango | 0.98-1.02 noise
  | 1.02-1.05 slight backwardation | > 1.05 backwardation (stress signal)

────────────────────────────────────────────────────────────────────────

Model Details
-------------

All models: LogisticRegression(C=0.1, class_weight="balanced"), 80/20 time-based
split, RANDOM_STATE=42.

  Phase 2  (15d direction)  threshold 0.55  — entry timing
  Phase 2B (63d direction)  threshold 0.55  — thesis validation (LEAPS-aligned)
  Phase 3  (IV expansion)   threshold 0.60  — sizing modulation

Vol-adjusted thresholds (compute_vol_thresholds in modules/features.py):
  WIN_THRESHOLD       = 0.41 × median_HV × sqrt(15/252)   [P2_VOL_MULTIPLE=0.41]
  WIN_THRESHOLD_63    = 0.55 × median_HV × sqrt(63/252)   [P2B_VOL_MULTIPLE=0.55]
  EXPANSION_THRESHOLD = 0.20 × median_HV                  [P3_VOL_MULTIPLE=0.20]
  Falls back to AMD defaults (0.05/0.10/0.10) if HV data insufficient.
  P2B uses a higher multiple than P2 to offset secular drift inflating the 63d
  base rate on index ETFs (QQQ at 0.41 → ~70% win rate, nearly no losers to
  learn from). Validated on QQQ; needs NVDA co-validation before permanent default.

Calibration: RAW is production default. Isotonic calibration tested in S11 —
helped indices marginally, destroyed individual-stock edge (NVDA STRONG ENTRY
4.4% → -0.4%). Available as --calibrate research toggle on direction/entry/backtest.

IV features: HV proxy default. --iv-features uses real Massive-derived IV
(atm_iv_30d, iv_skew_25d, term_structure) with HV-based imputation for pre-backfill
rows. NO clean backtest edge (S24): after fixing the Phase 2/2B indicator leak, the
STRONG-ENTRY A/B is within noise on both real-IV tickers (AMD 6mo -2.0pp, NVDA +0.6pp).
The S23 "NVDA +2.3pp" pass was a LEAK ARTIFACT. Real IV does improve Phase 3
*classification* (QQQ +0.8pp precision; AMD +8pp test precision on the recent split) but
that does not translate into STRONG-ENTRY return edge. Stays opt-in, default OFF.

────────────────────────────────────────────────────────────────────────

Current Backtest Baselines
--------------------------

QQQ (53 windows, 2001-2026, post-S18) — framework reference baseline
  P2_VOL_MULTIPLE=0.41, P2B_VOL_MULTIPLE=0.55, P3_VOL_MULTIPLE=0.20
  WIN_THRESHOLD 1.82%, WIN_THRESHOLD_63 5.00%, EXPANSION_THRESHOLD 3.64%
  Signal           Count   Avg    Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY       570   1.8%   64.2%   51.9%    5.2%   -4.3%   ← best 15d
  CAUTION           1285   1.1%   61.3%   49.3%    4.5%   -4.4%
  SHORT-TERM ONLY    607   0.6%   59.5%   44.6%    3.8%   -4.2%
  LEAPS ONLY         766   0.7%   60.7%   44.1%    3.9%   -4.2%
  STAY OUT          3088   0.6%   61.8%   43.0%    3.5%   -3.9%

QQQ 6-month forward returns (post-S18):
  STRONG ENTRY    +9.4%   76.3%  ← only signal with edge on BOTH 15d + 6mo
  LEAPS ONLY      +7.5%   69.5%  ← above ALL DAYS (7.0%) — real 6mo edge
  SHORT-TERM      +6.8%   78.2%  (high win rate but no 63d confirmation)
  CAUTION         +7.3%   70.5%
  STAY OUT        +6.5%   77.7%  (secular QQQ bid)
  ALL DAYS        +7.0%   75.2%

(Minor numerical drift from pre-S18 baseline expected — today-row addition
in S16 shifts the train/test split by 1 each indicators.py run.)

AMD (91 windows, 2000-2026, post-S24 — HV proxy production, P2B=0.55)
  Signal           Count   15d    Win%    6mo    6mo Win
  STRONG ENTRY      383    3.4%   58.7%   33.9%   74.8%   ← best both horizons
  CAUTION           729    2.5%   52.3%   15.1%   58.0%
  SHORT-TERM ONLY   683   -2.5%   41.3%    2.8%   42.3%   ← hard NO (63d confirmation load-bearing)
  LEAPS ONLY        976    2.6%   55.6%   17.1%   55.8%   (> STAY OUT 6mo → real LEAPS edge)
  STAY OUT         3691    2.0%   51.9%   16.3%   53.0%
  WIN_THRESHOLD 4.98% (vs QQQ 1.82%) — much harder bar. STRONG AvgWin/AvgLoss 11.6%/-8.3%.
  vs pre-S17 (377/3.9%/57.0%): 15d slightly lower from P2B tightening, win rate UP, 6mo strong.
  AMD IV backfill RESTORED (462 rows). --iv-features clean A/B: no edge (15d 3.4→2.8%,
  6mo 33.9→31.9%) — HV proxy is production. P4 + VIX gates both REJECT again.

NVDA (53 windows, 2001-2026, RAW mode, post-S24 with P2B=0.55)
  HV proxy:      STRONG ENTRY 355 / 2.8% / 58.9% / 6mo 33.3% / 71.2%  ← production
  --iv-features: STRONG ENTRY 355 / 2.9% / 60.0% / 6mo 33.9% / 71.8%  (clean, post-leak-fix)
  S24 CORRECTION: S23's "--iv-features 318 / 35.6% / +2.3pp" was a LEAK ARTIFACT (Phase
  2/2B indicator leak — see S24 log). Post-fix STRONG count returns to 355 (= HV) and the
  clean 6mo delta is +0.6pp (noise). --iv-features does NOT pass NVDA.
  Pre-S17 baseline was 391 / 4.4% / 65.5% — drop reflects P2B threshold
  tightening (0.41 → 0.55), not regression. Hierarchy intact at 6mo.
  S23 finding: edge is NOT concentrated in high-confidence tail (contradicts
  S11 explanation). NVDA STRONG ENTRY edge concentrates in MID-confidence
  range (P2 prob 0.60-0.70 → +7%/+47% 15d/6mo; prob ≥ 0.75 → -0.7%/+11%).
  Investigation traced 0.75+ inversion to model over-applying a "post-drop
  recovery" pattern learned in early windows + 2009 GFC training data.
  CALIBRATED mode COLLAPSES STRONG ENTRY to -0.4% / 52% (S11 regression — drove default-revert).
  Underlying mechanism for S11 is now uncertain (was attributed to tail compression).

SPY: STRUCTURALLY UNSUITABLE — 0.1pp edge over base, hierarchy broken.
  Framework's price-action lens vs SPY's macro-driven moves don't match.

CRSP: unsuitable for direction (binary FDA/trial events). Phase 3 viable for
vol plays — straddles/strangles around PDUFA dates rather than directional calls.

────────────────────────────────────────────────────────────────────────

Ticker Suitability
------------------

  QQQ   framework reference baseline; clean hierarchy; 53 windows
  AMD   well-suited; STRONG ENTRY only (CAUTION ≈ STAY OUT, SHORT-TERM ONLY
        is a hard NO); STRONG AvgWin/AvgLoss skew (13.0% / -8.3%) supports
        FULL sizing
  NVDA  well-suited in RAW mode (STRONG ENTRY 4.4% / 65.5%); calibration
        destroys edge; high-confidence-tail-driven
  SOFI  marginal — short history (2021 IPO); rate features need more rate-regime
        variation
  AAPL  backfill partial (180 IV rows since 2025-07-24); backtest not run
  LYFT  backfill complete (439 IV rows); backtest not run
  CRSP  unsuitable for direction; Phase 3 viable for vol plays
  SPY   structurally unsuitable

Cross-ticker findings:
- STRONG ENTRY win rate ~65% reproduces across QQQ/NVDA/SPY — use as suitability
  test (new ticker can't hit ~60%+ → probably unsuitable)
- Direction filter works: STAY OUT consistently underperforms benchmark
- CAUTION avg loss is consistently 3-4pt worse than STRONG ENTRY across
  AMD/NVDA/SOFI — IV contraction risk on losing trades is real, validates
  REDUCED sizing
- Phase 2B (63d) edge stronger than Phase 2 (15d) on AMD (+8.5pt) and CRSP
  (+22.5pt — longer horizon filters binary event noise)
- SHORT-TERM ONLY ticker-dependent: best on AMD when computed without 63d split
  but post-S15 splits show it as a hard NO; QQQ is near-zero either way
- Framework edge concentrates where micro-inefficiencies exist:
  individual stocks (NVDA 4.4%, AMD 3.9%) > tech-heavy index (QQQ 1.9%) >
  broad index (SPY 0.8%)

────────────────────────────────────────────────────────────────────────

Cross-Cutting Lessons
---------------------

Edge-in-tail theory — REVISED in S23, partially contradicted
  Original belief (pre-S23): index ETFs distribute edge uniformly across
  the probability range; individual stocks concentrate edge in the high-
  confidence tail.
  S23 measured this directly via probability_deciles.py:
    QQQ: modest U-shape, tail (≥0.70) +2.9pp over base — mild edge-in-tail
    NVDA: edge concentrates in MID-confidence (0.60-0.70: +7% 15d / +47%
          6mo). The high-confidence tail INVERTS (0.75+: -0.7% 15d / +11%
          6mo). Tail is catastrophically worse, not better.
  Mechanism (probability_diagnostics.py): 0.75+ signals fire after -16%
  20d drawdowns (vs +0.7% in mid bucket). Model learned an inflexible
  "post-drop recovery" pattern from 2009 GFC training data and over-applies
  it to subsequent dip setups (2002 dotcom, 2011 sideways, 2008 GFC bottom).
  Not pure overfitting: 2011 cohort (19 signals) came from windows with
  12 years of training data.
  S11 attribution to "compressed extremes" no longer holds — there is no
  high-confidence edge to compress on NVDA. Why isotonic calibration broke
  NVDA is now an open question.
  Cross-ticker (S24): AMD tested — does NOT replicate NVDA's mid-confidence
  sweet spot. AMD is horizon-split: 15d edge RISES with confidence (0.75+ bucket
  +9.0%, opposite of NVDA's tail inversion), 6mo edge FALLS with confidence
  (0.55-0.60 bucket +40.2%, tail +25.2%). Third distinct shape (QQQ mild
  edge-in-tail; NVDA mid-confidence; AMD horizon-split) → edge distribution is
  ticker- AND horizon-specific. SOFI/LYFT still pending backfill.

Calibration helps indices, hurts individual stocks
  Isotonic Phase 2 calibration: QQQ marginal pass (-0.3pt STRONG ENTRY),
  NVDA catastrophic fail (-4.8pt, hierarchy fully inverted, STRONG ENTRY
  underperforming ALL DAYS). Production default is RAW; --calibrate retained
  as research toggle.

Cross-ticker validation required
  QQQ alone is INSUFFICIENT validation for any framework change. Always
  co-validate on QQQ + NVDA minimum before adopting as production default.
  Index/stock edge profiles differ structurally.

Stress regime is a contrarian BUY signal, not a sell signal (S21)
  Counter-intuitive finding from the regime-gate rejection: direction-model
  STRONG ENTRYs that fire in high-VIX regimes have FORWARD RETURNS ABOVE
  AVERAGE across QQQ + NVDA + AMD (NVDA stress-STRONG-ENTRYs +42% 6mo vs
  all-STRONG 33%). The framework's price-action lens already encodes
  mean-reversion behavior — direction models firing bullishly in high VIX
  are catching post-shock recovery rallies. Any gate that downgrades signals
  based on raw VIX state removes the highest-return entries. Implication:
  don't add VIX-state gates to direction signals; if anything, AMPLIFY them
  in stress (continuous sizing experiment).

Per-window threshold calibration (backtest.py)
  compute_vol_thresholds(df_train) called inside run_backtest() loop after
  each df_train slice — eliminates lookahead contamination from future vol
  data in early training windows. Material impact on AMD (40y data);
  negligible for QQQ (stationary HV).

Today-row addition shifts train/test split (S16)
  indicators.py adds a today-row when today is a weekday and yfinance
  hasn't returned today's bar (yfinance end is exclusive). The today-row
  carries the IV harvest stamp instead of overwriting yesterday's IV.
  Side effect: each indicators.py run grows df by 1 row, shifting the
  80/20 split forward by 1 sample. Daily probabilities can drift
  meaningfully run-to-run (observed +16pp shift in QQQ Phase 3 expansion
  prob during S16 verification). Expected, not a bug.

IV_COLS exclusion required in all ML scripts
  The 7 IV columns are NaN for pre-backfill rows. Every train()/train_model()
  must exclude IV_COLS (or IV_META_COLS when --iv-features is on) from
  feature_cols, otherwise dropna() destroys the training set. Applied in
  direction/volatility/entry/backtest/calibrate_multipliers.

CSV merge preserves IV history (indicators.py)
  harvest_iv_snapshot reads existing CSV and merges prior IV via
  combine_first before writing today's. Without this, every indicators.py
  re-run would wipe accumulated forward IV history.

Classification edge ≠ trading P&L
  S8 finding: P2 multiplier 0.90 won the classification edge sweep (4×
  better than 0.41) but produced identical trading returns and broke the
  signal hierarchy. Validate threshold/multiplier ideas via backtest avg
  return, not classification precision alone.

EVENT_DRIVEN_TICKERS catalyst neutralization
  for_direction=True in add_catalyst_proximity fills 90 (constant) for
  tickers in EVENT_DRIVEN_TICKERS = {"CRSP"}. Reason: catalyst proximity
  creates spurious "near event → bullish" association in direction models
  for binary-event biotechs. Phase 3 uses default for_direction=False
  (catalyst signal is real for IV expansion).

────────────────────────────────────────────────────────────────────────

Massive.com Integration
-----------------------

Daily harvest (indicators.py → modules/massive.py:get_chain_summary)
  Two-call pattern (avoids 1250-contract pagination cap):
    Front: dte=target±7, strike=spot×0.85 to ×1.15
           → atm_iv_30d, iv_skew_25d, put_call_oi_ratio
    Back:  dte=55-90,    strike=spot×0.97 to ×1.03
           → back-month ATM for term_structure
  Filters out IV=20 placeholder (Massive returns this for deep ITM/OTM
  with empty greeks). Uses ALL contracts (with or without IV) for OI counting.

Historical backfill (backfill_iv.py → modules/massive.py:get_historical_iv_snapshot)
  Stage A: contracts reference (expired=true) for front calls + puts + back calls
  Stage B: per-contract aggregates fetch → BS-invert via modules/bs_invert.py
  Quality filters (post-S13/S14 hardening):
  - MIN_OPTION_VOLUME = 5  (rejects single-trade artifacts)
  - MIN_OPTION_TRADES = 5  (rejects block-trade artifacts)
  - IV bounds: 0.05 ≤ iv ≤ 2.0
  - Monthly-expiry preference (3rd Friday) over weeklies
  - Near-ATM delta filter 0.30-0.70 for ATM IV (rejects deep-ITM artifacts)
  - Two-call corroboration required (≥ 2 ATM calls must invert)
  - FAST_FAIL_MISSES = 5 early termination on empty dates

Plan tier: Options Starter (15-min delayed snapshots, 2-year historical, unlimited rate).

IV_COLS structure:
  IV_FEATURE_COLS = [atm_iv_30d, iv_skew_25d, term_structure]   ← ML features
  IV_META_COLS    = [atm_strike, atm_expiry, atm_dte, put_call_oi_ratio]
                                                                ← always excluded
  IV_COLS = IV_FEATURE_COLS + IV_META_COLS                       ← full list

Current backfill state (post-S24, 2026-05-28):
  AMD   462 rows since 2024-05-28  ✓ complete (RESTORED — S24)
  NVDA  452 rows since 2024-06-10  ✓ complete (S23)
  SOFI    no atm_iv_30d col        ✗ HISTORY WIPED (was 498; re-backfill required)
  LYFT    1 row                    ✗ HISTORY WIPED (was 439; re-backfill required)
  QQQ     1 row                    ✗ HISTORY WIPED (was 318; re-backfill required)
  AAPL    NO CSV                   ✗ MISSING (was 180 partial; needs indicators.py + backfill)
  Probable cause: indicators.py harvest_iv_snapshot had a destructive merge
  path when START_DATE was narrowed (rows in prior CSV outside the new
  range were silently dropped on save). Fixed in S23. Pre-fix runs may
  have wiped these backfills if user ever entered a recent START_DATE.

────────────────────────────────────────────────────────────────────────

Econ Calendar Integration
-------------------------

New module 2026-05-18 (modules/econ_calendar.py) — forward-looking macro
release proximity features. Addresses the Geopolitical/Exogenous Shock
Limitation noted below: lets models position around scheduled FOMC/CPI/NFP/
PCE releases that pure price-history features can't see coming.

Data source: FRED API (https://api.stlouisfed.org/fred). Free key required;
read from $env:FRED_API_KEY. Endpoint release/dates with
include_release_dates_with_no_data=true returns the forward calendar.

Schema (modules/econ_calendar.csv):
  series,date,release_id,release_name,tier

Tracked series:
  Tier 1: FOMC, CPI, NFP, PCE
  Tier 2: PPI, GDP, Retail, JOLTS, Claims

Feature columns added by add_macro_event_proximity(df, data_dir, for_direction):
  Days_to_FOMC, Days_to_CPI, Days_to_NFP, Days_to_PCE,
  Days_to_PPI,  Days_to_GDP, Days_to_Retail, Days_to_JOLTS, Days_to_Claims,
  Days_to_macro  (aggregate min across all series)

All values are integer, bounded [0, 90]. Sentinel 90 fills missing CSV /
no future event found. for_direction kwarg reserved for future use
(signature symmetry with add_catalyst_proximity); ignored in v1.

CLI: gated by --econ-features flag in entry/direction/volatility/exit/
backtest (default OFF — REJECTED by S20 A/B validation, see below).
calibrate_multipliers.py has a module-level ECON_FEATURES = False constant
(no argparse) so vol-multiplier calibration matches the production feature
set by default.

A/B validation REJECTED (2026-05-18) — same pattern as S11 calibration:
                       Baseline           --econ-features      Δ
  QQQ STRONG ENTRY 15d  570 / 1.8% / 64%   515 / 1.7% / 64%    -0.1pp avg
  QQQ STRONG ENTRY 6mo  +9.5% / 76.7%      +9.4% / 77.1%       ~flat
  QQQ LEAPS ONLY 6mo    +7.4% / 69.4%      +6.4% / 68.4%       -1.0pp ◄ now below ALL DAYS
  NVDA STRONG ENTRY 15d 355 / 2.9% / 59%   273 / -0.1% / 54%   -3.0pp ◄ destroyed
  NVDA STRONG ENTRY 6mo +33.4% / 71%       +13.6% / 60%        -19.8pp ◄ catastrophic
  NVDA hierarchy        STRONG > CAUTION   STRONG is WORST     BROKEN
Root cause: adding 10 feature cols (~33% inflation on ~30-base set) compresses
the high-confidence tail where individual-stock edge concentrates. Index ETFs
(QQQ) absorb this marginally; individual stocks (NVDA) catastrophically lose
discrimination. Identical to S11 isotonic calibration regression.
Feature retained as opt-in flag. Future experiments may revisit with smaller
feature subset (e.g. Tier 1 only: 4 cols + aggregate = 5) or richer transforms
(actual values, surprise data) — but not before backtest re-validates.

FOMC release_id=101 was unusable — FRED returns every weekday as a "press
release" date (3896 total entries). Switched to a hardcoded FOMC_MEETING_DATES
constant in econ_calendar.py with 48 dates (2022-2027) curated from
federalreserve.gov/monetarypolicy/fomccalendars.htm. Annual maintenance
(update each November when Fed publishes next 2 years' calendar).

Refresh cadence: weekly. Run:
  python -m modules.econ_calendar --refresh

Verify release IDs (one-time, before first refresh):
  python -m modules.econ_calendar --list-releases

Daily-use display CLI (S22):
  python -m modules.econ_calendar --upcoming        # next 7 days
  python -m modules.econ_calendar --upcoming 14     # next 14 days

Display helpers used by entry.py (S22, both in modules/econ_calendar.py):
  next_event_per_series(as_of=None, data_dir="modules")
    → {series_name: (date | None, days_to | SENTINEL_DAYS)} for all 9 series
  upcoming_events(within_days=7, as_of=None, data_dir="modules")
    → DataFrame sorted by date with columns date / weekday / days_to / tier /
      series / release_name; empty df if no events or CSV missing

Failure modes (graceful — mirror catalyst pattern):
  FRED_API_KEY unset + --refresh   → RuntimeError, no partial write
  FRED_API_KEY unset + pipeline    → no-op (CSV read only; no key needed)
  CSV missing                      → fill all Days_to_* with 90, warn
  CSV staleness (< 30d forward)    → per-series warning, no fail

Scope decisions (v1):
- Proximity features only. Historical values (CPI YoY, NFP delta) and
  surprise data (actual vs consensus) deferred — values introduce
  as-of dating complexity; surprise data needs paid feed.
- No per-ticker neutralization (no equivalent to EVENT_DRIVEN_TICKERS
  for macro). The CRSP biotech case doesn't generalize — macro events
  affect all tickers similarly.

Smoke tests (tests/test_smoke.py) extended from 5 to 8:
  test_econ_calendar_loads         module import + ECON_FEATURE_COLS shape
  test_days_to_next_bounds         synthetic CSV via tmp_path; all cols
                                   integer-valued, bounded [0, 90]
  test_days_to_specific_event      FOMC 2026-06-18; row 2026-06-11 →
                                   Days_to_FOMC == 7

────────────────────────────────────────────────────────────────────────

Geopolitical / Exogenous Shock Limitation
-----------------------------------------

The framework is reactive, not predictive, of exogenous shocks. All inputs
are derived from price/volume/HV history; the model cannot detect geopolitical
events before they affect prices. Phase 3 classification report directly
evidences this:

  Contraction precision ~79%   (calm regimes mean-revert reliably)
  Expansion precision   ~64%   (shocks structurally unlearnable from price history)

Key tells during stress:
- IV/HV gap encodes information the model can't see (e.g. QQQ on 2026-05-07:
  HV 14.2% but IV 22-26% → 60-80% premium; that gap IS the options market
  pricing in tail risk Phase 3 doesn't pick up)
- Term structure > 1.05 (backwardation) signals near-term stress
- 25Δ skew elevation signals tail-risk hedging demand
- VIX9D_VIX_ratio + VIX_VIX3M_ratio = market-wide near-term fear proxy

During known crises: trust contraction signals less; weight options-market-implied
tail risk higher than Phase 3 output; don't size like the SHORT-TERM ONLY
backtest avg (those windows don't include "Iran-war-2026" type events).

S21 result: a VIX-state regime gate (binary one-tier-down on stress) does NOT
mitigate this limitation — it actively hurts edge.  Direction-model STRONG ENTRYs
in stress regime are above-average buys, not below-average (mean-reversion edge
that the price-action lens already encodes).  The limitation remains: the framework
is reactive, not predictive, of shocks.  Mitigation is HUMAN — don't size like the
backtest avg during known crises; use IV/HV gap + skew + term structure as
options-market-implied tail risk read.

────────────────────────────────────────────────────────────────────────

Outstanding Work
----------------

Active TODO
- ~~Run backfill_iv.py on NVDA~~  ✓ DONE in S23 (452 rows)
- ~~After NVDA backfill: retrain Phase 3 with --iv-features~~  DONE S23, but the
  "+2.3pp" was a LEAK ARTIFACT (corrected S24 — clean delta +0.6pp / noise).
- Re-backfill SOFI/LYFT/QQQ (history wiped pre-S23; indicators.py bug fixed S23
  so safe to redo). ~15-25 min per ticker. (AMD ✓ RESTORED S24, 462 rows.)
- Re-create AAPL indicators CSV + backfill (CSV missing entirely)
- ~~Re-run AMD backtest with P2B=0.55~~  ✓ DONE S24 (new HV baseline 383/3.4%/33.9%).
- ~~Promote --iv-features to default ON?~~  RESOLVED S24: NO. After fixing the Phase 2/2B
  leak, clean A/B shows no edge on either real-IV ticker (AMD 6mo -2.0pp, NVDA +0.6pp).
  Keep opt-in, default OFF. The prior "2/2 validated" rested on the leak (NVDA) + a
  Phase-3-precision metric that doesn't move returns (QQQ).
- ~~Cross-ticker decile diagnostic on AMD~~  ✓ DONE S24: NVDA's mid-confidence sweet
  spot does NOT generalize (AMD is horizon-split). LYFT still pending re-backfill.
- ~~A/B backtest validation for --econ-features~~ COMPLETED 2026-05-18 (S20):
- ~~A/B backtest validation for --econ-features~~ COMPLETED 2026-05-18 (S20):
  REJECTED. QQQ marginal pass (STRONG ENTRY 1.8% → 1.7%); NVDA catastrophic
  (STRONG ENTRY 2.9% → -0.1%, hierarchy inverted). Same S11 pattern. Flag
  retained opt-in; default OFF. See Econ Calendar Integration section above.
- ~~Regime detection layer~~ SHIPPED + REJECTED 2026-05-18 (S21) as modules/regime.py
  + --regime-gate flag. Rule-based VIX bands, one-tier-down on stress. Cross-ticker
  REJECT (QQQ + NVDA + AMD all 4/4 criteria fail). Core finding: stress regime is
  a CONTRARIAN BUY signal, not a sell signal — gate removes highest-return entries
  (NVDA stress-regime STRONG ENTRYs +42% 6mo avg). Flag retained opt-in; default OFF.
  See S21 session log for details. Surgical CAUTION-only variant deferred to future
  experiment.
- Phase 4 / exit.py follow-ups:
  - Co-validate on AMD + SOFI before treating 15d as universal default
    for exit.py output. AMD's vol scale (4.98% WIN_THRESHOLD vs QQQ
    1.82%) may favor 5d.
  - Option B (P4 gate) REJECTED by S18 backtest validation — keep code
    behind --p4-gate flag (default OFF). Future experiments:
    * Shorter gate window (5d) to avoid filtering 15d-wobble winners
    * Compound gate (require BOTH P4 + IV/HV to fire) — stricter trigger
    * Per-ticker gate enablement (NVDA showed +0.48pp on STRONG ENTRY,
      borderline on sample size; AMD/SOFI unknown)
  - Tune P4_VOL_MULTIPLE = 1.0 starting point via per-ticker calibration
    sweep (analogous to MULTIPLIER_SWEEP in backtest.py).
  - Option C (held-position mode) deferred — needs position-state features
    (days held, current unrealized P&L) not present in framework today.

Backlog (prioritized by leverage)

1. ~~Exit-signal model~~  SHIPPED 2026-05-13 (S18) as Phase 4 / exit.py.
   Target: max drawdown over N days <= -(P4_VOL_MULTIPLE × σ × sqrt(N/252))
   with P4_VOL_MULTIPLE = 1.0. Trains 3 candidate windows (5d/15d/63d) per
   ticker, ships winner. QQQ best at 15d (+17.7pp edge), NVDA best at 5d
   (+19.7pp); 63d collapses on individual stocks (NVDA -20.7pp tail inversion)
   and is excluded from production. 15d is the framework default — symmetric
   with Phase 2 entry window. Not yet integrated into entry.py SIGNAL output.

2. Regime detection layer (HMM / change-point / VIX regime tagging)
   ~~PARTIAL SHIPPED 2026-05-18 (S21)~~ — rule-based VIX bands gate REJECTED across
   QQQ + NVDA + AMD.  Stress regime turns out to be a contrarian BUY signal in this
   framework's price-action lens (direction models firing bullishly in high-VIX are
   catching mean-reversion bottoms).  The original hypothesis ("downweight signals
   in stress regimes") was inverted by the data.
   Remaining variants worth trying:
   - Surgical CAUTION-only gate (only CONTRACTION-flavored signal is downgraded;
     STRONG ENTRY untouched) — matches the original "downweight contraction signals"
     wording more literally.
   - Regime as confidence multiplier (raise P2_THRESHOLD in stress) rather than
     binary downgrade.
   - HMM / change-point may surface latent regimes not captured by VIX-band rules.

3. Net-of-cost backtest returns (gross numbers eat ~0.3-0.8pp on 6-12mo options)
   All backtest numbers are gross. Bid-ask + commissions eat ~0.3-0.8pp per
   round trip on long-dated options. QQQ STRONG ENTRY 1.9% → ~1.4% net;
   CAUTION 1.2% likely drops below STAY OUT after costs. Doesn't change
   signal hierarchy but changes sizing + marginal cases (SHORT-TERM ONLY
   especially). Implementation is mechanical in backtest.py:summarize().

4. Portfolio-level context (correlated exposure, sector concentration)
   Models score tickers in isolation. Simultaneous STRONG ENTRY on AMD+NVDA
   is one concentrated semi bet, not two independent ones. Needs correlation
   matrix + sector exposure tracking. Output: max-position-size multiplier
   on top of FULL/REDUCED bins. No new alpha — caps drawdown when correlated
   signals cluster.

5. Kelly-style continuous sizing (vs current FULL/REDUCED bins)
   Sizing is binary today; LogReg returns continuous probabilities. 0.62 vs
   0.84 both clear 0.55 but have very different expected edge. Kelly =
   (edge/variance) off predicted prob extracts more from high-confidence
   tail (where NVDA edge lives — see S11). Risk: Kelly is aggressive on
   noisy probabilities; half-Kelly / fractional safer.

6. ~~Smoke-test layer~~  SHIPPED 2026-05-14 (S19) as tests/test_smoke.py.
   5 pytest tests: signal hierarchy (backtest CSV), STRONG ENTRY baseline
   sanity (count/return/win-rate), vol thresholds range, signal logic unit
   test via determine_signal() helper, S16 threshold-sensitivity guard.
   Run: .\trade\Scripts\python.exe -m pytest tests/ -v  (~1-2s, no network).

7. Short interest ratio (FINRA monthly) — squeeze-setup detection
   New feature, not structural change. Monthly FINRA SI captures squeeze
   setups (rapid buildup) that price/vol features miss. AMD/NVDA/SOFI/RIVN
   tier — high-beta individual stocks where short-squeeze moves are common
   and currently invisible. Monthly cadence, individual-stocks only.

8. Earnings estimate revisions — individual-stock alpha
   Framework has Days_to_earnings but not whether Street is revising up/down.
   Revision momentum is durable individual-stock alpha. Data acquisition is
   the bulk of the work: yfinance doesn't expose this; needs paid feed
   (FactSet/Zacks) or scraping. Lowest priority for that reason.

9. Trump-regime / tweet-policy feature — exogenous shock proxy
   Hypothesis: the Trump administration (terms 2017-01-20 to 2021-01-20 and
   2025-01-20 onward) has documented unique market effects — tariff
   announcements, social-media-driven moves, executive-action volatility.
   The framework currently can't see any of this (price/vol features are
   reactive). Adding a feature could partially address the Geopolitical /
   Exogenous Shock Limitation below.
   Feature variants (cheapest → most expensive):
     - Binary "Trump-regime active" flag — trivial; date lookup. Captures
       regime effect without per-event signal. ~21% of NVDA history covered.
     - Days-since-last-tariff-announcement — needs curated event list
       (~50 dates 2017-2026). Manual maintenance like FOMC_MEETING_DATES.
     - Tweet/post sentiment or topic tags — needs Twitter archive + Truth
       Social data + NLP pipeline. Significant data-acquisition cost.
     - Policy-uncertainty index (e.g. Baker-Bloom-Davis EPU) — existing
       academic series, may already partially capture this; check FRED.
   Framework discipline: this is a new feature → same A/B validation
   bar as S11/S20/S21 (cross-ticker QQQ + NVDA minimum, default OFF
   until validated). Risk profile is similar to --econ-features
   (S20 REJECTED): adding date-proximity-style features can compress
   the high-confidence tail. Suggested start: binary regime flag only
   (1 column, lowest feature inflation), backtest on QQQ + NVDA.
   If hierarchy holds, escalate to event-proximity. NLP-derived features
   deferred until simpler variants prove out.
   Reference: see Geopolitical / Exogenous Shock Limitation section
   for the framework's current treatment of exogenous shocks (human
   judgement layer, not model feature).

Won't Fix / Structural Limits
- Binary event direction (FDA decisions, trial readouts) — direction unknowable
  from price/volume features
- Geopolitical shocks — see Geopolitical Risk Limitation
- SPY edge — broad-market efficiency dampens framework lens below noise threshold
- Decision 2 (Platt scaling on Phase 2B) — DEPRIORITIZED. D1 fails on
  individual stocks; Phase 2B's signal lives in similar high-confidence tail
  that Platt would still regularize toward the mean.

────────────────────────────────────────────────────────────────────────

Known Issues
------------
- modules/tradier.py: TRADIER_TOKEN reads $env:TRADIER_TOKEN if set, else
  hardcoded fallback. Set the env var to keep token out of git.

Recently Fixed (S24)
- Phase 2/2B IV-INDICATOR LEAK (latent since S13's impute_iv_features). impute_iv_features
  adds binary cols iv_available/term_available; these are NOT in IV_COLS, so train_model's
  Phase 2/2B exclude set (IV_META_COLS if use_iv_features else IV_COLS) did not drop them —
  they leaked into Phase 2 AND Phase 2B feature sets whenever --iv-features was on. Effect:
  --iv-features silently perturbed all three phases (not just Phase 3), confounding EVERY
  --iv-features A/B (S13 QQQ, S23 NVDA). Detected via: LEAPS ONLY count changed between HV
  and iv arms (976→884 on AMD) even though Phase 3 only modulates STRONG↔CAUTION. Fix: new
  IV_INDICATOR_COLS constant (modules/massive.py); exclude = IV_META_COLS if use_iv_features
  else IV_COLS + IV_INDICATOR_COLS (backtest.py:213, entry.py:161). Phase 3 keeps the
  indicators; Phase 2/2B/4 drop them. HV-proxy mode unaffected (no-op — impute never runs).
  13/13 smoke pass. Verified: post-fix LEAPS/SHORT/STAY counts identical HV vs iv (QQQ+NVDA
  exact, AMD ±2 solver noise).

Recently Fixed (S23)
- backtest.py run_backtest(): per-window threshold recalibration used the
  imported P2/P2B/P3_VOL_MULTIPLE constants regardless of MULTIPLIER_SWEEP
  iteration values. Latent since S13. Any prior sweep silently returned
  identical results. Fix: thread multipliers as kwargs through run_backtest;
  default to production constants. Single-config runs (sweep empty) were
  unaffected.
- indicators.py harvest_iv_snapshot(): merge only operated on the
  intersection of df.index and prior.index. Rows in prior outside the
  new df range were silently dropped, then df.to_csv() overwrote the
  whole file. Triggered when user entered a narrowed START_DATE — wiped
  pre-START_DATE IV history. Fix: preserve prior rows outside df range
  via pd.concat before merge. Default behavior (START_DATE="1792-05-17")
  unaffected.

────────────────────────────────────────────────────────────────────────

Operational Notes
-----------------
- Use trade venv python explicitly: .\trade\Scripts\python.exe -X utf8 script.py
  (Claude Code's shell doesn't inherit venv activation)
- On Windows: PowerShell tool (NOT Bash) for piped script execution. Pattern:
    cmd /c "(echo TICKER && echo.) | python -X utf8 script.py" 2>&1
  (Bash drops Python stdout from cmd /c subprocesses)
- $env:MASSIVE_API_KEY does NOT persist across PowerShell sessions. Add to
  $PROFILE for permanence (after key restoration).
- data/ directory must exist before running any script
- modules/ contains shared code (benchmarks, features, massive, tradier,
  bs_invert) + catalysts.csv
- memory/ subdirectory is Claude's auto-memory system
- backtest.py is SELF-CONTAINED relative to direction.py / volatility.py
  (only imports from modules.features). Feature changes outside features.py
  must be manually mirrored.
- CLI flags: --calibrate (Phase 2 isotonic), --iv-features (Phase 3 real IV);
  both default OFF, available on direction/entry/backtest.
- Smoke tests: .\trade\Scripts\python.exe -m pytest tests/ -v
  Requires data/QQQ_indicators.csv + data/QQQ_backtest_results.csv.
  pytest installed in venv (S19); not in requirements.txt.
- iv_log.csv (S8 deprecated): preserved on disk as historical record but
  no new writes. IV history lives in indicators CSV.
- Catalyst CSV: data/catalysts.csv must have no commas in description field
  (use dashes instead) — pandas reads ragged CSV otherwise.
- ETFs (QQQ): no earnings dates from yfinance; Days_to_earnings defaults to
  45 (neutral). "May be delisted" yfinance warning is harmless.

────────────────────────────────────────────────────────────────────────

Tech Stack
----------
yfinance, pandas, numpy, ta, matplotlib, scikit-learn (LogisticRegression,
StandardScaler, precision_score, CalibratedClassifierCV, brier_score_loss),
lxml (earnings dates), requests (Tradier + Massive APIs)

Tradier Config (modules/tradier.py + sizing.py)
- TRADIER_TOKEN: $env:TRADIER_TOKEN if set, else hardcoded fallback (S8)
- MIN_DTE = 180, MAX_DTE = 365 (6-12 month expiries) — sizing.py default
- DEFAULT_STRIKE_RANGE = 10 strikes above/below ATM
- IV source: smv_vol (smoothed model vol — matches Tradier app display)

────────────────────────────────────────────────────────────────────────

Recent Session Log
------------------

S24 (2026-05-28) — AMD re-backfill validation → Phase 2/2B IV-indicator LEAK found+fixed
                   → --iv-features promotion case REVERSED (no clean edge)
1. User restored AMD IV backfill: 462 rows (2024-05-28 to 2026-05-28), matches pre-loss 459.
   Verified: atm_iv_30d/iv_skew_25d 462 nonnull, term_structure 423.
2. Ran AMD --iv-features backtest A/B (planned 3rd cross-ticker promotion check). Pre-fix it
   looked like a mild FAIL (STRONG 15d 3.4→2.8%, 6mo 33.9→32.2%, LEAPS 6mo dropped below STAY OUT).
3. LEAK FOUND. Phase 3 only modulates STRONG↔CAUTION, so LEAPS/STAY counts MUST be invariant
   between HV and iv arms if --iv-features is Phase-3-only. They weren't (AMD LEAPS 976→884).
   Cause: impute_iv_features() adds iv_available/term_available; not in IV_COLS, so train_model's
   Phase 2/2B exclude (IV_META_COLS if use_iv_features else IV_COLS) didn't drop them → leaked
   into Phase 2 AND 2B. --iv-features was perturbing all 3 phases, confounding every prior A/B.
4. FIX: IV_INDICATOR_COLS=[iv_available,term_available] in modules/massive.py; exclude →
   IV_META_COLS if use_iv_features else IV_COLS+IV_INDICATOR_COLS (backtest.py:213, entry.py:161).
   Phase 3 keeps indicators; Phase 2/2B/4 drop them. HV mode unaffected (no-op, impute never runs).
   13/13 smoke pass. Verified: post-fix LEAPS/SHORT/STAY identical HV vs iv (QQQ+NVDA exact,
   AMD ±2 solver noise; two HV runs also differ ±2).
5. CLEAN cross-ticker A/B (same session, post-fix). STRONG ENTRY HV→--iv-features:
     QQQ:  15d 1.7→1.8% (+0.1) | 6mo 9.6→9.6%  (0.0)  | cnt 574→587   [only 1 real IV row →
                                                          imputed-only, NOT a real-IV test]
     NVDA: 15d 2.8→2.9% (+0.1) | 6mo 33.3→33.9% (+0.6) | cnt 355→355   [452 real IV rows]
     AMD:  15d 3.4→2.8% (-0.6) | 6mo 33.9→31.9% (-2.0) | cnt 383→370   [462 real IV rows]
   VERDICT: on the two tickers with real IV (AMD, NVDA), --iv-features has NO clean edge
   (all deltas within noise). Promotion to default ON → NO. Stays opt-in.
6. S23 NVDA "+2.3pp / first feature to pass" was a LEAK ARTIFACT. Pre-fix selected a different
   318-signal subset (vs HV 355) via the Phase 2/2B perturbation; post-fix count returns to 355
   and clean 6mo delta is +0.6pp (noise). S13 QQQ "+0.8pp Phase 3 precision" is Phase-3-internal
   (not leak-confounded) and stands, but is a classification metric — no STRONG-ENTRY return edge.
7. Reconciliation: entry.py single recent split showed real IV lifting Phase 3 TEST PRECISION
   +8pp on AMD (52.7→60.7%). Real IV sharpens Phase 3 classification but doesn't move STRONG
   ENTRY returns (Phase 3 only sizes STRONG vs CAUTION; that re-sort ≠ P&L edge vs HV proxy).
8. New AMD HV production baseline (post-S17, P2B=0.55, 91 windows) — see Current Backtest
   Baselines (replaces stale pre-S17 table). Clean hierarchy, STRONG best both horizons.
   P4 gate + VIX regime gate both REJECT again (P4 -0.40pp; VIX -1.38pp / cnt 276 < 300).
9. AMD decile (probability_deciles.py, HV proxy): NVDA's mid-confidence sweet spot does NOT
   generalize. AMD horizon-split: 15d edge RISES with confidence (0.75+ +9.0%, opposite of
   NVDA tail inversion); 6mo edge FALLS (0.55-0.60 +40.2%, tail +25.2%). Third distinct shape.
10. Process: the AMD backfill did its job — surfaced a leak latent since S13 that had silently
    confounded EVERY --iv-features A/B. "LEAPS/STAY counts must be invariant under --iv-features"
    is now a reusable diagnostic. 5th time the default-OFF-then-validate discipline paid off —
    here it caught a contaminated PASS (S23 NVDA), not a fail.

S23 (2026-05-26 / 2026-05-27) — NVDA backfill, multiplier sweep bug, --iv-features
                                validation, probability-decile diagnostic
1. NVDA backfill completed: 452 IV rows since 2024-06-10 (~90% of plan limit).
   Closes the long-standing active TODO from S12. Backfill ran ~25 min while
   other work proceeded in parallel.
2. CRITICAL BUG found + fixed: backtest.py run_backtest() per-window threshold
   recalibration (line 267) always used the imported P2/P2B/P3_VOL_MULTIPLE
   constants regardless of MULTIPLIER_SWEEP iteration values. Latent since
   S13's per-window recalibration. Symptom: 5 consecutive identical sweep
   results before catching it. Fix: thread p2_mult/p2b_mult/p3_mult kwargs
   through run_backtest with production fallbacks. Sweep call site (line 773)
   updated. Single-config runs were always correct (use imported constants).
   S17's P2B=0.55 selection was unaffected (single-config validation).
3. First VALID NVDA P2B multiplier sweep (13 values, P2B 0.25-1.45 step 0.10,
   P2=0.41 + P3=0.20 fixed):
     P2B   Count   15d Avg   6mo Avg
     0.25  350     +3.0%     +34.4%
     0.35  352     +3.5%     +34.5%
     0.45  357     +3.4%     +34.7%  ◄ nominal best
     0.55  355     +2.8%     +33.3%  ◄ production
     0.65  337     +2.7%     +34.2%
     0.85  307     +2.9%     +32.9%
     0.95  278     +2.4%     +30.0%
     1.45  216     +0.1%     +26.9%
   Conclusion: production 0.55 is approximately optimal. Wide flat zone
   0.25-0.85 on 6mo edge (32.9-34.7%). Nominal P2B=0.45 improvement
   (+1.4pp 6mo) within ~1 SE on n=357. Past 0.95 degrades materially.
   No change to production. MULTIPLIER_SWEEP reverted to [] with values
   preserved as commented reference for future re-runs.
4. NVDA --iv-features VALIDATED (closes context.md TODO):
                          HV proxy    --iv-features    Δ
     STRONG ENTRY 15d cnt   355         318            -10%
     STRONG ENTRY 15d avg   +2.8%       +3.0%          +0.2pp
     STRONG ENTRY 6mo avg   +33.3%      +35.6%         +2.3pp  ◄ real
     STRONG ENTRY 6mo win   71.2%       71.2%          0pp
     Hierarchy 6mo          STRONG > STAY OUT          intact (gap +8.5pp)
   This is the FIRST feature-addition experiment to PASS the NVDA test
   (S11 calibrate, S20 econ-features, S21 regime-gate all FAILED on NVDA).
   With QQQ already at +0.8pp Phase 3 precision, this is the second
   confirming ticker — close to the threshold for promoting --iv-features
   to default ON, pending one more cross-ticker check.
5. Bug + fix in indicators.py harvest_iv_snapshot:
   - Pre-fix: merge operated on df.index.intersection(prior.index) only.
     Rows in prior outside df range were silently dropped. Then df.to_csv
     overwrote whole file. User running indicators.py with a narrowed
     START_DATE would lose all pre-START_DATE IV history permanently.
   - Fix (lines 322-329): preserve outside-range rows via concat before
     merge, with a one-line "Preserving N prior rows outside current
     range" notice. Default behavior (START_DATE="1792-05-17") unaffected.
6. IV backfill data loss DISCOVERED. Pre-S23 context.md claimed:
     AMD 459 / SOFI 498 / LYFT 439 / QQQ 318 / AAPL 180 partial / NVDA 2
   Actual disk state in S23:
     AMD 2 / SOFI no col / LYFT 1 / QQQ 1 / AAPL no CSV / NVDA 452
   All prior backfills are gone except NVDA's (which we just ran). Probable
   cause: the indicators.py bug above wiped history when user ran indicators
   with a narrowed START_DATE at some point. Bug now fixed; re-backfills
   are safe.
7. probability_deciles.py — new analysis tool. Pure analysis on existing
   backtest_results.csv. Buckets STRONG ENTRY signals by P2 (15d direction)
   probability and reports count / 15d avg / 15d win / 6mo avg / 6mo win
   per bucket. Surfaced a major finding:
     NVDA STRONG ENTRY by P2 prob:
       0.55-0.60   95   +2.7%   +45.1% 6mo
       0.60-0.65   88   +7.1%   +46.7% 6mo  ◄ best mid
       0.65-0.70   52   +5.5%   +45.2% 6mo
       0.70-0.75   18   -8.9%   -4.2%  6mo  ◄ inverted
       0.75+       65   -0.7%   +11.2% 6mo  ◄ inverted
     Tail (≥0.70) vs base (<0.65): -7.2pp 15d, -38pp 6mo
     QQQ: modest U-shape, tail +2.9pp 15d (conventional pattern, weak)
   This CONTRADICTS the framework's edge-in-tail theory for individual
   stocks. NVDA's edge concentrates in the MID-confidence range, not
   the tail. The S11 calibration regression mechanism is now uncertain
   (cannot be "compressed extremes" if no high-confidence edge exists).
8. probability_diagnostics.py — second new analysis tool. Tests 4 hypotheses
   on why NVDA's 0.75+ bucket inverts:
     H1 (time clustering): REJECTED. 0.75+ in 2008/2018/2022 drawdown
        years = 15% vs base 25%. Not clustered in known bad markets.
     H2 (walk-forward window): CONFIRMED. 0.75+ mean window 15.2, only
        6% from window ≥40. Base bucket mean 39.5, 70% from window ≥40.
     H3 (multi-phase filter degradation): REJECTED INVERTED. P2B/P3
        confidence is HIGHER at 0.75+ (P2B 0.877 vs 0.717; P3 0.800
        vs 0.724). Filters are firing harder, not failing.
     H4 (mean reversion): CONFIRMED but INVERTED from hypothesis.
        0.75+ signals fire after 20d MEAN of -16.4% (post-drawdown).
        Base fires after +0.7% (neutral). Model is catching dip setups.
   Mechanism: the model learned a strong "post-drop recovery" pattern
   from training data (likely dominated by 2009 GFC recovery) and over-
   applies it confidently to subsequent dip setups. Breakdown by year:
     2002: 31 of 65 0.75+ signals (48%) — small training set, overfit
     2008: 10 signals — model just had 2008 in training
     2011: 19 signals — ~12 years training data, NOT data-poor; learned
           rule over-application after 2009 example
   Conclusion: the model isn't "fundamentally broken" but carries strong
   learned priors from rare events. Not pure early-window overfitting.
9. MIN_TRAIN_DAYS=504 test — NULL RESULT, reverted. Hypothesis was that
   raising the minimum training window from 1 to 2 years would cut the
   0.75+ overfit signals. Reality: NVDA's first STRONG ENTRY was 2002-02-05
   (~3 years into history, well past either cutoff). Dropping windows
   1-2 dropped zero signals. Bucket counts essentially unchanged
   (95/88/52/18/65 → 96/87/52/18/65). The 0.75+ signals come from windows
   that exist at both 252 and 504 settings.
   To actually eliminate them, would need either:
     - MIN_TRAIN_DAYS ~3000 (drops 2002 cohort but not 2008+2011)
     - Rolling fixed-window (limits learned-rule memory; complex change)
     - Direct cap dir_prob < 0.70 (surgical fix at the symptom level)
10. Sweep infrastructure improvements (kept post-revert):
    - run_backtest(df_full, p2_mult=None, p2b_mult=None, p3_mult=None)
      — accepts per-call multipliers with production fallbacks
    - collect_signal_stats now collects 6mo (fwd_return_126d) stats
    - sweep CSV write includes avg_return_126d and win_rate_126d cols
11. New analysis scripts (no production behavior change):
    - probability_deciles.py — bucket STRONG ENTRY by P2 prob
    - probability_diagnostics.py — 4-hypothesis investigation
   Both pure-analytical, no model retrain required. Run on existing
   data/{ticker}_backtest_results.csv.
12. Open questions for future sessions:
    - Does NVDA's mid-confidence sweet spot replicate on AMD/LYFT?
      (requires re-backfill first)
    - Is the dir_prob < 0.70 cap worth implementing as a per-ticker rule?
      Would cut 83 historical NVDA signals; mature-model impact ~zero
      (current model rarely fires 0.75+).
    - What's the real S11 mechanism if not "compressed extremes"?
    - Should --iv-features be promoted to default ON given 2/2 validation?

S22 (2026-05-18) — Econ Calendar Display Surfaces (no model wiring)
1. Motivated by the S21 analysis: "information that fails as a model feature can
   still be valuable as human-decision context."  Econ proximity was rejected as
   a feature (S20) but the user wants the same data as a daily visual under
   entry.py and as a standalone CLI shortcut.  No backtest / model changes.
2. Two new public helpers in modules/econ_calendar.py (after _load_cache, before
   _check_staleness):
   - `next_event_per_series(as_of=None, data_dir="modules")` returns
     `{series_name: (date | None, days_to | SENTINEL_DAYS)}` for every series in
     ALL_SERIES.  Used by entry.py.  Missing CSV: all 9 entries fall back to
     `(None, SENTINEL_DAYS)`.
   - `upcoming_events(within_days=7, as_of=None, data_dir="modules")` returns a
     DataFrame of upcoming events sorted by date, with columns date / weekday /
     days_to / tier / series / release_name.  Used by the CLI.
3. New CLI flag: `python -m modules.econ_calendar --upcoming [N]` (default 7).
   `nargs="?", const=7, type=int` so bare `--upcoming` = 7 days, `--upcoming 14`
   overrides. Prints chronological table with weekday + tier marker.  Verified
   today (2026-05-18) shows Claims (3d) in 7-day window; Claims + GDP + PCE in
   14-day window.
4. entry.py display: 9 new lines under the existing "Days to Catalyst" line in
   `print_combined_signal`, format `Days to {series}:   {days}d   ({YYYY-MM-DD})`.
   Always rendered (no flag) — pure display, no model wiring.  Falls back to
   "N/A" if a series has no future event or CSV missing.
5. Smoke tests extended 11 → 13 (tests/test_smoke.py):
   - test_next_event_per_series_shape — synthetic CSV with FOMC + CPI; verifies
     shape (9 entries), known events return correct (date, days), missing series
     fall back to (None, SENTINEL_DAYS), missing-CSV path returns all-None.
   - test_upcoming_events_window_filter — three events at +3d/+10d/+25d; verifies
     within_days correctly bounds the result, sort order, column population,
     missing-CSV returns empty DataFrame.
6. NOT changed: add_macro_event_proximity, the `--econ-features` flag/constant in
   any consumer, or any model behavior.  S20 rejection still stands; display path
   is independent.
7. Visual verification (QQQ, 2026-05-18) — 9 lines render correctly under the
   DIRECTION block of `entry.py` output, aligned with existing earnings/catalyst
   format.  No `--econ-features` flag required for the display path.

S21 (2026-05-18) — VIX Regime Gate Shipped + A/B REJECTED (4th rejection of the pattern)
1. New module: modules/regime.py (~95 lines). Rule-based VIX bands; no fitting,
   no model risk. Public surface:
   - REGIME_VIX_NORMAL=18.0, REGIME_VIX_STRESS=25.0, REGIME_TERM_STRESS=1.05
   - classify_regime(df) → Series of {'calm','normal','stress'} aligned to df.index
   - is_stress_regime(row) → scalar bool, used by entry.py display
   - apply_regime_gate(signal, sizing, regime) → one-tier-down on stress
     (STRONG ENTRY → CAUTION, CAUTION → STAY OUT, others unchanged)
2. Threshold calibration discovered a bug-adjacent issue: REGIME_TERM_STRESS=1.00
   initially fired on 38.2% of QQQ rows because modules/features.py:148-149 fills
   VIX_VIX3M_ratio NaN with sentinel 1.0 (VIX3M history only starts Dec 2007 — so
   2001-2007 had the sentinel triggering stress).  Bumped threshold to 1.05 (matches
   framework's existing "term > 1.05 = stress" convention in entry.py 5-band display).
   Post-fix stress frequency: QQQ 19.2%, NVDA 19.3%, AMD 19.8% (consistent — VIX is
   market-wide).
3. Wired into:
   - entry.py: --regime-gate flag (default OFF), gate applied AFTER IV/HV gate
     (composes one-tier-down: STRONG→CAUTION→STAY OUT possible if both fire),
     stress-tells display extended to fire on VIX/term whenever is_stress_regime
     returns True regardless of REGIME_GATE state (useful pre-opt-in diagnostic).
   - backtest.py: always-on A/B (matches P4 pattern, no flag needed).  New columns
     in results: 'regime' + 'signal_regime_gated'.  New summarize_regime_gate_ab()
     with explicit ACCEPT criteria (4 boxes, all must pass).
   - NOT wired into direction.py / volatility.py / exit.py / calibrate_multipliers.py
     — gate-only by design, never a training feature.
4. Smoke tests extended 8 → 11:
   - test_classify_regime_thresholds: synthetic VIX+term rows → expected labels
   - test_apply_regime_gate_logic: 5 signals × 3 regimes = 15 combos
   - test_classify_regime_handles_nan: missing VIX → 'normal' fallback, no exception
5. Cross-ticker A/B (post-1.05 threshold fix):
                          QQQ                NVDA               AMD
   Stress freq           19.2%              19.3%              19.8%
   STRONG ENTRY 15d
     ungated             1.77%              2.83%              3.36%
     gated               0.75%              2.26%              1.97%
     Δ                   -1.03pp            -0.57pp            -1.39pp
     gated count         314                231 (< 300)        277 (< 300)
   STRONG ENTRY 6mo
     ungated             9.5%               33.3%              33.9%
     gated               6.7%               28.6%              30.9%
     Δ                   -2.8pp             -4.7pp             -3.0pp
   Hierarchy intact?     NO                 NO                 NO
                         (gated CAUTION    (gated STAY OUT    (gated CAUTION
                          > gated STRONG)   > gated STRONG)    > gated STRONG)
   ACCEPT verdict        ✗ REJECT (4/4)     ✗ REJECT (4/4)     ✗ REJECT (4/4)
6. CORE FINDING: STRESS REGIME IS A CONTRARIAN BUY SIGNAL, NOT A SELL SIGNAL.
   Per-ticker, the STRONG ENTRYs that got downgraded in stress had FORWARD RETURNS
   ABOVE AVERAGE:
     QQQ:  261 downgrades, avg 15d +3.0%   (vs all-STRONG 1.8%)
     NVDA: 124 downgrades, avg 15d +3.9%, 6mo +42.0% (vs all-STRONG 33.3%)
     AMD:  107 downgrades, avg 15d +6.95%, 6mo +41.7% (vs all-STRONG 33.9%)
   Mechanism: direction models firing bullishly in high-VIX environments are often
   catching mean-reversion bottoms (post-shock recovery rallies).  Downgrading those
   signals removes the highest-return entries.  This is the opposite of the original
   hypothesis ("can't predict the shock but can know we're in stress regime") —
   the framework's price-action lens already encodes contrarian behavior; the VIX
   regime tag doesn't add information about which way prices are going next, only
   that vol is elevated.
7. Code retained as opt-in (--regime-gate flag, default OFF) per the S11/S18/S20
   precedent.  Future variants worth testing (deferred to user direction):
   - Surgical: only CAUTION → STAY OUT (matches context.md backlog wording
     "downweight CONTRACTION signals" — CAUTION is the contraction-flavored signal;
     STRONG ENTRY's expansion read in stress may be the contrarian buy).  Test
     before declaring the entire regime concept dead.
   - Regime as multiplier on confidence rather than binary gate (e.g. require higher
     P2_THRESHOLD in stress vs calm).
   - Pre-event positioning: gate triggers on imminent macro releases (Days_to_FOMC
     ≤ 1, etc.) rather than VIX state.  Different signal entirely.
8. Process: 4th time the default-OFF-then-validate discipline catches a regression
   (S11 calibrate, S18 p4-gate, S20 econ-features, S21 regime-gate).  Pattern is
   now load-bearing — any new feature/gate should ship behind a flag and require
   cross-ticker (QQQ + NVDA minimum) ACCEPT before becoming default.

S20 (2026-05-18) — Econ Calendar Module Shipped + A/B REJECTED
1. New module: modules/econ_calendar.py (~250 lines).
   - FRED API client. Reads FRED_API_KEY env var; refresh fails clearly if unset.
   - TIER1_SERIES = [(FOMC, 326, ...), (CPI, 10, ...), (NFP, 50, ...), (PCE, 21, ...)]
     TIER2_SERIES = [(PPI, 46, ...), (GDP, 53, ...), (Retail, 117, ...),
                     (JOLTS, 192, ...), (Claims, 32, ...)]
     Release IDs are best-guess from FRED docs — verify via --list-releases
     on first run before treating as canonical.
   - add_macro_event_proximity(df, data_dir="modules", for_direction=False)
     reads modules/econ_calendar.csv, computes Days_to_{name} for each series
     plus Days_to_macro aggregate (min across all). Sentinel SENTINEL_DAYS=90
     for missing CSV / no future event. Values bounded [0, 90], integer.
     for_direction kwarg reserved for future use (signature symmetry with
     add_catalyst_proximity); ignored in v1.
   - CLI: `python -m modules.econ_calendar --refresh` (weekly cadence) and
     `--list-releases` (one-time ID verification). Atomic write (tmp → rename).
2. Wired 6 consumer files with --econ-features flag (default OFF):
   entry.py, direction.py, volatility.py, exit.py, backtest.py,
   calibrate_multipliers.py (latter via module-level constant, no argparse).
   Insertion point in every script: immediately after add_catalyst_proximity,
   before normalize_features (same conceptual tier).
3. Smoke tests extended 5 → 8 (tests/test_smoke.py):
   - test_econ_calendar_loads: import + ECON_FEATURE_COLS shape sanity
   - test_days_to_next_bounds: synthetic CSV via tmp_path; all 10 Days_to_*
     cols integer-valued, bounded [0, 90]
   - test_days_to_specific_event: FOMC 2026-06-18; row 2026-06-11 →
     Days_to_FOMC == 7. End-to-end arithmetic check, no network.
   All 8 tests pass in ~1.2s. No-CSV path tested via tmp_path fixture.
4. CLI design (default-OFF opt-in flag) chosen per --iv-features /
   --calibrate / --p4-gate precedent. The framework has burned itself
   defaulting things ON before backtest validation (S11 calibration
   regression on NVDA, S18 P4 gate REJECT).
5. Documentation: CLAUDE.md updated (workflow / module table / CLI flags
   section / new Econ Calendar Config section). context.md updated with
   Econ Calendar Integration section + active TODO entry for A/B
   validation.
6. FOMC release_id surprise: FRED release_id=101 ("FOMC Press Release")
   publishes every weekday, not meeting dates. Switched to hardcoded
   FOMC_MEETING_DATES constant (48 dates 2022-2027 from federalreserve.gov).
   refresh() special-cases FOMC to read from this list instead of FRED.
   Annual maintenance (Fed publishes next 2y calendar each November).
   Also discovered: FRED's release/dates default sort is ASC, so for high-
   volume releases (FOMC has 3896 total dates), first 1000 by default
   are old. Fixed with sort_order=desc parameter.
7. Other 8 series verified via release_id lookup. Corrections from
   best-guess: PCE 21 → 54, Retail 117 → 436, Claims 32 → 180, FOMC 326 → 101.
   CPI, NFP, PPI, GDP, JOLTS were right.
8. A/B validation: QQQ marginal pass (STRONG ENTRY 1.8% → 1.7%, count
   570 → 515; LEAPS ONLY 6mo regressed from 7.4% to 6.4% — now below ALL
   DAYS baseline 7.0%, losing rationale). NVDA catastrophic: STRONG ENTRY
   15d 2.9% → -0.1%, 6mo 33.4% → 13.6%, hierarchy fully inverted (STRONG
   ENTRY becomes the WORST signal). Same failure mode as S11 isotonic
   calibration — adding ~33% feature inflation compresses high-confidence
   tail where individual-stock edge lives. Flag stays opt-in, default OFF.
9. Process note: validates the framework's default-OFF-then-validate
   discipline. The QQQ result alone (1.7%) looked acceptable; only
   cross-ticker NVDA test revealed the structural problem. This is the
   third time this pattern has fired (S11 calibrate, S18 p4-gate, S20
   econ-features) — strong evidence that cross-ticker validation is
   load-bearing, not optional.

S19 (2026-05-14) — Smoke-Test Layer Shipped
1. Created tests/ directory: tests/__init__.py, tests/conftest.py,
   tests/test_smoke.py. pytest installed into venv (not in requirements.txt).
2. Extracted determine_signal(dir_win, dir_win_63, expansion) helper from
   print_combined_signal() in entry.py — maps three binary phase signals
   to five-tier SIGNAL label. Behaviour unchanged; now unit-testable.
3. 5 smoke tests (all pass, ~1-2s, no network):
   - test_signal_hierarchy_qqq: reads QQQ_backtest_results.csv, asserts
     STRONG ENTRY > CAUTION > STAY OUT by avg 15d fwd_return.
   - test_strong_entry_baseline_qqq: STRONG ENTRY count >= 300, avg >= 0.8%,
     win rate >= 55%. Loose bounds survive daily train/test-split drift.
   - test_vol_thresholds_range_qqq: compute_vol_thresholds() returns positive
     values in expected ranges; t2b > t2 guards P2B_VOL_MULTIPLE not reverted.
   - test_signal_logic: unit test of determine_signal() — all 8 input combos
     map to correct label.
   - test_entry_train_threshold_sensitivity (S16 regression guard): calls
     entry.train() at decision_threshold=0.50 and 0.55; asserts prec_55 !=
     prec_50 and prec_55 > prec_50. Uses stripped features (no VIX/benchmarks)
     to avoid network calls — precision is sub-0.50 but threshold sensitivity
     is intact. QQQ edge on stripped features is near-zero; test is about
     threshold wiring, not absolute precision level.
4. conftest.py fixtures: backtest_results + df_qqq are module-scoped (loaded
   once per session); both pytest.skip if CSV not found (not an error).

S18 (2026-05-13) — Phase 4 (Exit Signal) Shipped + Massive Env-Var Restored
1. Massive API key regression resolved:
   - modules/massive.py:15-16: restored env-var-only pattern; deleted
     hardcoded fallback. Compromised key (was in git) was subsequently
     rotated at Massive.com on 2026-05-15.
   - CLAUDE.md + context.md cleaned: removed "HARDCODED" warnings, pruned
     stale Known Issues (diag files / N_ESTIMATORS / mdates / add_vix
     wrappers — all resolved in S17 but list never updated).
2. Phase 4 / exit signal shipped as exit.py:
   - Target: max drawdown over N days <= -(P4_VOL_MULTIPLE × median_HV ×
     sqrt(N/252)) with P4_VOL_MULTIPLE = 1.0. Captures forward-window MAE
     using shift(-N).rolling(N).min() on Low column.
   - Trains 3 candidate windows jointly (5d / 15d / 63d) and reports
     per-window edge so per-ticker winners are visible.
   - New shared functions in modules/features.py:
     - add_trend_break_features() — backward-looking trend-vulnerability
       features (above_ma20/50, dist_above_ma20/50_pct, ma20/50_slope_5d,
       days_above_ma20/50). Must run BEFORE normalize_features (drops MA cols).
     - compute_p4_drawdown_threshold(df, n) — vol-adjusted threshold from
       median HV (prefers HV_20 col if present; falls back to log-return
       computation; final fallback 0.20 if data insufficient).
     - add_p4_drawdown_target(df, n, threshold, target_col) — apply forward
       drawdown target via Low.shift(-n).rolling(n).min(); truncates last
       n rows. Used by both exit.py (loop over 3 windows) and entry.py.
3. Cross-ticker validation (per project rule):
   QQQ:  5d +16.2pp | 15d +17.7pp ◄ best | 63d  +2.3pp
   NVDA: 5d +19.7pp ◄ best | 15d +15.8pp | 63d -20.7pp ◄ tail inversion
   Both: 5d and 15d both produce real edge (+15-20pp). 63d unsafe on
   individual stocks — NVDA 63d model has 0% precision at thresholds
   >= 0.60 (high-confidence anti-prediction; same failure pattern as S11
   calibration). 63d excluded from production surface.
4. Production default: 15d (QQQ-best, NVDA only 4pp behind 5d, symmetric
   with Phase 2 entry window). 5d available as aggressive alternative.
   Top features that paid off: price_vs_kc_lower (+), days_above_ma50 (+),
   dist_above_ma50_pct (+) — the trend-break features earned their keep.
   Counterintuitive but correct: price_vs_kc_upper has NEGATIVE coefficient
   (breaking above upper Keltner = momentum protection, less near-term
   drawdown). Mean reversion isn't immediate.
5. Option A integration shipped to entry.py: display-only "EXIT RISK
   (Phase 4 — 15d drawdown)" section between Phase 3 IV TIMING and
   OPTIONS-MARKET CHECK. Shows drawdown bar, probability, signal
   (EXIT ⚠ / NO EXIT ✓), and top drivers. Does NOT affect SIGNAL or
   POSITION SIZING — those still come from P2/P2B/P3 only.
6. Option B (P4 gate) implemented and REJECTED via backtest validation:
   - Gate logic: one-tier-down (STRONG ENTRY → CAUTION, CAUTION /
     SHORT-TERM ONLY → STAY OUT, LEAPS ONLY unchanged) when exit_prob
     >= P4_THRESHOLD (0.55).
   - Implementation: --p4-gate flag in entry.py (default OFF), Phase 4
     model trained per walk-forward window in backtest.py (mirrors P2/P2B/P3),
     A/B summary table compares ungated vs gated signal distributions.
     summarize() refactored to take signal_col parameter; new
     summarize_p4_gate_ab() function prints A/B verdict.
   - Cross-ticker results:
     QQQ:  STRONG ENTRY 1.8% → 1.5% (-0.24pp), 6mo 9.4% → 7.6% (-1.8pp)
     NVDA: STRONG ENTRY 2.9% → 3.4% (+0.48pp), 6mo 33.4% → 29.1% (-4.3pp)
            gated count 294 < 300 floor — sample-size REJECT regardless
   - Diagnostic signature: gated win rate UP, avg return DOWN — gate is
     filtering winners along with losers at a worse ratio. The 15d
     drawdown horizon is too short for LEAPS — filters out 6mo winners
     that had 15d wobbles.
   - Code retained as opt-in (--p4-gate flag, default OFF). Future
     experiments could try shorter window (5d) or compound gate logic
     (require BOTH P4 + IV/HV to fire before downgrade).
   - Full edge-vs-horizon curve mapped post-rejection (32d/126d added then
     removed from P4_FORWARD_DAYS_LIST after data collected). Shows hard
     horizon ceiling for drawdown prediction:
                  QQQ                     NVDA
       5d:   +16.2pp                +19.7pp ◄ NVDA peak
      15d:   +17.7pp ◄ QQQ peak     +15.8pp
      32d:   +16.0pp                 -3.2pp ◄ stocks break
      63d:    +2.3pp                -20.7pp ◄ NVDA worst (confident wrong)
     126d:    -5.1pp ◄ QQQ breaks  -15.7pp (noise floor — only 30 signals)
     Insight: drawdown predictability has a hard ceiling — ~15d for
     individual stocks, ~30d for index ETFs. The 32-63d range is where
     stock models are most confidently wrong (tail inversion). LEAPS gate
     use case (60-180d holding) is structurally outside P4's predictive
     horizon for ANY ticker — no N solves the gate problem.
     P4_FORWARD_DAYS_LIST trimmed to [5, 15] for production cleanliness.
7. Process note: re-ask cycle on design questions (user pushed back on
   "10d forward window" recommendation that lacked rigor; reformulated as
   "tactical 5-10d / symmetric 15d / strategic 63d / train all three").
   User picked "train all three" — surfaced the 63d tail inversion that
   would have been invisible if we'd hardcoded a single window.
8. As-a-side-effect: this backtest run is the first full QQQ + NVDA
   re-run under P2B=0.55 (from S17). Co-validation now satisfied. Updated
   QQQ baseline: STRONG ENTRY 570 / 1.8% / 64.2% / 6mo 9.4% / 76.3%.
   Updated NVDA baseline: STRONG ENTRY 355 / 2.9% / 59.2% (vs pre-S17
   391 / 4.4% / 65.5% — drop reflects P2B threshold tightening, not
   regression). Older CLAUDE.md figures (574/1.9%/63.2%) are pre-S17/S18.

S17 (2026-05-13) — Code Cleanup + Market Stress Warning + P2B Multiple
1. Code cleanup completed:
   - Deleted 7 diag/_diag_*.py files (flagged since S12)
   - Removed dead N_ESTIMATORS=200 constant from direction.py
   - Removed unused `import matplotlib.dates as mdates` from indicators.py
   - Completed S14/S16 refactor: add_vix(df, start_date, end_date) and
     add_benchmarks(df, benchmarks, start_date, end_date) moved from inline
     copies in direction.py/volatility.py into modules/features.py. Call sites
     updated to pass START_DATE/END_DATE explicitly.
   - backtest.py now imports P2_VOL_MULTIPLE, P2B_VOL_MULTIPLE, P3_VOL_MULTIPLE
     from modules.features (single source of truth). Local copies removed.
     Dead reassignments inside sweep loop removed.
2. Market stress warning added to entry.py (display-only, no logic change):
   - Fires when Phase 3 = CONTRACTION and options market signals near-term risk
   - Triggers on term_structure >= 1.05 (backwardation) OR IV/HV >= 1.40
   - Prints tells and advisory under OPTIONS-MARKET CHECK section
   - Threshold rationale: 1.05 is the existing framework stress level; 1.02
     (slight backwardation) rejected as too noisy
3. P2B_VOL_MULTIPLE = 0.55 added as separate constant from P2_VOL_MULTIPLE = 0.41:
   - Rationale: 63d bar uses same sqrt(T) scaling as 15d but ignores secular
     drift — for QQQ the drift makes the 63d bar too easy to clear (~2.9%),
     producing ~70% base rate and near-zero discriminative power at low thresholds
   - 0.55 raises QQQ 63d bar to 5.0% (from 2.9%), creating more balanced classes
   - MULTIPLIER_SWEEP updated to 3-tuples: (P2_mult, P2B_mult, P3_mult)
4. QQQ backtest validation (53 windows, P2B=0.55):
   - STRONG ENTRY: 1.9% / 63.2% — no regression vs pre-S17 baseline
   - LEAPS ONLY 6-month: 6.4% → 7.5% (now above ALL DAYS 7.0% — first time)
   - P2B=0.55 validated on QQQ; needs co-validation on NVDA before permanent default

S16 (2026-05-12/05-13) — Pipeline Verification + entry.py Refactor + Today-Row Fix
1. Full QQQ pipeline verification uncovered three issues:
   a) entry.py never refactored to use modules/features.py (S14 omission) —
      had inline copies of HV/VIX/earnings/normalize and local
      compute_vol_thresholds + duplicated constants
   b) entry.py reported precision via clf.predict() (default 0.50 threshold)
      instead of production thresholds (P2/P2B 0.55, P3 0.60). Displayed
      precision didn't reflect what the actual signal would fire at.
   c) indicators.py stamped today's IV harvest onto yesterday's row when
      yfinance hadn't returned today's bar (yfinance end is exclusive).
      Re-running mid-day overwrote yesterday's close-of-day IV with today's
      intraday IV.
2. Fixes applied:
   - entry.py imports HV_WINDOW, IV_RANK_WINDOW, P2/P2B/P3_FORWARD_DAYS,
     P2/P3_VOL_MULTIPLE, compute_hv_features, compute_vix_features,
     add_earnings_proximity, normalize_features, compute_vol_thresholds
     from modules.features. Local compute_vol_thresholds removed; call
     site updated to tuple-unpack pattern.
   - entry.py train() takes decision_threshold param; precision computed
     via predict_proba >= threshold. All three call sites pass the
     production threshold (P2_THRESHOLD, P2B_THRESHOLD, P3_THRESHOLD).
   - indicators.py harvest_iv_snapshot adds today-row when today.weekday()
     < 5 and today not in df.index. Spot uses latest non-NaN Close
     (yesterday's close anchors the ATM strike). Logs `→ row YYYY-MM-DD`
     to confirm where the IV stamp landed.
3. Verification (post-fix):
   - Phase 2 + Phase 2B precision now byte-identical between entry.py and
     direction.py (P2: 58.1% / 47.7%; P2B: 67.3% / 56.0%)
   - Phase 3 entry.py vs volatility.py: 47.6% vs 47.8% (gap closed from
     0.5pp; residual is volatility.py reporting at DECISION_THRESHOLD=0.50
     vs entry.py at P3_THRESHOLD=0.60)
   - Today-row addition shifted Phase 3 prob 31.3% → 47.8% on 2026-05-11
     (1 extra recent training sample). Real model behavior, not a bug —
     means run-to-run probabilities can drift.
4. Confirmed Massive quality filters all in place (v<5, n<5, IV cap 2.0,
   monthly preference, ATM delta filter, fast-fail). Context.md "PENDING"
   item from S12/S14 already shipped.
5. Discovered backfill state: AMD/SOFI/LYFT/QQQ all healthy (300-500 IV
   rows); NVDA stuck at 2 rows; AAPL partial at 180 (interrupted run).

S15 (2026-05-12) — LEAPS ONLY Signal Tier + 6-Month Forward Returns
1. Added 5th signal tier `LEAPS ONLY` (15d NO SIGNAL + 63d WIN). Triggers
   ~12% of QQQ days; 0.8% avg / 63.0% win rate (beats STAY OUT 0.6% / 61.1%).
2. Added 6-month forward return table to backtest.py summarize(). For QQQ,
   STRONG ENTRY +10.6% / 77.3% win is the only signal with edge on BOTH 15d
   AND 6mo horizons.
3. impute_iv_features() moved from volatility.py inline to modules/features.py;
   imported by backtest.py.
4. STAY OUT count fell 4676 → 3066 on QQQ (LEAPS ONLY pulled ~25% of days).
5. AMD/NVDA backtests not yet re-run with LEAPS ONLY tier — those tables
   still reflect pre-S15 baselines.

S14 (2026-05-12) — Shared Features Module Refactor (partial)
1. Extracted ~700 lines of duplicated feature engineering from backtest.py +
   direction.py + volatility.py into new modules/features.py.
2. Centralized: HV_WINDOW, IV_RANK_WINDOW, P2/P2B/P3 forward days, P2/P3
   vol multiples, compute_hv_features, compute_vix_features,
   add_earnings_proximity, normalize_features, compute_vol_thresholds.
3. INCOMPLETE: entry.py was missed (caught + fixed in S16). direction.py and
   volatility.py still have inline add_vix() and add_benchmarks() wrappers.
4. Regression verified on QQQ (no change to backtest STRONG ENTRY 587/1.9%/63.2%).

S13 (2026-05-10/11) — Backfill Completion + Imputation + Per-Window Threshold
1. QQQ 2-year IV backfill completed: 266/447 fill rate (40% NaN — no contracts
   traded that day, or all aggregates filtered out).
2. impute_iv_features() added: fills NaN IV with HV_20 / 0.0 / 1.0 + binary
   indicators (iv_available, term_available). Preserves 5,240 training rows
   (vs 316 without imputation).
3. Phase 3 retrain: HV proxy 74.2% expansion precision; --iv-features 75.0%
   (+0.8pp gain mostly absorbed by HV-IV near-collinearity in pre-2024 windows).
4. Per-window threshold calibration fix in backtest.py: compute_vol_thresholds
   now called inside run_backtest() loop after df_train slice. Eliminates
   lookahead from future vol data in early training windows. Material on AMD
   (40y data); minimal on QQQ.
5. AMD first full-history backtest (91 windows): STRONG ENTRY 3.9% / 57.0%,
   SHORT-TERM ONLY -1.4% (hard NO), CAUTION ≈ STAY OUT (Phase 3 HV proxy
   doesn't discriminate at AMD's vol scale).

Earlier work (condensed)
- S1-S6: foundational pipeline; vol-adjusted thresholds; benchmark detection;
  earnings/catalyst features; Phase 2B (63d) added; 4-label SIGNAL output
- S7: catalyst CSV path fix; EVENT_DRIVEN_TICKERS for CRSP; SIGNAL terminology
  unified across entry.py and backtest.py
- S8: gap features (gap_pct, gap_ma_5d, gap_vol_5d); VIX term structure
  (VIX9D_VIX_ratio, VIX_VIX3M_ratio); Tradier IV gate (later replaced by S10)
- S9: probability calibration diagnostic added (read-only, no production change)
- S10: Massive.com integration replacing Tradier IV gate; daily chain harvest
  with merge to preserve forward IV history; entry.py reads IV from CSV
- S11: isotonic-calibrated Phase 2 implemented + tested + reverted to RAW
  default after NVDA regression (-4.8pp STRONG ENTRY, hierarchy inverted).
  Drove the cross-ticker validation requirement.
- S12: BS-inversion backfill infrastructure (modules/bs_invert.py +
  get_historical_iv_snapshot + backfill_iv.py); --iv-features CLI flag;
  three Massive API bugs found and fixed (as_of conflict, scoring units,
  candidate cap)
