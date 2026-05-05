---
name: AMD Options Trading ML Pipeline
description: Context for AMD options swing trading ML enhancement project — phases, status, and design decisions
type: project
originSessionId: 537663a3-00dd-452f-b617-42c29677d60f
---
Goal: Supplement a chart-based swing trading strategy for AMD 6-12 month Call Options with ML-derived signals to improve entry/exit timing and signal confidence (not replace strategy).

**Current Strategy (Webull-based):**
- Instruments: AMD 6-12 month Call Options
- Indicators: RSI (6, 14, 23), MA (20, 50, 100, 200), EMA (8, 21, 34, 55, 89 — Fibonacci), Keltner Channels, OBV, MACD, Stochastic Oscillator
- Candle style: Gap-based coloring (close vs previous close), hollow/filled based on open vs close

**Confirmed indicator settings:**
- KC_EMA = 21, KC_ATR = 14, KC_MULT = 2.0
- RSI_PERIODS = [6, 14, 23]
- MA_PERIODS = [20, 50, 100, 200]
- EMA_PERIODS = [8, 21, 34, 55, 89]
- STOCH_K = 14, STOCH_D = 3, STOCH_SMOOTH = 3

**Phase 1 — COMPLETE (`amd_indicators.py` → renamed entry_phase1.py)**
- Pulls AMD OHLCV from 2018-01-01 via yfinance
- Calculates all indicators using `ta` library
- Interactive prompt for ticker, start date, end date at runtime (end date defaults to today)
- Outputs dark-theme 5-panel dashboard chart matching Webull style
- Saves `{ticker}_indicators.csv` with a `Ticker` column for downstream scripts
- Fully ticker-agnostic — works on any ticker with sufficient history

**Phase 2 — COMPLETE (`entry_phase2.py`)**
- Loads `{ticker}_indicators.csv`, reads ticker/dates automatically from the file
- Model: Logistic Regression (C=0.1, class_weight="balanced") — switched from Random Forest due to overfitting on small dataset
- Training data: 2018–present (~1,600 rows after extending from 2022)
- Features: normalized MA/EMA/KC ratios, MACD normalized by price, OBV 5d change, HV_20, VIX features, SOX relative strength (5d/20d), Days_to_earnings
- Normalization: all price-level indicators converted to ratios (e.g. Close/MA_20 - 1) for scale invariance
- Target: AMD closes ≥5% higher in 15 trading days (binary)
- Performance: 50.4% win precision at 0.55 threshold vs 37.8% base rate (~12.6pt edge)
- Threshold marker: auto-marks best precision threshold in sweep
- Outputs: classification report, threshold sweep (0.30–0.60), top 10 coefficients with direction
- Key coefficients: RSI_23 bullish, price_vs_kc_lower bearish, price_vs_ma200 bearish, SOX_RS_20d bullish, Days_to_earnings bullish — classic "dip in uptrend" pattern
- Note: install lxml (`pip install lxml`) for earnings dates to work

**Phase 3 — COMPLETE (`entry_phase3.py`)**
- Predicts whether HV (IV proxy) expands ≥10% over next 10 trading days
- Features: HV_20, IV_rank, IV_pct, HV trend (5d/10d change, vs MA20), VIX features, Days_to_earnings, normalized price indicators
- IV rank: (HV_20 - 52w_low) / (52w_high - 52w_low) — 0=cheap, 1=expensive
- IV percentile: % of past year where HV was below current level
- Performance: 59% expansion precision at 0.60 threshold vs 27.8% base rate (~31pt edge) — much stronger than Phase 2 because vol is more predictable than direction
- Train/test gap: 74.5% vs 71.3% — excellent generalization
- Key coefficients: HV_20 bearish (mean reversion), HV_chg_10d bullish (vol momentum), VIX_vs_ma20 bullish
- Outputs: threshold sweep, top 10 coefficients, IV signal summary with plain-English recommendation
- Signal summary covers all 6 IV rank × signal combinations explicitly
- df_full pattern: saves full dataset before target truncation for signal summary and HV chart

**Combined Signal — COMPLETE (`entry_signal.py`)**
- Trains both models internally, outputs single consolidated recommendation
- Decision framework:
  - Win + Expansion → STRONG ENTRY
  - Win + Contraction → CAUTION (smaller size or wait)
  - Loss + Expansion → STAY OUT
  - Loss + Contraction → STAY OUT
- Thresholds: P2_THRESHOLD=0.55, P3_THRESHOLD=0.60 (best precision from each model)
- This is the primary daily-use script — run each morning before acting on a chart setup

**Phase 4 (planned):** Options-specific layer — delta, theta, and IV-aware position sizing.

**Tech stack:** yfinance, pandas, ta, matplotlib, scikit-learn, lxml

**Key design decisions:**
- Switched from Random Forest to Logistic Regression (less overfitting on ~1,600 rows)
- Extended history from 2022 to 2018 to increase training data (~600 → ~1,600 rows)
- HV used as IV proxy (real IV data from Tradier discussed but deferred — HV adequate for Phases 2/3)
- All scripts fully ticker-agnostic via interactive ticker prompt
- Phase 2/3 read ticker and dates from CSV automatically (no prompt needed)
- Test size: 20% held out as most recent data (time-based split, not random)
- Regularization: C=0.1 on logistic regression

**Why:** Practical deployment focus, not academic. Keep models simple and interpretable.
**How to apply:** User has Python + options trading experience. No need to explain basics. Frame suggestions in terms of trading impact.
