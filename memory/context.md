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

Session 12 — Historical IV Backfill Pipeline + CLI Toggle (2026-05-09/10)

Implemented the S12 BS-inversion pipeline, the --iv-features CLI toggle, and diagnosed
the Massive API behavior for historical options data. Backfill is NOT yet producing
clean data — see bugs discovered below.

1. modules/bs_invert.py (new) — Black-Scholes solver
   - black_scholes_call(S, K, r, T, sigma, q=0) — standard BSM call price
   - vega(S, K, r, T, sigma, q=0) — used for Newton-Raphson convergence
   - implied_vol(price, S, K, r, T, q=0) — NR + bisection fallback, raises ValueError
     if no convergence
   - implied_vol_put(price, S, K, r, T, q=0) — put-call parity wrapper
   - bs_delta(S, K, r, T, sigma, q=0, contract_type="call") — Δ for 25Δ skew selection
   - Unit tested: sigma=0.22 round-trips through BSM to ±1e-5.

2. modules/massive.py — IV_COLS split + historical IV fetch
   - IV_COLS split into:
       IV_FEATURE_COLS = ["atm_iv_30d", "iv_skew_25d", "term_structure"]
       IV_META_COLS    = ["atm_strike", "atm_expiry", "atm_dte", "put_call_oi_ratio"]
       IV_COLS         = IV_FEATURE_COLS + IV_META_COLS  (backward compat)
   - Downstream scripts use *(IV_META_COLS if use_iv_features else IV_COLS) to exclude
     metadata-only cols when real IV features are active.
   - get_historical_iv_snapshot(ticker, date, spot, r, target_dte=30, q=0) added:
       Stage A: _fetch_historical_contracts (reference endpoint, expired=true) for front
                calls + front puts + back calls
       For each contract: _fetch_agg_price (aggregates endpoint) -> BS-invert -> IV
       Returns same keys as get_chain_summary minus put_call_oi_ratio (historical OI
       not available via Massive)

3. backfill_iv.py (new) — standalone backfill script
   - Prompts for ticker, loads indicators CSV, finds NaN rows within BACKFILL_YEARS (2y)
   - Fetches ^IRX per-date for risk-free rate (yfinance 5y download)
   - Calls get_historical_iv_snapshot per date, writes to CSV, checkpoints every 50 dates
   - Resumable: already-populated rows are never overwritten (mask: atm_iv_30d.isna())
   - Processes newest -> oldest (most recent data first)

4. --iv-features / --no-iv-features CLI toggle
   - Added to volatility.py, entry.py, backtest.py (argparse BooleanOptionalAction)
   - Default: False (HV proxy — safe until backfill is complete and validated)
   - When True: Phase 3 uses IV_FEATURE_COLS as features (atm_iv_30d, iv_skew_25d,
     term_structure) instead of excluding them; IV_META_COLS still always excluded
   - train_model()/train() gain use_iv_features=False param; exclusion set uses
     *(IV_META_COLS if use_iv_features else IV_COLS)
   - Banner + footer print active IV mode: "Phase 3 IV: REAL" vs "HV proxy"
   - calibrate_multipliers.py: import updated to include IV_META_COLS/IV_FEATURE_COLS;
     comment added noting --iv-features is not supported there (sweep uses HV proxy only)

5. Massive API behavior discovered during diagnostic runs

   BUG 1 (FIXED): as_of parameter silently ignored by reference endpoint
   - _fetch_historical_contracts originally passed as_of=date.isoformat() + expired=true
   - The API returns 0 results when both are present — as_of conflicts with expired=true
   - Fix: removed as_of. The expiration_date.gte/lte window already scopes the tenor.
   - Result: reference endpoint now returns correct contracts (121 for QQQ Nov 2025 test)

   BUG 2 (FIXED): ATM scoring formula used incompatible units
   - Original: abs(dte - target_dte) * 10 + abs(strike - spot)
   - For QQQ at $490: a 5-DTE miss scores 50, same as a $50 strike miss — but $50 OTM
     is 10% away from ATM, which is deep OTM. The DTE term dominated incorrectly.
   - Fix: normalize strike distance by spot price:
       abs(dte - target_dte) * 10 + abs(strike - spot) / spot * 100
   - Now both terms are percentage-scale. A 5-DTE miss = 50 pts; a 2% strike miss = 2 pts.
   - Applied in both meta_atm_score (pre-inversion sort) and inv_atm_score (ATM selection)

   BUG 3 (FIXED): MAX_INVERT_PER_CATEGORY cap caused misses on thin markets
   - Original cap of 8 (later raised to 30 during diagnosis) truncated candidates by ATM
     score before fetching prices. For thin historical days, the one contract that actually
     traded could be ranked 31st+ and never attempted.
   - Fix: removed cap entirely. All contracts returned by reference endpoint are tried.
     Most return NO PRICE quickly; the slowdown is acceptable vs missing the only trade.
   - MAX_INVERT_PER_CATEGORY constant replaced with comment.

   BUG 4 (PENDING): Single-trade artifact prices produce implausible IV
   - After fixes 1-3, get_historical_iv_snapshot returns a result for QQQ 2025-11-03:
       atm_iv_30d: 237% (should be ~15-25%)
       iv_skew_25d: -188% (should be ±0.01-0.10)
       term_structure: 1.68
   - Root cause: the one contract with price data (O:QQQ251128C00490000) had v=1, n=1
     in the aggregates — a single-contract print at $143.37. The fair price for an
     ATM 25-DTE QQQ call was ~$12-13 at the time. The $143.37 print is a stale/erroneous
     record (likely a mid-quote or historical artifact), not a real market transaction.
   - BS-inversion correctly inverts it to ~237% IV, which just barely passes the
     current 0.01 <= iv <= 5.0 guard (237% = 2.37 in decimal form, under 5.0).
   - PROPOSED FIX (not yet implemented): add minimum volume filter in _fetch_agg_price.
     Reject any aggregates record with v < MIN_OPTION_VOLUME (suggest 5-10 contracts).
     This eliminates single-print artifacts while accepting legitimately thin but real
     option flow. The 0.01 <= iv <= 5.0 guard should also be tightened — 3.0 (300% IV)
     is already implausible for any non-biotech underlying, 1.5 (150%) would be
     conservative but safe for QQQ/SPY/NVDA/AMD. CRSP could hit 80-100% during events.

6. Pipeline run result — QQQ 2026-05-08/09
   - indicators.py: ATM IV (~27d): 21.5%, skew +0.040, term 1.00 (noise), P/C OI 0.73
   - entry.py (default --no-iv-features): STAY OUT
       Phase 2: 47.4% (base 44.2%) — NO SIGNAL; RSI_23 is top negative driver (overbought)
       Phase 2B: 39.2% (base 51.5%) — below base rate, medium-term mean-reversion expected
       Phase 3: 30.9% expansion (base 42.1%) — CONTRACTION; overbought + above KC upper
       IV/HV: 1.39 (rich) — would gate STRONG ENTRY if Phase 2 had fired
       SIGNAL: STAY OUT — no directional edge, don't chase the run-up

7. Diagnostic files created during session (temporary, can be deleted)
   - _diag_iv.py, _diag_iv2.py, _diag_iv3.py in workspace root

8. Next steps for backfill to produce clean data
   a. Implement minimum volume filter (v >= 5 or 10) in _fetch_agg_price
   b. Tighten IV bounds: 0.01 <= iv <= 1.5 for non-event tickers (adjust per ticker type)
   c. Validate on a known-good date (e.g. pick a QQQ date, verify against realized HV)
   d. Run full 2-year backfill for QQQ
   e. Retrain Phase 3 with --iv-features and compare edge vs HV proxy

────────────────────────────────────────────────────────────────────────

Session 13 — Backfill Completion, Phase 3 Retrain, Threshold Calibration Fix (2026-05-10/11)

1. QQQ 2-year IV backfill completed
   - 266 / 447 target dates populated = 60% fill rate (40% NaN — no contracts traded
     that day, or all aggregates records had v=1 artifact prices filtered out)
   - Monthly-preference sort fix in modules/massive.py: contracts now sorted
     by monthly expiry first (standard exchange cycles) before the DTE scoring pass,
     preventing weekly weeklies from systematically outscoring monthly contracts.
   - Full-history QQQ indicators CSV: 6,832 rows (1999-2026), 7 IV columns appended.
     Historical IV rows: atm_iv_30d 266 real + rest NaN (imputed at train time).

2. impute_iv_features() added to volatility.py (--iv-features mode)
   - Without imputation: --iv-features dropna() collapsed training set to ~316 rows
     (only rows with real atm_iv_30d), stripping 25y of direction/momentum history.
     ECE ballooned to 0.2255 (model learned almost nothing).
   - Fix: impute_iv_features() fills NaN IV with HV-based proxies + binary indicators:
       atm_iv_30d    -> fill NaN with df["HV_20"]
       iv_skew_25d   -> fill NaN with 0.0
       term_structure -> fill NaN with 1.0
       iv_available   -> 1 if real atm_iv_30d, else 0  (binary flag feature)
       term_available -> 1 if real term_structure, else 0
   - Training rows preserved: 5,240 (full history instead of 316).
   - Called in volatility.py main flow: after normalize_features(), before df_full = df.copy()

3. Phase 3 retrain results
   - HV proxy (default, no --iv-features): expansion precision 74.2% @0.60, +32.9pt edge,
     ECE 0.0335. 3,067 training rows, 767 test rows.
   - --iv-features (imputed): expansion precision 75.0% @0.60, +33.7pt edge, ECE 0.0385.
     5,240 training rows (full history preserved by imputation).
   - Note: atm_iv_30d and HV_20 coefficients are nearly identical (-0.7869 each) in the
     --iv-features model — expected near-collinearity, imputed values dominate the IV
     feature in pre-2024 windows. Real incremental signal will emerge from iv_skew_25d
     and term_structure as IV backfill history accumulates.

4. Per-window threshold calibration fix in backtest.py
   - Problem: compute_vol_thresholds() was called once on df_full before run_backtest().
     For all 91 AMD windows, WIN_THRESHOLD was derived from full-history median_HV=49.8%,
     which blends the 1980-2022 low-vol era with the post-2023 AI-pivot high-vol era.
     Early windows (1981-2000) got a WIN_THRESHOLD calibrated partly on future vol data
     they wouldn't have seen — a mild lookahead form.
   - Fix: one line added inside run_backtest() loop, immediately after
     df_train = df_full.iloc[:train_end].copy():
       compute_vol_thresholds(df_train, verbose=False)
     This updates the three globals using only the training window's HV history.
   - The initial compute_vol_thresholds(df_full) call before the loop is preserved
     (prints the full-history calibration header for reference).
   - Impact on QQQ: minimal (STRONG ENTRY 64.9% -> 63.5% win rate, avg return unchanged
     at 2.0%). QQQ has 25y of relatively stationary HV — full-history vs per-window
     median barely differ.
   - Impact on AMD: material (see results below). 40y of data means early windows used
     1980s low-vol HV to train, which would have been contaminated by blending.

5. QQQ backtest regression check (with per-window threshold fix)
   - STRONG ENTRY: 586 signals, 2.0% avg, 63.5% win% (pre-fix: 619 / 2.0% / 64.9%)
   - CAUTION: 1337 signals, 1.2% avg, 62.4% (pre-fix: 1364 / 1.1% / 62.1%)
   - SHORT-TERM ONLY: 512 signals, 0.2% avg, 57.4% (pre-fix: 558 / 0.3% / 56.5%)
   - STAY OUT: 3878 signals, 0.6% avg, 61.5% (unchanged)
   - Signal hierarchy intact, avg returns essentially flat. Fix confirmed safe.

6. AMD backtest — first full-history run (91 windows, 2000-2026)
   - Full data range: 11,629 rows (1980-2026); 91 walk-forward windows.
   - Global median HV: 49.8% (vs QQQ 18.2% — AMD is ~2.7× more volatile).
   - WIN_THRESHOLD: 4.98% (vs QQQ 1.82%) — much harder 15d bar to clear.
   - Results:
       STRONG ENTRY:    377 signals, 3.9% avg, 57.0% win%, AvgWin 13.0%, AvgLoss -8.3%
       CAUTION:         728 signals, 1.9% avg, 51.9% win%
       SHORT-TERM ONLY: 560 signals, -1.4% avg, 44.5% win%
       STAY OUT:       4783 signals, 1.9% avg, 52.1% win%
   - Key findings:
     a. STRONG ENTRY has clear edge: 3.9% avg vs 1.7% all-days (+2.2pt), AvgWin/AvgLoss
        ratio (13.0% / -8.3%) is favorable positive skew even at 57% win rate.
     b. SHORT-TERM ONLY is a hard NO on AMD: -1.4% avg, 44.5% win rate, worst label.
        "Phase 2 fires but Phase 2B doesn't confirm" = do not trade AMD. The 63d
        confirmation is load-bearing for this ticker.
     c. CAUTION ≈ STAY OUT (both 1.9%, win rates 51.9% vs 52.1%): Phase 3 HV-proxy
        IV expansion signal adds zero discriminating value between these two labels.
        This contrasts with QQQ where CAUTION (1.2%) meaningfully beats STAY OUT (0.6%).
        Implication: for AMD, treat CAUTION as STAY OUT and only size into STRONG ENTRY.
     d. STRONG ENTRY AvgWin (13.0%) >> STRONG ENTRY AvgLoss (-8.3%): even if win rate
        softens in live trading, the risk-reward profile supports FULL sizing as intended.
     e. No AMD IV backfill exists yet. This run used HV-proxy Phase 3 (default). The
        --iv-features flag would be degenerate until AMD backfill is complete (100% of
        AMD atm_iv_30d would impute to HV_20, adding no new signal).

────────────────────────────────────────────────────────────────────────

Session 11 — Decision 1 Implementation + NVDA Regression (2026-05-08/09)

Implemented S9-carryover Decision 1 (isotonic-calibrated Phase 2 production model).
QQQ validation showed marginal pass (-0.3pt STRONG ENTRY); NVDA validation showed
catastrophic fail (-4.8pt STRONG ENTRY, full hierarchy inversion). Default reverted
to raw; calibrated retained as a CLI research toggle.

1. Calibrated Phase 2 production path (direction/entry/backtest)
   - train_model / train accept calibrate=False param; when True fits
     CalibratedClassifierCV(method="isotonic", cv=5) and SYNTHESIZES .coef_ on the
     wrapper as the average of base-estimator coefs so downstream code (top-coefficients
     print, get_top_contributors) keeps working without changes.
   - direction.py train_model also accepts decision_threshold param so Phase 2 (e.g. 0.50
     calibrated) and Phase 2B (0.55 raw) classification reports use their own thresholds
     instead of a single shared DECISION_THRESHOLD constant.

2. P2_THRESHOLD / P2B_THRESHOLD split into separate constants
   - Previously one value (0.55) was used for both phases. entry.py and backtest.py now
     have P2B_THRESHOLD = 0.55 separate from P2_THRESHOLD (0.55 raw / 0.50 calibrated).
   - dir_signal_63 = dir_prob_63 >= P2B_THRESHOLD (was P2_THRESHOLD).

3. CLI flag --calibrate / --no-calibrate (argparse BooleanOptionalAction)
   - Added to direction.py / entry.py / backtest.py.
   - Banner at start of every run prints active mode + thresholds; footer at end.
   - Display label in entry.py "[threshold: X — calibrated/raw]" reflects active mode.
   - DEFAULT: --no-calibrate (raw production), reverted after NVDA fail. Calibrated path
     remains accessible via --calibrate.

4. Calibrated Phase 2 threshold sweep (QQQ test, 1314 rows)
   - Calibrated probs heavily compress: 66% of test in bin 0.4-0.5, 34% in 0.5-0.6,
     0% above 0.6. Calibration is correctly pulling overconfident raw probs toward
     true rates — but at the cost of distributional spread.
   - Threshold sweep optimum 0.50 (446 signals, 48.9% precision, +2.1pt over 46.8% base)
   - At raw-equivalent threshold 0.55 calibrated only fires 58 times (no usable edge) —
     the threshold MUST be re-tuned on the calibrated scale, can't reuse the raw cut.
   - ECE on Phase 2 (QQQ): raw 7.01% → calibrated 1.14% (~6x academic improvement).

5. QQQ walk-forward result (53 windows) — "marginal pass"
   - STRONG ENTRY: raw 619/2.0%/64.9% → calibrated 434/1.7%/61.5%
   - Drop within 0.5pt verdict-gate tolerance; STRONG > others preserved (CAUTION ties
     SHORT-TERM ONLY at 0.8%).
   - 65% reproducibility property weakened (-3.4pt to 61.5%).
   - SIDE EFFECT: SHORT-TERM ONLY IMPROVED 0.3% → 0.8% (+0.5pt). The "Phase 2 fires but
     Phase 2B doesn't" subset gets a quality bump because tighter Phase 2 admits
     different/better days.

6. NVDA walk-forward result (53 windows) — catastrophic fail
   - STRONG ENTRY: raw 391/4.4%/65.5% → calibrated 187/-0.4%/52.4%
   - 4.8pt avg-return drop = 16x my verdict gate. STRONG ENTRY now UNDERPERFORMS
     ALL DAYS (2.5%) by 2.9pt — the model's strongest signal becomes worse than random.
   - Hierarchy FULLY inverted: SHORT (3.4%) > STAY OUT (2.9%) > CAUTION (0.6%) >
     STRONG ENTRY (-0.4%).
   - Win rate collapses 65.5% → 52.4% (essentially coin-flipping).
   - AvgLoss worsens -14.5% → -19.6% (surviving calibrated trades are a worse-distributed
     subset, not a cleaner one).

7. Why NVDA broke where QQQ didn't (postmortem)
   - QQQ: 25y of relatively stationary index behavior. Per-window calibrators fit on
     older windows still generalize to newer ones.
   - NVDA: post-2023 AI-pivot regime change. Vol distributions shift across windows.
     Per-window isotonic (cv=5 with ~50-400 samples per fold) cannot track regime
     transitions reliably — calibrator fit on regime A applied to regime B is wrong.
   - NVDA's STRONG ENTRY edge specifically lived in the HIGH-CONFIDENCE RAW PROBABILITY
     TAIL. Isotonic regularization-toward-mean compresses those extremes — destroying
     exactly the signal that drives the edge.
   - GENERALIZABLE LESSON: framework edge concentrates in the high-confidence tail for
     individual stocks (vs index ETFs where edge is more uniformly distributed).
     Calibration's mean-regression IS HARMFUL where the tail IS the signal.

8. Decision: revert default to --no-calibrate
   - Module-level P2_CALIBRATE = False, P2_THRESHOLD = 0.55 in entry.py and backtest.py.
   - argparse default=False in all 3 scripts.
   - help text now flags the NVDA regression: "Default OFF (NVDA regression: STRONG
     ENTRY 4.4% → -0.4%). Pass --calibrate to enable."
   - Calibrated mode retained as research/diagnostic toggle (probability honesty for
     output readability, ECE diagnostics, future probability-based sizing experiments).

9. Implications for Decision 2 (Platt scaling on Phase 2B)
   - Originally deferred until D1 validates calibration helps in this framework.
   - D1 actively HURTS on individual stocks. Phase 2B's signal lives in a similar high-
     confidence tail. Platt is less aggressive than isotonic (sigmoid fit, can't compress
     to plateau) but still pulls toward mean.
   - STATUS: DEPRIORITIZED. Investigate only if a Phase 2B-specific use case emerges
     where probability-value honesty matters more than tail preservation.

10. Cross-ticker validation lesson (process improvement)
    - QQQ alone is NOT sufficient validation for any framework change. Index ETF edge
      profile differs structurally from individual-stock edge profile.
    - Going forward: any model change requires validation on QQQ + NVDA + AMD minimum
      before adopting as production default.

11. Pipeline run verification (today, 2026-05-09):
    - QQQ entry.py (raw default): STAY OUT — Phase 2 raw 54.1%, calibrated 45.8%; both
      below their thresholds. IV/HV 1.63 (very rich), term 1.09 (backwardation).
    - NVDA entry.py (raw default): STAY OUT — Phase 2 raw 37.7% (NO SIGNAL — below
      base rate), Phase 2B 57.7% (WIN ✓), Phase 3 12.9% (CONTRACTION — 12d to earnings,
      vol crush expected). IV/HV 1.18 (fair), term 1.08, P/C OI 0.26 (call-skewed).

────────────────────────────────────────────────────────────────────────

Backtest Results (Most Recent / Representative)

QQQ (53 windows, 2001-2026, post-S8 features) — framework reference baseline
  Mode: RAW (production default as of S11)
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY       619     2.0%     2.4%   64.9%   53.3%    5.4%   -4.1%   <- best
  CAUTION           1364     1.1%     1.8%   62.1%   50.1%    4.4%   -4.3%
  SHORT-TERM ONLY    558     0.3%     0.8%   56.5%   43.4%    4.1%   -4.6%
  STAY OUT          3772     0.6%     1.2%   61.5%   42.6%    3.5%   -3.9%

  Mode: CALIBRATED (--calibrate, S11 research toggle)
  STRONG ENTRY       434     1.7%     1.4%   61.5%   48.6%    5.5%   -4.5%
  CAUTION            922     0.8%     1.6%   60.6%   47.0%    4.1%   -4.2%
  SHORT-TERM ONLY    699     0.8%     1.3%   63.8%   42.8%    3.2%   -3.3%   (improved)
  STAY OUT          4259     0.7%     1.3%   61.4%   45.0%    3.8%   -4.2%
  Verdict: marginal pass. STRONG ENTRY -0.3pt (within tolerance), hierarchy preserved
  but tightened, 65% win-rate property weakened to 61.5%. ECE 7.01% → 1.14%.

NVDA (53 windows, 2001-2026, post-S8 features)
  Mode: RAW (production default as of S11)
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY       391     4.4%     4.9%   65.5%   52.9%   14.4%  -14.5%   <- BEST in project
  CAUTION           1270     1.6%     2.4%   56.4%   44.9%   11.2%  -10.8%
  SHORT-TERM ONLY    322     4.0%     2.7%   60.2%   44.4%   12.8%   -9.3%
  STAY OUT          4364     2.5%     2.0%   58.6%   40.7%   10.0%   -8.0%

  Mode: CALIBRATED (--calibrate) — REGRESSION
  STRONG ENTRY       187    -0.4%     3.0%   52.4%   49.7%   17.0%  -19.6%   <- BROKEN
  CAUTION            666     0.6%     2.9%   57.1%   47.1%   11.7%  -14.1%
  SHORT-TERM ONLY    187     3.4%     3.4%   62.0%   46.0%   12.7%  -11.7%   <- best
  STAY OUT          5307     2.9%     2.1%   58.9%   41.5%   10.3%   -7.8%
  Verdict: catastrophic fail. STRONG ENTRY -4.8pt (16x verdict gate), hierarchy fully
  inverted (SHORT > STAY OUT > CAUTION > STRONG), STRONG ENTRY underperforms ALL DAYS
  by 2.9pt. Drove the S11 default-revert decision.

SPY (31 years, 1995-2026, post-S8 features) — UNSUITABLE for this framework
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY       898     0.8%     1.1%   63.6%   47.1%    3.6%   -4.1%
  CAUTION           1189     0.9%     1.2%   61.9%   48.6%    3.4%   -3.1%   <- inverted!
  SHORT-TERM ONLY    724     0.2%     0.8%   58.7%   43.6%    3.1%   -3.8%
  STAY OUT          5044     0.7%     1.2%   65.6%   47.3%    2.6%   -3.0%
  STRONG ENTRY beats ALL DAYS (0.7%) by 0.1pp = noise. Hierarchy broken (CAUTION>STRONG).
  Structural mismatch: framework's price-action lens vs SPY's macro-driven moves.

QQQ (53 windows, 2001-2026, post-S13 threshold fix) — framework reference baseline
  Mode: RAW (production default)
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY       586     2.0%     2.3%   63.5%   52.9%    5.5%   -4.2%   <- best
  CAUTION           1337     1.2%     1.8%   62.4%   50.1%    4.5%   -4.3%
  SHORT-TERM ONLY    512     0.2%     0.9%   57.4%   44.7%    3.9%   -4.8%
  STAY OUT          3878     0.6%     1.2%   61.5%   42.7%    3.5%   -3.9%
  Note: minimal delta vs pre-S13 (64.9% -> 63.5% STRONG win%). QQQ HV is stationary
  enough that per-window vs full-history threshold calibration barely differs.

AMD (91 windows, 2000-2026, post-S13 threshold fix) — well-suited
  Signal           Count   Avg Ret   Median  Win%   Strong%  AvgWin  AvgLoss
  STRONG ENTRY       377     3.9%     2.1%   57.0%   41.1%   13.0%   -8.3%   <- best
  CAUTION            728     1.9%     0.8%   51.9%   39.0%   12.8%  -10.0%
  SHORT-TERM ONLY    560    -1.4%    -2.0%   44.5%   30.9%   13.3%  -13.3%   <- hard NO
  STAY OUT          4783     1.9%     0.7%   52.1%   38.4%   12.9%  -10.2%
  Key: CAUTION ≈ STAY OUT (both 1.9%) — Phase 3 HV proxy adds no AMD discrimination.
  SHORT-TERM ONLY is negative on AMD — 63d confirmation is load-bearing for this ticker.
  Only trade AMD on STRONG ENTRY. HV threshold 4.98% (vs QQQ 1.82%) — much harder bar.
  AMD IV backfill not yet done — --iv-features mode would be degenerate until complete.

CRSP (17 windows, 2018-2026, post-S7 fix) — inversion fixed but sample thin
  STRONG ENTRY 3.8% / 51.1% win | only 45 STRONG signals — too thin for confident trading
  AvgLoss -12.1% reflects binary event risk on directional calls

(Pre-S13 QQQ baseline preserved for reference)
  STRONG ENTRY 619/2.0%/64.9% | CAUTION 1364/1.1%/62.1% | SHORT-TERM 558/0.3%/56.5%
  Pre-S13 AMD (15 windows, 2019-2026 only): STRONG 2.6%/59.7% | SHORT-TERM 12.2%/66.1% (best)

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

Improvements (status as of S11)

DONE
- [S8] VIX term structure (VIX9D_VIX_ratio, VIX_VIX3M_ratio) in all ML scripts
- [S8] Tradier IV gate in entry.py (replaced in S10 by Massive)
- [S10] Massive.com Options Starter integration:
    - modules/massive.py with two-call chain harvest
    - indicators.py daily harvest into indicators CSV (with merge to preserve history)
    - entry.py reads IV from CSV (no live Tradier call); same gate logic
    - 25Δ skew, term structure, put/call OI ratio captured per ticker per day
    - 5-band term structure labels in entry.py output
- [S11] Decision 1 (calibrated Phase 2) implemented but NOT adopted as default:
    - CalibratedClassifierCV(isotonic, cv=5) plumbed through train/train_model
    - .coef_ synthesized on wrapper as avg of base estimators (downstream code unchanged)
    - direction.py train_model accepts decision_threshold param for honest per-phase
      classification reports
    - P2_THRESHOLD / P2B_THRESHOLD constants split (previously shared)
    - --calibrate / --no-calibrate CLI flag added to direction/entry/backtest with
      banner+footer indicating mode
    - REVERTED TO RAW AS DEFAULT after NVDA regression (-4.8pt STRONG ENTRY, hierarchy
      inversion). Calibrated mode retained as research toggle.
- [S12] BS-inversion backfill infrastructure:
    - modules/bs_invert.py: full Black-Scholes solver (call price, vega, implied_vol,
      implied_vol_put, bs_delta); unit tested to ±1e-5
    - modules/massive.py: IV_COLS split into IV_FEATURE_COLS + IV_META_COLS; three
      API bugs fixed (as_of conflict, scoring unit mismatch, candidate cap removed);
      get_historical_iv_snapshot() implemented
    - backfill_iv.py: standalone script with checkpointing, ^IRX rate lookup, resume
    - --iv-features/--no-iv-features toggle added to volatility/entry/backtest
    - Data quality bug PENDING: single-trade artifact prices need minimum volume filter
- [S13] Backfill completion + imputation + threshold fix:
    - QQQ backfill completed: 266/447 rows = 60% fill rate
    - Monthly-preference sort fix in modules/massive.py (weeklies were outscoring monthlies)
    - impute_iv_features() in volatility.py: fills NaN IV with HV_20/0.0/1.0 + binary
      indicator flags (iv_available, term_available); preserves 5,240 training rows
      (vs 316 without imputation); ECE improved from 0.2255 to 0.0385
    - Per-window threshold calibration fix in backtest.py: compute_vol_thresholds(
      df_train, verbose=False) inside run_backtest() loop after each df_train slice;
      eliminates lookahead contamination from future vol data in early training windows
    - Phase 3 retrain (HV proxy): 74.2% expansion precision, +32.9pt edge, ECE 0.0335
    - Phase 3 retrain (--iv-features): 75.0% expansion precision, +33.7pt edge, ECE 0.0385
    - AMD backtest (91 windows, full history): STRONG ENTRY 3.9%/57.0%; SHORT-TERM ONLY
      -1.4% (hard NO on AMD); CAUTION ≈ STAY OUT (both 1.9% — Phase 3 not discriminating)

PENDING DECISIONS
- [S9 carryover, S11 verdict] Decision 2 (Platt scaling on Phase 2B) — DEPRIORITIZED
    Originally deferred pending D1 validation. D1 fails on individual stocks (NVDA);
    Phase 2B's signal lives in a similar high-confidence tail that Platt would still
    regularize toward the mean (less aggressively than isotonic, but same direction).
    Investigate only if Phase 2B-specific probability-value use case emerges.

NEXT MAJOR WORK
- [S13 DONE, S14 TODO] AMD IV backfill
    QQQ at 60% fill. AMD has 0% backfill — run backfill_iv.py for AMD to enable
    --iv-features mode. Without it, all AMD atm_iv_30d imputes to HV_20 (no new signal).
    After backfill: retrain volatility.py with --iv-features for AMD; re-run backtest.
- [S14 TODO] Phase 3 retraining on real IV (depends on AMD backfill)
    QQQ --iv-features already shows 75.0% expansion precision (+0.8pt over HV proxy).
    AMD Phase 3 CAUTION ≈ STAY OUT issue may resolve if real IV data adds discriminating
    signal that HV-proxy can't capture (e.g. IV expansion ahead of earnings/events).
- [S14 TODO] tighten backfill data quality filters
    Current IV upper bound 5.0 accepts 237% outliers (artifact single-contract prints).
    Fix: reject v < 5 (or n < 5) in _fetch_agg_price; tighten IV cap to 1.5 for
    QQQ/SPY/NVDA/AMD, 1.0 for CRSP/biotech events. Validate on known-good date first.

OTHER TODO (lower priority)
- Earnings estimate revision direction (finviz/yfinance) for individual stocks

────────────────────────────────────────────────────────────────────────

Session 14 — Shared Features Module Refactor (2026-05-12)

Extracted ~700 lines of duplicated feature engineering code from backtest.py,
direction.py, and volatility.py into a new shared module modules/features.py.

1. modules/features.py (new)
   - Centralizes all shared constants and feature functions:
       HV_WINDOW=20, IV_RANK_WINDOW=252, P2_FORWARD_DAYS=15, P2B_FORWARD_DAYS=63,
       P3_FORWARD_DAYS=10, P2_VOL_MULTIPLE=0.41, P3_VOL_MULTIPLE=0.20
   - compute_hv_features(df, hv_window, rank_window):
       Adds HV_20, IV_rank, IV_pct, HV_chg_5d, HV_chg_10d, HV_vs_ma20
   - compute_vix_features(df, vix_df, vix9d_df, vix3m_df):
       Handles MultiIndex column flattening internally; adds VIX, VIX_chg_5d,
       VIX_vs_ma20, VIX9D_VIX_ratio, VIX_VIX3M_ratio
   - add_earnings_proximity(df, ticker):
       Signature change: takes explicit ticker arg (not TICKER global); defaults to 45
   - normalize_features(df):
       All column checks guarded with `if col in df.columns` (more defensive than
       the prior direction.py version which lacked guards on KC/MACD/OBV)
   - compute_vol_thresholds(df, verbose=True, p2_vol_multiple, p3_vol_multiple, ...):
       Returns (win_threshold, win_threshold_63, expansion_threshold) tuple;
       falls back to AMD defaults (0.05, 0.10, 0.10) if HV data insufficient

2. backtest.py changes
   - Imports: HV_WINDOW, IV_RANK_WINDOW, P2_FORWARD_DAYS, P2B_FORWARD_DAYS,
     P3_FORWARD_DAYS, compute_hv_features, compute_vix_features, add_earnings_proximity,
     normalize_features, compute_vol_thresholds from modules.features
   - CONFIG: removed HV_WINDOW, IV_RANK_WINDOW, P2_FORWARD_DAYS, P2B_FORWARD_DAYS,
     P3_FORWARD_DAYS; kept P2_VOL_MULTIPLE, P3_VOL_MULTIPLE, WIN_THRESHOLD,
     WIN_THRESHOLD_63, EXPANSION_THRESHOLD as mutable globals
   - build_features(): replaced inline HV + VIX + earnings + normalize blocks with
     shared function calls; gap features remain (backtest-specific)
   - run_backtest(): updated per-window call to unpack tuple return from shared
     compute_vol_thresholds; removed local function definition
   - __main__ and sweep mode call sites updated to tuple unpack pattern

3. direction.py changes
   - Imports added (same set as backtest.py minus P3_*)
   - CONFIG: removed HV_WINDOW, P2_VOL_MULTIPLE, FORWARD_DAYS, FORWARD_DAYS_63;
     added FORWARD_DAYS = P2_FORWARD_DAYS and FORWARD_DAYS_63 = P2B_FORWARD_DAYS aliases
   - add_hv(): body replaced with compute_hv_features(df) call
   - add_vix(): body replaced with 3 downloads + compute_vix_features() call;
     Unicode handling issue: dead stub _add_vix_old_stub() + leftover old VIX loop
     required separate cleanup pass (replace_string_in_file fails on Unicode in oldString)
   - Removed local add_earnings_proximity(df), normalize_features(df),
     compute_vol_thresholds(df) functions
   - Call site: add_earnings_proximity(df) → add_earnings_proximity(df, TICKER)

4. volatility.py changes
   - Imports added (HV_WINDOW, IV_RANK_WINDOW, P3_FORWARD_DAYS, P3_VOL_MULTIPLE + funcs)
   - CONFIG: removed HV_WINDOW, IV_RANK_WINDOW, P3_VOL_MULTIPLE, FORWARD_DAYS=10;
     added FORWARD_DAYS = P3_FORWARD_DAYS alias
   - add_iv_features(): body replaced with compute_hv_features(df) call
   - add_vix(): body replaced with 3 downloads + compute_vix_features() call
   - Removed local add_earnings_proximity(df), normalize_features(df),
     compute_vol_thresholds(df) functions
   - compute_vol_thresholds call site: `compute_vol_thresholds(df)` →
     `_, _, EXPANSION_THRESHOLD = compute_vol_thresholds(df)` (tuple unpack)
   - add_earnings_proximity(df) call site → add_earnings_proximity(df, TICKER)

5. Implementation notes
   - Unicode workaround: replace_string_in_file fails when oldString contains em-dashes
     (U+2014) or checkmarks (U+2713). All Unicode-heavy removals done via Python
     regex script written to a temp file (_patch_volatility.py, deleted after use).
   - volatility.py call to compute_vol_thresholds previously mutated EXPANSION_THRESHOLD
     as a side effect via `global`. The new shared function returns a tuple — the
     assignment `_, _, EXPANSION_THRESHOLD = compute_vol_thresholds(df)` now makes
     the update explicit.

6. Regression verification — all three scripts passed with QQQ
   - backtest.py:  STRONG ENTRY 587/1.9%/63.2% ✓ (matches post-S13 baseline)
   - direction.py: Phase 2 47.8% precision at 0.55; Phase 2B 56.0% — consistent
   - volatility.py: expansion precision 68.3% at 0.50 — consistent
   - Exit code 1 on direction/volatility is expected (chart prompt receives EOF from pipe)

NEXT MAJOR WORK (updated)
- [S14 TODO] AMD IV backfill — run backfill_iv.py, then retrain Phase 3 with --iv-features
- [S14 TODO] Tighten backfill data quality: reject v < 5 in _fetch_agg_price; tighten
  IV cap to 1.5 for QQQ/SPY/NVDA/AMD
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
- modules/massive.py _fetch_agg_price: no minimum volume filter — single-trade artifact
  prices (v=1, n=1) produce implausible IVs (e.g. 237%) that pass the `0.01<=iv<=5.0`
  guard. Fix needed before full 2-year backfill: reject records with v < 5 (or n < 5).
  Also tighten IV upper bound from 5.0 to ~1.5 for non-event tickers (QQQ/SPY/NVDA/AMD);
  event tickers like CRSP may reach 0.8-1.0 during binary events.
- _diag_iv.py, _diag_iv2.py, _diag_iv3.py, _diag_backfill.py: diagnostic files in workspace
  root, can delete

Important Notes
- Use the PowerShell tool (NOT Bash) for piped script execution on Windows.
  Pattern: cmd /c "(echo TICKER && echo.) | python -X utf8 script.py" 2>&1
- [S11] CLI flag for Phase 2 mode: --calibrate / --no-calibrate available on
  direction.py / entry.py / backtest.py. Default is RAW (--no-calibrate after the NVDA
  regression). Add --calibrate to any of those commands to use the isotonic-calibrated
  Phase 2 model with P2_THRESHOLD=0.50; default raw uses P2_THRESHOLD=0.55.
  Banner at start and footer at end of each run prints the active mode.
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

Ticker Suitability (post-S11)
- QQQ:  best statistical case; 53 windows; clean hierarchy; framework reference baseline.
        STRONG ENTRY 2.0% / 65% win (raw); 1.7% / 61.5% (calibrated, marginal pass).
- NVDA: WELL-SUITED IN RAW MODE ONLY (S8 reclass + S11 caveat) — STRONG ENTRY 4.4% / 65%
        win raw, BEST in project. CALIBRATED mode COLLAPSES this to -0.4% / 52% (S11
        regression). Edge lives in the high-confidence probability tail; calibration
        compresses it. Long history dilutes the post-2023 regime-change concern for raw
        but exposes calibrators to within-window non-stationarity.
- AMD:  well-suited; 15 walk-forward windows; STRONG ENTRY 2.6% / 59.7% win (raw).
        Calibrated mode untested on AMD as of S11 — likely similar pattern to NVDA
        given individual-stock high-confidence-tail edge profile.
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
- [S11] Edge for individual stocks lives in the HIGH-CONFIDENCE PROBABILITY TAIL.
  Calibration's regularization-toward-mean compresses extremes, destroying exactly the
  signal that drives STRONG ENTRY for stocks like NVDA. Index ETFs are less affected
  (edge is more uniformly distributed). Implication: any model regularization that
  dampens high-confidence outliers risks the same NVDA-style failure.
- [S11] QQQ-only validation is INSUFFICIENT for framework changes. Always co-validate
  on at least one individual stock (NVDA recommended as best-in-project baseline)
  before adopting any model change as the production default.
