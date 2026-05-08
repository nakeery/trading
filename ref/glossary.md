# KEY TERMS

Here's a layered walkthrough — each layer builds on the last. I'll use the QQQ readings from 2026-05-07 (the latest pipeline run) as a running example so
  the numbers are real, not made up.

  ---
  1. Options basics

  An option is a contract giving you the right (but not obligation) to buy or sell a stock at a specific price by a specific date.

  - Call option: right to BUY 100 shares at a fixed price (the "strike"). You buy calls when you think the price will go UP.
    - Example: QQQ trades at $500. You buy a $510 call expiring in 6 months for $20/share ($2,000 total). If QQQ rises to $560, the call is worth ~$50
  ($5,000 — a profit of $3,000). If QQQ stays at or below $510 by expiration, the call expires worthless and you lose $2,000.
  - Put option: right to SELL — bet on the price going DOWN. (The pipeline doesn't trade these; you just need to know they exist because their prices feed
  the "skew" measurement.)
  - Strike price: the price at which you can exercise the option.
  - DTE (Days to Expiration): how long until the option expires. The pipeline targets 180–365 DTE (6–12 months).
  - Premium: what you pay for the option. Your max loss.
  - ITM / ATM / OTM:
    - In-the-money (ITM): option has intrinsic value (call with strike below stock price)
    - At-the-money (ATM): strike ≈ stock price
    - Out-of-the-money (OTM): no intrinsic value yet (call with strike above stock price)
  - LEAPS: long-dated options (>1 year). The pipeline's 6–12 month target is essentially LEAPS-style.

  ---
  2. Volatility — the heart of the pipeline

  Most beginners assume options trading is about predicting direction. It's actually MORE about predicting volatility — how much a price moves around,
  regardless of which way.

  Why? Because option prices are mostly determined by expected volatility. If you buy a call and the stock moves up but slowly, the option might still lose
  value (because volatility was lower than priced in). If volatility "expands," the option gains value even before any directional move.

  The two volatilities

  - Historical Volatility (HV) — backward-looking. Measured from actual past price moves. The pipeline uses HV-20 = annualized standard deviation of the
  last 20 days of returns.
    - Example: QQQ HV-20 ≈ 14% means "scaled up to a year, QQQ's recent daily wiggles correspond to a 14% standard deviation."
  - Implied Volatility (IV) — forward-looking. The volatility level "baked into" current option prices.
    - Example: QQQ option prices on 2026-05-07 imply 22% vol over the next 30 days.

  IV/HV ratio — premium richness

  This is the single most important number in entry.py. It compares what's priced in (IV) vs what's been happening (HV).

  ┌─────────────┬───────────┬──────────────────────────────────────────────────────┐
  │    IV/HV    │   Label   │                    Interpretation                    │
  ├─────────────┼───────────┼──────────────────────────────────────────────────────┤
  │ < 0.85      │ cheap     │ Options priced below realized — favorable for buyers │
  ├─────────────┼───────────┼──────────────────────────────────────────────────────┤
  │ 0.85 – 1.20 │ fair      │ Roughly priced                                       │
  ├─────────────┼───────────┼──────────────────────────────────────────────────────┤
  │ 1.20 – 1.40 │ rich      │ Options expensive vs reality                         │
  ├─────────────┼───────────┼──────────────────────────────────────────────────────┤
  │ ≥ 1.40      │ very rich │ Gate triggers — STRONG ENTRY → CAUTION               │
  └─────────────┴───────────┴──────────────────────────────────────────────────────┘

  Example: QQQ 2026-05-07 had HV-20 ≈ 14.5% but ATM IV ≈ 22% → IV/HV = 1.52 (very rich). Stock has been calm but the options market is pricing a possible
  storm. If you bought calls, you'd need a big move just to break even on the inflated premium.

  ATM IV at 30 DTE

  The "standard" reference point because:
  - ATM strikes have the most reliable IV (no missing/junk data)
  - 30 days matches the HV-20 timeframe (~20 trading days = ~30 calendar days)

  VIX, VIX9D, VIX3M

  - VIX: implied vol of the S&P 500 options ~30 days out. The famous "fear gauge."
    - VIX 12 = complacent · VIX 20 = average · VIX 30+ = stressed · VIX 40+ = panic
  - VIX9D: 9-day version (very near-term)
  - VIX3M: 3-month version (longer-term)
  - The pipeline uses ratios (VIX9D/VIX and VIX/VIX3M) as features. Ratio > 1 = "near-term fear higher than long-term" = stress.

  Term structure (per-ticker version of VIX ratios)

  Ratio of front-month IV to back-month IV for the specific ticker.

  ┌─────────────┬──────────────────────┬──────────────────────────────────────────────────────────┐
  │    Term     │        Label         │                         Meaning                          │
  ├─────────────┼──────────────────────┼──────────────────────────────────────────────────────────┤
  │ < 0.95      │ contango             │ Back-month higher (NORMAL — uncertainty grows over time) │
  ├─────────────┼──────────────────────┼──────────────────────────────────────────────────────────┤
  │ 0.95 – 0.98 │ slight contango      │ Mostly normal                                            │
  ├─────────────┼──────────────────────┼──────────────────────────────────────────────────────────┤
  │ 0.98 – 1.02 │ noise                │ No clear regime                                          │
  ├─────────────┼──────────────────────┼──────────────────────────────────────────────────────────┤
  │ 1.02 – 1.05 │ slight backwardation │ Mild near-term stress emerging                           │
  ├─────────────┼──────────────────────┼──────────────────────────────────────────────────────────┤
  │ > 1.05      │ backwardation        │ STRESS — market expects near-term storm                  │
  └─────────────┴──────────────────────┴──────────────────────────────────────────────────────────┘

  Example: QQQ 2026-05-07 = 1.02 (slight backwardation). The market sees near-term concerns starting to enter the chain.

  ---
  3. Market sentiment indicators (Greeks & flow)

  The "Greeks" measure how option prices react to various inputs. You only need to know delta for this pipeline.

  - Delta: how much the option price moves per $1 move in the stock.
    - ATM call: delta ≈ 0.50 (option moves $0.50 per $1 stock move)
    - Deep ITM call: delta → 1.0 (moves like the stock)
    - Deep OTM call: delta → 0 (barely reacts)
    - 25Δ: a strike with delta ≈ 0.25 — meaningfully OTM, e.g., a put 5–10% below current price

  25Δ skew — crash fear

  Difference in IV between OTM puts (25Δ put) and OTM calls (25Δ call).
  - Positive skew = puts pricier than calls = market pricing more downside risk than upside potential
  - Higher = more crash fear

  Example: QQQ 2026-05-07 = +0.037. Modest put-side fear, normal-ish.

  Open Interest (OI)

  Number of option contracts currently open (not the number traded today — that's volume).

  Put/Call OI ratio

  Total put OI ÷ total call OI in the chain.
  ▎ 1: more puts open → bearish positioning
  - < 1: more calls open → bullish positioning

  Example: QQQ 2026-05-07 = 0.66 → slight call bias, mildly bullish positioning.

  ---
  4. Statistics & ML concepts

  Logistic Regression

  The simplest probability-output model. Takes inputs (RSI, HV, sector strength, etc.) and outputs a number between 0 and 1 — interpreted as "probability of
   the event happening." It's linear and interpretable: every feature has a weight you can read directly.

  Example: Phase 2 takes 30+ features and outputs "0.61 probability that QQQ is up materially in the next 15 days."

  Threshold

  A cutoff applied to the probability output. Pipeline uses 0.55 for direction (Phase 2/2B) and 0.60 for vol (Phase 3).
  - Probability ≥ 0.55 → fire WIN signal
  - Probability < 0.55 → no signal

  Class weight balanced

  On most days, no signal fires (most days are "boring"). Without balancing, a model can score high accuracy by always predicting "no signal." Balancing
  forces the model to weight the rare WIN cases as heavily as the common no-signal cases — so it actually learns the WIN pattern.

  Train/test split (time-based)

  Train the model on early data (80%), test on recent held-out data (20%). The pipeline does this chronologically, not randomly. Why: financial data points
  are correlated through time. A random split would let the model "peek at the future" by training on data points adjacent to test points. Time-based split
  eliminates this.

  Lookahead bias

  Accidentally using future information at training time. The cardinal sin in time-series ML. The pipeline avoids it through time-based splits and
  walk-forward backtests.

  Walk-forward backtest

  Simulate live trading by repeatedly training on history up to date T, then predicting period T+1, then sliding forward. Pipeline runs 53 such windows on
  QQQ (2001–2026). It's the closest you can get to "what would have actually happened" without live trading.

  Precision

  Of all the predictions the model called WIN, what fraction actually were WINs?
  - Example: model predicts WIN on 100 days; 65 of those days really were WINs → precision = 65%

  Base rate

  The natural frequency of the event without any model — what you'd get from random guessing.
  - Example: if 45% of all days are WINs naturally, base rate = 45%
  - Model precision of 65% beats base rate by 20pp → that's the model's edge

  Brier score & ECE — calibration metrics

  - Brier score: averages how far off the model's probabilities are from reality. Lower = better.
  - ##### Expected Calibration Error (ECE): bucket predictions ("predictions in 70–80% range") and compare predicted vs actual frequency. If model says 70% but
  reality is 55% in that bucket, the bucket is overconfident. ECE averages this gap.

  Calibration

  The property: "when the model says 70%, it really happens 70% of the time." The pipeline's Phase 2 (raw) is overconfident — says 60% but actual is ~48%.
  The pending S9 work (Direction 1) would post-process the probabilities to align them with reality, then re-tune the threshold.

  Why this matters in practice: if "60%" actually means 48%, then the 0.55 threshold is firing signals on actual ~43% setups. Calibrating fixes this.

  ---
  5. Putting it all together — the 4 SIGNAL labels

  Three models each produce a WIN / no-signal call:

  ┌────────────────┬────────────────────────────────────────────┬───────────┐
  │     Model      │                  Question                  │ Threshold │
  ├────────────────┼────────────────────────────────────────────┼───────────┤
  │ Phase 2 (15d)  │ Will price be up materially in 15 days?    │ 0.55      │
  ├────────────────┼────────────────────────────────────────────┼───────────┤
  │ Phase 2B (63d) │ Will price be up materially in 63 days?    │ 0.55      │
  ├────────────────┼────────────────────────────────────────────┼───────────┤
  │ Phase 3 (IV)   │ Will implied vol expand over next 10 days? │ 0.60      │
  └────────────────┴────────────────────────────────────────────┴───────────┘

  Combining them produces the SIGNAL:

  - STRONG ENTRY — both direction models agree AND vol likely expanding. Vol expansion inflates premium (good for option buyers). → FULL position.
  - CAUTION — both direction models agree BUT vol likely contracting. Even if direction is right, premium decays as IV shrinks. → REDUCED position.
  - SHORT-TERM ONLY — short-term direction looks good but medium-term thesis didn't confirm. Riskier. → REDUCED position.
  - STAY OUT — short-term direction signal is missing. Don't trade.

  Then the IV/HV gate applies a final overlay: if SIGNAL = STRONG ENTRY but IV/HV ≥ 1.40 (very rich premium), downgrade to CAUTION. Reason: when premium is
  that inflated, you need a bigger move to break even — even a "good" trade often loses.

  ---
  What you'll see in entry.py output

  The OPTIONS-MARKET CHECK section reports the live numbers:
  - ATM IV (e.g., 22.0%) — what the market expects vol to be
  - IV/HV ratio (e.g., 1.52 → "very rich") — premium richness
  - 25Δ skew (e.g., +0.037) — crash fear
  - Term structure (e.g., 1.02 → "slight backwardation") — near-term stress
  - Put/Call OI (e.g., 0.66) — positioning bias

  These are diagnostic — they help you understand why the model said what it said and let you override the conclusion if the options market is signaling
  something the model can't see (like a geopolitical shock).


# PROBABILITY TABLE WALKTHROUGH


  Good — now I can show you the exact format your diagnostic prints. The numbers below are illustrative (matched to the known QQQ ECE of 6.99% and the overconfidence pattern), since I'd need to actually run
  direction.py on QQQ to get your literal output. The format and the patterns are real.

  The format your terminal will show

  [Raw Logistic Regression]
    Brier: 0.2483  ECE: 0.0699  (lower=better; 0=perfect)
    Bin              N     Pred   Actual       Gap
    0.1-0.2         12    16.5%    22.0%     -5.5% under
    0.2-0.3         78    25.8%    30.5%     -4.7%
    0.3-0.4        196    35.2%    39.5%     -4.3%
    0.4-0.5        287    45.1%    43.0%     +2.1%
    0.5-0.6        312    55.2%    47.5%     +7.7% over
    0.6-0.7        198    64.7%    52.5%    +12.2% over
    0.7-0.8         88    73.8%    58.5%    +15.3% over
    0.8-0.9         28    82.5%    60.7%    +21.8% over
    0.9-1.0          6    91.5%    66.7%    +24.8% over

  Reading the columns

  ┌────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │ Column │                                                                        What it means                                                                        │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Bin    │ The probability range this row represents. Predictions of 50–60% land in 0.5-0.6.                                                                           │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ N      │ How many test-set predictions fell in this bin. Most QQQ predictions cluster in the middle (0.4-0.5 and 0.5-0.6 have 287 and 312 — over half the test set). │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Pred   │ Average predicted probability of the predictions in this bin. So in 0.5-0.6, the model said an average of 55.2%.                                            │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Actual │ Actual win rate for those same predictions. Of the 312 predictions in 0.5-0.6, only 47.5% really were WINs.                                                 │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Gap    │ Pred − Actual. Positive = overconfident (model said more than reality). Negative = underconfident.                                                          │
  ├────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Marker │ "over" appears if gap > +5pp; "under" if gap < −5pp; blank otherwise. Anything marked is a flag.                                                            │
  └────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  Reading the rows — the overconfidence story

  Walk down the gap column. Two patterns jump out:

  Pattern 1: Underconfident at low probabilities (rare)
  0.1-0.2         12    16.5%    22.0%     -5.5% under
  0.2-0.3         78    25.8%    30.5%     -4.7%
  0.3-0.4        196    35.2%    39.5%     -4.3%
  When the model says "low chance of WIN," the actual frequency is a bit higher than predicted. Mild — and these bins together hold ~286 predictions, well below the threshold (0.55) so they don't affect
  signals anyway.

  Pattern 2: Overconfident at high probabilities (the problem)
  0.5-0.6        312    55.2%    47.5%     +7.7% over
  0.6-0.7        198    64.7%    52.5%    +12.2% over
  0.7-0.8         88    73.8%    58.5%    +15.3% over
  0.8-0.9         28    82.5%    60.7%    +21.8% over
  0.9-1.0          6    91.5%    66.7%    +24.8% over
  The gap grows as predicted probability rises. The model becomes increasingly disconnected from reality at the high end.

  This is the classic class-balanced-LR signature: the model spreads predictions across the full [0, 1] range, but its sense of "high probability" is calibrated to a 50/50 baseline rather than the actual ~45%
  WIN base rate. So everything in the upper half gets pushed too high.

  Why this matters for your threshold

  The threshold is 0.55. Look at where 0.55 falls in the table:

  0.5-0.6        312    55.2%    47.5%     +7.7% over

  312 predictions land here — and their actual win rate is 47.5%, not 55%. Some land in 0.6-0.7 (actual 52.5%) and 0.7-0.8 (actual 58.5%). The whole "over the threshold" zone has actual win rates well below
  the predicted rates.

  A signal that fires "with 57% confidence" is, in reality, ~48% likely to win. The threshold is doing roughly what you'd want from a 0.48 cutoff on calibrated probabilities — looser than intended.

  What the calibrated table would look like

  After running through CalibratedClassifierCV (isotonic, 5-fold), the same test set rebins:

  [Calibrated (Isotonic, 5-fold CV)]
    Brier: 0.2381  ECE: 0.0156  (lower=better; 0=perfect)
    Bin              N     Pred   Actual       Gap
    0.2-0.3         60    26.5%    27.8%     -1.3%
    0.3-0.4        220    36.0%    38.0%     -2.0%
    0.4-0.5        380    45.3%    44.5%     +0.8%
    0.5-0.6        360    53.5%    51.0%     +2.5%
    0.6-0.7        145    62.8%    60.5%     +2.3%
    0.7-0.8         35    72.5%    70.0%     +2.5%
    0.8-0.9          5    82.0%    80.0%     +2.0%

  Three things changed:
  1. All gaps shrank to ±2.5pp. No more "over" or "under" markers anywhere. ECE = 1.56%.
  2. The extreme bins got compressed. No predictions at all below 0.2 or above 0.9 (isotonic collapsed those tails toward the body).
  3. The middle inflated. The calibrator pulled the formerly-overconfident upper bins down. Predictions that were in 0.6-0.7 raw mostly land in 0.5-0.6 calibrated. So if you kept threshold at 0.55, you'd fire
  fewer signals — because what raw called "62%" is now honestly called "55%."

  This is why Direction 1 (S9 pending) involves both steps: calibrate the model AND re-tune the threshold against the new honest scale. Otherwise calibration alone would silently shift signal volume.

  How to read your own output when you actually run it

  Your eyes should go to:
  1. The Brier and ECE numbers at the top. Brier ≈ 0.25 is roughly random; lower is better. ECE > 5% = clearly miscalibrated.
  2. Marker words ("over" / "under"). Quick visual scan — anywhere they appear is where the model is lying about its certainty.
  3. The N column at and above your threshold (0.55 for direction). That tells you how many signals you're actually firing on — if 0.5-0.6 has 312 and 0.6-0.7 has 198, you're firing on 510+ signals. Compare
  predicted vs actual in those rows: that's your signal-zone calibration.
  4. The shape of the gap column. Growing positively as predicted probability rises = overconfidence (Phase 2's pattern). Random scatter = noise. Growing negatively = underconfidence (rare).


  # ISOTONIC

  The word itself

  Isotonic = "preserving order." If raw probability A < raw probability B, then calibrated A ≤ calibrated B. The ranking is sacred — calibration only adjusts absolute values, never reverses judgments.

  This is the key property: if the raw model says "trade A is more likely a WIN than trade B," calibrated still says that. You're not changing what the model thinks is best; you're correcting how confident the
   numbers claim to be.

  What it produces — a staircase

  The output is a step function that maps raw probabilities to calibrated probabilities:

  calibrated probability
    ^
  1 |
    |                     .____.
    |                _____/
    |          .____/
    |     ____/
    |    /
  0 |___/
    +---|---|---|---|---|---|------>  raw probability
    0   0.2 0.4 0.6 0.8 1.0

  Each flat segment ("step") is a range of raw probabilities that all map to the same calibrated value. Wider step = more compression in that region.

  It's non-parametric — it doesn't assume any particular shape (linear, sigmoid, etc.). It fits whatever shape the data actually shows.

  How it's fit — Pool Adjacent Violators (PAV)

  The classic algorithm. Walk through it with a tiny example:

  Step 1: Sort all (raw_pred, actual_outcome) pairs by raw_pred, then bucket and compute actual win rate per bucket:

  ┌─────────┬──────────────┬─────────────────┐
  │ Raw bin │ Avg raw pred │ Actual win rate │
  ├─────────┼──────────────┼─────────────────┤
  │ A       │ 0.20         │ 22%             │
  ├─────────┼──────────────┼─────────────────┤
  │ B       │ 0.40         │ 45%             │
  ├─────────┼──────────────┼─────────────────┤
  │ C       │ 0.55         │ 40%             │
  ├─────────┼──────────────┼─────────────────┤
  │ D       │ 0.70         │ 55%             │
  ├─────────┼──────────────┼─────────────────┤
  │ E       │ 0.85         │ 62%             │
  └─────────┴──────────────┴─────────────────┘

  Step 2: Scan for violations — places where actual win rate drops as raw probability rises. The data should be non-decreasing for calibration to make sense; any drop is a violation.

  Here B → C goes 45% → 40%. That's a violation.

  Step 3: Merge violating buckets by combining their counts and recomputing the actual rate. If B and C each have 100 samples:

  ┌──────────────┬───────────────────────┐
  │     Bin      │   Calibrated value    │
  ├──────────────┼───────────────────────┤
  │ A            │ 22%                   │
  ├──────────────┼───────────────────────┤
  │ B + C merged │ (45 + 40) / 2 = 42.5% │
  ├──────────────┼───────────────────────┤
  │ D            │ 55%                   │
  ├──────────────┼───────────────────────┤
  │ E            │ 62%                   │
  └──────────────┴───────────────────────┘

  Now check: 22, 42.5, 55, 62 — all non-decreasing. Done.

  Step 4: Apply the mapping at predict time:
  - Raw 0.20 → calibrated 22%
  - Raw 0.40 → calibrated 42.5%
  - Raw 0.55 → calibrated 42.5% ← same as 0.40 — this is the compression
  - Raw 0.70 → calibrated 55%
  - Raw 0.85 → calibrated 62%

  If there are multiple violations chained together, PAV keeps merging until the whole sequence is non-decreasing — sometimes pooling many buckets into one large flat step.

  Why it sometimes compresses too much (the Phase 2B issue)

  If the data has many violations close together, PAV merges aggressively. Noisy data triggers more violations, which trigger more merges, which create wider flat steps.

  Phase 2B is 63-day direction — at that horizon, today's features have a noisier connection to the outcome than 15-day Phase 2 does. More noise → more violations → more pooling.

  Result on QQQ Phase 2B: 1002 of 1304 calibrated samples landed in a single output bin. The calibrator essentially said "I can't distinguish anything in the middle of the range — these all map to the same
  calibrated probability." That improves ECE on paper (predictions match actual frequencies in aggregate) but destroys signal differentiation: you can't put a meaningful threshold on a model whose output
  collapses to one value for most of its range.

  Why isotonic works fine for Phase 2

  Phase 2 is 15-day direction — much less noise, fewer violations, less aggressive merging. context.md notes the calibration was "minimal compression": ECE dropped 6.99% → 1.56% without flattening the output
  range. Predictions still spread across many calibrated values, so the threshold still differentiates.

  Comparison to Platt scaling

  ┌──────────────────┬───────────────────────────────────────────┬───────────────────────────────────────────────┐
  │                  │                 Isotonic                  │                     Platt                     │
  ├──────────────────┼───────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ Shape            │ Step function (staircase)                 │ Smooth sigmoid (S-curve)                      │
  ├──────────────────┼───────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ Parameters       │ Many (one per merged bucket)              │ Two (slope, intercept)                        │
  ├──────────────────┼───────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ Flexibility      │ High — fits any monotonic shape           │ Low — only sigmoid-shaped miscalibration      │
  ├──────────────────┼───────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ Compression risk │ Yes (when data is noisy)                  │ No — sigmoid is always smoothly rising        │
  ├──────────────────┼───────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ Data needed      │ More (one per bucket)                     │ Less (two params)                             │
  ├──────────────────┼───────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ Best for         │ Plenty of data, possibly complex patterns │ Smaller data or smooth uniform overconfidence │
  └──────────────────┴───────────────────────────────────────────┴───────────────────────────────────────────────┘

  Platt is the candidate fix for Phase 2B specifically because its sigmoid can't compress — every distinct raw probability gets a distinct calibrated probability. It might not fit as tightly, but it preserves
  the differentiation the threshold needs.

  The "5-fold CV" wrapper

  The pipeline calls CalibratedClassifierCV(method="isotonic", cv=5). The CV part means:

  1. Split training data into 5 folds.
  2. For each fold: train LR on the other 4 folds, predict on this fold (data the LR hasn't seen).
  3. Pool all those held-out (predicted, actual) pairs.
  4. Fit the isotonic mapping on the pooled held-out pairs.

  Why hold-out? If you fit the calibrator on data the LR has already memorized during training, you're calibrating against the LR's training noise, not its real predictive behavior. Held-out predictions give
  honest "this is what the model does on unseen data" probability estimates. That's the only thing worth calibrating against.

  TL;DR

  - Isotonic = staircase mapping that preserves rank order
  - Built by merging adjacent buckets that violate monotonicity (PAV algorithm)
  - Non-parametric — adapts to whatever miscalibration shape the data shows
  - Risk: noisy data → many merges → predictions collapse into few calibrated values (compression)
  - Phase 2 (15d): minimal compression, ECE 6.99% → 1.56% — works
  - Phase 2B (63d): heavy compression, 1002/1304 in one bin — kills threshold differentiation, hence Platt as candidate


# PLATT SCALING

The word itself

  Platt scaling is named after John Platt, who proposed it in 1999 to convert SVM outputs into probabilities. The idea is general: take a raw model output and pass it through a sigmoid function to produce a
  calibrated probability. Sklearn calls this method "sigmoid" (in CalibratedClassifierCV(method="sigmoid")).

  What it produces — a smooth S-curve

  The output is a sigmoid (logistic) curve mapping raw probabilities to calibrated probabilities:

  calibrated probability
    ^
  1 |                      ___________
    |                  ___/
    |              ___/
    |          ___/
    |      ___/
    |  ___/
  0 |_/
    +---|---|---|---|---|---|------>  raw probability
    0   0.2 0.4 0.6 0.8 1.0

  The curve has two knobs:
  - Slope (A) — how steeply it rises through the middle
  - Intercept (B) — where the midpoint sits horizontally

  Just two parameters. Compare to isotonic, which has one parameter per merged bucket (potentially many). Platt is parametric — it assumes the miscalibration takes a sigmoid shape and only fits two numbers.

  How it's fit — minimizing log-loss

  Given calibration data — pairs of (raw_pred, actual_outcome) — Platt finds the (A, B) that minimize log-loss between the calibrated probabilities and the actual outcomes:

  calibrated_prob = 1 / (1 + exp(A × raw_pred + B))

  The fitting routine just walks (A, B) toward their optimal values via gradient descent. Done in milliseconds, doesn't merge anything, doesn't decide groupings.

  Worked example

  Let me reuse the same QQQ-like data from the isotonic walkthrough so you can compare directly:

  ┌─────────┬──────────────┬─────────────────┐
  │ Raw bin │ Avg raw pred │ Actual win rate │
  ├─────────┼──────────────┼─────────────────┤
  │ A       │ 0.20         │ 22%             │
  ├─────────┼──────────────┼─────────────────┤
  │ B       │ 0.40         │ 45%             │
  ├─────────┼──────────────┼─────────────────┤
  │ C       │ 0.55         │ 40%             │
  ├─────────┼──────────────┼─────────────────┤
  │ D       │ 0.70         │ 55%             │
  ├─────────┼──────────────┼─────────────────┤
  │ E       │ 0.85         │ 62%             │
  └─────────┴──────────────┴─────────────────┘

  Platt fits a sigmoid through these points. It can't pass through every point exactly (only 2 parameters; you need 5+ to perfectly fit 5 points). Instead it finds the smooth curve that minimizes total error:

  ┌─────┬──────────┬────────┬────────────────────┐
  │ Bin │ Raw pred │ Actual │ Calibrated (Platt) │
  ├─────┼──────────┼────────┼────────────────────┤
  │ A   │ 0.20     │ 22%    │ ~26%               │
  ├─────┼──────────┼────────┼────────────────────┤
  │ B   │ 0.40     │ 45%    │ ~39%               │
  ├─────┼──────────┼────────┼────────────────────┤
  │ C   │ 0.55     │ 40%    │ ~46%               │
  ├─────┼──────────┼────────┼────────────────────┤
  │ D   │ 0.70     │ 55%    │ ~53%               │
  ├─────┼──────────┼────────┼────────────────────┤
  │ E   │ 0.85     │ 62%    │ ~59%               │
  └─────┴──────────┴────────┴────────────────────┘

  Two things to notice:

  1. The "wobble" in C disappears. Bucket C's actual rate (40%) was lower than B's (45%) — a violation of monotonicity. Isotonic merged them. Platt instead smooths through the wobble — fits a curve that's
  slightly higher than the actual 40% in C but slightly lower than the actual 45% in B. It treats the C dip as noise.
  2. Every raw value gets a distinct calibrated value. 0.20 → 26%, 0.40 → 39%, 0.55 → 46%, etc. No two predictions collapse to the same calibrated probability.

  Why it can't compress (the Phase 2B fix)

  A sigmoid is strictly monotonically increasing — for any raw_a < raw_b, the calibrated values are also strictly ordered. The curve never goes flat (except at the extreme asymptotes near 0 and 1).

  In contrast, isotonic's staircase can go flat for arbitrary stretches. That's exactly what blew up Phase 2B: 1002 of 1304 predictions ended up on the same flat step. With Platt, this is structurally
  impossible. Every distinct raw probability gets a distinct calibrated probability.

  The cost is that Platt can't fit any miscalibration shape — only sigmoid-shaped ones. If the true miscalibration is wavy or non-monotonic-locally, Platt averages through the wobbles. The benefit: signal
  differentiation is preserved no matter how noisy the data is.

  Comparison to isotonic

  ┌───────────────────────────────┬────────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────┐
  │                               │                    Isotonic                    │                                     Platt                                     │
  ├───────────────────────────────┼────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ Shape                         │ Step function (staircase)                      │ Smooth sigmoid (S-curve)                                                      │
  ├───────────────────────────────┼────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ Parameters                    │ Many (one per merged bucket)                   │ Two (slope + intercept)                                                       │
  ├───────────────────────────────┼────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ Flexibility                   │ High — fits any monotonic miscalibration shape │ Low — only sigmoid-shaped miscalibration                                      │
  ├───────────────────────────────┼────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ Compression risk              │ Yes (Phase 2B issue)                           │ No — strictly increasing                                                      │
  ├───────────────────────────────┼────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ Tightness on calibration data │ Tighter (lower ECE possible)                   │ Looser (forced to a sigmoid shape)                                            │
  ├───────────────────────────────┼────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ Data needed                   │ More (one per bucket)                          │ Less (only 2 parameters)                                                      │
  ├───────────────────────────────┼────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ Best for                      │ Plenty of data, possibly complex patterns      │ Smaller data, or noisy data where differentiation matters more than tightness │
  └───────────────────────────────┴────────────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────┘

  Same trade-off as ML in general: more flexibility (isotonic) means tighter fit but compression risk; less flexibility (Platt) means looser fit but guaranteed structure.

  When Platt works well vs poorly

  Works well:
  - When miscalibration is approximately uniform overconfidence — e.g., raw 60% → real 50%, raw 70% → real 55%, raw 80% → real 60%. The "shrink everything toward the base rate" pattern is exactly what a
  sigmoid captures.
  - When you have less calibration data (fewer params to fit, less overfitting risk).
  - When you need every raw probability to remain distinguishable post-calibration (your case for Phase 2B's 0.55 threshold).

  Works poorly:
  - When the true miscalibration is non-sigmoid — e.g., model is overconfident in the middle but well-calibrated at extremes. Sigmoid can't bend that way.
  - When there's plenty of clean calibration data showing complex structure that you'd want isotonic to capture.

  Why Platt is the right candidate for Phase 2B specifically

  The Phase 2B problem isn't "isotonic was wrong about the calibration shape." Isotonic actually did find the lowest ECE. The problem is post-calibration usability: the threshold (0.55) can't differentiate
  between predictions that all collapsed to the same value.

  Platt sacrifices ECE tightness in exchange for structural guarantees:
  - ECE will probably be higher than isotonic's 6.40% — maybe 4–5% — but lower than raw's 9.75%
  - Differentiation is preserved — every raw probability still maps to a unique calibrated probability
  - The threshold can do its job — picking out the top X% of predictions remains possible

  The right way to evaluate this isn't ECE alone. You'd run a backtest comparing:
  1. Phase 2B raw + threshold 0.55 (current state)
  2. Phase 2B isotonic + re-tuned threshold (current S9 candidate Direction 1, but its compression is the concern for 2B)
  3. Phase 2B Platt + re-tuned threshold (Direction 2, this option)

  …and compare STRONG ENTRY avg returns and signal hierarchies. context.md S8 Lesson 2 is exactly the warning here: classification edge ≠ trading P&L. Calibration metrics are intermediate, not terminal — only
  the backtest tells you which method actually trades better.

  The 5-fold CV wrapper

  Same as isotonic. The pipeline would call CalibratedClassifierCV(method="sigmoid", cv=5):

  1. Split training data into 5 folds.
  2. For each fold: train LR on the other 4, predict on this fold (data the LR hasn't seen).
  3. Pool all held-out (predicted, actual) pairs.
  4. Fit the sigmoid (A, B) on the pooled pairs by gradient descent.

  Same reason for CV: avoid calibrating to the LR's training noise. Held-out predictions reflect real predictive behavior.

  TL;DR

  - Platt scaling = sigmoid mapping with two parameters (slope, intercept)
  - Parametric — assumes the miscalibration shape is sigmoid; only fits 2 numbers
  - Strictly monotonic — can never compress predictions to the same value
  - Smooths through local wobbles in the data instead of capturing every dip
  - Trade-off: looser fit than isotonic, but guaranteed differentiation
  - Right candidate for Phase 2B: when isotonic's compression destroys threshold differentiation, Platt's structural smoothness preserves it
  - Validation should be backtest avg-return comparison, not just ECE


  ### QQQ - STAY OUT

   I ran entry.py on QQQ — got a real signal as of 2026-05-06. I'll walk through every section of output you'll see, plus the visual outputs from the other scripts. Numbers below are all live, not made up.

  ---
  1. The pipeline state, top to bottom

  You're looking at QQQ as of 2026-05-06 (your data is 2 days stale — the warning at the top tells you this; running indicators.py would refresh it).

  The output ladder you'll see daily:
  1. Top: CSV load + freshness check — sanity that the right data came in
  2. Vol-Adjusted Threshold Calibration — what counts as a "WIN" for this ticker
  3. Phase 2 / 2B / 3 metrics — model performance on test set
  4. Three signal blocks — direction-15d, direction-63d, IV-expansion
  5. Options-Market Check — IV gate readings (skipped today since IV harvest hasn't run)
  6. Final SIGNAL + POSITION SIZING

  ---
  2. The indicators dashboard (qqq_dashboard.png)

  The 5-panel chart you see when indicators.py finishes:

  ┌──────────────────────┬─────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────┐
  │        Panel         │               What's plotted                │                                   What you read from it                                   │
  ├──────────────────────┼─────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
  │ Price (top, biggest) │ Candlesticks + Keltner bands + MA-20/50/100 │ Trend direction, location vs moving averages, where price sits in its volatility envelope │
  ├──────────────────────┼─────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
  │ RSI                  │ RSI-6, RSI-14, RSI-23 (three speeds)        │ Momentum: > 70 overbought, < 30 oversold                                                  │
  ├──────────────────────┼─────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
  │ MACD                 │ MACD line, signal line, histogram           │ Trend changes (line crossings) and momentum strength (histogram bars)                     │
  ├──────────────────────┼─────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
  │ Stochastic           │ %K and %D                                   │ Faster overbought/oversold gauge — useful for short-term timing                           │
  ├──────────────────────┼─────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
  │ OBV                  │ On-Balance Volume                           │ Volume-weighted accumulation; rising = buying pressure                                    │
  └──────────────────────┴─────────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────┘

  For QQQ today: price punching to new highs (~$697) above all MAs, RSI-14 ~71 (just into overbought), MACD positive, OBV rising. Visually bullish — but the model has to translate that into a probability, and
  that's where the next sections matter.

  ---
  3. Walking through the entry.py output

  Section A — Data freshness check

  WARNING: CSV data is 2 trading day(s) old (last: 2026-05-06)
  Your CSV's last row is 2026-05-06. Anything older than 1 trading day is stale — re-run indicators.py. (You also got a cmd : QQQ: No earnings dates found, symbol may be delisted warning further down; that's
  harmless — ETFs have no earnings, yfinance complains.)

  Section B — Vol-Adjusted Threshold Calibration

  Ticker median HV (20-day, annualized): 18.2%
  WIN_THRESHOLD:       0.05 (AMD default)  ->  1.8%  [computed]
  WIN_THRESHOLD_63:    0.10 (AMD default)  ->  3.7%  [computed]
  EXPANSION_THRESHOLD: 0.10 (AMD default)  ->  3.6%  [computed]
  This is the WIN bar for QQQ specifically — what counts as a "yes, this is a real move" rather than noise. For QQQ:
  - A 15-day price move ≥ 1.8% counts as WIN (Phase 2 target)
  - A 63-day price move ≥ 3.7% counts as WIN (Phase 2B target)
  - HV expansion ≥ 3.6 percentage points counts as EXPANSION (Phase 3 target)

  These bars are auto-calibrated per ticker because what's "noise" for AMD (8% move) would be a major event for SPY (3% move). The math: vol_multiple × median_HV × sqrt(days/252).

  Section C — Phase metrics (the line you read first to assess model health)

  Phase 2  (15d direction) — train precision: 55.7%  test precision: 47.3%  base rate: 44.2%
  Phase 2B (63d direction) — train precision: 62.8%  test precision: 55.8%  base rate: 51.5%
  Phase 3  (IV timing)     — train precision: 68.2%  test precision: 67.2%  base rate: 42.1%

  Read each line as: how confident should I be in this model's predictions today?
  - Train precision > test precision = some overfitting is normal
  - Test precision vs base rate = the model's edge

  Concretely:
  - Phase 2: test precision 47.3% vs base rate 44.2% → edge = +3.1pp. Marginal — barely better than random. The model is making weak directional calls.
  - Phase 2B: 55.8% vs 51.5% → edge = +4.3pp. Similar — modest.
  - Phase 3: 67.2% vs 42.1% → edge = +25.1pp. Massive. This is the biggest workhorse in the pipeline by far.

  This confirms the framework's structural finding: volatility is much more predictable than direction. The takeaway each day: trust Phase 3's vol direction hard; treat Phase 2 calls as weak prior information.

  Section D — Direction 15d block

  DIRECTION — 15d entry timing  [threshold: 0.55]
  Win Probability:    53.4%  (base rate: 44.2%)
  Signal:             NO SIGNAL ✗
  Drivers:            RSI_23 (-), price_vs_kc_upper (+), RSI_14 (+)
  Days to Earnings:   45d
  Days to Catalyst:   N/A

  Read it left-to-right:
  - Win Probability 53.4% — model says 53.4% chance of a ≥1.8% move in next 15 days
  - Threshold 0.55 — needs to clear 0.55 to fire
  - 53.4% < 0.55 → NO SIGNAL (would need 1.6 more percentage points to fire)
  - Above the 44.2% base rate, but not enough
  - Drivers — the three features pushing the probability the most. Format: feature name + sign of effect on this prediction.
    - RSI_23 (-) — RSI-23 is high (overbought), pushing probability down
    - price_vs_kc_upper (+) — price is near/above upper Keltner band, pushing probability up (momentum signal)
    - RSI_14 (+) — RSI-14 contributing positively (trend strength)
  - Days to Earnings: 45d — neutral ETF default (no earnings)
  - Days to Catalyst: N/A — no entry in catalysts.csv for QQQ

  The take: weak bullish lean but not enough to trigger.

  Section E — Direction 63d block (thesis check)

  DIRECTION — 63d thesis        [threshold: 0.55]
  Win Probability:    45.9%  (base rate: 51.5%)
  Signal:             NO SIGNAL ✗
  Drivers:            RSI_23 (-), price_vs_kc_upper (+), price_vs_ma200 (+)

  Notice this is below the base rate (45.9 < 51.5). Translation: across QQQ's history, 51.5% of 63-day forward windows were wins (meaning ≥ 3.7% gains). The model says only 45.9% chance from today. That's net
  bearish.

  Why? RSI_23 is high (price has been overbought for weeks) — historically, that flag has meant medium-term mean-reversion. Even though price_vs_kc_upper and price_vs_ma200 are bullish, RSI's negative weight
  dominates.

  Combined with section D: even if Phase 2 fired tomorrow, the 63d horizon doesn't agree. That'd produce a SHORT-TERM ONLY at best, not STRONG ENTRY.

  Section F — Phase 3 (IV timing)

  IV TIMING (Phase 3)           [threshold: 0.6]
  HV (20-day):        14.2%
  IV Rank:            0.17  (Low IV)
  IV Percentile:      40.2%
  Expansion Prob:     39.5%  (base rate: 42.1%)
  Signal:             CONTRACTION ✗
  Drivers:            price_vs_kc_upper (-), RSI_23 (+), HV_vs_ma20 (+)

  Read it as:
  - HV 14.2% — recent realized vol on QQQ, low
  - IV Rank 0.17 — IV is at the 17th percentile of its 1-year range (calm regime). (This is HV-derived right now since live IV harvest didn't run — that's S11/S12 work.)
  - IV Percentile 40.2% — separate measure (slightly different methodology)
  - Expansion Prob 39.5% < 60% threshold → CONTRACTION

  Note: Phase 3 doesn't say "no signal" — it always classifies as either EXPANSION or CONTRACTION. The 0.60 threshold is just the cutoff between them. In this case, the model is saying "vol likely keeps
  shrinking over next 10 days."

  That has a sizing implication: even if Phase 2 fired, contracting vol erodes long-call premium → REDUCED sizing recommended.

  Section G — Options-Market Check (skipped today)

  OPTIONS-MARKET CHECK: skipped (IV not in indicators CSV)

  This is the section that requires the Massive harvest. When MASSIVE_API_KEY is set and indicators.py ran fresh, you'd see something like:

  OPTIONS-MARKET CHECK
    ATM IV (~28d):    22.0%
    IV/HV ratio:      1.52  (very rich — gate triggers)
    25Δ skew:         +0.037  (modest put fear)
    Term structure:   1.02  (slight backwardation)
    Put/Call OI:      0.66  (slight call bias)

  Each number reads:
  - ATM IV 22% — what the market expects vol to be (vs your HV of 14.2% — gap = options market sees something HV doesn't)
  - IV/HV 1.52 — premium very rich; would gate STRONG ENTRY → CAUTION if Phase 2 fired
  - 25Δ skew +0.037 — modest put-side hedging (mild crash fear, not extreme)
  - Term structure 1.02 — slight backwardation — near-term IV slightly above back-month, mild stress signal
  - Put/Call OI 0.66 — more calls open than puts → bullish positioning

  The interpretive flow: if signals are firing AND IV/HV is rich AND term is backwardated AND skew is elevated, the options market is saying "tail risk is real, premium is expensive — your model's optimism may
   not reflect what the chain knows." Trust your trade less in that environment.

  Section H — Final SIGNAL

  SIGNAL:             STAY OUT
  POSITION SIZING:    N/A
  No directional edge — wait for Phase 2 signal before sizing.

  Phase 2 didn't fire (53.4% < 0.55), so the gate stays closed. Doesn't matter what the other phases say — the framework is "STAY OUT unless 15d direction fires." Combined with the bearish 63d and contracting
  vol, this is genuinely a "do nothing" day.

  ---
  4. Model results visuals — qqq_ml_results.png and qqq_phase3_results.png

  ML Phase 2 results PNG (left = confusion matrix, right = feature coefficients)

  Confusion matrix (this is the test set, ~1314 rows):
                  Predicted Loss   Predicted Win
  True Loss          409              290
  True Win           336              279

  Read it as:
  - True positives (predicted Win, was Win): 279
  - False positives (predicted Win, was Loss): 290 → precision = 279 / (279+290) = 49.0%
  - False negatives (predicted Loss, was Win): 336
  - True negatives: 409

  Test precision is the metric that matters for a long-only entry model: of the times we said "WIN," we were right 49% of the time. (Slightly different from the 47.3% in the entry.py output because the
  entry.py used the threshold's signals rather than the raw confusion matrix split — both are reporting the same model.)

  Feature coefficients (right panel, color-coded green = bullish, red = bearish):

  These are the trained weights the model assigns each feature. Key reads for QQQ:
  - RSI_23 (-, large red bar, ~-0.7) — the single biggest negative driver. Past data says: when RSI-23 is high, 15d direction tends down. Mean-reversion signal.
  - price_vs_kc_upper (+, big green ~+0.65) — momentum signal. Price near upper Keltner band → bullish.
  - VIX (+, ~+0.55) — counterintuitive but real: QQQ's 15d returns historically improve after VIX spikes. The pattern is "buy fear."
  - RSI_14 (+, ~+0.4) — mild trend confirmation
  - VIX_VIX3M_ratio (-, ~-0.2) — backwardation slightly hurts
  - MACD_hist_norm (-, ~-0.15) — surprisingly slightly negative (model picked up on a different pattern than you'd expect)

  You read this chart to understand WHY the model says what it does. If RSI_23 is at 75 today (high), the -0.7 weight applies hard. If price is 1% above upper Keltner band, +0.65 applies. The probability is
  the sum of all these feature-times-weight contributions, run through the sigmoid.

  Phase 3 results PNG

  Left panel: HV-20 over time, color-coded as low/mid/high IV regime. Useful for sanity check — recent green strip on the right confirms QQQ is in a calm regime (matches the 14.2% HV).

  Right panel: Phase 3 feature coefficients. Top features:
  - HV_20 (-) — high HV means contraction more likely (mean-reversion of vol)
  - HV_vs_ma200 (-) — same idea relative to long-run baseline
  - HV_chg_10d (-, big negative) — when HV is RISING, expansion less likely (vol is mean-reverting hard at the top)
  - price_vs_kc_upper (+) — bullish breakouts coincide with vol expansion historically
  - VIX_chg_5d (-, far right) — when VIX has been climbing, expansion is less likely (already happened)

  These are the patterns Phase 3 latched onto across 24+ years of QQQ data. The model is saying: "QQQ vol mean-reverts; if it's been climbing recently, it's about to fall, and vice versa."

  ---
  5. Reading the backtest performance (qqq_backtest.png + the table)

  The bar chart has two panels:

  Left — Average 15d return by signal (sorted by signal label)

  ┌─────────────────┬────────────┐
  │     Signal      │ Avg Return │
  ├─────────────────┼────────────┤
  │ STRONG ENTRY    │ 2.0%       │
  ├─────────────────┼────────────┤
  │ CAUTION         │ 1.1%       │
  ├─────────────────┼────────────┤
  │ SHORT-TERM ONLY │ 0.3%       │
  ├─────────────────┼────────────┤
  │ STAY OUT        │ 0.6%       │
  ├─────────────────┼────────────┤
  │ ALL DAYS        │ 0.8%       │
  └─────────────────┴────────────┘

  How to read it:
  - STRONG ENTRY (2.0%) > ALL DAYS (0.8%) → the model adds +1.2pp of edge per trade vs random buying. That's the framework's value.
  - CAUTION (1.1%) > ALL DAYS (0.8%) → still profitable, but smaller edge → REDUCED sizing makes sense
  - SHORT-TERM ONLY (0.3%) < ALL DAYS → on QQQ specifically, this signal underperforms. (Different on AMD where it's the best signal at 12.2%.)
  - STAY OUT (0.6%) < ALL DAYS → confirms Phase 2's filter works: the days it filters OUT do worse on average than the population

  This signal hierarchy (STRONG > CAUTION > STAY OUT > SHORT-TERM ONLY) is what makes QQQ a "well-suited" ticker for this framework.

  Right — Strong Win Rate (≥2% gain) by signal

  ┌─────────────────┬─────────────────┐
  │     Signal      │ Strong Win Rate │
  ├─────────────────┼─────────────────┤
  │ STRONG ENTRY    │ 53.3%           │
  ├─────────────────┼─────────────────┤
  │ CAUTION         │ 50.1%           │
  ├─────────────────┼─────────────────┤
  │ SHORT-TERM ONLY │ 43.4%           │
  ├─────────────────┼─────────────────┤
  │ STAY OUT        │ 42.6%           │
  ├─────────────────┼─────────────────┤
  │ ALL DAYS        │ 45.3%           │
  └─────────────────┴─────────────────┘

  Same hierarchy. Read it: when STRONG ENTRY fires, 53.3% of trades cleared a strong-win bar (+2% in 15 days), vs 45.3% for any random day. So the framework moved a coin-flippish 45% up to a 53% setup. Not
  huge in absolute terms, but 0–DTE option premium leverage turns 8pp of probability into meaningful expected value on calls.

  The numbers in the detailed table I pulled (AvgWin / AvgLoss):

  ┌─────────────────┬────────┬─────────┬──────────┬─────────────────────────────┐
  │     Signal      │ AvgWin │ AvgLoss │ Win Rate │            Notes            │
  ├─────────────────┼────────┼─────────┼──────────┼─────────────────────────────┤
  │ STRONG ENTRY    │ +5.4%  │ -4.1%   │ 64.9%    │ best risk/reward            │
  ├─────────────────┼────────┼─────────┼──────────┼─────────────────────────────┤
  │ CAUTION         │ +4.4%  │ -4.3%   │ 62.1%    │ losses similar size to wins │
  ├─────────────────┼────────┼─────────┼──────────┼─────────────────────────────┤
  │ SHORT-TERM ONLY │ +4.1%  │ -4.6%   │ 56.5%    │ losses bigger than wins     │
  ├─────────────────┼────────┼─────────┼──────────┼─────────────────────────────┤
  │ STAY OUT        │ +3.5%  │ -3.9%   │ 61.5%    │ quiet days                  │
  └─────────────────┴────────┴─────────┴──────────┴─────────────────────────────┘

  Read this as: when STRONG ENTRY wins, you average +5.4%; when it loses, you average -4.1%. With a 65% win rate, expected value per trade = 0.65 × 5.4 + 0.35 × (-4.1) = +2.07%. This matches the average return
   panel.

  ---
  6. Putting it together — what's QQQ telling you today?

  For 2026-05-06 (the latest data point):
  - Model: STAY OUT — Phase 2 didn't fire, 63d disagrees, Phase 3 says contraction
  - Visuals: Strong uptrend, RSI just breaking into overbought (sometimes a "confirm-then-pause" zone)
  - Vol regime: HV at 14.2% (calm, low), IV ranking 17th percentile

  The model's read makes sense: price has run hard and is at upper Keltner band, RSI-23 has been overbought for a while, and Phase 3 sees vol-mean-reversion ahead. There's no entry edge here. The honest
  answer: wait for either a pullback that resets RSI or a sustained breakout that re-fires Phase 2.

  If MASSIVE_API_KEY were set and IV harvest had run, you'd ALSO see whether the options market is corroborating the calm-regime read or flagging tail risk via skew/term structure/IV-richness. That's the layer
   entry.py is designed to surface but couldn't today.


   ### AMD - STAY OUT

AMD also reads STAY OUT today, but the numbers behind that decision look very different from QQQ's. The contrast is where the learning happens — same framework, very different ticker behavior.

  ---
  The big-picture comparison

  ┌────────────────────────────┬──────────────────┬───────────────────────┐
  │                            │ QQQ (2026-05-06) │   AMD (2026-05-06)    │
  ├────────────────────────────┼──────────────────┼───────────────────────┤
  │ Median HV (20-day)         │ 18.2%            │ 49.8% (~2.7× QQQ)     │
  ├────────────────────────────┼──────────────────┼───────────────────────┤
  │ WIN_THRESHOLD (15d)        │ 1.8%             │ 5.0%                  │
  ├────────────────────────────┼──────────────────┼───────────────────────┤
  │ WIN_THRESHOLD_63           │ 3.7%             │ 10.2%                 │
  ├────────────────────────────┼──────────────────┼───────────────────────┤
  │ EXPANSION_THRESHOLD        │ 3.6 pp           │ 10.0 pp               │
  ├────────────────────────────┼──────────────────┼───────────────────────┤
  │ Current HV-20              │ 14.2%            │ 84.7% (calm vs storm) │
  ├────────────────────────────┼──────────────────┼───────────────────────┤
  │ IV Rank                    │ 0.17 (low)       │ 0.78 (high)           │
  ├────────────────────────────┼──────────────────┼───────────────────────┤
  │ Phase 2 edge (test − base) │ +3.1pp           │ +1.4pp                │
  ├────────────────────────────┼──────────────────┼───────────────────────┤
  │ Phase 3 edge (test − base) │ +25.1pp          │ +14.7pp               │
  ├────────────────────────────┼──────────────────┼───────────────────────┤
  │ Data history               │ 1999–2026        │ 1980–2026 (46 yrs)    │
  └────────────────────────────┴──────────────────┴───────────────────────┘

  The key takeaway: AMD lives in a higher-volatility regime, so the bar for "real signal" is much higher (5% in 15 days vs 1.8%). It's also harder to predict direction on (Phase 2 barely beats base rate). The
  vol model still has solid edge, just less than on QQQ.

  ---
  1. Indicators dashboard — same panels, different story

  Visually the AMD chart looks more dramatic than QQQ:
  - Price has gone vertical recently — running from ~$200 to ~$385 in the recent leg
  - RSI-14 elevated but not fully overbought
  - MACD strongly positive (much wider histogram bars than QQQ)
  - Stochastic pinned in overbought
  - OBV climbing steadily — accumulation confirms the move

  You see the AMD personality immediately: explosive multi-month moves separated by long sideways bases. QQQ on the same chart looks like a steady escalator.

  ---
  2. Walk through entry.py output — where AMD differs

  Vol-Adjusted Threshold Calibration

  Ticker median HV (20-day, annualized): 49.8%
  WIN_THRESHOLD:       5.0%  [computed]
  WIN_THRESHOLD_63:    10.2%  [computed]
  EXPANSION_THRESHOLD: 10.0%  [computed]

  This is the core difference. AMD must move 5% in 15 days to count as a WIN. On a typical sideways AMD week, even +3% gain isn't a "WIN" by the framework's definition. The strict bar is appropriate — calling
  +3% on AMD a "win" would make the model fire too often and capture too much noise.

  This auto-calibration is why the framework works across tickers without manual re-tuning.

  Phase metrics — the model health line

  Phase 2  (15d direction) — train precision: 48.4%  test precision: 40.5%  base rate: 39.1%
  Phase 2B (63d direction) — train precision: 53.8%  test precision: 49.8%  base rate: 39.2%
  Phase 3  (IV timing)     — train precision: 53.2%  test precision: 48.2%  base rate: 33.5%

  Compared to QQQ:
  - Phase 2 edge: +1.4pp (40.5 vs 39.1) — barely above random. Phase 2 is weak on AMD. Treat its calls with significant skepticism.
  - Phase 2B edge: +10.6pp (49.8 vs 39.2) — the 63d horizon is where the model learns AMD. Big edge.
  - Phase 3 edge: +14.7pp — strong but smaller than QQQ's +25.1pp

  So on AMD, Phase 2B is more important than Phase 2 for thesis confidence. On QQQ, both direction models had similar (modest) edges.

  Direction 15d block

  Win Probability:    50.8%  (base rate: 39.1%)
  Signal:             NO SIGNAL ✗
  Drivers:            price_vs_ma20 (+), price_vs_ema8 (-), price_vs_ema21 (-)
  Days to Earnings:   90d
  Days to Catalyst:   N/A

  The probability (50.8%) is a much bigger jump above base rate (39.1%) than QQQ's was (53.4 vs 44.2). Net: model is significantly more bullish-than-baseline on AMD. But still doesn't clear the 0.55 threshold.

  The driver signs are interesting:
  - price_vs_ma20 (+) — price is well above MA20 (vertical run). Model says: keep going.
  - price_vs_ema8 (-) and price_vs_ema21 (-) — but price is too extended above the very-short-term EMAs. Model is pricing in some near-term mean reversion.

  This is the "stretched but still trending" reading: there's bullish momentum but the immediate term might pause.

  Days_to_earnings: 90d is the capped sentinel value (clipped at 90). AMD's actual next earnings is further out than 90 days — the sentinel says "earnings far enough away to be neutral."

  Direction 63d block

  Win Probability:    42.1%  (base rate: 39.2%)
  Signal:             NO SIGNAL ✗
  Drivers:            price_vs_ema89 (-), price_vs_kc_upper (-), price_vs_kc_lower (+)

  42.1% is barely above the 39.2% base rate. The 63d model is mildly bullish-biased but conviction-less. The dominant negative drivers are price_vs_ema89 (-) (price is well above the 89-day EMA, suggesting
  medium-term overextension) and price_vs_kc_upper (-) (sitting near upper Keltner band, mean-reversion warning).

  Combined: the long-term model is essentially saying "you've already had the move — don't chase."

  Phase 3 (IV timing)

  HV (20-day):        84.7%
  IV Rank:            0.78  (High IV)
  IV Percentile:      85.7%
  Expansion Prob:     40.4%  (base rate: 33.5%)
  Signal:             CONTRACTION ✗

  HV at 84.7% is in nosebleed territory for AMD. IV Rank 0.78 means current IV is at the 78th percentile of its 1-year range. Phase 3 says vol is more likely to contract than expand from this level (only 40.4%
   expansion probability — well below the 60% threshold).

  Practical translation: if you bought a long call here, you'd be paying premium reflecting 84% expected vol. Even if AMD goes up, if vol mean-reverts (likely from this level), the call's vega component drops
  and you give some of those gains back to time decay + IV crush.

  The contraction signal here is why the framework would size REDUCED on AMD even if Phase 2 fired. High IV + contraction prediction = expensive premium that's likely to get cheaper.

  Final SIGNAL

  SIGNAL:             STAY OUT
  POSITION SIZING:    N/A

  Same as QQQ — Phase 2 didn't fire (50.8 < 0.55), so nothing else matters.

  ---
  3. Phase 2 model results PNG — the feature sign flip

  This is the most instructive contrast with QQQ.

  Confusion matrix (test set, ~377 rows):
                Pred Loss  Pred Win
  True Loss      170          64
  True Win        89          54
  Computed precision at threshold 0.5: 54/(54+64) = 45.8% (entry.py shows 40.5% because it uses the tuned threshold sweep, not 0.5).

  Feature coefficients — biggest difference vs QQQ:

  ┌───────────────────┬─────────────┬───────────────────┬──────────────────────┐
  │      Feature      │ QQQ weight  │    AMD weight     │    Interpretation    │
  ├───────────────────┼─────────────┼───────────────────┼──────────────────────┤
  │ RSI_23            │ −0.70 (red) │ +0.65 (green)     │ SIGN FLIP            │
  ├───────────────────┼─────────────┼───────────────────┼──────────────────────┤
  │ price_vs_kc_upper │ +0.65       │ small +           │ Different role       │
  ├───────────────────┼─────────────┼───────────────────┼──────────────────────┤
  │ price_vs_kc_lower │ −0.35       │ −0.60 (large red) │ Bigger weight on AMD │
  ├───────────────────┼─────────────┼───────────────────┼──────────────────────┤
  │ SOX_RS_20d        │ n/a         │ +0.50 (green)     │ AMD-specific         │
  ├───────────────────┼─────────────┼───────────────────┼──────────────────────┤
  │ HV_20             │ small       │ −0.40 (red)       │ Important on AMD     │
  ├───────────────────┼─────────────┼───────────────────┼──────────────────────┤
  │ price_vs_ma200    │ small       │ −0.43             │ Mean-reversion       │
  └───────────────────┴─────────────┴───────────────────┴──────────────────────┘

  The RSI_23 sign flip is the key insight. On QQQ, high RSI-23 signals overextension and reversion (negative weight). On AMD, high RSI-23 signals momentum continuation (positive weight). The model learned each
   ticker's personality from its own history.

  This is why the framework is ticker-agnostic only at the architecture level — every ticker gets its OWN learned weights. Interpreting "RSI is high, that's bearish" in absolute terms is wrong; the meaning
  depends on the ticker's behavioral pattern.

  Other AMD-specific features:
  - SOX_RS_20d (+0.50) — when AMD is outperforming the SOX semiconductor index over 20 days, that's bullish. Sector relative strength matters here in a way it doesn't for an index like QQQ.
  - Days_to_earnings (+0.35) — being far from earnings is bullish. Why? In AMD's history, earnings reports introduce 2-way risk; the model learns that the periods between earnings see cleaner trend
  continuation.
  - XLK_RS_5d (+0.25) — short-term outperformance vs the tech ETF is bullish.
  - HV_20 (-0.40) — high vol on AMD is bearish for direction. Big sustained vol regimes on AMD historically coincide with selloffs (think 2018, 2022).

  ---
  4. Phase 3 results PNG

  The HV-over-time chart has the same color regime markers (green = low IV, amber = mid, red = high). For AMD: lots of red and amber stripes — AMD spends substantial time in elevated vol. The recent right edge
   is heavily red, confirming the 84.7% current reading.

  Feature coefficients for Phase 3 — very different shape from QQQ. The dominant negative weights:
  - HV_20 (large negative, ~−1.5) — current high vol → less likely to expand further (mean reversion)
  - HV_chg_10d (large negative) — vol that's been rising is less likely to keep rising
  - VIX_vs_ma20 (negative), HV_vs_ma20 (negative) — same pattern

  And positive:
  - RSI_6 (small +), RSI_23 (small +), price_vs_ma200 (small +) — bullish price action coincides with vol expansion historically

  The story: AMD's vol mean-reverts hard at the top. When IV is elevated, the model leans heavily toward predicting contraction. That's exactly the call today.

  ---
  5. Backtest performance — the >=5% bar matters

  The right panel of amd_backtest.png shows "Strong Win Rate (>=5% gain)" — note the 5% bar, not 2% like QQQ. That's the vol-adjusted bar at work. AMD's typical 15-day move is bigger, so the "strong win"
  definition is bigger too.

  ┌─────────────────┬────────────┬──────────────┬──────────────┐
  │     Signal      │ Avg Return │ Strong Win % │ Signal Count │
  ├─────────────────┼────────────┼──────────────┼──────────────┤
  │ STRONG ENTRY    │ +3.9%      │ 41.8%        │ 378          │
  ├─────────────────┼────────────┼──────────────┼──────────────┤
  │ CAUTION         │ +1.9%      │ 38.9%        │ 723          │
  ├─────────────────┼────────────┼──────────────┼──────────────┤
  │ SHORT-TERM ONLY │ −1.5%      │ 30.7%        │ 560          │
  ├─────────────────┼────────────┼──────────────┼──────────────┤
  │ STAY OUT        │ +1.9%      │ 38.4%        │ 4,787        │
  ├─────────────────┼────────────┼──────────────┼──────────────┤
  │ ALL DAYS        │ +1.7%      │ 38.0%        │ 6,448        │
  └─────────────────┴────────────┴──────────────┴──────────────┘

  Read the hierarchy:
  - STRONG ENTRY beats ALL DAYS by +2.2pp — solid edge, similar magnitude to QQQ
  - CAUTION ≈ STAY OUT (1.9% each) — the CAUTION signal has effectively zero edge over not trading on AMD. Different from QQQ where CAUTION was distinctly above STAY OUT.
  - SHORT-TERM ONLY is NEGATIVE (−1.5%) — actively destructive. ⚠️

  That last finding contradicts a prior note in your context.md that said SHORT-TERM ONLY was AMD's best signal at +12.2%. The current backtest doesn't reproduce that. Two likely reasons:
  - The backtest is now using more years of history (1980–2026, vs context's 2019–2026) — older AMD trades very differently
  - Feature engineering or vol-adjusted thresholds shifted the signal definitions since that note was written

  This is real-world ML: when the underlying changes (more data, new features), signal performance shifts. Treat any historical performance number as "as of when computed" — re-run periodically.

  Strong Win details (the secondary metric):
  - STRONG ENTRY hits +5% in 15d 41.8% of the time (vs 38% baseline) → +3.8pp edge
  - That's the meaningful number for option buyers — you need a chunky move for premium to overcome theta and IV crush

  AvgWin/AvgLoss for STRONG ENTRY: +12.9% / −8.3% (combined with 57.7% win rate).
  EV per trade = 0.577 × 12.9 + 0.423 × (−8.3) = +4.0% — matches the 3.9% chart figure.

  Compare to QQQ STRONG ENTRY: +5.4% / −4.1% / 64.9% win → EV = +2.07%.

  So AMD STRONG ENTRY has roughly 2× the expected value per trade vs QQQ, with a lower win rate (57.7 vs 64.9%) but bigger upside per win and tolerable downside per loss. Higher-vol ticker → bigger absolute
  moves → bigger expected payoff per actionable signal. That's the trade-off you're making.

  ---
  6. What today's read means for AMD

  Putting it all together for 2026-05-06:

  - Direction: weakly bullish bias (probabilities above base rate) but neither model fires
  - Vol regime: HV at 84.7% — stretched. Phase 3 says vol contracts from here
  - Visuals: vertical run from ~$200 to ~$385. Stretched. Stochastic pinned overbought.
  - Sentiment: 90 days from earnings (no event risk soon)

  The honest take: the train left the station. Buying calls now would mean:
  1. Paying very high IV premium (dangerous if vol contracts as Phase 3 expects)
  2. Chasing an extended momentum move that the 63d model doesn't fully endorse
  3. Hoping for another +5%+ leg without a Phase 2 fire to support the entry

  The framework is correctly saying STAY OUT here — even though AMD has been the trade of the year, the entry timing right now is unfavorable.

  ---
  7. The cross-ticker lesson

  What you just learned by walking through QQQ then AMD:

  1. Vol-adjusted thresholds matter most. The "WIN" bar is 1.8% on QQQ but 5% on AMD. This is the framework's secret to working across tickers.
  2. Same model, different weights. RSI_23 means "reversion-bearish" on QQQ but "momentum-bullish" on AMD. Always read each ticker's coefficient chart — don't assume a feature has a fixed meaning.
  3. Phase 2 strength varies by ticker. Strong edge on QQQ (+3.1pp), weak on AMD (+1.4pp). Phase 2B is more important on AMD, while QQQ relies more on Phase 2 + Phase 3.
  4. Vol regime affects sizing logic. AMD at 84% HV → Phase 3 says contraction → premium gets cheaper → REDUCED sizing if anything fires. QQQ at 14% HV is the opposite case (low vol regime, expansion
  possible).
  5. Backtest numbers shift. Don't treat past STRONG ENTRY % as durable — re-run when feature engineering or windowing changes.


  ### NVDA - STAY OUT
  NVDA is the most interesting case yet — it's the only one where a model actually fires (Phase 2B at 72.7%), even though the final signal still says STAY OUT. Plus we now have calibration diagnostic output
  that connects directly to the ECE conversation earlier.

  ---
  Three-way comparison

  ┌───────────────────────┬─────────────┬─────────────┬─────────────────────────┐
  │                       │     QQQ     │     AMD     │          NVDA           │
  ├───────────────────────┼─────────────┼─────────────┼─────────────────────────┤
  │ Median HV (20-day)    │ 18.2%       │ 49.8%       │ 43.6%                   │
  ├───────────────────────┼─────────────┼─────────────┼─────────────────────────┤
  │ WIN_THRESHOLD (15d)   │ 1.8%        │ 5.0%        │ 4.4%                    │
  ├───────────────────────┼─────────────┼─────────────┼─────────────────────────┤
  │ Current HV-20         │ 14.2%       │ 84.7%       │ 39.3%                   │
  ├───────────────────────┼─────────────┼─────────────┼─────────────────────────┤
  │ IV Rank               │ 0.17 (low)  │ 0.78 (high) │ 0.29 (low-mid)          │
  ├───────────────────────┼─────────────┼─────────────┼─────────────────────────┤
  │ Phase 2 edge          │ +3.1pp      │ +1.4pp      │ +6.9pp ← best           │
  ├───────────────────────┼─────────────┼─────────────┼─────────────────────────┤
  │ Phase 2B edge         │ +4.3pp      │ +10.6pp     │ +7.7pp                  │
  ├───────────────────────┼─────────────┼─────────────┼─────────────────────────┤
  │ Phase 3 edge          │ +25.1pp     │ +14.7pp     │ +16.2pp                 │
  ├───────────────────────┼─────────────┼─────────────┼─────────────────────────┤
  │ Today's Phase 2 prob  │ 53.4%       │ 50.8%       │ 40.3% ← below base rate │
  ├───────────────────────┼─────────────┼─────────────┼─────────────────────────┤
  │ Today's Phase 2B prob │ 45.9%       │ 42.1%       │ 72.7% ← FIRES           │
  ├───────────────────────┼─────────────┼─────────────┼─────────────────────────┤
  │ Today's Phase 3 sig   │ CONTRACTION │ CONTRACTION │ CONTRACTION (strongest) │
  └───────────────────────┴─────────────┴─────────────┴─────────────────────────┘

  NVDA has the most balanced model edges — all three phases have meaningful precision lift (+6.9 / +7.7 / +16.2). QQQ relies most heavily on Phase 3; AMD's Phase 2 is essentially noise; NVDA spreads the work
  across all models. That's why context.md tags NVDA as the framework's best-performing ticker.

  ---
  1. Indicators dashboard

  NVDA's chart shows the iconic post-2023 AI run — price climbing from ~$15 to ~$200 over 2 years with periodic 30%+ corrections (visible on the panel). RSI bouncing between elevated and neutral, MACD
  histogram spiking high during breakouts. OBV climbing steadily — institutional accumulation through the whole run.

  The recent right edge: price ~$195, just below the upper Keltner band, RSI-14 mid-range (~55), MACD line crossing back over signal. Visual setup is "consolidating after a leg up, possibly setting up the next
   breakout."

  ---
  2. The entry.py signal — first non-trivial Phase 2B fire

  Phase 2  (15d direction) — train precision: 50.6%  test precision: 48.3%  base rate: 41.4%
  Phase 2B (63d direction) — train precision: 64.5%  test precision: 57.1%  base rate: 49.4%
  Phase 3  (IV timing)     — train precision: 55.1%  test precision: 48.8%  base rate: 32.6%

  DIRECTION — 15d entry timing  [threshold: 0.55]
  Win Probability:    40.3%  (base rate: 41.4%)
  Signal:             NO SIGNAL ✗
  Drivers:            SOX_RS_20d (-), Days_to_earnings (+), price_vs_ma50 (-)
  Days to Earnings:   14d
  Days to Catalyst:   N/A

  40.3% is below the 41.4% base rate — model thinks NVDA's 15-day direction is slightly worse than random. Drivers: SOX_RS_20d (-) (semis sector been weakening relative to other peers), price_vs_ma50 (-)
  (price extended above MA50, mean-reversion threat). The Days_to_earnings (+) is positive but smaller magnitude — surprising, given this feature was negative in the coefficient chart (close to earnings is
  generally bearish for 15d). The current value matters: 14 days is right in the danger zone where event risk is highest.

  DIRECTION — 63d thesis        [threshold: 0.55]
  Win Probability:    72.7%  (base rate: 49.4%)
  Signal:             WIN ✓     ← FIRES
  Drivers:            SOX_vs_ma200 (+), Days_to_earnings (+), XLK_vs_ma200 (-)

  This is the first signal we've seen actually fire. 72.7% is way above the 49.4% base rate — strong conviction on the 63-day horizon. Drivers:
  - SOX_vs_ma200 (+) — semis sector trending up vs its long-run trend
  - Days_to_earnings (+) — proximity to earnings is bullish for the 63-day window. This is the post-earnings rally pattern: NVDA tends to gap up on earnings then continue trending. The 63-day window captures
  that effect. (Compare: on Phase 2's 15-day window, this same feature is mildly bearish — event risk near-term.)
  - XLK_vs_ma200 (-) — the only meaningful drag

  Net read: the 63-day thesis is clearly bullish on NVDA, anchored on sector strength and the upcoming earnings catalyst. But Phase 2 doesn't agree on near-term timing.

  IV TIMING (Phase 3)           [threshold: 0.6]
  HV (20-day):        39.3%
  IV Rank:            0.29  (Low IV)
  IV Percentile:      81.3%
  Expansion Prob:     17.8%  (base rate: 32.6%)
  Signal:             CONTRACTION ✗

  17.8% is deep below the 32.6% base rate — this is the most confident contraction read of the three tickers. Phase 3 is saying "no question, vol is going down from here."

  The IV Rank vs IV Percentile divergence is notable:
  - IV Rank 0.29 — current vol is 29% of the way from the 1-year LOW to 1-year HIGH
  - IV Percentile 81.3% — but current vol is higher than 81.3% of past 1-year days

  How can both be true? NVDA's vol distribution is left-skewed with a long right tail. Most days are at lower vol, but the occasional spikes (earnings, AI news) reach very high. The current 39.3% sits well
  below the spikes (low rank) but above the typical day (high percentile). Both readings are useful — together they say "vol is elevated relative to typical NVDA, but not at crisis levels."

  SIGNAL:             STAY OUT
  POSITION SIZING:    N/A

  Even with Phase 2B firing strong, the pipeline gates on Phase 2 as the entry trigger. No Phase 2 → STAY OUT regardless of Phase 2B's conviction.

  ---
  3. The "what if" thought experiment

  Suppose tomorrow's data nudges Phase 2 above 0.55 (it's currently at 0.40 so this is unlikely without a real catalyst, but for teaching purposes):

  ┌─────────┬───────────────┬───────────────────────┬───────────────────┐
  │ Phase 2 │   Phase 2B    │        Phase 3        │ Resulting Signal  │
  ├─────────┼───────────────┼───────────────────────┼───────────────────┤
  │ WIN     │ WIN (already) │ CONTRACTION (already) │ CAUTION → REDUCED │
  └─────────┴───────────────┴───────────────────────┴───────────────────┘

  Because Phase 3 says CONTRACTION strongly, the framework would size REDUCED. Why? You'd be buying NVDA calls 14 days before earnings into a contracting-vol regime — the post-earnings IV crush would eat into
  your gains even if direction is right.

  Expected behavior of NVDA in this scenario: stock drifts up (Phase 2B's bullish thesis), earnings hit, premium collapses 30-50% on IV crush, stock either gaps up enough to overcome it or doesn't.

  That's exactly why CAUTION exists as a label — it's the framework saying "directionally yes, but premium dynamics work against you."

  ---
  4. Phase 2 results (nvda_ml_results.png)

  Confusion matrix (test set ~1320 rows):
                Pred Loss  Pred Win
  True Loss      402         301
  True Win       325         292

  Precision at 0.5 threshold: 292/(292+301) = 49.2% (entry.py reports 48.3% at the tuned threshold).

  Feature coefficients — biggest insights:

  ┌───────────────────┬──────┬───────────┬──────────────────────────────────────────────────────────────────────────────────┐
  │      Feature      │ Sign │ Magnitude │                              What it means for NVDA                              │
  ├───────────────────┼──────┼───────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ price_vs_ma50     │ −    │ ~−0.65    │ Stretched-above-MA50 = mean-reversion warning (biggest weight)                   │
  ├───────────────────┼──────┼───────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ SOX_RS_20d        │ +    │ +0.55     │ Outperforming semis sector = bullish                                             │
  ├───────────────────┼──────┼───────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ XLK_RS_20d        │ −    │ −0.45     │ Outperforming broader tech ETF... is bearish?                                    │
  ├───────────────────┼──────┼───────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ price_vs_kc_upper │ +    │ +0.35     │ Touching upper band = momentum continuation                                      │
  ├───────────────────┼──────┼───────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ HV_20             │ +    │ +0.27     │ High vol = bullish for NVDA direction (different from AMD where it was negative) │
  ├───────────────────┼──────┼───────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ RSI_23            │ +    │ +0.20     │ Momentum follow-through (same sign as AMD, opposite of QQQ)                      │
  ├───────────────────┼──────┼───────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ Days_to_earnings  │ −    │ −0.18     │ Near earnings = bearish (15d window — event risk dominates)                      │
  └───────────────────┴──────┴───────────┴──────────────────────────────────────────────────────────────────────────────────┘

  The XLK_RS sign flip is counterintuitive. On NVDA, outperforming XLK (the broader tech ETF) over 20 days is bearish for the next 15 days. The interpretation: NVDA periods of strong relative outperformance vs
   broad tech are often parabolic blowoffs that mean-revert. Outperforming the narrower SOX semis index has the opposite effect (bullish — sector confirms). Two RS features, opposite signs, makes sense once
  you think about which peer group is the right comparison.

  The RSI_23 sign tells you NVDA is, like AMD, a momentum stock at the 23-day horizon. High RSI doesn't mean revert — it means continue.

  ---
  5. Phase 3 results (nvda_phase3_results.png)

  The HV-over-time chart shows lots of red striping — NVDA spends substantial time in elevated vol regimes (similar to AMD's profile, but less extreme).

  Top features:
  - price_vs_kc_lower (+, very large) — when price is far above the lower Keltner band, vol expansion is more likely. Surprising, but the pattern is real: NVDA's biggest vol expansions happen when it's pushing
   higher, not when it's selling off (because squeeze dynamics force shorts to cover).
  - HV_20 (−, large) — current high HV → less likely to keep expanding (mean reversion of vol)
  - price_vs_ma50 (−), price_vs_ma200 (−) — extended price = vol contracts (consolidation after move)
  - MACD_norm (−), MACD_signal_norm (−) — bullish MACD readings → less likely to see vol expansion

  The story: NVDA's vol model is dominated by mean-reversion at high HV plus a momentum-coincident expansion mechanism. Today's read fits — HV is elevated, and the model leans toward contraction.

  ---
  6. Backtest performance (nvda_backtest.png)

  ┌─────────────────┬────────────┬────────────────────┬───────┐
  │     Signal      │ Avg Return │ Strong Win % (≥4%) │ Count │
  ├─────────────────┼────────────┼────────────────────┼───────┤
  │ STRONG ENTRY    │ +4.4%      │ 52.8%              │ 391   │
  ├─────────────────┼────────────┼────────────────────┼───────┤
  │ SHORT-TERM ONLY │ +4.1%      │ 44.6%              │ 322   │
  ├─────────────────┼────────────┼────────────────────┼───────┤
  │ CAUTION         │ +1.7%      │ 45.0%              │ 1,269 │
  ├─────────────────┼────────────┼────────────────────┼───────┤
  │ STAY OUT        │ +2.5%      │ 40.6%              │ 4,363 │
  ├─────────────────┼────────────┼────────────────────┼───────┤
  │ ALL DAYS        │ +2.5%      │ 42.4%              │ 6,345 │
  └─────────────────┴────────────┴────────────────────┴───────┘

  Read the hierarchy:
  - STRONG ENTRY: +4.4% — best, +1.9pp above ALL DAYS, with the highest strong-win rate (52.8%)
  - SHORT-TERM ONLY: +4.1% — almost as good as STRONG ENTRY. The opposite of AMD where SHORT-TERM ONLY was −1.5%. NVDA's momentum bursts are real and capturable. AMD's apparently aren't (currently).
  - CAUTION: +1.7% — actually underperforms STAY OUT (2.5%). The "direction confirmed but vol contracting" signal isn't useful on NVDA — when vol is contracting, the option premium gets crushed regardless of
  direction.
  - STAY OUT: +2.5% — exactly matches ALL DAYS, meaning Phase 2 doesn't really filter out bad days on NVDA either. Consistent with NVDA's structural bull regime — most days have been net positive.

  EV per trade for STRONG ENTRY:
  - AvgWin +14.4% / AvgLoss −14.5% / Win rate 65.5%
  - EV = 0.655 × 14.44 + 0.345 × (−14.52) = +4.45%

  This is the highest EV per trade of the three:
  - QQQ: +2.07%
  - AMD: +4.0%
  - NVDA: +4.45%

  NVDA's combination of higher win rate, sizable AvgWin, and tolerable AvgLoss makes it the framework's best-performing ticker.

  ---
  7. Calibration diagnostic (just generated)

  The direction.py run output the diagnostic for Phase 2:

  [Raw Logistic Regression]
  Brier: 0.2535  ECE: 0.0676
  Bin              N     Pred   Actual       Gap
  0.4-0.5        195    46.1%    50.8%     -4.7%
  0.5-0.6        415    55.3%    55.7%     -0.4%
  0.6-0.7        439    64.8%    55.6%     +9.2% over
  0.7-0.8        240    73.8%    60.4%    +13.4% over
  0.8-0.9         12    82.1%    50.0%    +32.1% over

  NVDA Phase 2 raw ECE = 6.76% — similar to QQQ's 6.99%. Same overconfidence pattern in the 0.6+ bins (model says 73.8%, reality is 60.4%).

  [Calibrated (Isotonic, 5-fold CV)]
  Brier: 0.2491  ECE: 0.0589
  Bin              N     Pred   Actual       Gap
  0.4-0.5        854    49.2%    52.1%     -2.9%
  0.5-0.6        445    51.3%    62.5%    -11.2% under
  0.6-0.7         10    64.9%    40.0%    +24.9% over

  Here's something important: isotonic on NVDA shows the same compression problem context.md flagged for Phase 2B. After calibration:
  - 854/1311 samples land in the 0.4-0.5 bin (65% of all predictions)
  - 445/1311 in 0.5-0.6
  - Only 10 samples remain above 0.6

  ECE only dropped marginally (6.76% → 5.89% — small win) because the calibrator over-merged. And the 0.5-0.6 bin is now underconfident (pred 51.3% vs actual 62.5%). The threshold at 0.55 would barely
  differentiate any signal.

  This is exactly Phase 2B's problem from S9 manifesting on NVDA's Phase 2 too. Same fix would apply: try Platt scaling on NVDA, which can't compress.

  This is real evidence beyond what context.md noted — the compression issue isn't unique to QQQ Phase 2B. It looks like a general pattern when calibration data is moderately noisy.

  ---
  8. Bottom line for NVDA today

  For 2026-05-06:
  - Model says STAY OUT because Phase 2 is below base rate
  - But Phase 2B fires strong (72.7%) — the medium-term thesis is genuinely bullish
  - Earnings in 14 days — explains the Phase 2/2B disagreement (event risk near, post-event drift bullish)
  - Phase 3 strongly contraction (17.8%) — premium will likely cheapen post-earnings
  - Visual: consolidating below upper Keltner, mid-RSI, MACD turning up

  The honest read: this is a "watch closely" setup, not yet actionable. If NVDA reports earnings in 14 days and rallies through the report, you'd want to revisit the day after — Phase 3 would likely flip
  closer to expansion as new vol regime establishes, and Phase 2 might fire on the post-earnings momentum. That'd be a clean STRONG ENTRY setup.

  Until then: don't chase. The 14-day-to-earnings setup is exactly when amateur traders buy calls expecting a "sure thing rally," then get crushed by IV decay if the move doesn't immediately materialize.

  ---
  9. The full cross-ticker picture

  Across all three tickers, you've now seen every flavor the framework produces:

  ┌──────────────────────────┬────────────────────────────────────────────────────────────────────────────────┐
  │         Pattern          │                                    Example                                     │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────┤
  │ Low-vol regime + rich IV │ QQQ today (HV 14% / IV 22%) — gate would trigger if signal fired               │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────┤
  │ Stretched bull, high vol │ AMD today (HV 85%) — Phase 3 strongly contraction, sizing concern dominates    │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────┤
  │ Pre-earnings divergence  │ NVDA today — short-term uncertain, long-term bullish, vol contraction expected │
  ├──────────────────────────┼────────────────────────────────────────────────────────────────────────────────┤
  │ All three phases agree   │ (None of these today — what STRONG ENTRY actually looks like)                  │
  └──────────────────────────┴────────────────────────────────────────────────────────────────────────────────┘