Project Context — Multi-Timeframe Trading LENS
==============================================

(Consolidated S35. Prior session-by-session detail lives in git history; this is the working summary.)

CURRENT FOCUS: lens.py (the Lens)
---------------------------------
The project's **primary tool is now `lens.py`** — a multi-timeframe market-structure & risk LENS. It
is a wide-angle CONTEXT layer around the user's OWN chart-based trading: it characterizes CURRENT
STATE (trend, momentum, volume, structure, options/vol, macro, cross-asset/geopolitical) so a narrow
read doesn't miss the bigger picture. It makes **NO prediction and claims NO edge** — "state
characterization, not prediction." The user brings the entry edge (levels, chart structure); the Lens
makes sure they aren't blindsided (e.g. oversold daily but overbought weekly, or an oil/geopolitical
stress backdrop the single-ticker price lens can't see).

Run: `python -X utf8 lens.py` (1 prompt) or `--ticker QQQ`. Works on any ticker (yfinance daily
fallback if no indicators CSV). Flags: `--thesis bullish --level 700` (confirm/contradict), `--geo`
(cross-asset/geopolitical backdrop), `--no-intraday`, `--candle box|braille|sixel`, `--prev N`.
Full operational reference: CLAUDE.md.

How the project got here (the journey)
--------------------------------------
This began as an ML options-swing-trading framework (predict 6–12mo call entries) and pivoted to a
context tool after the data repeatedly said the predictive edge wasn't there:

1. Built a 5-tier signal (STRONG ENTRY … STAY OUT) from logistic-regression phases; tuned ~30
   sessions on ~25y history.
2. **S31 — the leak.** `Days_to_earnings` was a calendar-time leak (yfinance returns only ~20–25
   recent earnings dates → older rows became a near-perfect time ramp; NVDA 79% of rows, corr −0.999).
   It had inflated essentially ALL of the individual-stock edge. Fixed (cap + drop from features).
   Clean result: **QQQ is the only ticker with intact hierarchy + real edge**; NVDA became
   anti-predictive, AMD marginal. The "stocks beat the index" thesis WAS the leak.
3. **S32–33 — red-team + rewrite gates.** A contrarian audit showed the signal is a regime-dependent
   dip-buyer with only ~40 independent 6mo bets/ticker; cheap kill-gates on the tractable rewrites
   (cross-sectional factors, GARCH vol) failed / were marginal. Edge accessible with free data +
   standard methods on liquid names is marginal at best.
4. **S34 — reorientation.** Reframed: the USER brings the edge (charting); the framework's job is
   wide-angle CONTEXT (accuracy + completeness, which it CAN do), not alpha. Built lens.py + its
   modules. That is the current project; S35 hardened it and added the geopolitical backdrop.

The Lens — what it prints (all CONTEXT, none a prediction)
---------------------------------------------------------
- **Header + candle** — last-bar OHLC + a TradingView-style hollow candlestick panel of the last N+1
  daily bars. Hollow = close ≥ open; colour green/red = close vs PRIOR close. Styles: sixel (default,
  true-pixel image), box, braille. `--prev N` (default 10).
- **MARKET BACKDROP** — SPY 1M/1W/1D trend + VIX regime.
- **MULTI-TIMEFRAME table** — trend / RSI / Stoch / MACD / RVOL / ΔPrc% / ΔVol% / VolTrend across
  1M/1W/1D/4h/1h, with an inline column legend + a confluence/conflict synthesis (the
  oversold-daily / overbought-weekly blind spot). Indicator windows are in candles OF THAT ROW's
  timeframe (RSI-14 = 14 months on 1M, 14 hours on 1h). In-progress W/M bars are marked `*`; their
  volume reads use the last completed bar (S35 partial-bar fix).
- **DIVERGENCES** — price vs RSI/OBV per timeframe.
- **VOLUME PROFILE** — POC, value area (70%), HVN shelves / LVN gaps, price location.
- **RALLY vs DRAWDOWN RISK** — a transparent two-sided scorecard; every firing factor listed.
- **OPTIONS & VOL CONTEXT** — IV/HV, 25Δ skew, term, P/C OI, HV/IV-rank, VIX complex + regime, each
  with trailing-1y percentile (reuses `gather_context`).
- **GEOPOLITICAL / CROSS-ASSET BACKDROP** (`--geo`, S35) — see below.
- **MACRO** — next macro releases ≤10d. **THESIS CHECK** (`--thesis`) — confirmations /
  contradictions / blind spots vs your stated bias.

Modules: `timeframes.py` (per-TF OHLCV; `last_bar_partial`), `structure.py` (reads; `read_volume`
`exclude_last`; no ML), `volume_profile.py`, `sentiment.py` (`gather_context` + `percentile_of`),
`geocontext.py` (S35; `--geo`), `pc_oi.py` (S36; `gather_pc_oi`/`pc_by_expiry`; `--pc-oi`).

S36 also moved `pc_oi.py` → `modules/pc_oi.py` (one file = library + CLI, run `python -m modules.pc_oi`)
and added `lens.py --pc-oi [near|leaps|monthly …]` (bare = all; tokens combine, e.g. `--pc-oi leaps monthly`):
a live Tradier put/call-OI-by-expiry block (opt-in, best-effort, quiet). Bare scope = all expiries; the
`near`/`leaps`/`monthly` tokens narrow it (and cut the 1-call-per-expiry latency). NB bare `--pc-oi` parses
to `[]` (falsy) so the lens gate tests `is not None`. Distinct from the OPTIONS gauge's Massive-harvested blended ~30d P/C number.
NOTE the lens candle code already uses a local `pc` (prior close) — the new param is `pcoi` to avoid the clash.

S37: pc-oi data is now CACHED per (ticker, scope) to `data/pc_oi_cache/{ticker}_{scope}.json` (`gather_pc_oi`).
Staleness is SESSION-based — stale once a new market close has passed since the cache (`_most_recent_close`
= last weekday 16:00 ET), because OI settles once/day at the close (volume is the only intraday-changing
column; a post-close refresh still updates it). On stale: prompts to refresh **only if a TTY** (`sys.stdin.isatty()`);
piped/`--ticker` runs reuse the cache + a "stale" note (never hang on `input()`). Fresh hit = zero network.
Standalone caches the blank-filter "all" path; a single-date filter stays a direct live call. Modeled on
`geocontext.py`'s JSON cache. `gather_pc_oi` now returns `as_of`/`as_of_str`/`age_str`/`stale`/`cached` too.

S37: `lens.py --vol` adds a VOLATILITY SETUP block for straddle/strangle (long-vol) context — descriptive,
no prediction. Stage A (done): `structure.read_squeeze` (per-TF Bollinger-Keltner squeeze = price-action
compression), `volsetup.expected_move` (1σ = spot·iv·√(dte/365), vs realized HV move), `features.next_earnings`
(next date + median |reaction| over E/E+1 of last ~6, robust to BMO/AMC), and `volsetup.vol_setup` — a
two-sided long-vol-vs-short-vol scorecard (IV/HV, IV-rank as a vol-LEVEL/regime read not a price read,
squeeze, term, skew, earnings, implied-vs-realized move) mirroring `rally_drawdown_risk`. Pulls IV gauges
from `gather_context` by name (so `--vol` is best with the vol block, i.e. not `--no-vix`). Stage B (DONE):
`modules/volquote.straddle_quote` — live options pricer folded into `--vol`, tuned for LIQUIDITY (all three
liquidity levers): (1) picks the near **MONTHLY** expiry (3rd Friday via `is_monthly_expiry`, falls back to
closest-to-30d) since OI concentrates there — this alone fixed CRSP (weekly straddle OI 5/29 → monthly 153/749);
(2) an **"auto" strangle** — wings at ±the EXPECTED MOVE (= ATM straddle price / spot; `EM_MULT` tunes it,
1.0 = at the exp move), so the width auto-normalizes to each name's vol/DTE (CRSP ±11%, NVDA ±6%), NO delta
(sidesteps unreliable far-OTM greeks; the earlier fixed ±5/10/15% ladder was replaced by this single auto row
at the user's request, Webull-style); (3) both legs (straddle + strangle) show **OI + bid/ask** so thin/wide
strikes are obvious. Key lesson surfaced: liquidity = OI/volume/SPREAD, NOT legs-equal-in-price (that's a
*balanced* strangle, a different thing). CRSP's OTM puts barely trade (OI ~1, wide) while calls are deep; NVDA
all deep/tight. Cached per ticker session-stale (`data/pc_oi_cache/{ticker}_straddle4.json`; SCOPEKEY bumped
`straddle → … → straddle4` as the payload shape evolved: legs, then monthly+ladder, then the auto strangle).
NB option PRICES move intraday → a cached quote is a snapshot 'as of HH:MM' (TTY refresh like pc-oi).

--geo cross-asset / geopolitical backdrop (S35)
-----------------------------------------------
Opt-in (`--geo`, default off). Surfaces the assets that move on geopolitical/macro shocks — the
framework's documented blind spot. **CONTEXT ONLY, never a model feature** (macro features were
rejected as features twice; see Lessons). Each gauge prints level · trailing percentile · stress tag,
plus a composite "geopolitical/macro stress: LOW/ELEVATED/HIGH" naming which gauges are in their
stress tail:
- ENERGY: WTI, Brent, OVX (oil VIX) · HAVEN: gold, DXY · CREDIT: HY OAS (FRED), MOVE
- SECTORS: defense (ITA), semis (^SOX), wheat, nat gas · INDICES: EPU (FRED `USEPUINDXD`) + GPR (Caldara-Iacoviello daily `.xls`)

GPR vs EPU: **GPR = war/conflict/terrorism risk** (the direct geopolitical measure); **EPU =
domestic economic-POLICY uncertainty** (debt ceiling, Fed, tariffs). They diverge — a tariff fight
lifts EPU; a Middle-East war lifts GPR (and oil).

Mechanics: yfinance (batched) + FRED (reuses `econ_calendar` `FRED_API_KEY`) + GPR `.xls` (needs
`xlrd>=2.0.1`, installed). Percentile = `sentiment.percentile_of` over the **last 252 observations**
(`IV_RANK_WINDOW`). Calendar span varies by series frequency: ~1 year for the market/business-daily
gauges; **~8 months for EPU/GPR** (calendar-daily incl. weekends). Cached to `data/geo_cache.json`
(~6h TTL). Never raises — missing sources degrade to notes (no FRED key → credit/EPU skip).

The original ML framework (intact, for reference — no longer the focus)
----------------------------------------------------------------------
Daily flow `indicators.py → entry.py → sizing.py`; diagnostics direction/volatility/exit/backtest.
Five-tier signal (STRONG ENTRY / CAUTION / SHORT-TERM ONLY [demoted to informational, S30] / LEAPS
ONLY / STAY OUT) from logistic-regression phases (P2 15d, P2B 63d, P3 IV expansion, P4 drawdown), all
`LogisticRegression(C=0.1, class_weight=balanced)`, 80/20 time split, vol-adjusted per-ticker
thresholds; IV/HV ≥ 1.40 downgrades STRONG→CAUTION.

CLEAN leak-free baselines (post-S31, earnings-free):
  QQQ   STRONG 1.6%/64% 15d · 8.9%/75% 6mo (+1.8pp) — hierarchy INTACT — the only trustworthy edge
  Ford  STRONG 4.0%/58% · 25.0%/48% 6mo (+19.3pp) — clean validator (cyclical, no secular trend)
  JPM   STRONG 2.6%/64% · 13.4%/73% 6mo (+6.2pp)  — clean validator (financial; needed the S31 yield-curve inf fix)
  NVDA  UNSUITABLE — STRONG anti-predictive (−0.8% 15d; 6mo < STAY OUT). The old ~33% was the leak.
  AMD   marginal (STRONG 6mo below STAY OUT). SPY structurally unsuitable. CRSP = Phase-3/vol only.

Rejected research flags (all default OFF; retained for experimentation — do NOT re-enable blindly):
`--calibrate`, `--iv-features`, `--econ-features`, `--regime-gate`, `--p4-gate`, `--side put`. Each
failed cross-ticker validation (recurring failure mode: feature inflation compresses the
high-confidence edge tail on individual stocks).

S30 forward signal ledger: `entry.py` writes `data/{ticker}_signal_ledger.csv` (one row per as-of
date) — the pristine out-of-sample record, the only data that can validate the post-signal layers.

Key cross-cutting lessons (durable)
-----------------------------------
- **Cross-ticker validation is load-bearing.** QQQ alone is insufficient; clear QQQ + an independent
  non-secular-trend ticker (Ford/JPM) before adopting any change. Caught 7+ regressions.
- **Leak-audit method:** scan new features for correlation with calendar order; cap/difference
  anything that ramps with time (unbounded "days since/until", cumsum, raw level) — it manufactures
  edge on secular-uptrend names in walk-forward. (S31)
- **Info that fails as a model feature can still be valuable as human CONTEXT.** Econ proximity (S20)
  and VIX regime (S21) were rejected as features but are useful to a human — the rationale for
  market_context.py (S29) and the Lens / `--geo`. Display ≠ feature.
- **Geopolitical / Exogenous Shock Limitation:** all model inputs derive from price/vol history → the
  framework is reactive, not predictive, of wars / CB surprises / oil shocks. Mitigation is HUMAN:
  read the IV/HV gap, skew, term structure, VIX complex, and (S35) the `--geo` backdrop. Don't size
  like the backtest average during known crises.
- **Stress regime = contrarian BUY, not sell (S21):** direction-model STRONG ENTRYs in high-VIX have
  above-average forward returns (mean reversion); any VIX-state gate removes the best entries.

Operational notes
-----------------
- Venv python explicitly: `.\trade\Scripts\python.exe -X utf8 script.py` (Claude Code's shell doesn't
  inherit venv activation). `-X utf8` required (avoids cp1252 errors on the unicode glyphs).
- Windows piped run: PowerShell tool, `cmd /c "(echo TICKER) | python -X utf8 script.py"` (Bash drops
  stdout from cmd /c subprocesses; PowerShell native `|` prepends a BOM). For lens.py prefer
  `--ticker` to skip the prompt entirely.
- `data/` must exist. Env vars (add to `$PROFILE`): MASSIVE_API_KEY, FRED_API_KEY, TRADIER_TOKEN.
- lens.py is now the daily DRIVER (S36): on launch it auto-runs `indicators.py --ticker SYM --no-chart`
  for any ticker whose CSV is ABSENT (builds it from scratch, S37) or is missing the latest completed
  session (weekday past 4 PM ET, else prior weekday; file-mtime-guarded so market holidays don't
  re-trigger every run). Best-effort/non-fatal — on failure it proceeds on whatever exists (yfinance
  fallback if still no CSV). `--no-refresh` opts out (skips build+refresh); `--refresh` forces even if
  current. indicators.py gained a non-interactive CLI (`--ticker/--start/--end/--no-chart/--data-dir`).
- Smoke: `.\trade\Scripts\python.exe -m pytest tests/ -q` (15 tests, offline, ~2s).
- Harmless: `Select-Object -First N` truncating a lens pipe gives exit 255 (SIGPIPE), not a crash.

Outstanding / backlog
---------------------
- IV backfills wiped pre-S23 and not yet restored: SOFI, LYFT, QQQ (~15–25 min each, backfill_iv.py);
  AAPL missing entirely. AMD (462 rows) + NVDA (452) intact.
- Re-validate any NVDA-passed history (every pre-S31 cross-check used leaked features).
- Optional `--geo` polish: normalize EPU/GPR to a ~365-obs window so all gauges are a true 1-year
  percentile (currently ~8mo for the calendar-daily indices).
- ML-side backlog (lower priority now): net-of-cost backtest, portfolio correlation/sizing, Kelly
  continuous sizing.

S35 (this session) — lens hardening + --geo
-------------------------------------------
- Partial-bar volume fix: in-progress (or stale mid-period) W/M bars marked `*`; RVOL/ΔVol%/VolTrend
  use the last completed bar (NVDA 1M RVOL 0.2x→0.7x). `timeframes.last_bar_partial` +
  `structure.read_volume(exclude_last=)`.
- Multi-TF column legend (decodes RVOL / ΔPrc% / ΔVol% inline; dimmed when colour on).
- TradingView hollow candles in the panel (colour vs prior close, fill vs open) across sixel/box/braille.
- NEW `modules/geocontext.py` + `--geo` cross-asset/geopolitical backdrop (all 4 gauge bundles).
  Installed `xlrd>=2.0.1` (GPR `.xls`) + added to requirements.txt; EPU series fixed to `USEPUINDXD`.
- Built then REVERTED a `--marker` candle-annotation feature (user: bloat).
- 15/15 smoke (added offline geocontext stress/composite test). CLAUDE.md + this file updated.
