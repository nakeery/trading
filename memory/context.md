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
(cross-asset/geopolitical backdrop), `--no-intraday`, `--candle box|braille|sixel`, `--prev N`,
`--vol` (straddle/strangle context), `--pc-oi`, `--live` (S40 intraday mode), `--squeeze` (S41
short positioning), `--insider` (S42 EDGAR Form 4 cluster buys). SETUP CHECK checklist + F&G
backdrop segment are default-on (S41). Full operational reference: CLAUDE.md.

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

S38: `--vol` reoriented toward PRE-EARNINGS long-vol (buy vol into the IV ramp, sell BEFORE the report
to sidestep IV crush). Two `volquote` changes: (1) the quote is now EARNINGS-AWARE — when
`features.next_earnings` is ≤`EARN_WINDOW=45`d out it anchors to POST-earnings expiries (an expiry ending
before earnings carries no event premium, so it can't ramp): the nearest one (steepest ramp / most
concentrated premium) AND the nearest post-earnings monthly when they differ (more liquid) — BOTH shown;
else it falls back to the near-monthly ~30d with an explanatory note. (2) each auto-strangle wing now SNAPS
to the most-liquid of the nearest `SNAP_K=3` OTM strikes (rank OI, tie-break tighter spread, prefer
tradeable bid/ask>0), not the mathematically nearest — fixes landing on a dead strike (the CRSP OTM-put
case). New PURE helpers `_select_expiries`/`_liquid_strike` (+ per-expiry `_build_block`), unit-tested
offline (17 smoke tests now). `--vol` also prints a one-line straddle-vs-strangle guide (straddle = max
vega, enter close to the print; strangle = cheaper + lower theta, enter earlier / run more names / vega
convexity). Quote payload is now `{spot, earn_days, quotes:[block,…], notes}`; SCOPEKEY straddle4→straddle5.
The strangle label shows the realized ≈±width plus a `target ±EM` clause when the snap drifted the width
off the expected-move target (e.g. CRSP `≈±25%, target ±19%` — lumpy round-number OI pulled the wings out);
hidden when they match (NVDA/QQQ), so evenly-liquid names stay clean.

S39: `modules/vol_history.py` — a pre-earnings VOL STUDY that gives `--vol` an EVIDENCE base (does the
IV ramp it assumes actually show up for this name?). For the last ~8 earnings, off on-disk `atm_iv_30d`
+ `Close` (no new API load): the IV RAMP (pre-print vs ~entry_td sessions earlier), the post-earnings
CRUSH, and a buy-early/sell-before-print ATM straddle P&L via `bs_invert.black_scholes_call` (IV gain −
theta − spot drift), plus a 5/10/15-session entry-timing sweep. Descriptive only. **HV was rejected**:
the ramp is IMPLIED-vol; realized/HV is flat-to-down pre-earnings and spikes AFTER → an HV-priced sim
bakes in theta but misses the ramp (systematic false-negative). Surfaced two ways: standalone `python -m
modules.vol_history` (full table + sweep + verdict + caveats) and a one-line inline verdict in `--vol`
(`history (N earnings): …`). When IV history is thin (`status insufficient_iv`, `MIN_USABLE`=3) it OFFERS
the Massive backfill — TTY-gated in BOTH the CLI and `lens --vol` (`interactive=sys.stdin.isatty()`),
never in piped runs. `backfill_iv.py` refactored into a reusable `backfill(ticker)` (returns a status
dict, no `sys.exit`) that degrades cleanly when Massive is unavailable (no key / 401 → clear message,
never crashes). Shared `features.earnings_dates` helper. Caveats printed: ~8-earnings sample (2yr IV cap)
is indicative not proof; `atm_iv_30d` is a constant-maturity 30d proxy (blunts the true front-expiry
ramp — AMD reads a weak/inconsistent ramp partly for this reason); BS r=q=0, no fills. 18 smoke tests.

S40: `--vol` HONESTY PASS — a CRSP run (validated on NVDA/QQQ) exposed three defects that made the
scorecard's verdict dishonest exactly when it matters, all fixed:
(1) **The IV cheap/rich factor used the HV-20 proxy, not real IV.** `features.IV_rank`/`IV_pct` are
HV-20's position in its own 1y range (the pre-Massive proxy) — pre-catalyst, implied ramps while the
stock stays quiet, and the proxy misses it. Live CRSP: real ATM IV at the 97%ile of its 178-row
history while the proxy read 0.44 "Mid" → no counterweight → "favor BUYING vol (2–0)" at the top of
the IV range. Fix: `volsetup.gauge_pct(ctx,"ATM IV (30d)")` — the factor now uses the REAL harvested
percentile (bands `IV_PCT_LOW/HIGH` = 0.30/0.70); HV-proxy only as an explicitly-labeled fallback
when IV history is thin (<63 obs → pct None; QQQ exercises this path until its backfill is redone).
Gauges renamed `IV Rank (HV-proxy)` / `IV Pctile (HV-proxy)` so they can't be read as real IV
(fits the ≤20-char gauge column; volsetup lookup updated).
(2) **Wing snap was pure max-OI within the nearest 3 — a moth to round numbers.** Reproduced live:
NVDA put target 185.1 picked 190 (OI 39k) over the perfectly liquid 185 (OI 21k, 5¢ spread), tilting
the strangle −3.5%/+6.6% while the averaged "≈±5%" label hid it; CRSP decided 42.5-vs-45 on 47-vs-42
OI noise. Fix: `SNAP_OI_FRAC=0.5` — nearest tradeable candidate holding ≥half the busiest candidate's
OI (dead strikes still skipped; busiest always qualifies so the pick can't fail; OI tie-break on
equidistant strikes). Labels now PER-WING (`−a% / +b%`, `target ±EM` clause when ≥1pp off), and an
`at ask:` cost/BE line prints when mid understates executable cost by >3% (CRSP straddle $11.10 mid
vs $14.00 ask on an OI-0 fresh weekly — visible; NVDA/QQQ tight spreads — hidden). `_combo` gains
ask-side fields; SCOPEKEY straddle5→straddle6.
(3) **Off-horizon/unconditional factors.** Intraday (1h/4h) squeezes no longer count as long-vol
factors (`SQUEEZE_TFS = 1M/1W/1D`; the compression line still lists all TFs) — a 4h squeeze says
nothing about a 51-DTE option. And the earnings catalyst demotes to a `notes` line ("event premium
likely priced; ramp mostly done") when real ATM IV already ≥70%ile — an upcoming print is only a
reason to buy vol while it's still cheap. Hint copy aligned to S38: "exit BEFORE the print; IV crush
erases the ramp" (was "size for the IV crush"). Post-fix CRSP reads "no clear vol edge" with the
97%ile short factor + priced-event note — the honest read. 19 smoke tests (test 16 rewritten for the
new snap rule + new test 19 for the factor logic, both offline).

S40 (cont.): **CRSP IV backfill = DEAD END — do not re-attempt.** User ran it (~26% "fill rate", but
the work list was 447 dates = 329 missing IV + 118 missing only term_structure; most fills were
term-refills → only +23 net new atm_iv_30d rows, 172/501 sessions = 34% coverage). Vol study still
0/8 earnings usable: it needs IV at three exact sessions (entry −10 / pre −1 / post +1) and EVERY
CRSP earnings is missing pre and/or post with nothing within ±3 sessions (measured — a tolerance
patch rescues zero). Root cause is structural, not tunable: (1) pre-print option flow migrates into
short-dated event expiries (7–21 DTE), so the backfill's 23–37 DTE window has literally zero ATM
trades on the sessions the study needs; (2) CRSP is so thin that even its event expiries printed
vol=5/trades=4 max the day before a report — below the ≥5/≥5 artifact gates, and rightly so. Massive
history on this plan is TRADES-only; an IV nobody traded can't be reconstructed (quote/NBBO history
= higher tier). **Forward path**: the daily harvest is QUOTE-based and fills reliably — run the
daily refresh through earnings windows (for 2026-08-10: especially Aug 7 pre + Aug 11 post) and each
print becomes a usable study row; MIN_USABLE=3 ⇒ study unlocks ~mid-2027. Until then the Aug-10 play
rests on live `--vol` context only. Known-but-deferred (user skipped): backfill overwrites
quote-based harvest IV on term-refill dates (docstring "never overwritten" is wrong — fix = write
only NaN keys); lens `--vol` history line still suggests backfill_iv.py for CRSP where it can't help.
**→ Both deferred items FIXED in S44** (per-cell `_apply_result`; harvest-accumulation wording).

S40 (cont.): `lens.py --live` — INTRADAY mode. Motivated by measured source freshness (2026-07-02,
market open): **Tradier brokerage-token market data is REAL-TIME (~4s delay on trades AND quotes)**;
Massive Options Starter snapshots are 15-min-delayed values with NO last_quote/last_trade fields
(IV/greeks/OI/day only — gauge engine, not a live feed); yfinance daily structurally excludes today
+ its intraday endpoint gets throttled intermittently (measured: worked 11:50, refused 12:37 same
day). `--live` (all Tradier, all display-only, non-live runs byte-identical):
(1) provisional today-bar from `get_daily_quote` (`timeframes.fetch_live_bar`/`apply_live_bar`) —
header "LIVE HH:MM ET", today's forming candle, 1D marked `*` (partial → volume reads use last
completed bar), 1W/1M re-derived so the forming week/month absorb it; skipped when the CSV already
covers today; NEVER written to disk (Tradier is unadjusted — same convention as the S30 stamp).
(2) 1h frame topped up to the current session via NEW `tradier.get_timesales` (15min→60m resample
onto yfinance's :30-anchored grid; `merge_intraday_topup` replaces overlapping cached hours);
forming 1h/4h bars now marked partial in live mode — fixes the misleading `RVOL 0.0x` a
2-minute-old hour used to print (CRSP verify: 1h 0.0x → `1h* 1.4x`, the honest read on a +5.5% day).
(3) live ATM IV gauge (`tradier.get_atm_iv`, smv) printed beside the harvested one — CRSP verify
showed 67.0% live vs 63.8% harvested [97%ile], i.e. IV pumping intraday — and used for the expected
move; the scorecard's percentile stays harvest-based (history needs the harvested series).
(4) `--pc-oi`/`--vol` quote caches force-refreshed (`force=` param on `gather_pc_oi`/
`straddle_quote`). Also hardened independently of --live: `_load_intraday` falls back to a stale
cache with a note instead of dropping 1h/4h when Yahoo refuses the download. 21 smoke tests
(test 20 live-bar append, test 21 top-up merge, both offline).

S41 (same working day as S40): squeeze block + setup checklist + Fear & Greed. Three additions,
all CONTEXT (transparent factor lists, no prediction), all sources probed live before building:
(1) **`--squeeze` SHORT POSITIONING block** (`modules/shortint.py`): bi-monthly short interest +
days-to-cover from the NASDAQ API (unofficial, UA-gated, session-stale cache; **NASDAQ-LISTED
NAMES ONLY** — NYSE tickers like JPM/F return an explicit no-data message, rendered honestly as
n/a; FINRA Query API is the future fix for NYSE coverage) + daily short-volume ratio from FINRA
Reg SHO files (official CDN, no auth; per-ticker incremental cache — first run ~90 small files,
then 1/day; percentile via `sentiment.percentile_of`) + a pure two-sided fuel-vs-counter
scorecard (`squeeze_read`: DTC ≥8/≥15, SI ±10% settlement-over-settlement, SVR ≥80%ile,
shorting-into-a-rally "underwater" read, +3%/1.5x covering thrust, call-flow surge off `--pc-oi`
totals when present, LVN air ≤+8% overhead from the lens' own volume profile). Verified live:
CRSP read "SQUEEZE CONDITIONS PRESENT" on DTC 16.3 EXTREME + SI +23% + call-heavy flow + LVN air
— while its 57% SVR day correctly did NOT fire (only 42%ile of CRSP's ~50% baseline — the
percentile-not-level design working); JPM read partial/absent. Caveats always printed (bi-monthly
lag, MM baseline, fuel ≠ ignition).
(2) **SETUP CHECK** (`modules/setupcheck.py`, default-on): ✓/✗/– completeness checklist — HTF
alignment, momentum room, volume confirmation, NEW relative-strength-vs-benchmark row
(`TICKER_BENCHMARK` first entry / SPY fallback, one yf fetch, series aligned to common last
date), value-area location, vol regime (very-rich IV ✗; VIX stress → S21 contrarian note, not a
fail), catalyst timing (earnings ≤7d / Tier-1 macro ≤1d = flagged `–`, never failed — may be
intentional). Explicit footer: completeness, not probability. Blind-spot catcher per the S34
ethos — the S32 lesson (no free-data edge) stands.
(3) **CNN Fear & Greed** (`modules/fng.py`): unofficial endpoint (418 without browser UA +
Referer), ~6h cache, percentile off the payload's own ~1y history; on the lens MARKET BACKDROP
line (`F&G 31 fear [24%ile]`) + a market_context.py gauge with the S21 contrarian note.
24 smoke tests (22 shortint parsers/scorecard, 23 setupcheck, 24 fng — all offline fixtures).
Rejected/deferred for sentiment: earnings-call transcripts (no reliable free source), Reddit/
StockTwits mention counts (noisy; possible later), Ortex borrow/utilization (paid; the free
NASDAQ+FINRA combo is the legitimate substitute).

S42 (same working day): **`--insider` EDGAR block — BUILT** (`modules/insider.py`), per the S41
sketch. Data path all official/free: `company_tickers.json` ticker→CIK (cached 7d) →
`data.sec.gov/submissions/CIK{cik}.json` recent Form 4 accessions → per-filing raw XML (the
`primaryDocument` xsl-prefix is stripped to reach the raw file). SEC fair-access respected:
User-Agent carries a contact email (`$env:SEC_CONTACT` overrides the default), 0.12s sleep between
requests, ≤25 filings/run, per-ticker summary cached session-stale under `data/insider_cache/`.
Scoring: NON-DERIVATIVE open-market P/S only (M/A/G/F excluded — not conviction trades);
trailing-90d net $ flow + **cluster-buy detection** (≥2 DISTINCT insiders buying inside any 30d
window — Lakonishok-Lee; best window reported with owners/$/dates). Read is two-sided house
style; caveats always printed (sales = diversification/comp noise — never a short thesis; Form 4
files ≤2 business days after the trade; 10b5-1 planned sales not separated). Verified live:
CRSP → "$-210,577, 0 buys / 1 sell — sales only, weakly informative"; NVDA → "$-410.6M, 7 sells /
3 insiders" with the ⚑ broad-selling flag (the 10b5-1 caveat earning its keep); second run 2.7s
(session cache). 25 smoke tests (test 25: Form 4 XML parse, code filtering, 30d-window/distinct-
owner cluster logic, net-flow read — offline fixtures).

S42 (cont.) display polish: every lens section headline now renders as a dimmed title-in-rule
separator (`── TITLE ────…`, `lens._section`, 78-col, dim only when colour is on) — the top/bottom
`═` double lines are unchanged. Chosen over a full-width rule-above-title via user preview.

S43: lens calculation-review honesty fixes (user-requested audit of lens.py + modules). Core math
verified clean (BEs, expected move, heatmap, candles, percentiles); six output/scorecard-integrity
defects found and fixed:
(1) **`vol_setup` double-counted IV/HV** — the implied-vs-realized-move factor reduces to the SAME
atm_iv/HV_20 ratio as the IV/HV factor (the √(dte/365) cancels; lens builds `em` from the same two
gauges), so one input could fire 2 of the 2-factor verdict margin and flip the NET alone. Factor
removed (the expected-move line is still displayed; `em` param kept for signature stability).
(2) **HVN "approaching resistance/support" had no proximity check** — `near_hvn_above/below` was
the nearest HVN at ANY distance, so both risk-scorecard factors fired nearly every run. Now bounded
±`HVN_NEAR_PCT` (5%, volume_profile.py) like shortint's LVN-air band; setupcheck says "no HVN
support nearby".
(3) **`last_bar_partial(frac=0.7)` missed late-period forming bars** (a Thu/Fri forming week, the
last ~third of a forming month) → unmarked, understated W/M volume reads — the S35 defect, just
later in the period. Now calendar-aware: partial when the period end (resample label rolled back to
a weekday) is after the most recent completed session (`now_session` injectable for tests); the
count heuristic is kept as the stale-mid-period fallback.
(4) **`gather_context` could present weeks-old gauges as current** — last-non-NaN per column, so a
stopped Massive harvest kept showing the old IV/skew/term. Beyond `STALE_GAUGE_SESSIONS`=5 sessions
the label now carries "(stale Nd)" + a note.
(5) **Thin frames printed definite states from NaN indicators** — a 30–33-bar frame has no MACD
signal yet but printed "bearish"; MACD/Stoch/RSI states are now None → "—" in the table.
(6) **No-bid legs made the straddle/strangle mid fictional** (mid = ask/2) — combos carry `no_bid`,
the lens prints "⚠ a leg has no bid — mid cost indicative" (volquote SCOPEKEY straddle6→straddle7).
Minor: live-mode expected move uses the live IV's own DTE (was hardcoded 30); volume profile takes
`ref_price` from the 1D close (the 1h stale-cache fallback skewed price_location); read_volume
missing 10-bar history → "—" not "+0.0%"; dead `lens._fmt_vol` removed. 26 smoke tests (new test 26
= Thursday-week/late-month calendar fixtures; test 19e asserts `em` is no longer scored).

S44 (same working day): IV restoration prep + CRSP forward-capture — CODE ONLY (user runs the
backfills/harvests themselves). Chosen as the next framework step because the S40 honesty pass made
the `--vol` cheap/rich verdict depend on the REAL ATM-IV percentile, which QQQ (the reference
ticker) can't produce until its wiped IV history is restored; and CRSP's ramp evidence can only be
built forward (its backfill is a proven dead end — trades-only history, S40).
(1) **backfill overwrite bug FIXED** (the S40 known-but-deferred item): new pure
`backfill_iv._apply_result` writes result keys ONLY into NaN cells — a term-refill date keeps its
harvested quote-based atm_iv_30d (previously every returned key was clobbered; the docstring's
"never overwritten" claim is now true per-cell). Safe to re-run backfills over harvested history.
(2) **Event-expiry IV in the daily harvest**: `massive.get_event_iv` (+ pure `pick_event_atm`,
`_parse_snapshot_rows`) quotes the ATM IV of the nearest POST-earnings expiry (strictly after the
report — an expiry ending on/before it carries no event premium, volquote convention); stamped by
`indicators.harvest_iv_snapshot` as `atm_iv_event`/`event_expiry`/`event_dte` when earnings ≤45d
out (`EVENT_EARN_WINDOW`). New `IV_EVENT_COLS` folded into `IV_META_COLS` → auto-excluded from every
model's features and auto-merged/preserved by the CSV machinery; the harvest's IV_COLS stamp loop is
key-guarded so the daily summary doesn't null the event cells. Rationale: the constant-maturity 30d
gauge BLUNTS the front-expiry ramp (S39 caveat — why AMD reads weak); quote-based snapshots fill
even for thin names like CRSP whose options rarely trade.
(3) **vol_history prefers event IV** via `_iv_triplet` — but ONLY when all three sessions
(entry/pre/post) carry it; tenors are never mixed inside one ramp measurement (that would fabricate
ramp). 30d proxy fallback otherwise; per-row `iv_src` + an honest caveat line reporting the mix.
(4) **Lens earnings-window capture guard**: when earnings ≤10d and the latest session's atm_iv_30d
harvest is missing, a note fires same-day ("missed pre-earnings sessions cannot be backfilled") —
for the Aug-10 CRSP window a missed day is unrecoverable. Also the `--vol` thin-history line no
longer blindly recommends backfill_iv.py (it now says history accumulates via the daily harvest;
backfill restores liquid names — resolving the second S40 deferred item).
28 smoke tests (27 = per-cell no-overwrite; 28 = event-ATM selection + the no-tenor-mixing guard).
STILL PENDING (user-run): QQQ backfill (~15–25 min) to restore the real-IV percentile path; then
optionally SOFI/LYFT re-backfill + AAPL build.

S46: **long-call decision context** — user asked "what other context matters before opening long
calls?"; web-research-validated gap analysis found the lens covered direction/timing/vol but
stopped before the INSTRUMENT's mechanics. Four additions (user-selected all four):
(1) **`--call` LONG CALL VIABILITY block** (`modules/callquote.py`, volquote-pattern cache
SCOPEKEY call1): nearest monthlies to 45/90 DTE, ATM + ~0.375Δ (the 0.35–0.40 trend band)
candidates — mid premium, BE move, **theta/day as % of premium** (the carry number: QQQ live read
45d ATM 1.2%/d vs 101d 0.5%/d — the DTE tradeoff made concrete), OI/spread, at-ask line (>3% S40
pattern), per-expiry earnings notes (before-print = no event exposure / after = crush risk) and
ex-div-before-expiry notes, an ATM-IV-by-expiry curve (`curve_read` cheap-tenor tag; ≤5 monthlies
≤150d), and a "paying up" caution when real ATM IV ≥70%ile. Pure helpers
(`pick_call_candidates`/`liquidity_grade`/`curve_read`/`_select_expiries`) offline-tested.
(2) **Chain liquidity grade** — ATM-region (5 strikes, calls+puts) median mid-relative spread +
OI → tight/ok/wide/dead (≤1%+OI≥1k / ≤3% / ≤8% / else; OI<100 demotes; majority-no-bid = dead).
In the `--call` block always + a DEFAULT-ON `options liquidity:` line in OPTIONS & VOL CONTEXT
served ZERO-NETWORK from the freshest `--call` cache (`cached_liquidity`, as-of + stale tag) —
the principle held: no new default-on network calls.
(3) **Ex-dividend awareness** — `features.next_ex_dividend` (exact from yfinance calendar, else
pure `estimate_next_ex_div` cadence estimate flagged `~`; <4 payments or median gap >400d → None)
→ SETUP CHECK Catalyst-timing suffix ≤45d ("calls don't earn it; deep-ITM early-exercise risk").
(4) **Market beta SETUP CHECK row** — pure `setupcheck.beta_corr` (60d OLS β + corr vs SPY,
`fetch_beta` one bounded yf call) — always-informational "–" row: corr ≥0.6 backdrop applies /
<0.3 largely idiosyncratic (QQQ read β1.59 corr 0.92; CRSP β1.85 corr 0.41 moderate). NB this row
made the checklist 8 rows (test 23's "7/7" → "7/8").
(5) **KNOWN CATALYSTS section** (default-on) — `benchmarks.upcoming_catalysts` surfaces
catalysts.csv (ticker,date,type,description) entries ≤45d in the lens; first run immediately
surfaced CRSP's 2026-08-01 PDUFA (Casgevy pediatric, 25d out, 9d BEFORE the Aug-10 earnings) that
only the ML layer could see before.
**Rejected on ethos grounds** (researched, documented): GEX / call-walls / max pain (dealer
positioning INFERRED not observed; vendor-marketing-driven, thin evidence), seasonality (n≈20 per
calendar month; post-S31 calendar-feature skepticism), news/social sentiment (no reliable free
source — S41 rejection stands). 31 smoke tests (30 = callquote pure helpers; 31 =
beta/ex-div-estimator/catalysts filters).

S47: **ATM IV (180d) — the LEAPS-tenor gauge** (user: "I don't buy 30d options; add a ~6mo IV
reading" + "is the 30d reading real IV?" — answer: YES, quote-based Massive harvest; the
labeled `(HV-proxy)` gauges are the only synthetic ones). Long-dated IV moves far less than the
event-bid front (CRSP curve read 70.2% at 10d vs 67.0% at 101d while 30d sat at the 97
percentile), so the front percentile can scream "expensive" while the tenor the user actually
buys is merely elevated — the 180d gauge + ITS OWN percentile is the number that prices a LEAPS
entry. Implementation: third narrow-strike fetch in `massive.get_chain_summary` (dte 150–240,
own failure domain — a thin long chain never costs the front harvest; pure `_atm_at_tenor` pick,
test 32) → `atm_iv_180d`/`atm_dte_180d` in new `IV_LONG_COLS` ⊂ `IV_META_COLS` (S44 pattern:
auto-excluded/merged/stamped); "ATM IV (180d)" OPTIONS gauge (sentiment.py) with a "N.NNx front"
tenor-ratio label + S43 stale flag; percentile FORWARD-ONLY (~63 harvests ≈ 3 months — no
backfill; long-dated contracts are too thin for the trades-only inversion). `--call` IV curve
extended to the LEAPS tenors (CURVE_MAX_DTE 150→400, 7 expiries, YY-MM-DD labels, SCOPEKEY
call1→call2) and its paying-up caution now cites the 180d percentile beside the 30d when
available. Model/scorecard side untouched (IV/HV gate + vol_setup factor stay 30d — tenor-matched
to HV-20 / near-dated straddles). **Display convention (user rule, permanent): "percentile"
written in full, never "%ile"** — full sweep done (lens/volsetup/shortint/market_context header +
test assertions; format specs `{x*100:.0f} percentile`); saved to auto-memory
(feedback_percentile_display.md). 32 smoke tests.

S48: **lens_web.py — the Lens as a local web page** (user: "interactive window with a search bar
for the ticker"). Shape decision: Streamlit chosen over (a) a Textual TUI — screen-owning
frameworks repaint the terminal as a character grid and destroy raw sixel; Textual+textual-image
(image-widget candles via the terminal graphics protocol) recorded as the deferred TUI
alternative — and (b) a prompt_toolkit bottom-prompt shell (sixel-safe but not a window). KEY
FINDING: in a browser sixel is unnecessary — a real interactive Plotly candlestick (hover OHLC,
zoom) supersedes it.
- **Core refactor (pure move, verified byte-identical on a piped QQQ run)**: the per-ticker body
  of lens.py's `__main__` is now module-level `render_ticker(ticker, args, use_color,
  interactive, backdrop_base)`; the SPY/breadth/F&G assembly is `build_backdrop(data_dir)`;
  `interactive` param replaces the four scattered `sys.stdin.isatty()` calls. Done via a
  deterministic transformation script (200-line re-indent), not hand-retyping.
- **`--candle none`** style (argparse + print_report): skips the candle panel; lens_web uses it.
- **lens_web.py**: ticker text box + quick-pick pills (scanned from data/*_indicators.csv),
  checkbox blocks (vol/call/squeeze/insider/geo/live + pc-oi scope select), optional
  thesis/level, Plotly candlestick (last ~120 daily bars via timeframes._load_daily), report
  captured from render_ticker (redirect_stdout, use_color=True, interactive=False → stale caches
  reused; "live" checkbox clears the cache) and rendered via ansi2html **inside `st.html`** —
  st.markdown was tried first and FAILED: CommonMark ends an HTML block at the first blank line,
  shredding the <pre> and the monospace alignment (verified in the browser via preview tooling,
  then fixed). Run: `.\trade\Scripts\python.exe -m streamlit run lens_web.py` → localhost:8501.
- Deps added to requirements.txt + venv: streamlit, ansi2html, plotly. `.claude/launch.json`
  gained a `lens-web` entry (preview/verification tooling). CLI behavior unchanged.
- **Rerun-model fix (same day, user-reported)**: Streamlit reruns the WHOLE script on any
  interaction and on the menu's Rerun/R-hotkey; a button reads True only in the run its click
  happened in — gating the display on the click made menu-Rerun BLANK the page. Fixed: the
  rendered report lives in `st.session_state` and is redrawn every rerun; regeneration triggers
  on (ticker, flags)-key change (flag toggles now auto-run, no Run click needed) or an explicit
  Run click (busts the 2-min cache = force-fresh). Verified in-browser: R-hotkey rerun preserves
  the report; ticking `vol` auto-adds the VOLATILITY SETUP block.
- **2s argument debounce (user request)**: a changed (ticker, flags) key starts a settle timer
  (`DEBOUNCE_S=2.0`; sleep-remainder + `st.rerun()` loop); another click during the wait arrives
  as a NEW key and restarts it, so rapid toggles collapse into ONE regeneration. Run bypasses the
  wait. A "⏳ applying in Ns" caption shows during the window. Verified in-browser: vol+call
  clicked 400ms apart → single fetch containing BOTH blocks.
- **Continuous live chart (user request)**: with the `live` flag on the DISPLAYED report,
  the chart renders inside `st.fragment(run_every=LIVE_CHART_EVERY_S=10)` — the fragment reruns
  ONLY itself: one Tradier quote per tick → provisional today-bar via
  `fetch_live_bar`/`append_live_bar` (the CLI --live machinery), 🔴 LIVE price/timestamp caption
  ("session in progress/closed"), daily tail cached (`load_daily_tail`, ttl 600 — keeps the
  yfinance-fallback path from re-downloading per tick). The heavy report is never re-fetched by
  the timer. Verified in-browser mid-session: 10s apart the caption moved 15:09:05→15:09:15 AND
  the price $60.68→$60.56 — a real CRSP tick.
- **Price line + indicator overlays (user request)**: dotted price line at last close (static) /
  the live quote (rides each tick; verified annotation == caption price 60.52 mid-session), and
  display-only checkboxes MA20/MA50 (default on) / MA200 / EMA9 / BB(20,2σ) / volume pane /
  price line. Overlays are computed on a warm-up-extended tail (CHART_WARMUP=200 extra bars) then
  sliced to the 120-bar window so MA200/BB are formed at the left edge. The checkboxes live
  INSIDE the chart section (fragment scope, own st.session_state keys, NOT part of the flags
  key) → toggling redraws only the chart, never triggers the report debounce/regeneration.
  Volume pane = make_subplots row 2, bars colored by close-vs-prior-close.
- **Chart fidelity fixes (user-reported)**: (1) price-tag label was clipped — now anchored
  xanchor="left" at x=1.0 extending into a widened right margin (r=64); NB `add_hline` appends
  " domain" to the annotation xref ITSELF — passing xref explicitly produced "x domain domain"
  and a silent ValueError that blanked the whole chart (the try/except ate it; reproduced
  offline to find it). (2) Candles now follow the lens' TWO-AXIS hollow-candle convention
  (COLOR = close vs PRIOR close, FILL = close vs open) — plotly's single trace can only key on
  close-vs-open, so bars are split into FOUR style-group traces (green/red × hollow/solid);
  within a group close-vs-open is uniform so increasing/decreasing styles are set identically.
  CRSP window: 19/120 bars (7 green-filled + 12 red-hollow) had been drawn wrong before.
- **Volume-profile chart overlay (user request)**: a `vol profile` checkbox reveals aspect pills
  (value area / POC / HVN / LVN / histogram, default all). `volume_profile` gained an opt-in
  `with_hist=True` (returns hist_centers/hist_volumes — backwards compatible). Rendering:
  add_hrect value-area band, POC amber line + inside-left tag, HVN dashed / LVN dotted level
  lines (POC excluded from the HVN list — it duplicates), and the volume-at-price HISTOGRAM as
  horizontal bars on an overlaying reversed x-axis (`xaxis3`, range [max*3.5, 0] → bars hug the
  RIGHT edge, ~28% width). Profile = daily bars, lookback 252 (~1y), cached ttl 600; caption
  notes the report's own profile may differ (1h bars, ~6mo). Verified in-browser on CRSP:
  histogram bulge peaks at the POC line (54.77), 50 bins, band+LVN lines render, price tag
  unaffected.
33 smoke tests (33 = candle-none render path).

S45 (same working day): **equal-weight BREADTH on the MARKET BACKDROP** (`modules/breadth.py`),
answering "is the equal-weighted S&P worth checking?" — yes: "SPY: up" is cap-weighted (top ~10
mega-caps ≈ 35–40%), so the headline can rise while the MEDIAN stock falls. RSP−SPY (and
QQQE−QQQ for the even-more-top-heavy NDX) 20d/63d relative returns read the AVERAGE stock's tape
— what an individual-name entry actually trades. Design honesty: short horizons + a percentile of
the rolling 20d-spread SERIES (not the ratio level) sidestep the secular mega-cap drift that would
otherwise read "narrow" permanently; tags broad-led/narrow/mixed on a ±0.5% dead band. Mirrors the
fng.py pattern exactly: pure `read_breadth` (offline test 29) + `fetch_breadth` (one batched
yfinance download, `data/breadth_cache.json` ~6h TTL, stale fallback, never raises). Surfaced on
the lens MARKET BACKDROP line (`breadth(20d) RSP−SPY +2.9% [91%ile] broad-led · …`, computed once
before the ticker loop) + two market_context.py MARKET gauges (names ≤20 chars per the S40
convention) with a narrow-breadth note (fires when narrow AND ≤25%ile). CONTEXT only — never a
model feature (S20/S32) and deliberately NOT a rally/drawdown-scorecard factor (S43 lesson:
near-always-on factors inflate the tally); narrow = fragility tell, not a sell (S21). First live
read (2026-07-06): both pairs broad-led at the ~91st %ile — rotation INTO the average stock.
29 smoke tests.

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
- Smoke: `.\trade\Scripts\python.exe -m pytest tests/ -q` (33 tests, offline, ~2-7s).
- Web lens: `.\trade\Scripts\python.exe -m streamlit run lens_web.py` → localhost:8501 (S48).
- Display convention (user rule): "percentile" written in full in ALL output — never "%ile";
  number without a % sign (`{x*100:.0f} percentile`).
- Harmless: `Select-Object -First N` truncating a lens pipe gives exit 255 (SIGPIPE), not a crash.

Outstanding / backlog
---------------------
- IV backfills wiped pre-S23 and not yet restored: SOFI, LYFT, QQQ (~15–25 min each, backfill_iv.py
  — now safe to re-run over harvested history, S44 per-cell writes); AAPL missing entirely.
  AMD (462 rows) + NVDA (452) intact. CRSP sparse (178 rows; backfill is a structural dead end per
  S40 — the S44 event-expiry harvest through earnings windows is CRSP's path).
- QQQ backfill run (user): restores the real-IV percentile path for the `--vol` scorecard + the
  `[N percentile]` gauge columns (needs ≥63 IV rows).
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
