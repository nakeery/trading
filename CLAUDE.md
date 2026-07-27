# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Pipeline

Daily workflow:

```bash
# 1. Refresh data + indicators + harvest today's options chain snapshot from Massive
python indicators.py

# 2. Get entry decision — SIGNAL + POSITION SIZING (reads IV from indicators CSV)
python entry.py

# 3. If signal is actionable: get live options chain sizing via Tradier
python sizing.py
```

`indicators.py` requires a Massive API key for the chain harvest. Set `$env:MASSIVE_API_KEY` and
add it to `$PROFILE` for persistence across PowerShell sessions. If the env var is unset, the
Massive client raises `RuntimeError` on the first API call; IV columns are written as NaN and
`entry.py` warns to re-run.

Weekly maintenance:

```bash
# Refresh forward economic release dates (FOMC, CPI, NFP, etc.) from FRED.
# Required only if running with --econ-features (default OFF).
python -m modules.econ_calendar --refresh
```

As-needed analysis:

```bash
# Direction model detail (Phase 2 + 2B)
python direction.py

# IV expansion model detail (Phase 3)
python volatility.py

# Exit signal detail (Phase 4) — drawdown forecast across 5d/15d/63d windows
python exit.py

# Walk-forward backtest (periodic validation)
python backtest.py

# Put/call OI + volume by expiry off the live Tradier chain (positioning vs flow; ad-hoc)
python -m modules.pc_oi          # moved into modules/ (S36); also available inside lens.py via --pc-oi

# Graphical economic calendar — popup month grid of tracked macro release dates (S27)
python econ_calendar_view.py

# Consolidated market-context surface — fear/positioning gauges + trailing percentiles (S29)
python market_context.py            # add --graphical for a matplotlib panel + PNG

# Multi-timeframe market-structure & risk LENS (S34) — the project's PRIMARY tool now: wide-angle
# CONTEXT for your own chart-based entries (state characterization, NOT prediction/alpha).
python lens.py                      # 1h/4h/D/W/M trend+momentum+volume, divergences, vol profile, risk scorecard
python lens.py --thesis bullish --level 700   # confirm/contradict overlay vs your bias
python lens.py --geo                # + cross-asset / geopolitical stress backdrop (oil/OVX/gold/DXY, credit, sectors, EPU/GPR)
# Auto-refresh (S36): lens.py is now the daily driver — if a ticker's indicators CSV is absent, OR is
# missing the latest completed session (weekday past 4 PM ET, else prior weekday; mtime-guarded against
# holiday re-runs), it transparently runs `indicators.py --ticker SYM --no-chart` first (building the
# CSV from scratch when absent, S37), then renders. Best-effort: a failure prints a one-line note and
# the lens proceeds on whatever data exists (yfinance fallback if there's still no CSV).
#   --no-refresh  skip the auto-refresh/build (render whatever is on disk)
#   --refresh     force a refresh even if current
python lens.py --ticker CRSP --squeeze      # SHORT POSITIONING / SQUEEZE block (S41): bi-monthly short
# interest + days-to-cover (NASDAQ API — NASDAQ-LISTED names only, NYSE returns n/a), daily short-volume
# ratio w/ trailing percentile (FINRA Reg SHO files, incrementally cached), and a two-sided squeeze-fuel
# scorecard (DTC bands, SI trend, SVR pctile, shorts-underwater, covering thrust, call-flow surge via
# --pc-oi totals when present, LVN air overhead). Fuel ≠ ignition — caveats printed.
# S41 also adds: a default-on SETUP CHECK ✓/✗/– completeness checklist (HTF alignment, momentum room,
# volume confirmation, NEW relative-strength-vs-benchmark row, value-area location, vol regime, catalyst
# timing) and a CNN Fear & Greed segment on the MARKET BACKDROP line (cached ~6h, unofficial endpoint).
# LENS AS A WEB PAGE (S48): the same engine in a browser window — ticker search bar + quick-pick
# pills, checkbox blocks, ANSI report converted to HTML, and an interactive Plotly candlestick
# replacing the sixel panel (browsers show real images). CLI untouched; report generation is the
# shared lens.render_ticker(). Non-interactive server mode: stale caches reused (tick "live" to force).
.\trade\Scripts\python.exe -m streamlit run lens_web.py     # → http://localhost:8501

python lens.py --ticker QQQ --as-of 2025-03-10   # AS-OF / BACKTEST mode (S57): the whole report
# computed as of a PAST date — every frame truncated engine-side before the reads (forming W/M
# bars resample from source ≤ as-of; last_bar_partial gets the historical session), so trend/
# momentum/volume/profile/risk/setup/gauges/percentiles have NO LOOKAHEAD. Historically valid:
# VIX complex (refetched for the window), SKEW/VVIX (≤2y), SPY tide backdrop, macro proximity
# (econ cache has 5y history), catalysts.csv (today=as_of), as-of next-earnings (yfinance list,
# trusted ≤120d), RS/beta (auto-degrade to n/a beyond the 6mo benchmark fetch), --vol scorecard/
# expected move. Disabled with a note (current-only): live chain quotes (pc-oi/gex/vol quote/
# call), squeeze, insider, geo, breadth/F&G/COT, ex-div, liquidity line, live. Purpose: backtest
# YOUR OWN chart reads against what the lens would have said then. lens_web: "🕰 date range /
# as-of backtest" expander (as-of date + optional chart-from window start — display-only, no
# regenerate) + ?asof=YYYY-MM-DD&from=YYYY-MM-DD deep links; snapshots/diff/ledger suppressed
# in as-of mode (no history pollution, no realized-outcome leakage).
# S57 also adds a TREND REGIME line on the risk scorecard (structure.trend_regime — the
# "overbought can stay overbought" fix, motivated by AMD's Mar–Apr 2026 run reading "DRAWDOWN
# risk elevated 7v0" mid-rally): 1D+1W trend agreement (1M strengthens) + a ≥REGIME_MIN_RUN(5)-
# session close streak on one side of the daily MA20 (`ma20_run`, new read_timeframe field) →
# "ESTABLISHED UPTREND/DOWNTREND — …why…" + a which-lens-to-read-the-factors-through note
# (stretch in an intact uptrend = PULLBACK timing, not a top call; washout in a downtrend =
# BOUNCE risk, not a bottom call). Factor TALLIES untouched (S43 — trend-in-force would be
# near-always-on during rallies). Rides risk["regime"]; web shows a pill + caption in the risk
# panel and regime FLIPS surface in the "Δ what changed" diff.

# LENS AS A REACT WEB APP (S60) — the lens_web.py successor: FastAPI (api/) serves the
# gather_report payload + server-built plotly figs as JSON; a Vite+React+TS app (web/)
# renders it natively. Streamlit lens_web.py stays runnable in parallel until retired.
.\trade\Scripts\python.exe -m uvicorn api.main:app --port 8000 --reload --reload-dir api
npm run dev --prefix web    # Vite dev on :5173 (proxies /api). NB PowerShell: a QUOTED exe
                            # path needs the call operator — & "C:\...\npm.cmd" run dev …
# Prod single-process: npm run build --prefix web, then just uvicorn :8000 (serves web/dist).
# Deep links: ?ticker=QQQ&gex=1&asof=2026-03-10&from=2026-01-02&live=1. Docs: web/FRONTEND.md
# (React orientation + parity checklist). --reload-dir MUST stay restricted to api/ (a
# generate writes under data/ — an unrestricted reload restarts the server mid-generate).
# Never re-implement the candle fig in JS — api/charts.py builds every complex figure.

python lens.py --ticker QQQ --gex           # GAMMA EXPOSURE block (S56): dealer GEX by strike off
# the live Tradier chain (expiries ≤60d via select_gex_expiries — nearest 5 + monthlies, capped 8;
# session-stale cache like --pc-oi) — net GEX regime (dealers long/short gamma → stabilizing vs
# amplifying), call/put walls, zero-gamma flip (BS gamma repricing via bs_invert.bs_gamma), max
# pain (nearest monthly), and unusual volume-vs-OI strikes (vol ≥500 & ≥2×OI; zero-OI = NEW).
# Naive dealer-convention caveats always printed. lens_web draws the levels on the price chart
# ("GEX levels" toggle) + a diverging per-strike bar chart.

python score_ledger.py --ticker QQQ         # score the entry.py forward signal ledger against
# REALIZED 15d/63d returns (S56 — the S30 standing TODO, landed): win = fwd return ≥ the row's
# OWN stamped vol-adjusted threshold (recalibration never rewrites history); rows younger than a
# horizon print "pending"; on a STAY OUT row a ✗ means staying out was right. Reusable
# score(ticker, data_dir); the lens_web signal-ledger expander shows the scored columns.

python lens.py --ticker AMD --street        # STREET & NEWS block (S58): analyst price-target range
# (mean/median/high–low vs spot), 30d EPS-estimate revision momentum per period, trailing-90d
# upgrade/downgrade + PT raise/lower counts, and recent headlines — all yfinance, cached ~6h,
# ETFs degrade to headlines-only. S58 also adds DEFAULT-ON: a SECTOR ROTATION table (11 SPDR
# sectors ranked by 20d/63d RS vs SPY, ► = this ticker's sector), a RETAIL ATTENTION line
# (reddit buzz outside --squeeze, explicit "unranked" state, own-history percentile as
# data/buzz_history.csv accumulates), and a `sent` MARKET BACKDROP segment (CBOE equity P/C ·
# AAII bull−bear · NAAIM exposure · Fed net liquidity 13w tide) — modules/marketsent.py, also
# in market_context.py.

python lens.py --ticker QQQ --ltf           # DAY-TRADER TIMEFRAMES (S63): the multi-TF table splits
# into two blocks — TREND (1M/1W/1D/4h/2h/1h) and, below a divider, ENTRY TIMING (30m/15m/5m).
# 2h is DEFAULT-ON and free (a 90min-offset resample of the cached 1h frame → session-anchored
# 09:30/11:30/13:30/15:30 bins; it also joins the alignment `lower` tuple). The sub-hourly rows are
# opt-in AND live-session-only: outside 09:30–16:00 ET they are skipped with a note ("market
# closed"), and they never load in --as-of mode. Source = ONE Tradier timesales 5min fetch (~20d,
# real-time; yfinance 5m/60d fallback), cached 2min under data/intraday/{tkr}_5m.csv; 15m/30m are
# pure resamples of it. STRICTLY DISPLAY-ONLY (`modules.timeframes.INTRADAY_TFS`): excluded from
# multi_timeframe_summary (synthesis AND the RSI-split line), the rally/drawdown scorecard's
# divergence factors (lens._trend_divs), the thesis blind spots, the squeeze line and the setup
# check. Their heat colouring uses its OWN half-scale so 5m RVOL swings don't wash out the trend
# rows. 5m/15m divergences still print, tagged "(intraday — not a risk factor)".

python lens.py --ticker QQQ --movers        # SECTOR ROTATION top performers (S59): top 3 of each
# sector's ~10 largest constituents by 63d ABSOLUTE return (20d fallback), indented under each
# rotation row (web: extra table column). ~11 yf.Sector constituent lookups + 1 batched download,
# cached ~6h (data/sector_top_cache.json). Yahoo classification — biggest names, not membership.

python lens.py --ticker CRSP --insider      # INSIDER ACTIVITY block (S42): trailing-90d open-market
# Form 4 flow from SEC EDGAR (official free API; contact email in UA — $env:SEC_CONTACT to override;
# ≤10 req/s, ≤25 filings/run, session-stale cache) — net $ flow, latest buy, and CLUSTER-BUY detection
# (≥2 distinct insiders buying within 30d — the Lakonishok-Lee research-backed pattern). Sales are
# printed as weak signals (diversification/comp noise), never a short thesis.
python lens.py --ticker CRSP --vol --live   # INTRADAY mode (S40): live provisional today-bar from the
# Tradier quote (real-time, ~4s; display-only, header shows "LIVE HH:MM ET", bar marked *), 1h frame
# topped up to the current session via Tradier timesales, forming 1h/4h bars marked partial, live
# Tradier ATM IV printed beside the harvested gauge (and used for the expected move), and the
# --pc-oi/--vol quote caches force-refreshed. Without --live nothing changes (session-stale caches).
```

Install dependencies:

```bash
pip install -r requirements.txt
pip install pytest  # not in requirements.txt — dev-only
```

Run smoke tests:

```powershell
.\trade\Scripts\python.exe -m pytest tests/ -v
# 92 tests (S64; 3 skipped), ~3-12s. Requires data/QQQ_indicators.csv + data/QQQ_backtest_results.csv.
```

### Prompt counts per script (for piped input via Claude Code)

| Script | Prompts |
|---|---|
| indicators.py | 3 (ticker, start date, end date) + trailing chart prompt — OR fully non-interactive via `--ticker SYM` (+ optional `--start` / `--end` / `--no-chart` / `--data-dir`), which skips all prompts. `lens.py` uses this for its auto-refresh. |
| direction.py | 2 (ticker, benchmarks — blank = default) |
| volatility.py | 1 (ticker) |
| exit.py | 2 (ticker, benchmarks — blank = default) |
| entry.py | 2 (ticker, benchmarks — blank = default) |
| backtest.py | 2 (ticker, benchmarks) + trailing chart prompt |
| sizing.py | interactive (ticker, budget, strikes) |
| modules/pc_oi.py | 2 (ticker, optional expiry filter — blank = all); run as `python -m modules.pc_oi`. Also surfaced in `lens.py --pc-oi`. |
| modules/vol_history.py | 1 (ticker); run as `python -m modules.vol_history`. Pre-earnings vol study; TTY-gated backfill prompt if IV history is thin. Non-interactive when imported by `lens.py --vol`. |
| econ_calendar_view.py | 0 (argparse flags only — no prompts) |
| market_context.py | 1 (ticker) + argparse flags (--graphical / --save-only / --no-vix) |
| lens.py | 1 (ticker; or `--ticker QQQ JPM …` to skip prompt) + argparse flags (--thesis / --level / --geo / --no-intraday / --no-vix / --no-color / --candle box\|braille\|sixel\|none / --candle-px N / --prev N / --no-refresh / --refresh / --as-of YYYY-MM-DD / --pc-oi [all\|near\|leaps\|monthly …] / --vol / --call / --gex / --live / --ltf / --squeeze / --insider / --street / --movers) |
| lens_web.py | 0 prompts — browser UI; run `.\trade\Scripts\python.exe -m streamlit run lens_web.py` (not for piped/Claude runs; use lens.py). Deep links: `?ticker=QQQ&gex=1` (S56), `&asof=2025-03-10&from=2024-06-03` (S57 backtest/date-range) |
| score_ledger.py | 0 with `--ticker SYM`, else 1 (ticker; EOF-safe default QQQ) |

### Running scripts via Claude Code on Windows

Use the **PowerShell tool** (not Bash) with the cmd /c echo pipe:

```powershell
cmd /c "(echo TICKER && echo.) | python -X utf8 script.py" 2>&1
```

- `-X utf8` is required — avoids cp1252 UnicodeEncodeError on Windows
- `cmd /c` echo pipe is required — PowerShell's native `|` prepends a BOM to stdin
- **Bash tool does not capture Python stdout from cmd /c subprocesses** — script runs but output is dropped. Always use the PowerShell tool.

## Architecture

`indicators.py` must run first — all downstream scripts depend on its CSV output.

| Script | Purpose | Output |
|---|---|---|
| `indicators.py` | Fetch OHLCV, compute 30+ indicators, harvest today's chain summary from Massive; **S44**: when earnings ≤45d out, also stamps `atm_iv_event`/`event_expiry`/`event_dte` — ATM IV of the nearest POST-earnings expiry (`massive.get_event_iv`; quote-based, fills for thin names) so the true front-expiry pre-earnings ramp accumulates for `modules/vol_history.py` (the 30d constant-maturity gauge blunts it) | `data/{ticker}_indicators.csv` (with IV cols), `data/{ticker}_dashboard.png` |
| `direction.py` | Direction ML models (Phase 2 + 2B) | `data/{ticker}_ml_features.csv`, `data/{ticker}_ml_results.png` |
| `volatility.py` | IV expansion ML model (Phase 3) | `data/{ticker}_phase3_features.csv`, `data/{ticker}_phase3_results.png` |
| `exit.py` | Exit signal ML model (Phase 4) — drawdown forecast across 5d/15d/63d windows | `data/{ticker}_exit_features.csv`, `data/{ticker}_exit_results.png` |
| `entry.py` | Combines all models → SIGNAL + POSITION SIZING (reads IV from CSV — no live API) | Console + `data/{ticker}_signal_ledger.csv` (S30 forward ledger — one row per as-of date; same-day re-run overwrites that date's row) |
| `backtest.py` | Walk-forward backtest + 6-month forward return table (53 windows QQQ; 91 AMD; 53 NVDA; 31y SPY; 17 CRSP) | `data/{ticker}_backtest.png`, `data/{ticker}_backtest_results.csv` |
| `sizing.py` | Live options chain sizing via Tradier API | Console only |
| `modules/pc_oi.py` | Put/call OI + volume by future expiry off the live Tradier chain (positioning vs flow); date filter + DTE/monthly narrowing + LEAPS-tenor flag; **per-(ticker,scope) cache** `data/pc_oi_cache/` (S37) — session-stale (a new market close → re-fetch) since OI only settles once/day; refreshes via an interactive prompt in a terminal, piped runs use the cache + a stale note. **Standalone CLI** (`python -m modules.pc_oi`) **and** imported by `lens.py --pc-oi` (S36) via `gather_pc_oi`/`pc_by_expiry` | Console / lens block |
| `backfill_iv.py` | Standalone 2-year historical IV backfill via BS-inversion (one-off per ticker). Reusable `backfill(ticker, data_dir)` returns a status dict (no `sys.exit`) and degrades cleanly when Massive is unavailable (no key / 401 → clean status, never crashes); called by `modules/vol_history.py` (S39). **S44**: writes only NaN cells (`_apply_result`) — a term-refill date keeps its harvested quote-based `atm_iv_30d`, so re-running over harvested history is safe | Updates `data/{ticker}_indicators.csv` in place; checkpointed |
| `probability_deciles.py` | Bucket STRONG ENTRY signals by Phase 2 probability; reports 15d + 6mo edge per bucket. Pure analysis on existing `data/{ticker}_backtest_results.csv` — no model retrain. (S23) | Console only |
| `probability_diagnostics.py` | Investigate WHY a probability bucket under/over-performs. Runs 4-hypothesis tests (time clustering, walk-forward window, multi-phase filter, preceding 20d return). (S23) | Console only |
| `econ_calendar_view.py` | Graphical economic-release calendar (matplotlib popup): month grid of tracked macro releases color-coded by tier, today highlighted; TTL refresh-if-stale + coverage footnotes + PNG export (S27) | `data/econ_calendar.png` + popup window |
| `market_context.py` | Consolidated fear/positioning surface — IV/HV, 25Δ skew, term structure, P/C OI, HV/IV-rank, VIX complex + regime, each with trailing-1y percentile + net read; console always, optional `--graphical` panel (S29). Human-context (S22), not a feature/signal | Console + optional `data/{ticker}_market_context.png` |
| `lens.py` | **PRIMARY TOOL — Multi-timeframe market-structure & risk LENS (S34, hardened S35).** Wide-angle CONTEXT for the user's own chart-based entries (NOT a signal, NO predicted edge). Reads trend/momentum/RSI-OB-OS/volume across 1h/4h/1D/1W/1M (confluence vs conflict — e.g. oversold daily but overbought weekly), divergences, volume profile (POC/value-area/HVN-LVN), a transparent two-sided rally/drawdown risk scorecard, options/vol context (reuses `gather_context`), macro proximity, an always-on SPY+VIX backdrop, an optional `--thesis` confirm/contradict overlay, TradingView-style hollow candles (box/braille/sixel) + a multi-TF column legend, and (S35) an opt-in `--geo` cross-asset/geopolitical stress backdrop, plus (S36) an opt-in `--pc-oi` live put/call OI by expiry (Tradier; combinable `near`/`leaps`/`monthly` scope tokens, bare = all), and (S37) an opt-in `--vol` VOLATILITY SETUP block (Bollinger-Keltner squeeze, expected move + breakevens, earnings catalyst, two-sided long-vol-vs-short-vol straddle/strangle scorecard, and a live ATM-straddle + auto-strangle pricer (S38: EARNINGS-AWARE for pre-earnings long-vol — when earnings ≤45d out it anchors to POST-earnings expiries, showing the nearest one AND the nearest post-earnings monthly when they differ, else falls back to near-monthly ~30d with a note; auto-width ±expected move (= straddle/spot); per-leg OI + bid/ask) with breakevens + move-needed + a one-line straddle-vs-strangle vega guide. **S40 honesty pass:** the scorecard's IV cheap/rich factor uses the REAL `atm_iv_30d` trailing percentile (bands 0.30/0.70; HV-proxy fallback explicitly labeled when IV history is thin), the earnings catalyst demotes to a `notes` line when ATM IV already ≥70%ile (event premium priced), only 1D/1W/1M squeezes count as factors (intraday still listed on the compression line), each strangle wing snaps to the NEAREST tradeable OTM strike holding ≥`SNAP_OI_FRAC`(0.5)× the busiest nearby candidate's OI (dead strikes skipped, but lumpy round-number OI no longer drags the wing off target), the strangle label shows PER-WING widths (`−a% / +b%, target ±EM` when ≥1pp off), and an `at ask:` cost/BE line appears when the mid understates the executable cost by >3%; `modules/volsetup.py` + `structure.read_squeeze` + `features.next_earnings` + `modules/volquote.py` (Tradier, cached like pc-oi)), plus (S40) an opt-in `--live` INTRADAY mode — live provisional today-bar from the real-time Tradier quote (display-only, "LIVE HH:MM ET" header, `*`-marked), Tradier-timesales top-up of the 1h frame, forming 1h/4h bars treated as partial, live ATM IV beside the harvested gauge (and in the expected move), and force-refreshed `--pc-oi`/`--vol` quotes, plus (S41) an opt-in `--squeeze` SHORT POSITIONING block (`modules/shortint.py`), a default-on SETUP CHECK ✓/✗/– checklist (`modules/setupcheck.py`), and a CNN Fear & Greed segment on the MARKET BACKDROP line (`modules/fng.py`), plus (S42) an opt-in `--insider` SEC EDGAR Form 4 block with cluster-buy detection (`modules/insider.py`), plus **(S43) scorecard-integrity fixes**: the implied-vs-realized move is display-only (it duplicated the IV/HV factor — one input could flip the vol verdict alone), HVN "approaching S/R" risk factors require ±5% proximity (`HVN_NEAR_PCT`), W/M partial-bar detection is calendar-aware (a Thu/Fri forming week or late-month forming month now gets the `*`), harvested gauges lagging the CSV are labeled "(stale Nd)", thin-frame MACD/Stoch print "—" instead of a definite state, and a no-bid leg flags the straddle/strangle mid as indicative, plus **(S46) long-call decision context**: an opt-in `--call` LONG CALL VIABILITY block (`modules/callquote.py` — 45/90-DTE monthly ATM + ~0.375Δ quotes with breakeven move, theta/day as % of premium, at-ask honesty line, earnings/ex-div notes, ATM-IV-by-expiry curve, chain liquidity grade; IV≥70%ile prints a paying-up caution), a default-on **options liquidity** line in OPTIONS & VOL CONTEXT (zero network — reads the `--call` cache with an as-of stamp), a default-on **Market beta** SETUP CHECK row (60d β/corr vs SPY — how much the backdrop applies to THIS name; always informational), an **ex-div** suffix on the Catalyst-timing row (`features.next_ex_dividend` — exact from the yfinance calendar, else cadence-estimated with `~`; calls don't earn the dividend + deep-ITM early-exercise risk), and a default-on **KNOWN CATALYSTS** section surfacing `catalysts.csv` binary events ≤45d (`benchmarks.upcoming_catalysts` — CRSP PDUFA dates were previously ML-only), plus **(S48) a shared render core**: the per-ticker body is module-level `render_ticker(ticker, args, use_color, interactive, backdrop_base)` + `build_backdrop(data_dir)` (pure extraction, byte-identical output; `interactive` gates the TTY cache-refresh prompts) and `--candle none` skips the candle panel, plus **(S49) a full compute/format split**: `gather_report(ticker, args, interactive, backdrop_base)` returns one picklable payload dict (all section data incl. the risk scorecard + macro events, previously computed inside `print_report` — now `risk=`/`macro_events=` kwargs with compute-if-absent defaults; NO DataFrames, st.cache_data pickles it) and `render_payload(p, ...)` prints the CLI report from it; `render_ticker` = gather + render (CLI byte-identical, verified). Percentiles display as ordinal + Unicode superscript via `sentiment.ordinal_percentile` ("97ᵗʰ percentile" — S49 user convention, applied in lens.py/volsetup/shortint), plus **(S56)** an opt-in `--gex` GAMMA EXPOSURE block (`modules/gex.py` — net dealer-gamma regime, call/put walls, zero-gamma flip, max pain, unusual vol-vs-OI strikes), a CFTC COT lev-funds segment on the MARKET BACKDROP line (`modules/cot.py`, weekly ~24h cache), retail buzz inside `--squeeze` (`modules/buzz.py`), SKEW/VVIX gauges in OPTIONS & VOL CONTEXT, and NYSE short-interest coverage via the FINRA consolidated API fallback, plus **(S58) four context expansions**: a DEFAULT-ON SECTOR ROTATION table (`modules/sectors.py` — 11 SPDR sectors ranked by 20d/63d RS vs SPY, quadrant tags, ► own-sector mark), a DEFAULT-ON RETAIL ATTENTION section (buzz outside `--squeeze` with an explicit unranked state + own-history mentions percentile off the new `data/buzz_history.csv`), an opt-in `--street` STREET & NEWS block (`modules/street.py` — analyst PT range/EPS-revision momentum/rating counts + headlines; ETFs headlines-only), and a `sent …` MARKET BACKDROP segment (`modules/marketsent.py` — CBOE equity P/C, AAII bull−bear [full-history percentile], NAAIM exposure, Fed net liquidity WALCL−TGA−RRP w/ 13w tide tag); all four current-only → suppressed in as-of mode with the note extended, plus **(S63) day-trader timeframes**: a default-on `2h` trend row (free — a 90min-offset resample of the cached 1h frame) and an opt-in `--ltf` sub-hourly ENTRY TIMING block (30m/15m/5m) rendered below a divider inside the SAME multi-TF table, live-session-only and strictly display-only (see the `--ltf` example above) | Console |
| `lens_web.py` | **(S48)** The Lens in a browser: `.\trade\Scripts\python.exe -m streamlit run lens_web.py` → localhost:8501. Ticker search box + quick-pick pills (from `data/*_indicators.csv`), checkbox blocks (vol/call/squeeze/insider/geo/live + pc-oi scope), optional thesis/level, an interactive Plotly candlestick (last ~120 daily bars; supersedes sixel — browsers render real images), and the full report with terminal colors via ansi2html inside `st.html` (NOT st.markdown — markdown ends HTML blocks at blank lines and shreds the `<pre>`). Captures `lens.render_ticker` stdout with `interactive=False` (stale caches reused; "live" checkbox force-refreshes); `st.cache_data(ttl=120)` per (ticker, flags). Rendering is REDRAWN FROM `st.session_state` on every script rerun (Streamlit reruns the whole script on any interaction/menu-Rerun; gating display on the Run click blanked the page — fixed). Regenerates when the (ticker, flags) key changes (flag toggles auto-run, DEBOUNCED 2s — rapid clicks batch into one fetch; the timer restarts on each change) or on an explicit Run click (bypasses the debounce and busts the 2-min cache = force-fresh). With "live" ticked the chart is CONTINUOUS: a `st.fragment(run_every=10s)` redraws it with a fresh Tradier quote appended as a provisional today-bar (same `fetch_live_bar`/`append_live_bar` as CLI `--live`; 🔴 LIVE price/timestamp caption; one quote per tick; the report is NOT re-fetched). Chart carries a dotted last/LIVE **price line** (rides each tick; price-tag label extends into a reserved right margin — never clipped) and DISPLAY-ONLY **indicator checkboxes** — MA20/MA50 (default on), MA200, EMA9, BB(20,2σ), volume pane, price line — computed on a warm-up-extended tail (`CHART_WARMUP=200` bars) so MA200/BB are formed at the window's left edge; toggles rerun only the chart section, never the report/debounce. Candles follow the lens' TWO-AXIS hollow convention (color = vs prior close, fill = vs open) via four split style-group traces (plotly's single trace can't express it). A **vol profile** checkbox reveals aspect pills (value area band / POC / HVN / LVN / right-edge volume-at-price histogram — `volume_profile(with_hist=True)`, daily ~1y, cached; the report's own profile may use 1h/6mo, caption notes the difference). Deps: streamlit/ansi2html/plotly. **(S49) native visual report**: the page renders the payload from `lens.gather_report` as native Streamlit sections (`lens_web_sections.py` — one renderer per report section in print order: metric-tile header, backdrop chips, color-styled multi-TF dataframe reusing the CLI heat/tint math, two-sided risk + setup-check panels, gauge tables with ordinal percentiles, put/call OI grouped-bar Plotly chart, straddle/strangle + long-call quote tables, IV-by-expiry curve; each renderer mirrors print_report's None-guards and a failure degrades to a warning, never a blank page); the full ANSI report (rendered from the SAME payload via `render_payload` — one compute, two renderings, byte-equal guarded by test 34) lives in a collapsed "full text report" expander; **(S56)** watchlist landing grid (CSV-only tiles + latest setup-score chip; click = pill semantics), day-over-day "Δ what changed" diff (compact snapshots under `data/payload_history/`, pruned 90/ticker: setup flips, risk factors added/cleared, gauge percentile moves ≥10pt), RSI/MACD chart subpanes, GEX-levels chart toggle + `sec_gex` per-strike bars, 25Δ-skew subpane on the IV-history figure, scored signal-ledger expander (`score_ledger.score`), `?ticker=QQQ&gex=1` deep links (read once pre-widgets, written back after each generate), st.status stage log, `.streamlit/config.toml` dark theme, sidebar quick-nav (anchor slugs via `lens_web_sections._slug`); **(S58)** `street` checkbox + `?street=1` deep link, `sec_street` (PT/revisions/ratings metric tiles + linked headlines), `sec_sectors` (tinted RS dataframe, own-sector row highlight), `sec_buzz` (chips + mentions sparkline off `data/buzz_history.csv`; renders only when the squeeze section is absent), backdrop chips pick up the `sent …` segment automatically | Browser (localhost:8501) |
| `modules/features.py` | Shared feature engineering (HV, VIX, earnings, normalize, vol thresholds, IV imputation, P4 drawdown threshold + target, trend-break features) + constants | Imported by direction/volatility/exit/entry/backtest |
| `modules/benchmarks.py` | Sector benchmarks, macro features, catalyst proximity | Imported by direction/entry/backtest/volatility |
| `modules/massive.py` | Massive.com API client + `get_chain_summary()` + `get_historical_iv_snapshot()` + `get_event_iv()` (S44 — nearest post-earnings-expiry ATM IV; pure `pick_event_atm` selection); **S47**: `get_chain_summary` also harvests `atm_iv_180d`/`atm_dte_180d` — the ~6mo LEAPS-entry tenor (third narrow-strike fetch, dte 150–240; pure `_atm_at_tenor` pick; own failure domain) shown as the "ATM IV (180d)" gauge with a "N.NNx front" tenor-ratio label; percentile accumulates FORWARD-ONLY (no backfill — long-dated contracts too thin for trades-only inversion). Exports `IV_COLS`, `IV_FEATURE_COLS`, `IV_META_COLS` (now incl. `IV_EVENT_COLS` + `IV_LONG_COLS`) | Imported by `indicators.py` (harvest), `backfill_iv.py` (history), and 5 ML scripts (exclude from features) |
| `modules/econ_calendar.py` | FRED client + `add_macro_event_proximity()` proximity features; display/GUI helpers `next_event_per_series`/`upcoming_events`/`events_in_range`/`coverage_end_per_series`/`refresh_if_stale` (S22/S27). Cache: `data/econ_calendar.csv`. CLI: `--refresh` (weekly) / `--upcoming` | Imported by entry/direction/volatility/exit/backtest/calibrate_multipliers (gated by `--econ-features`, default OFF) + `econ_calendar_view.py` |
| `modules/sentiment.py` | Band-labelers (IV/HV, skew, term, P/C, IV-regime) + `gather_context()` — per-ticker fear/positioning gauges with trailing percentiles, reusing `compute_hv_features`/`add_vix`/`classify_regime` (S29). **S56**: MARKET block adds CBOE **SKEW** (tail-risk pricing, bands 130/150) + **VVIX** (vol-of-vol, bands 85/110) gauges — yfinance ^SKEW/^VVIX 2y batch, own try so a miss never costs the VIX rows; display-only, never model features | Imported by `market_context.py` + `lens.py` |
| `modules/gex.py` | **(S56)** Dealer gamma-exposure analytics for `lens.py --gex`. Pure compute on per-strike chain rows (offline-testable): `gex_by_strike` (Γ×OI×100×S²×0.01, calls +/puts −), `key_levels` (call/put walls), `zero_gamma` (BS-repriced net-gamma profile ±15%, crossing nearest spot; `bs_invert.bs_gamma`), `max_pain` (min total intrinsic payout, nearest monthly), `unusual_activity` (vol ≥500 & ≥2×OI; zero-OI = NEW), `select_gex_expiries` (nearest 5 + monthlies ≤60d, cap 8). Fetch via `tradier.get_chain` (greeks already ride every chain call); cached session-stale under `data/pc_oi_cache/` (volquote pattern, SCOPEKEY gex1, `force=` under `--live`). Caveats always printed: naive dealer convention (long calls/short puts), OI settles once daily | Imported by `lens.py` (`--gex`) |
| `modules/cot.py` | **(S56)** CFTC Commitments of Traders — TFF futures-only Socrata dataset (official, NO key; id `gpe5-46if`), contracts E-MINI S&P 500 / NASDAQ MINI / VIX FUTURES: leveraged-funds net position as % of OI + inline weekly percentile (≥26w floor — `sentiment.percentile_of`'s 63-obs floor is a daily convention). `label_cot(invert=True)` for VIX (net-short specs = the vol-selling carry crowd). Cached ~24h `data/cot_cache.json` (fng pattern, stale fallback, never raises). Shown on the lens MARKET BACKDROP line + market_context gauges; Tuesday data publishes Friday (3-day lag baked in) | Imported by `lens.py` + `market_context.py` |
| `modules/buzz.py` | **(S56, expanded S58)** ApeWisdom retail-attention gauge — keyless API, top ~400 tickers cached ~6h (`data/buzz_cache.json`, ONE feed fetch serves every ticker); `buzz_read` (pure) → rank/mentions/24h-change. **S58: DEFAULT-ON** — its own RETAIL ATTENTION section when `--squeeze` is off (ranked reads still ride the squeeze block), an explicit `{"unranked": True}` state (quiet is visible, not silent; feed-down stays silent), and daily history accumulation to `data/buzz_history.csv` (`record_history` on every fresh fetch AND fresh cache read, deduped date+ticker, ~400d retention) powering `mentions_pct` (own-history percentile, ≥10 prior days) + a web sparkline. Attention ≠ direction — caveat printed | Imported by `lens.py` (default-on + `--squeeze`) |
| `modules/sectors.py` | **(S58, +S59 movers)** Sector rotation — the 11 SPDR sectors (all 11 GICS sectors covered: XLK/XLC/XLY/XLF/XLV/XLI/XLE/XLB/XLP/XLU/XLRE) ranked by RS vs SPY (20d/63d, mirrors breadth/setupcheck horizons) with RRG-style quadrant tags (leading/improving/weakening/lagging, ±0.5% flat band); `rotation_read` (pure) + `own_sector` (ticker's own SPDR via `TICKER_BENCHMARK`, no network — AMD→XLK, QQQ→None) + `fetch_sectors` (one batched yfinance download, cached ~6h `data/sectors_cache.json`, breadth.py pattern). DEFAULT-ON lens section (► marks own sector); as-of mode omits it. **S59: opt-in `--movers`** — top 3 of each sector's ~10 largest constituents ranked by 63d ABSOLUTE return (20d fallback on short series): `YF_SECTOR_KEYS` (SPDR→yfinance Sector key, all 11 probed live), pure `top_performers_read`, `fetch_top_performers` (~11 `yf.Sector(key).top_companies` lookups each in its own try + ONE batched 6mo download, cached ~6h `data/sector_top_cache.json`, stale fallback, never raises); rides `sectors["top"]` → indented `top:` lines under each CLI rotation row + a "Top performers (63d)" column in the web table. Biggest names ≠ full membership — caveat printed. Context only, never a feature, not a risk factor | Imported by `lens.py` (default-on) |
| `modules/street.py` | **(S58)** Street expectations + news for `lens.py --street` — four yfinance endpoints (probed live; NOT the 401-prone `.info`): `analyst_price_targets` (spot + mean/median/high/low), `upgrades_downgrades` (trailing-90d grade + PT-action counts), `eps_trend` (30d estimate-revision momentum per period), `news` (≤6 headlines). `street_read` (pure) → PT upside vs spot, revision tags + net drift, rating counts; ETFs degrade to headlines-only (QQQ probed). Cached ~6h per ticker `data/street_cache/`; yfinance logger silenced (ETF 404 noise). Caveat printed: targets follow price — post-selloff "upside" is stale ink | Imported by `lens.py` (`--street`) |
| `modules/marketsent.py` | **(S58)** Market-wide sentiment + liquidity — four gauges, each its own try (a miss never costs the rest), cached ~6h `data/marketsent_cache.json` with per-gauge stale fallback: **CBOE put/call ratios** (daily-stats page's Next.js blob, `parse_cboe` pure; EQUITY P/C banded 0.55/0.85, percentile accumulates forward-only ≥63d), **AAII bull−bear spread** (official free .xls, FULL history since 1987 → real percentile day one; OLE2 magic check — the server intermittently serves HTML/bot-blocks, weekly cadence means one success/week suffices), **NAAIM exposure** (site HTML table ~10 weeks; bands 90/30, percentile after ≥26 accumulated weeks), **Fed net liquidity** = WALCL − TGA − RRP (FRED, reuses `FRED_API_KEY`; WALCL/WTREGEN are $mn, RRPONTSYD $bn — probed; weekly W-WED aligned, 13w Δ tag ±$25bn, 1y level percentile). Shown as a `sent …` MARKET BACKDROP segment + market_context MARKET gauges; contrarian S21 note on the surveys | Imported by `lens.py` + `market_context.py` |
| `modules/overnight.py` | **(S64)** Overnight & extended-hours context — the off-hours blind-spot fix (the stack is otherwise RTH-gated + daily-bar). Three DEFAULT-ON display-only surfaces, the first two rendered ONLY when the market is closed (`not session_open()` — during RTH the SPY tide/live bar cover direction, so RTH runs make zero extra calls): **(1) futures backdrop segment** `fut ES +0.1% · NQ −0.4% (o/n vs prior settle, HH:MM ET)` on the MARKET BACKDROP line — pure `read_futures` + `fetch_futures`, ONE batched yfinance `ES=F`/`NQ=F` daily download (the in-progress Globex row's Close IS the live print; probed 2026-07-27 — `fast_info.previous_close` matches no settle, prior settle must come from the daily history), cached `data/futures_cache.json` **TTL 20 MINUTES** (deliberate deviation from the ~6h convention — overnight tape decays in minutes; the segment carries its fetch timestamp); **(2) after-hours print** — one line under the O/H/L/C (`AH`/`pre-mkt`, last extended-hours trade vs official `close`/`prevclose`). **S64 fix — the price comes from the Tradier TIMESALES tape (`session_filter="all"`), NOT the quote**: `/markets/quotes` latches `last` to the official close at the bell exactly like `close` (probed live 2026-07-27 16:34 ET on SOFI, 34 min post-close with ~130k AH shares traded — `last` 16.88 == `close` 16.88, `trade_date` frozen at 16:00:00.153, while `bid_date` was 8s old and the tape showed 16.92), so the original quote-derived read was structurally pinned to +0.00%. `fetch_ext_print` takes the last **1min** bar (`EXT_INTERVAL` — 5min left the tile's stamp frozen for minutes at a time) strictly outside RTH and strictly after `_ext_window_start` (= the last completed session's 16:00 — one rule covering the evening AND the next pre-market; the strict `>` also drops the 16:00 closing-auction bar Tradier stamps at the bell, so a name with no real AH trade shows nothing rather than its own close); `afterhours_read(quote, ext, now)` stays pure with an injectable clock, uses the quote only for the reference close, stamps `hhmm` with the PRINT's time (not the wall clock), and returns **None when there is no extended-hours print** so the caller renders nothing rather than a frozen 0.00%; **(3) gap gauges** (in `sentiment.gap_gauges`, ride `gather_context`'s VOL group) — "Gap at open" + "Gap vol (5d)" off the indicators CSV's `gap_pct`/`gap_ma_5d`/`gap_vol_5d` columns (written by indicators.py since S1, previously unconsumed), zero network, percentile of \|gap\| (magnitude), historically valid in as-of mode for free. Futures/AH suppressed under `--as-of`. Never a model feature, NOT risk-scorecard factors (S20/S43). Web: fut chip + gap gauges automatic; AH header tile in `HeaderTiles.tsx` polls its OWN `GET /api/afterhours/{ticker}` every 30s (🔴 once the poll answers), falling back to `payload["ah"]` for the first paint. The endpoint short-circuits to `{"ah": null}` during RTH before any Tradier call (server is the authority on session state → the client polls unconditionally) and sits behind a 10s `afterhours_cache`. It is deliberately NOT on the live tick any more: riding `LiveInfo.ah` coupled it to `CandleChart`'s miss-counter, which counts `fetch_live_bar` misses — and that always misses overnight/pre-market (`trade_date` isn't today), so polling died after ~30s and froze the tile. It also no longer needs the **live** checkbox at all | Imported by `lens.py` (default-on) + `modules/sentiment.py` (gap gauges) |
| `score_ledger.py` | **(S56)** Forward signal-ledger scorer — the S30 standing TODO, landed. Joins `data/{ticker}_signal_ledger.csv` to realized 15d/63d returns off the indicators CSV closes; WIN vs each row's OWN stamped `win_threshold`/`win_threshold_63` (threshold recalibration never rewrites history); young rows = pending; per-tier + ALL-ROWS aggregates. Reusable `score(ticker, data_dir)` status dict (backfill_iv pattern, never raises); the lens_web ledger expander renders the scored columns zero-network | Console + imported by `lens_web.py` |
| `modules/timeframes.py` | (S34) `build_timeframes()` → per-timeframe OHLCV {5m,15m,30m,1h,2h,4h,1D,1W,1M}: resamples daily (indicators CSV or yfinance fallback) for D/W/M; yfinance 60m (~2yr/730d, cached `data/intraday/`) + 1h→4h/2h resample for intraday. **S63**: `TF_ORDER` (the single source of row order for CLI + React — any key absent from it is dropped) gains 2h/30m/15m/5m; `INTRADAY_TFS`/`TF_MINUTES`/`session_open()` (RTH gate, `now` injectable); `_load_intraday` parameterised by interval/label/period (own cache file each); `_load_ltf` = Tradier 5min → yfinance 5m fallback, 2min TTL; `build_timeframes(ltf=)` adds 5m/15m/30m only when `session_open()` and not as-of. (S35) `last_bar_partial()` flags an in-progress (or stale mid-period) W/M bar via source-bar count. (S40) `fetch_live_bar`/`append_live_bar`/`apply_live_bar` — live provisional today-bar from the Tradier quote for lens `--live` (display-only, never written to CSV); `merge_intraday_topup`/`_topup_intraday` — Tradier timesales 15min→60m top-up of the 1h frame (live mode); `_load_intraday` now falls back to a stale cache with a note when the yfinance download is refused (Yahoo throttles intraday intermittently) | Imported by `lens.py` |
| `modules/structure.py` | (S34) transparent per-timeframe reads — `read_timeframe` (trend/RSI/Stoch/MACD), `read_volume` (RVOL/up-down/price-volume confirmation; S35 `exclude_last` drops an in-progress bar so partial-bar volume doesn't read artificially low), `detect_divergence` (price vs RSI/OBV), `multi_timeframe_summary` (confluence/conflict; **S63** drops `INTRADAY_TFS` up front — the `higher`/`lower` tuples already ignored unknown keys, but the OB/OS lists behind `rsi_conflict` iterated every read, so a 5m RSI spike would have raised an "RSI split" warning about a frame the synthesis never saw; `lower` also gains `2h`, which marginally tightens full-confluence since it is an `all()`), `rally_drawdown_risk` (two-sided scorecard). No ML, no prediction | Imported by `lens.py` |
| `modules/volume_profile.py` | (S34) `volume_profile()` → volume-at-price: POC, value area (70%), HVN/LVN levels + price location | Imported by `lens.py` |
| `modules/geocontext.py` | **(S35)** `gather_geo_context()` → opt-in cross-asset / geopolitical stress backdrop for `lens.py --geo` (CONTEXT only, never a model feature). Gauges: oil (WTI/Brent/OVX), gold, DXY, HY-OAS credit, MOVE, defense/semis/wheat/natgas, EPU + GPR — each level · trailing-252-obs percentile · stress tag, + a composite read. yfinance (batched) + FRED (reuses `econ_calendar` key) + best-effort GPR `.xls` (needs `xlrd`); reuses `sentiment.percentile_of`; cached `data/geo_cache.json` (~6h TTL); never raises | Imported by `lens.py` |
| `modules/bs_invert.py` | Black-Scholes implied-vol solver (Newton-Raphson + bisection fallback) — used by `backfill_iv.py` | Imported by `modules/massive.py` |
| `modules/vol_history.py` | **(S39)** Pre-earnings VOL STUDY — evidence layer for `--vol`. `pre_earnings_vol_study()` measures the historical IV ramp / post-earnings crush / buy-early-sell-before-print ATM-straddle P&L over the last ~8 earnings off on-disk `atm_iv_30d` (constant-maturity 30d proxy) + `Close`, with a 5/10/15-session entry-timing sweep; TTY-gated offer to run the Massive backfill when IV history is thin. HV rejected (ramp is implied-vol; HV misses it). Standalone `python -m modules.vol_history` + a one-line inline verdict in `lens --vol`. Descriptive only | Imported by `lens.py`; reuses `bs_invert.black_scholes_call` + `features.earnings_dates` + `backfill_iv.backfill` |
| `modules/tradier.py` | Tradier API client + `get_atm_iv()`; S30 adds `get_daily_quote()` (post-close OHLCV latch) + `get_daily_history()` (unadjusted daily bars); S40 adds `get_timesales()` (real-time intraday bars, ~40d of 15min history — lens `--live` 1h top-up). **Brokerage-token market data is REAL-TIME (measured ~4s delay)** — the only live source in the stack (Massive = 15-min-delayed snapshots, no quote timestamps on Options Starter; yfinance = after-market daily + intermittently-throttled intraday) | Imported by `sizing.py`, `modules/pc_oi.py`, `modules/volquote.py`, `modules/timeframes.py`, `lens.py` (`--live`), and `indicators.py` (same-day close stamp) |
| `modules/shortint.py` | **(S41, +S56 NYSE coverage)** Short positioning / squeeze context for `lens.py --squeeze`. `fetch_short_interest` (NASDAQ API first, unofficial/UA-gated; **S56 fallback: FINRA consolidated short interest Query API — official api.finra.org, NO auth needed** (probed live: unauthenticated POST filters work; a GTE settlementDate filter is REQUIRED — the API returns oldest-first and truncates at `limit`, so without it long-listed names surface stale settlements) → NYSE names now resolve; `parse_finra_si` maps to the NASDAQ row shape; session-stale cache) → bi-monthly SI + days-to-cover + ΔSI; `fetch_short_volume` (FINRA Reg SHO daily files, official CDN, incrementally cached per ticker — first run ~90 files, then 1/day) → daily short-volume ratio + trailing percentile; `squeeze_read` — pure two-sided fuel-vs-counter scorecard (DTC ≥8/≥15 bands, SI ±10%, SVR ≥80%ile, shorts-underwater, +3%/1.5x thrust, call-flow surge off `--pc-oi` totals, LVN air ≤+8%). Caveats always printed (bi-monthly lag; ~50% SVR baseline is normal — percentile is the tell; fuel ≠ ignition). Caches under `data/shortint_cache/` | Imported by `lens.py` (`--squeeze`) |
| `modules/setupcheck.py` | **(S41)** Default-on SETUP CHECK — transparent ✓/✗/– completeness checklist over reads the lens already computes: HTF alignment, momentum room, volume confirmation, **relative strength vs sector benchmark** (`fetch_rs` — `TICKER_BENCHMARK` first entry / SPY fallback, one yfinance fetch, series aligned to common last date, best-effort n/a), value-area location, vol regime (very-rich IV ✗; VIX stress = S21 contrarian note, not a fail), catalyst timing (earnings ≤7d / Tier-1 macro ≤1d = flagged `–`, NOT failed). Explicitly a blind-spot catcher, not a probability | Imported by `lens.py` |
| `modules/fng.py` | **(S41)** CNN Fear & Greed gauge (unofficial endpoint; needs browser UA + Referer — 418 otherwise). `fetch_fng` → {score, rating, pct (percentile off the payload's own ~1y history)}, cached `data/fng_cache.json` ~6h, stale-cache fallback, never raises. Shown on the lens MARKET BACKDROP line + as a market_context.py gauge with the S21 contrarian-read note | Imported by `lens.py` + `market_context.py` |
| `modules/breadth.py` | **(S45)** Equal-weight market breadth — RSP−SPY + QQQE−QQQ 20d/63d relative returns (cap-weighted "SPY up" can be a narrow mega-cap-led tape; the equal-weight twin reads the AVERAGE stock). Pure `read_breadth` (tags broad-led/narrow/mixed on a ±0.5% band; percentile off the rolling 20d-spread series — short horizons + own-series percentile sidestep the secular mega-cap drift) + `fetch_breadth` (one batched yfinance download, cached `data/breadth_cache.json` ~6h, stale fallback, never raises). Shown on the lens MARKET BACKDROP line + as market_context.py gauges. CONTEXT only — never a model feature, deliberately NOT a risk-scorecard factor (S43 lesson) | Imported by `lens.py` + `market_context.py` |
| `modules/callquote.py` | **(S46)** Long-call viability quote for `lens.py --call` — the directional instrument's carry math off the live Tradier chain: nearest monthlies to 45/90 DTE (`_select_expiries`), ATM + ~0.375Δ candidates (`pick_call_candidates`; no-bid strikes skipped) with mid premium, breakeven move, **theta/day as % of premium**, OI/spread (+at-ask line when mid understates >3%), earnings- and ex-div-aware per-expiry notes, an ATM-IV-by-expiry curve (`curve_read`, ≤5 monthlies ≤150d) and a chain `liquidity_grade` (ATM-region median spread + OI → tight/ok/wide/dead). Cached session-stale like volquote (SCOPEKEY call1, `force=` under `--live`); `cached_liquidity` serves the grade zero-network to the default-on OPTIONS line | Imported by `lens.py` (`--call` + the default-on liquidity line) |
| `modules/insider.py` | **(S42)** SEC EDGAR insider activity for `lens.py --insider`. Official free APIs: `company_tickers.json` ticker→CIK (7d cache) → `data.sec.gov` submissions → per-filing Form 4 XML (xsl prefix stripped; stdlib ElementTree). Non-derivative open-market P/S only; trailing-90d net $ flow + `cluster_buys` (≥2 DISTINCT insiders buying inside any 30d window — Lakonishok-Lee) + two-sided `insider_read` with always-printed caveats (sales = weak signal; Form 4 ≤2-day lag; 10b5-1 not separated). SEC fair-access: contact email in UA (`$env:SEC_CONTACT` overrides), 0.12s/req, ≤25 filings/run; summary cached session-stale under `data/insider_cache/` | Imported by `lens.py` (`--insider`) |
| `tests/test_smoke.py` | 52 pytest regression guards (signal hierarchy, STRONG ENTRY baseline, vol thresholds, signal logic, S16 threshold-sensitivity, econ_calendar loads, Days_to_* bounds, days-to-specific-event, regime thresholds/gate/NaN, next_event/upcoming shape, sentiment labelers, S35 geocontext stress/composite, S38 volquote snap + expiry selection, S39 vol-history study, S40 vol_setup factors + live-bar append + intraday top-up merge, S41 shortint parsers/scorecard + setupcheck + fng parser, S42 insider Form 4 parse + cluster detection, S43 last_bar_partial calendar check + vol_setup em-factor removal, S44 backfill per-cell no-overwrite + event-expiry IV selection/tenor guard, S45 equal-weight breadth read, S46 callquote candidates/liquidity-grade/IV-curve + beta/ex-div/catalysts helpers, S47 long-tenor ATM pick, S48 candle-none render path, S49 render_payload/print_report byte-equality + lifted risk/macro kwargs identity + gather_report payload contract + ordinal-percentile display, S53 seasonality/earnings-reactions, S56 GEX math incl. zero-gamma/max-pain/unusual-activity + ledger scorer + COT/buzz/FINRA-SI parsers + lens_web snapshot-diff/anchor-slugs, S57 as-of truncation — source-frame truncate + forming-period survival + historical last_bar_partial + gather_context as-of, S57 trend_regime — established up/downtrend detection + ma20_run streak + tallies-untouched guard, S58 sector rotation_read/quadrants/own_sector + buzz history/unranked-sentinel/mentions-percentile + street_read tags/ETF-degrade + marketsent parse_cboe/aaii/naaim/liq-units reads, S59 top_performers_read ranking/cap/20d-fallback/omission + YF_SECTOR_KEYS↔SECTORS coverage, S63 day-trader timeframes — session_open RTH boundaries, 5m→15m/30m + 1h→2h resample bins (the 2h offset is 90min not 30min: pandas anchors bins at midnight+offset and 09:30 sits 90min past a 2h boundary), sub-hourly excluded from synthesis/RSI-split/divergence-risk-factors, TF_ORDER ordering + the closed-market and as-of gates, S64 overnight — read_futures vs-prior-settle + afterhours_read AH/pre-mkt labels/prevclose-fallback/stale-trade_date drop/never-raises + the print_report AH line + gap_gauges signed-value-abs-percentile/NaN-today-row/missing-columns) | Run manually; requires `data/QQQ_*.csv` |

All CSVs and PNGs are written to the `data/` subdirectory (must exist — create manually if missing).

## Decision Framework

`entry.py` and `backtest.py` use a unified five-label SIGNAL output:

| Signal | Conditions | Position Sizing |
|---|---|---|
| **STRONG ENTRY** | 15d WIN + 63d WIN + Phase 3 EXPANSION | FULL |
| **CAUTION** | 15d WIN + 63d WIN + Phase 3 CONTRACTION | REDUCED |
| **SHORT-TERM ONLY** | 15d WIN + 63d NO SIGNAL (any Phase 3) | Informational-only (S30) — do not trade |
| **LEAPS ONLY** | 15d NO SIGNAL + 63d WIN | LEAPS (6–9mo expiries) |
| **STAY OUT** | 15d NO SIGNAL + 63d NO SIGNAL | N/A |

- Phase 2 (15d) drives ENTER vs STAY OUT for short-DTE setups
- Phase 2B (63d) confirms or rejects medium-term thesis (LEAPS-aligned)
- Phase 3 (IV expansion) modulates sizing — not a go/no-go gate
- **SHORT-TERM ONLY demoted to informational (S30)**: backtest avg ≈ STAY OUT on QQQ (0.7% vs
  0.7% 15d) and a documented hard NO on AMD (−2.5%); a +0.7% 15d underlying edge is likely
  negative on an actual option after spread + theta. Treat as STAY OUT in practice, pending
  forward-ledger evidence.
- **IV/HV gate (`entry.py` only)**: ATM IV (~30 DTE) read from `atm_iv_30d` column in indicators
  CSV (harvested by `indicators.py` from Massive) and compared to HV-20. If `signal == STRONG ENTRY`
  and `IV/HV >= 1.40`, downgrade to `CAUTION`. The ratio + label (cheap/fair/rich/very rich) prints
  regardless of signal. If `atm_iv_30d` is NaN (Massive harvest failed or never ran), prints a
  warning to re-run `indicators.py` and skips the gate.
- **Term structure** (`entry.py` display only — not yet a feature): printed with 5-band label.
  `< 0.95` contango → `0.95–0.98` slight contango → `0.98–1.02` noise → `1.02–1.05` slight
  backwardation → `> 1.05` backwardation. Treat `> 1.05` as a stress signal (trust contraction
  signals less; weight options-market-implied tail risk higher).
- **6-month forward return table** (`backtest.py`, S15): printed after the 15d table. For QQQ,
  `STRONG ENTRY` is the only signal with edge on both 15d (+1.9%) and 6mo (+10.6%) horizons.
  Use the 15d table to decide whether to enter; use the 6mo table to decide DTE.
  `LEAPS ONLY` does NOT outperform `ALL DAYS` at 6mo for QQQ — informational only at index level.

## Key Design Decisions

- **`determine_signal(dir_win, dir_win_63, expansion)` in `entry.py`** — module-level helper extracted from `print_combined_signal()` (S19). Maps the three binary phase signals to the five-tier label. Used by `print_combined_signal()` and directly importable for unit testing (`tests/test_smoke.py:test_signal_logic`).
- **Logistic regression only** — intentional for interpretability; black-box models avoided
- **Time-based train/test split** (not random) — avoids lookahead bias in time series
- **Price-level features normalized** to ratios/pct_change — ticker-agnostic and scale-invariant
- **`Days_to_earnings` DROPPED FROM ALL MODEL FEATURES (S31)** — excluded in every `train()`/`train_model()` (backtest/entry/direction/volatility/exit); `add_earnings_proximity` still computes it (capped `min(d,90)`) purely for `entry.py`'s "Days to Earnings: Nd" display. History: yfinance returns only ~20–25 recent earnings dates, so older rows got days-until-the-earliest-known-date — a near-perfect calendar-time ramp (NVDA corr −0.999 over 79% of rows) that manufactured spurious edge on secular-uptrend stocks (inflated NVDA/AMD 6mo to ~+33%). The S30 cap killed the ramp but left a residual 90-vs-real era split that still drove suspect live readings. Cross-ticker drop test → safe to remove entirely: no-op on QQQ (ETF), neutral on JPM (72% win preserved), helps AMD, only NVDA (unsuitable) depended on it. So the feature is gone from the models, kept as display-only context.
- **IV proxied from HV-20** — approximates IV rank/percentile without a paid options feed
- **Vol-adjusted thresholds** via `compute_vol_thresholds()` — auto-calibrates per ticker:
  - `WIN_THRESHOLD = P2_VOL_MULTIPLE × median_HV × sqrt(15/252)` (Phase 2)
  - `WIN_THRESHOLD_63 = P2_VOL_MULTIPLE × median_HV × sqrt(63/252)` (Phase 2B)
  - `EXPANSION_THRESHOLD = P3_VOL_MULTIPLE × median_HV` (Phase 3)
  - `P2_VOL_MULTIPLE = 0.41` (0.41-sigma difficulty bar; tuning range 0.25–1.0)
  - `P3_VOL_MULTIPLE = 0.20` (heuristic; validate via backtest for new tickers)
- **Benchmarks via `modules/benchmarks.py`** — 3-tier lookup: `TICKER_BENCHMARK` dict (no network) → yfinance sector/industry → SPX fallback
  - AMD/NVDA → SOX + XLK; SOFI → KBE + XLF; CRSP → IBB + XLV; RIVN → XLY; QQQ → SPX
  - Feature names: `{bench_name}_RS_5d`, `{bench_name}_RS_20d`, `{bench_name}_vs_ma200`
- **Macro features** (`MACRO_FEATURES` in benchmarks.py) — opt-in for rate-sensitive tickers
  - SOFI/JPM/BAC/GS/MS/WFC/C → ^TNX (UST10Y) + ^IRX (UST3M); derives yield_curve
- **Catalyst proximity** (`add_catalyst_proximity` in benchmarks.py) — reads `data/catalysts.csv`
  - `for_direction=True` flag neutralizes catalyst feature for `EVENT_DRIVEN_TICKERS = {"CRSP"}`
  - Reason: catalyst proximity creates spurious "near event → bullish" association in
    direction models for binary-event biotechs (FDA decisions, trial readouts unpredictable)
  - Phase 3 (`volatility.py`) uses default `for_direction=False` — IV expansion near events is real signal
- **`FORWARD_DAYS = 15`** kept intentionally — entry timing signal, not holding period predictor
  - Phase 2B (63-day) added as LEAPS-aligned thesis validation layer
- **IV harvest in `indicators.py`** (S10) — daily chain summary written to today's row of
  indicators CSV. Two-call pattern in `modules/massive.py`: front tenor (target_dte ± 7d, wide
  strikes) for ATM IV + 25Δ skew + P/C OI; back tenor (55–90 DTE, narrow ATM strikes) for term
  structure. Avoids hitting the 1250-contract pagination cap.
- **CSV merge preserves IV history** — `harvest_iv_snapshot()` reads existing CSV and merges
  prior IV via `combine_first` before writing today's. Without this, every `indicators.py` re-run
  would wipe accumulated IV data because the CSV is regenerated from scratch.
- **`IV_COLS` exclusion required in all ML scripts** — the 7 IV columns are NaN for pre-backfill
  rows. Every `train()` / `train_model()` must include `*IV_COLS` in its exclude set (or
  `*IV_META_COLS` if `--iv-features` is on), or `dropna()` removes the entire training set.
  Applied in entry/direction/volatility/backtest/calibrate_multipliers.
- **Today-row addition in `indicators.py`** (S16, extended S30) — yfinance is fetched with
  `END_DATE = today` and `end` is exclusive, so today's bar is structurally never requested.
  Post-S30: `augment_recent_prices_from_tradier()` (runs before `add_indicators`, only when
  END_DATE is the default today) stamps today's OHLCV from the Tradier quote **after 4 PM ET**
  (quote `close` is null until the bell — completed-session latch; `trade_date` must be today)
  and backfills trailing-week sessions yfinance skipped from Tradier daily history. Pre-close
  runs are unchanged: `harvest_iv_snapshot` appends the NaN-OHLCV today-row so the IV stamp
  lands on today's date. Tradier prices are unadjusted vs yfinance's adjusted series — stamped
  rows are replaced by the next run's fresh yfinance fetch (only IV columns merge-persist).
  Side effect unchanged: each run can grow the df by 1 row, shifting the 80/20 split forward
  by 1 sample; daily probabilities can drift run-to-run (observed +16pp shift in QQQ Phase 3
  expansion prob during S16 verification). Expected behavior, not a bug.
- **Shared feature engineering** (`modules/features.py`, S14/S16) — `compute_hv_features`,
  `compute_vix_features`, `add_earnings_proximity`, `normalize_features`, `compute_vol_thresholds`,
  `impute_iv_features`, plus all phase constants. Used by direction/volatility/entry/backtest.
  `direction.py` and `volatility.py` still wrap `compute_vix_features` and the benchmarks loop
  with thin local helpers (`add_vix`, `add_benchmarks`) — refactor incomplete.
- **Price data source policy (S30)** — one source per job; do NOT consolidate to a single vendor:
  - **yfinance** = full dividend-adjusted daily history (AMD back to 1980) + index/yield symbols
    (^SOX, ^TNX, ^IRX) + earnings dates. **Tradier** = post-close same-day OHLCV stamp + trailing
    gap backfill (`augment_recent_prices_from_tradier`) + live quotes/chains (sizing/pc_oi).
    **Massive** = options-chain harvest + IV backfill only (2-yr plan cap — never a price-history
    candidate).
  - Consolidating the harvest to Tradier was evaluated and REJECTED (probed live 2026-06-12):
    (1) Tradier daily history is capped/short for AMD — 1994-08-30 onward / exactly 8,000 bars vs
    the CSV's 1980 start (silently loses ~30% of the history behind the 91-window backtest);
    (2) Tradier closes are split-adjusted but NOT dividend-adjusted (QQQ Sep-2025 runs ≈ +$2.20
    above yfinance adjusted) — switching shifts the price basis of every target/threshold and
    invalidates comparability with all recorded baselines; (3) Tradier has no ^SOX / ^TNX / ^IRX
    and no earnings dates, so yfinance stays load-bearing regardless — "one dependency" is not
    reachable.
  - Disaster recovery: if yfinance breaks permanently, Tradier CAN serve QQQ/NVDA-depth history
    plus the VIX complex (VIX/VIX9D/VIX3M) and SPX with daily history — migration would require
    threshold re-validation (dividend-unadjusted basis); AMD pre-1994, SOX, and TNX/IRX have no
    Tradier fallback.

## Model Details

All models: `LogisticRegression(C=0.1, class_weight="balanced")`, 80/20 time-based split, `RANDOM_STATE=42`.

| | Phase 2 (15d) | Phase 2B (63d) | Phase 3 (IV) | Phase 4 (Exit) |
|---|---|---|---|---|
| Target | Vol-adjusted gain in 15d | Vol-adjusted gain in 63d | HV expansion in 10d | Max drawdown over N days ≥ vol-adjusted threshold |
| Threshold | 0.55 | 0.55 | 0.60 | 0.55 |
| Window | 15d (fixed) | 63d (fixed) | 10d (fixed) | 5d / 15d / 63d (trained jointly; 15d production default) |

Volatility is more predictable than direction — Phase 3 has roughly 3× the edge of either direction model
(QQQ: Phase 2 +1.5pt edge, Phase 2B +6.3pt, Phase 3 +27pt at production thresholds).
Phase 4 exit signal validates with comparable edge to Phase 3 (QQQ 15d +17.7pp, NVDA 5d +19.7pp);
63d window collapses on individual stocks (NVDA -20.7pp at τ=0.55 — high-confidence tail inverts) and
is excluded from production. Drawdown threshold = `P4_VOL_MULTIPLE × median_HV × sqrt(N/252)` with
`P4_VOL_MULTIPLE = 1.0` (one-sigma drawdown bar).

Threshold sweep auto-marks optimal using `max(precision - base_rate) × log(signals)` — rewards edge
above base rate and signal volume simultaneously.

CLI flags (default OFF; available on direction/entry/volatility/exit/backtest):
- `--calibrate` — isotonic Phase 2 (Decision 1, S11). Reverted to default OFF after NVDA regression
  (STRONG ENTRY 4.4% → -0.4%). Calibrated mode uses P2_THRESHOLD=0.50 instead of 0.55.
- `--iv-features` — Phase 3 uses real Massive IV (`atm_iv_30d`, `iv_skew_25d`, `term_structure`)
  with HV-based imputation for pre-backfill rows. Default uses HV proxy (full price history).
  **NO clean backtest edge (S24); stays default OFF.** After fixing the Phase 2/2B indicator leak
  (see Recently Fixed), the STRONG-ENTRY A/B is within noise on both real-IV tickers (AMD 6mo
  −2.0pp, NVDA +0.6pp). The S23 "NVDA +2.3pp / first to pass" result was a **leak artifact**.
  Real IV does sharpen Phase 3 *classification* (QQQ +0.8pp precision; AMD +8pp test precision on
  the recent split) but that does not translate into STRONG-ENTRY return edge (Phase 3 only
  modulates STRONG↔CAUTION sizing). Retained as an opt-in research flag.
- `--p4-gate` (entry.py only) — Phase 4 exit gate. One-tier-down downgrade: STRONG ENTRY → CAUTION,
  CAUTION / SHORT-TERM ONLY → STAY OUT, LEAPS ONLY unchanged. **REJECTED by S18 backtest validation**:
  QQQ STRONG ENTRY 1.8% → 1.5% (−0.24pp 15d), 9.4% → 7.6% (−1.8pp 6mo); NVDA gated count 294 < 300
  sample-size floor. 15d gate filters 6mo winners that had 15d wobbles. Retained as opt-in flag for
  future experimentation. backtest.py always reports gated/ungated A/B (no flag) so re-validation
  is automatic if upstream changes alter behavior. **NOTE (S30)**: `backtest.py`'s `P4_FORWARD_DAYS`
  was 5 (not 15) from S18 until 2026-06-12 — all P4-gate A/B numbers before then, including the
  S18 rejection above, were generated with a **5d** gate while entry.py/docs said 15d. Constant
  now aligned to 15d; first true 15d-gate A/B (QQQ, 2026-06-12): REJECT, and worse than the 5d
  gate — STRONG ENTRY 1.77% → 1.52% (−0.25pp 15d; 5d gate was −0.05pp), 6mo 9.6% → 7.7%, same
  winners-filtered-with-losers signature (gated win rate UP 64.0→66.9%, avg DOWN). The S18
  rejection conclusion now stands on directly-measured 15d evidence.
- `--econ-features` — adds 10 macro-release proximity columns (`Days_to_FOMC`, `Days_to_CPI`,
  `Days_to_NFP`, `Days_to_PCE`, `Days_to_PPI`, `Days_to_GDP`, `Days_to_Retail`, `Days_to_JOLTS`,
  `Days_to_Claims`, `Days_to_macro`) from `data/econ_calendar.csv`. Requires FRED API key
  (`$env:FRED_API_KEY`) and a prior `python -m modules.econ_calendar --refresh`. Default OFF.
  **REJECTED by S20 backtest validation**: QQQ STRONG ENTRY 1.8% → 1.7% (marginal); NVDA STRONG
  ENTRY 15d 2.9% → -0.1% (-3.0pp), 6mo 33.4% → 13.6% (-19.8pp), hierarchy inverted. Same
  failure mode as S11 isotonic calibration — ~33% feature inflation compresses individual-stock
  high-confidence tail. Retained as opt-in flag for future experiments (Tier 1-only subset,
  surprise-data features, etc.).
- `--side {call,put}` (backtest.py only; default `call` = production) — bearish-entry PoC (S28).
  `put` flips the Phase 2/2B direction target to a downside move (`<= -WIN_THRESHOLD`); Phase 3
  unchanged; `summarize` reports gross put P&L (`= -fwd_return`) and a downside win. Writes a
  separate `*_backtest_results_put.csv` and skips the call-oriented P4/VIX gate A/Bs + chart, so
  the call baseline is untouched. **NO-GO (S28 cross-ticker)**: put STRONG ENTRY passes only on
  QQQ (15d +2.1% / 6mo +6.2%, best + hierarchy holds) but FAILS both individual stocks — NVDA
  (15d -2.4% / 6mo -26.8%) and AMD (15d -1.5% / 6mo -35.1%, worst signal), hierarchy inverted.
  Confirms the framework's edge IS the long/mean-reversion bias: bearish signals on secular-
  uptrend names catch dips that mean-revert, so the puts get crushed at 6mo. Retained opt-in for
  research; directional puts NOT productionized. Hedging puts → use Phase 4 (`exit.py`) instead.

## Sizing Config (`sizing.py`)

- `TRADIER_TOKEN` — brokerage token required (not sandbox; sandbox uses simulated data)
- `MIN_DTE = 180`, `MAX_DTE = 365` — targets 6–12 month expiries
- `DEFAULT_STRIKE_RANGE = 10` strikes above/below ATM
- IV source: `smv_vol` (smoothed model vol — matches Tradier app display)
- ATM anchor: nearest real ATM strike, not exact stock price
- All strikes shown including "over budget" ones (not silently filtered)
- IV/HV ratio shown via `^` (+20%, expensive) and `v` (-20%, cheap) markers — useful for assessing whether option premium is rich relative to realized vol

## Massive Config (`modules/massive.py`)

- `MASSIVE_API_KEY` reads `$env:MASSIVE_API_KEY`; calls fail with `RuntimeError` if unset.
  Set in `$PROFILE` for persistence across PowerShell sessions.
- Plan tier: Options Starter (15-min delayed snapshots, 2yr historical, unlimited rate limit)
- `MASSIVE_URL = https://api.massive.com` — surface is functionally identical to Polygon.io
- `get_chain_summary(ticker, underlying_price, target_dte=30)` returns:
  `atm_iv_30d`, `atm_strike`, `atm_expiry`, `atm_dte`, `iv_skew_25d`, `term_structure`, `put_call_oi_ratio`
- Two-call daily harvest (avoids pagination cap):
  - Front: `dte=target±7`, strikes `spot×0.85` to `×1.15` → ATM IV + 25Δ skew + P/C OI
  - Back: `dte=55-90`, strikes `spot×0.97` to `×1.03` → back-month ATM for term structure
- Filters out `iv=20` placeholder (Massive returns this for deep ITM/OTM with empty greeks)
- Snapshot endpoint is current-only — `expired=true` is ignored on `/v3/snapshot/options/`
  (only honored on `/v3/reference/options/contracts`). Historical IV uses BS-inversion in
  `get_historical_iv_snapshot()` + `backfill_iv.py` + `modules/bs_invert.py` (contracts reference +
  per-contract aggregates + Newton-Raphson invert). Fill rate is capped at ~2yr by the plan limit.

### IV column structure
- `IV_FEATURE_COLS = [atm_iv_30d, iv_skew_25d, term_structure]` — usable as ML features after backfill
- `IV_META_COLS = [atm_strike, atm_expiry, atm_dte, put_call_oi_ratio]` — always excluded from features
- `IV_COLS = IV_FEATURE_COLS + IV_META_COLS` — full list for CSV column management

### Backfill quality filters (post-S13/S14 hardening)
- `MIN_OPTION_VOLUME = 5` — rejects single-trade artifacts in `_fetch_agg_price`
- `MIN_OPTION_TRADES = 5` — rejects block-trade artifacts (n < 5)
- `0.05 ≤ iv ≤ 2.0` bounds in `get_historical_iv_snapshot` — rejects implausible inversions
- Monthly-expiry preference (3rd Friday) over weeklies — fixes weekly-heavy tickers (QQQ)
- Near-ATM delta filter `0.30 ≤ delta ≤ 0.70` for ATM IV — rejects deep-ITM time-premium artifacts
- Two-call corroboration required (≥ 2 ATM calls must invert before trusting)
- `FAST_FAIL_MISSES = 5` — early termination when consecutive aggregates calls return empty

## Econ Calendar Config (`modules/econ_calendar.py`)

- `FRED_API_KEY` reads `$env:FRED_API_KEY`; refresh calls fail with `RuntimeError` if unset.
  Free signup at https://fredaccount.stlouisfed.org/apikeys. Add to `$PROFILE` for persistence.
- `FRED_URL = https://api.stlouisfed.org/fred` — endpoint `release/dates` with
  `include_release_dates_with_no_data=true` returns forward release dates.
- Cache: `data/econ_calendar.csv` (~50–500 rows: 5y history + ~12mo forward × 9 series). Moved from `modules/` in S27.
  Schema: `series,date,release_id,release_name,tier`.
- Tier 1 series (always tracked): FOMC, CPI, NFP, PCE.
- Tier 2 series: PPI, GDP, Retail, JOLTS, Claims.
- Refresh cadence: weekly. Run `python -m modules.econ_calendar --refresh`.
- **Cache moved to `data/` (S27)** — all `data_dir` defaults are now `"data"` (was `"modules"`);
  physical CSV at `data/econ_calendar.csv`. `add_catalyst_proximity` still uses `modules/` for
  `catalysts.csv` — only the econ calls flipped `MODULE_DIR`→`DATA_DIR`.
- `refresh_if_stale(max_age_days=7, data_dir="data")` (S27) — TTL refresh for on-demand tools:
  refreshes only when the cache is older than the threshold, falls back to the existing cache on
  missing key / network error, never raises. Used by `econ_calendar_view.py`. (Chosen over
  refresh-on-every-call, which would force a key + network + redundant fetches on a read-only tool.)
- `refresh()` Tier-1 partial-overwrite guard (S27) — won't replace a complete cache with one
  missing a Tier-1 series (transient FRED-outage protection).
- `events_in_range(start, end)` / `coverage_end_per_series()` (S27) — accessors for the calendar GUI.
- `add_macro_event_proximity(df, data_dir="data", for_direction=False)` adds 10 columns:
  per-series `Days_to_{name}` (sentinel-90 fallback) + aggregate `Days_to_macro` (min across all).
  Values capped at `SENTINEL_DAYS=90`. Integer. Gated by `--econ-features` CLI flag in every
  consumer; default OFF until validated.
- Failure modes (all graceful, mirror catalyst pattern):
  - `FRED_API_KEY` unset + `--refresh` → clean `RuntimeError`
  - CSV missing → fill all `Days_to_*` with 90, print one-line warning
  - CSV present but `< 30` forward days for a series → staleness warning per series
- Use `python -m modules.econ_calendar --list-releases` to enumerate FRED release IDs (run once
  to verify TIER1_SERIES / TIER2_SERIES constants match current FRED IDs).

## Geopolitical / Exogenous Shock Limitation

The framework is **reactive, not predictive** of shocks. All inputs are derived from price/volume/HV history; the model cannot detect war escalations, central bank surprises, or other exogenous events before they affect prices.

Phase 3 classification report directly evidences this:
- Contraction precision: ~79% (calm regimes mean-revert reliably)
- Expansion precision: ~64% (shocks are structurally unlearnable from price history)

During known geopolitical crises (e.g. Iran war, May 2026):
- The IV/HV ratio gap is itself information about tail risk — the options market sees what the model doesn't
- Trust contraction signals less when binary catalysts loom
- Weight options-market-implied premium higher than Phase 3's HV-based output

See `memory/context.md` "Geopolitical Risk Limitation" for proposed mitigations (VIX term structure, put/call ratio, etc.).

## Known Issues (not yet fixed)

- `modules/tradier.py`: `TRADIER_TOKEN` reads `$env:TRADIER_TOKEN` if set, else falls back to hardcoded
  constant. Set the env var to keep the token out of git.
- `data/iv_log.csv` (deprecated as of S10): file preserved on disk as historical record but no new rows
  are written. IV history now lives in `data/{ticker}_indicators.csv`.
- **SOFI / LYFT / QQQ IV backfills lost (S23 discovery)** — context.md pre-S23 claimed
  498 / 439 / 318 rows respectively; disk shows ~0-1. Probable cause was the
  `indicators.py` narrowed-START_DATE bug (now fixed in S23). Re-backfill required.
  AMD (462 rows, RESTORED S24) and NVDA (452 rows, S23) are intact.
- AAPL indicators CSV is missing entirely — needs `indicators.py` run then `backfill_iv.py`.

## Recently Fixed (S31)

- **`Days_to_earnings` CALENDAR-TIME LEAK** (latent since the feature was added; surfaced by the
  S30 cap). `add_earnings_proximity` computes days-to-next-earnings, but yfinance only returns
  ~20–25 recent earnings dates — so for any row older than that horizon, "next earnings" resolves
  to the *earliest known date*, making the value a near-perfect calendar-time ramp (NVDA 79% of
  rows, corr −0.999; AMD 87%, corr −1.000; values up to 14,743 days). In walk-forward this ramp
  varies *within every window*, letting the model fit the secular uptrend as "edge." It inflated
  NVDA STRONG ENTRY 6mo to +33.3% (clean: +15.2%, anti-predictive) and AMD to +33.9% (clean:
  +18.1%, below STAY OUT). QQQ was immune (ETF → constant 45), which is why the S30 QQQ-only
  verification missed it. **Fix:** `min(d,90)` cap (`modules/features.py`). Confirmed sole cause by
  controlled revert (revert → documented numbers return exactly; restore → collapse).
- **`add_catalyst_proximity` same latent bug** — capped `min(d,90)` defensively. Dormant today
  (catalysts.csv is CRSP-only; CRSP direction-neutralized) so no production impact, but it would
  have leaked identically if catalyst dates were ever added for a long-history stock.
- **VIX term-structure era marker** — `VIX_VIX3M_ratio`/`VIX9D_VIX_ratio` `fillna(1.0)` for
  pre-2007/2011 history was a weaker era marker (corr −0.5..−0.6). Added `vix3m_available` /
  `vix9d_available` missingness indicators (`compute_vix_features`, mirrors `iv_available`) so the
  model separates a real 1.0 from a filled 1.0. Negligible backtest impact (the flag is constant
  within nearly every walk-forward window) — hygiene, not the smoking gun.
- **Feature-set leak audit** (corr-vs-calendar-order scan): only the one major leak (earnings);
  everything else clean or excluded. Method retained as the standard new-feature check.
- **`Days_to_earnings` dropped from all model features** — after the cap, a cross-ticker drop test
  showed removal is safe (no-op QQQ, neutral JPM, helps AMD, only unsuitable NVDA depended on it).
  Excluded in all 5 train fns; kept as `entry.py` display only. New earnings-free clean validator
  trio: QQQ / Ford / JPM (see Ticker Suitability).
- **JPM / rate-ticker `inf` crash** — `yield_curve_chg_5d` used `pct_change(5)` on the 10Y–3M
  spread, which crossed exactly 0.0 at the 2007-08-10 curve inversion → `+inf` → `StandardScaler`
  `ValueError`. Fixed: `diff(5)` (absolute spread change, well-defined through zero) + a defensive
  `inf→NaN` sweep on macro columns, in both `backtest.py` (inline) and `benchmarks.py:add_macro_features`.
  Unblocks all 6 rate tickers (JPM/BAC/GS/MS/WFC/C) over 2007; SOFI was immune (post-2021 IPO).
- **`backtest.py` chart-prompt EOF guard** — `plot_results` `input()` wrapped in `try/except
  EOFError` so piped runs don't crash before `results.to_csv`.

## Recently Fixed (S24)

- **Phase 2/2B IV-indicator leak** (latent since S13). `impute_iv_features()` adds binary
  `iv_available`/`term_available` columns that were not in `IV_COLS`, so `train_model`'s Phase 2/2B
  exclude set (`IV_META_COLS if use_iv_features else IV_COLS`) did not drop them — they leaked into
  the Phase 2 and Phase 2B feature sets whenever `--iv-features` was on. Net effect: `--iv-features`
  silently perturbed all three phases, not just Phase 3, **confounding every prior `--iv-features`
  A/B** (S13 QQQ, S23 NVDA). Detected because LEAPS ONLY / STAY OUT counts changed between the HV and
  `--iv-features` arms (AMD LEAPS 976→884) even though Phase 3 only modulates STRONG↔CAUTION. Fix: new
  `IV_INDICATOR_COLS = ["iv_available", "term_available"]` constant in `modules/massive.py`; the
  exclude is now `IV_META_COLS if use_iv_features else IV_COLS + IV_INDICATOR_COLS` (`backtest.py`,
  `entry.py`). Phase 3 keeps the indicators; Phase 2/2B/4 drop them. HV-proxy mode is unaffected (a
  no-op — impute never runs there, so the columns never exist). 13/13 smoke tests pass; post-fix
  LEAPS/SHORT/STAY counts are identical between HV and `--iv-features` (QQQ + NVDA exact; AMD ±2
  solver noise). **Consequence:** the S23 "NVDA `--iv-features` +2.3pp / first feature to pass"
  result was a leak artifact; the clean cross-ticker A/B shows no `--iv-features` edge (see CLI flags).

## Recently Fixed (S23)

- **`backtest.py` `run_backtest()` multiplier sweep bug** (latent since S13). Per-window threshold
  recalibration always used the imported `P2_VOL_MULTIPLE`/`P2B_VOL_MULTIPLE`/`P3_VOL_MULTIPLE`
  constants regardless of `MULTIPLIER_SWEEP` iteration values. Any prior sweep silently returned
  identical results. Fix: thread `p2_mult`/`p2b_mult`/`p3_mult` kwargs through `run_backtest` with
  production fallbacks. Sweep call site passes per-combo values. Single-config runs (`MULTIPLIER_SWEEP = []`)
  were unaffected because they use the imported constants directly.
- **`indicators.py` `harvest_iv_snapshot()` destructive merge** (latent since S10). The IV merge only
  operated on `df.index.intersection(prior.index)`, dropping rows in prior outside the current df
  range. Then `df.to_csv()` overwrote the whole file. Triggered when user entered a narrowed
  `START_DATE` — wiped pre-START_DATE IV history. Fix: preserve outside-range prior rows via
  `pd.concat` before merge, with a one-line "Preserving N prior rows outside current range"
  notice. Default behavior (`START_DATE="1792-05-17"`) unaffected.

## Important Warnings

- **NEVER name a script `signal.py`** — it shadows Python's built-in `signal` module and causes `AttributeError: partially initialized module 'subprocess'`. The original `entry_signal.py` was renamed to `entry.py` to resolve this.
- **Re-running `indicators.py` is safe by default**, but **never enter a START_DATE more recent than the existing CSV's earliest date** unless you intend to lose history. The S23 fix preserves prior rows outside the range and prints "Preserving N prior rows outside current range" — if you see that line, your existing history was saved by the guard. Accepting the START_DATE default (`1792-05-17`) always fetches full history and is unconditionally safe.
- **`backtest.py` is self-contained** relative to `direction.py` / `volatility.py` (only imports from `modules/features.py`). If feature engineering changes outside `modules/features.py` (e.g. add_benchmarks loop bodies), `backtest.py` must be manually updated to match.
- **Today-row in `indicators.py`** (S16/S30) — re-running `indicators.py` mid-day appends a today-row with NaN OHLCV so the IV harvest stamps onto today's date; **after 4 PM ET** the today-row instead gets real OHLCV from the Tradier quote, so HV/indicators/signal use today's actual close. Either way the df grows by 1, shifting train/test splits in downstream scripts. Today's IV is from a fresh Massive snapshot.
- **`data/` directory must exist** before running any script — create it manually if missing.
- **`modules/` directory** holds `features.py`, `benchmarks.py`, `massive.py`, `bs_invert.py`, `tradier.py`, and `catalysts.csv`. Catalyst CSV path is `data_dir`-relative; the `csv_path = os.path.join(data_dir, "catalysts.csv")` fix in Session 7 is required for catalyst loading to work.
- **`trade/` subdirectory** is the Python virtual environment — do not delete. Use `.\trade\Scripts\python.exe -X utf8` explicitly; Claude Code's shell doesn't inherit venv activation.
- **`memory/` subdirectory** is Claude's auto-memory system.
- **`$env:MASSIVE_API_KEY` does not persist across PowerShell sessions** — once env-var pattern is restored, add to `$PROFILE` for permanence.
- **yfinance `.info` returns 401 errors** — `TICKER_BENCHMARK` dict in `benchmarks.py` bypasses this entirely for known tickers.
- **ETFs have no earnings** — yfinance "may be delisted" warning is harmless; `Days_to_earnings` defaults to 45 (neutral).
- **`data/catalysts.csv`** must have no commas in description field (use dashes instead) — pandas reads ragged CSV otherwise.
- **Unicode arrow (`->`)**: not a problem in VS Code/Windows Terminal; only affects cmd.exe with cp1252 encoding.

## Tech Stack

`yfinance`, `pandas`, `numpy`, `ta`, `matplotlib`, `scikit-learn` (LogisticRegression, StandardScaler, precision_score, CalibratedClassifierCV, brier_score_loss), `lxml` (earnings dates), `requests` (Tradier via `modules/tradier.py`, Massive via `modules/massive.py`, FRED via `modules/econ_calendar.py` + `modules/geocontext.py`), `xlrd>=2.0.1` (read the GPR `.xls` in `modules/geocontext.py`), `pytest` (smoke tests — dev only)

## Ticker Suitability Notes

> **⚠️ S31 LEAK CORRECTION (2026-06-13).** The `Days_to_earnings` calendar-time leak (yfinance
> returns only ~20–25 recent earnings dates, so pre-~2020 rows became a near-perfect time ramp —
> NVDA 79% of rows / corr −0.999, AMD 87% / corr −1.000) inflated NVDA/AMD 6mo edge ~entirely.
> Fixed (cap `min(d,90)`). **Clean leak-free baselines below supersede all prior stock numbers.**
> The "individual stocks > index" thesis was the leak; on clean features QQQ is the only ticker
> with intact hierarchy + real edge. NVDA/AMD STRONG-ENTRY figures elsewhere in this file predate
> the fix and are leak-inflated.

- **QQQ**: framework reference baseline AND now the only trustworthy edge; 53 windows (2001–2026); clean hierarchy, leak-free. Clean (S31) STRONG ENTRY 609 / 1.6% / 64.2% at 15d (+0.7pp over all-days), 8.9% / 75.2% at 6mo (+1.8pp). Modest but real and hierarchy-intact.
- **AMD**: **DOWNGRADED to marginal (S31)**; 91 windows. Clean STRONG ENTRY 562 / 2.0% / 55.7% at 15d (only +0.2pp over all-days; CAUTION edges it), 6mo 18.1% — *below* STAY OUT (19.4%). The documented 383 / 3.4% / 33.9% was the calendar-time leak. Not the signal to trade on clean features.
- **NVDA**: **DOWNGRADED to UNSUITABLE (S31)**; 53 windows. Clean STRONG ENTRY 417 / −0.8% at 15d (the WORST signal — anti-predictive), 6mo 15.2% — well below STAY OUT (25.7%). The documented 355 / 2.8% / 33.3% was ENTIRELY the leak. ⚠️ All NVDA lore built on the leaked features — the S23/S25 mid-confidence sweet spot, the high-confidence-tail inversion, every "passed the NVDA cross-check" result — is now SUSPECT and needs re-validation on clean features.
- **Ford (F)**: **CLEAN VALIDATOR (S31)** — cyclical auto, no secular trend (STAY OUT 6mo ≈ 0), so edge can't be drift-fitting. Earnings-free STRONG ENTRY 403 / 4.0% / 58% win at 15d, 25.0% / 48% win at 6mo (+19.3pp vs all-days); hierarchy intact. Survived both the leak fix and the earnings drop. High-magnitude / lower-accuracy (lottery-tailed: big winners, 48% 6mo hit rate). Signals start 2000 (benchmark XLY launched 1998-12 — the binding feature-availability gate; 1972–1998 history is training-only).
- **JPM**: **CLEAN VALIDATOR (S31), best accuracy** — financial, cyclical (real 2008 drawdown). Earnings-free STRONG ENTRY 566 / 2.6% / 64% win at 15d, 13.4% / 73% win at 6mo (+6.2pp vs all-days); hierarchy intact; broad/flat decile profile (every bucket 63–90% 6mo win → robust, not tail-fragile). Rate ticker (UST10Y/UST3M macro features); required the S31 yield-curve inf fix to backtest over 2007.
- **SOFI**: marginal — short history (2021 IPO); rate features wired but need more rate-regime variation. Has earnings → already excluded from features post-S31; re-baseline before trusting any prior number.
- **AAPL**: backfill partial (180 IV rows since 2025-07-24); backtest not yet run.
- **LYFT**: backfill complete (439 IV rows); backtest not yet run.
- **CRSP**: unsuitable for direction (binary FDA/trial events dominate); Phase 3 viable for vol plays — consider straddles/strangles around PDUFA dates rather than directional calls. Catalyst feature is automatically neutralized in direction models via `EVENT_DRIVEN_TICKERS = {"CRSP"}`.
- **SPY**: structurally UNSUITABLE — 0.1pp edge over base, hierarchy broken. Framework's price-action lens vs SPY's macro-driven moves don't match.

Cross-ticker findings:
- **⚠️ Most findings below predate the S31 leak fix and used leak-inflated NVDA/AMD baselines — re-validate before trusting.**
- ~~**STRONG ENTRY win rate ~65% reproduces across QQQ/NVDA**~~ — leak artifact (S31). Clean NVDA STRONG ENTRY is anti-predictive; the ~65% was the calendar-time ramp.
- **CAUTION avg loss 3–4pt worse than STRONG ENTRY** — measured on leaked features; re-check.
- **Phase 2B (63d) edge stronger than Phase 2 (15d)** on AMD/CRSP — measured on leaked features; re-check.
- ~~**Edge-in-tail / mid-confidence sweet spot (S23/S25)**~~ — the NVDA decile findings were computed on the leaked feature set (a calendar-time index dominated Phase 2); SUSPECT until re-run on clean features.
- **Cross-ticker validation required for any framework change**: QQQ alone is INSUFFICIENT — BUT note (S31) that NVDA's historical role as the co-validation ticker rested on a leaked baseline. Until NVDA/AMD are re-validated clean, treat QQQ as the only trustworthy reference and seek a genuinely independent second ticker (different sector, non-secular-trend).
- **NEW S31 lesson**: any feature that ramps with calendar time (an unbounded "days since/until X" where X is sparse, a cumulative sum, a raw level) will manufacture edge on a secular-uptrend name in walk-forward. Audit new features with a corr-vs-calendar-order scan; cap or difference them. See `confidence_band_ab.py` sibling tooling and the S31 context.md log.