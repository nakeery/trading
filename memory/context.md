Project Context — The LENS (terminal + web)
===========================================

(Consolidated S48 — prior session-by-session detail lives in git history; CLAUDE.md is the full
operational reference. This file centers on the two primary tools and what they use.)

CURRENT FOCUS: lens.py + lens_web.py
------------------------------------
The project's primary tools are **lens.py** (terminal) and **lens_web.py** (the same engine in a
browser). Both are a wide-angle CONTEXT layer around the user's OWN chart-based trading: they
characterize CURRENT STATE (trend, momentum, volume, structure, options/vol, positioning, macro)
so a narrow read doesn't miss the bigger picture. **No prediction, no claimed edge** — the user
brings the entry (levels, structure); the lens catches blind spots. The user primarily buys
LONG CALLS at 6–12mo tenors (sizing.py MIN_DTE=180) — hence the S46/S47 additions.

Run:
- CLI: `python -X utf8 lens.py --ticker QQQ` (+ flags: --vol --call --pc-oi --squeeze --insider
  --geo --live --thesis/--level --candle box|braille|sixel|none --no-refresh/--refresh
  --as-of YYYY-MM-DD).
- Web: `.\trade\Scripts\python.exe -m streamlit run lens_web.py` → localhost:8501.
- Both share `lens.render_ticker(ticker, args, use_color, interactive, backdrop_base)` +
  `build_backdrop(data_dir)` (S48 extraction, byte-identical to the old CLI). `interactive`
  gates TTY cache-refresh prompts (web passes False → session caches reused; "live" forces).
- **S49 compute/format split**: `render_ticker` = `gather_report(...)` (one picklable payload
  dict — all section data, NO DataFrames; the risk scorecard + macro events lifted out of
  print_report via `risk=`/`macro_events=` kwargs with compute-if-absent defaults) +
  `render_payload(p, ...)` (prints the CLI report from the payload). CLI byte-identical
  (verified by diff + tests 34/35). The web renders the payload NATIVELY.
- **Percentile display (S49 user convention)**: ordinal + Unicode superscript — "97ᵗʰ
  percentile" — via `sentiment.ordinal_percentile(pct, word=)`; applied in lens.py print
  sites, volsetup/shortint factor strings, and all web renderers. Any new display string
  must use the helper.
- Auto-refresh (S36): a missing/stale indicators CSV triggers `indicators.py --ticker SYM
  --no-chart` (builds from scratch when absent) — so both tools harvest IV daily as a side
  effect of use. Needs MASSIVE_API_KEY in the launching shell or IV columns write NaN.

What the lens prints (all CONTEXT): header+candles (two-axis hollow convention: COLOR = vs prior
close, FILL = vs open) · MARKET BACKDROP (SPY trend, equal-weight breadth RSP−SPY/QQQE−QQQ, CNN
F&G, VIX regime) · MULTI-TIMEFRAME 1M/1W/1D/4h/1h table (partial bars marked *, calendar-aware
S43) · divergences · volume profile (POC/value area/HVN/LVN) · two-sided RALLY vs DRAWDOWN
scorecard (+S57 TREND REGIME line: ESTABLISHED UPTREND/DOWNTREND off 1D+1W alignment + a ≥5-
session MA20-side close streak — stretch factors mid-rally read as PULLBACK timing, not a top
call; tallies untouched per S43) · SETUP CHECK ✓/✗/– checklist (HTF alignment, momentum, volume, RS vs benchmark,
market beta vs SPY, location, vol regime, catalyst timing + ex-div) · OPTIONS & VOL CONTEXT
gauges with trailing percentiles + cached liquidity line · KNOWN CATALYSTS (catalysts.csv) ·
macro ≤10d · optional blocks per flag (below).

lens_web.py specifics (S48, +S49 native visuals):
- **S49**: `generate_payload(ticker, flags_key)` (st.cache_data ttl=120) returns
  `(payload, preamble, ansi)` — gather once, then the ANSI text is printed FROM the payload
  (one compute, two renderings). `lens_web_sections.render_all(payload)` renders native
  sections in print order (styled multi-TF dataframe reusing the CLI heat/tint ramp, gauge
  tables with ordinal percentiles, two-sided risk/setup panels, put/call OI grouped bars,
  quote tables, IV curve); each renderer mirrors print_report's guards, failures degrade to a
  warning. The full ANSI report sits in a collapsed "full text report" expander (preamble
  prepended); payload-None → st.error with ANSI stripped. Debounce/live-fragment/session-state
  wiring unchanged.
- Ticker search box (`key="ticker_input"` = single source of truth) + recent-data pills that are
  ONE-SHOT events (on_change copies pick into the box then deselects — persistent pill selection
  silently overrode typed tickers before). Flag checkboxes auto-run with a 2s DEBOUNCE
  (`DEBOUNCE_S`; rapid clicks batch; Run bypasses + force-fresh via targeted
  `generate_payload.clear(ticker, flags_key)`).
- Report: `render_ticker` stdout captured (candle="none"), ansi2html inside **`st.html`** (NOT
  st.markdown — markdown ends HTML blocks at blank lines and shreds the <pre>). Rendered from
  st.session_state on EVERY rerun (menu-Rerun blanked the page when gated on the click).
- Chart: Plotly candlestick (~120 daily bars + `CHART_WARMUP=200` for indicator warm-up),
  four split style-group traces for the two-axis hollow convention, price line with right-margin
  price tag (NB: add_hline appends " domain" to annotation xref ITSELF — don't set it), display-
  only overlay checkboxes (MA20/50/200, EMA9, BB, volume pane), vol-profile aspects (band/POC/
  HVN/LVN/right-edge histogram via `volume_profile(with_hist=True)`; y-range PINNED to the
  visible window and aspects clipped — 1y levels otherwise squish the candles). With "live": the
  chart lives in `st.fragment(run_every=10s)` — one Tradier quote per tick becomes a provisional
  today-bar (fetch_live_bar/append_live_bar), price line rides it; the report is never
  re-fetched by the timer. Chart caches cleared after each generate (data-vintage match).
- **S50–S54 web-only additions** (all display-only per the S31 rule; zero default-on network):
  chart EVENT MARKERS (earnings / ex-div~ / Tier-1 macro / catalysts.csv ≤`EVENT_HORIZON_D`=30d
  — dashed vlines off payload scalars, weekend dates snapped to next trading day); IV-vs-HV
  history figure (harvested `atm_iv_30d` vs HV-20, event-tenor markers, pre-earnings windows
  shaded via contiguous `atm_iv_event` runs — CSV only); econ-calendar expander (S51/S52:
  two-month Mon–Fri FRED grid, tier-colored chips linking to the headline series' FRED graph,
  headline prints shown once out; network ONLY on its refresh button — `refresh_if_stale(-1)` +
  `fetch_release_results`); seasonality + earnings-reaction expanders (S53 — monthly base rates
  over full history / realized post-print gap/1d/5d + pre-print IV); signal-ledger expander
  (tail of entry.py's forward ledger); 52-week-range tile injected into `sec_header`;
  non-trading-gap rangebreaks + chart/report volume-profile unification (S54 — the chart
  renders the PAYLOAD's profile, never a local recompute).
- **S56 flesh-out (4 phases, all display-only per the durable rules)**:
  · **A — options positioning**: `modules/gex.py` + lens `--gex` (+ web checkbox) — dealer GEX
  by strike off the Tradier chain (greeks already ride every chain fetch; expiries ≤60d via
  `select_gex_expiries`, cached session-stale like pc-oi): net GEX regime (long/short gamma),
  call/put walls, zero-gamma flip (`bs_gamma` added to bs_invert.py — BS repricing across
  hypothetical spots), max pain (nearest monthly), unusual volume-vs-OI strikes; naive
  dealer-convention caveats always printed. Web: `sec_gex` diverging per-strike bars +
  "GEX levels" chart toggle (walls/zero-γ/max-pain hlines, inside-right tags); the IV-history
  figure gained a 25Δ-skew subpane (`load_iv_history` reads `iv_skew_25d`).
  · **D — ledger scorer (the S30 TODO, LANDED)**: `score_ledger.py` — joins each signal-ledger
  row to realized 15d/63d returns off the indicators CSV closes, WIN-tagged vs the row's OWN
  stamped thresholds (recalibration never rewrites history); rows younger than a horizon =
  pending; `score()` reusable, web ledger expander shows scored columns. NB win = the up-move
  bar for EVERY tier — on a STAY OUT row ✗ means staying out was right.
  · **B — new sources**: SKEW+VVIX gauges in `sentiment.gather_context` (yfinance ^SKEW/^VVIX,
  bands 130/150 + 85/110, own try — display-only); `modules/cot.py` CFTC TFF Socrata (no key;
  dataset gpe5-46if; contracts "E-MINI S&P 500"/"NASDAQ MINI"/"VIX FUTURES"; lev-funds
  net/OI + inline weekly percentile ≥26w — sentiment.percentile_of's 63-obs floor is a DAILY
  convention) on the MARKET BACKDROP line + market_context gauges; `modules/buzz.py` ApeWisdom
  reddit mentions (keyless, 4 pages cached ~6h, one feed serves all tickers) riding the
  --squeeze block; **FINRA consolidated short interest needs NO auth** (probed live — POST
  compareFilters to api.finra.org works unauthenticated; GTE settlementDate filter REQUIRED
  or oldest-first + limit truncates before the newest rows) → NYSE names now resolve in
  --squeeze (shortint `parse_finra_si` fallback after the NASDAQ API).
  · **C — web UX**: watchlist landing grid (CSV-only tiles: sparkline, Δ%, MA20/50 arrows,
  latest snapshot's setup-score chip; tile click = pill semantics); day-over-day diff
  (`snap_from_payload`/`diff_snapshots` — compact per-date snapshots under
  data/payload_history/{ticker}/, pruned to 90; "Δ what changed" expander: setup flips,
  risk factors added/cleared, gauge percentile moves ≥10pt); RSI/MACD chart subpanes
  (warm-up-computed, display-only; vp-histogram overlay axis moved x3→x9 to clear subplot
  rows); polish — `?ticker=QQQ&gex=1` deep links (read once pre-widgets, written back after
  each generate), st.status stage log (compute preamble visible), `.streamlit/config.toml`
  dark theme, sidebar quick-nav (anchor slugs stamped by `lens_web_sections._slug`).
- **S57 as-of / date-range backtest mode** (user request: backtest their OWN charting theory):
  `lens.py --as-of YYYY-MM-DD` + web "🕰 date range / as-of backtest" expander +
  `?asof=…&from=…` deep links. Engine: `build_timeframes(as_of=)` truncates the SOURCE frames
  before resampling (forming W/M periods survive — truncating resampled labels would drop
  them; NB inside gather_report the mode var is `asof_ts`, NOT `as_of` — that name is already
  the report's last-bar date and shadowing it broke the payload), `analyze` passes the
  historical session to `last_bar_partial(now_session=)` (a Thursday forming week clears the
  count heuristic — only the calendar check vs the HISTORICAL session marks it), and
  `gather_context(as_of=)` truncates the indicators frame so every gauge/percentile/spark/
  stale-flag reads as of then (VIX refetched for the window = fully historical; SKEW/VVIX
  ≤2y then silently absent). Historically valid: SPY-tide backdrop, macro proximity (5y econ
  cache), catalysts (`today=as_of`), as-of next-earnings (yfinance list, trusted ≤120d),
  RS/beta (auto-degrade beyond the 6mo benchmark fetch), --vol scorecard/EM. Disabled with
  ONE note: live-chain quotes (pc-oi/gex/vol quote/call), squeeze, insider, geo,
  breadth/F&G/COT, ex-div, liquidity, live. Web: banner + chart/IV-history/earnings-reactions
  truncated (`chart_frame(ticker, as_of, start)`); `from` widens the chart window only
  (NOT in flags_key — never regenerates); snapshots/diff/ledger suppressed in as-of mode
  (no history pollution / realized-outcome leakage). Payload key `as_of_mode` (iso|None).
- **S55 cleanup pass**: one cached full-history loader `load_daily_full` (chart tail +
  seasonality previously each ran `_load_daily` = two full yfinance downloads for CSV-less
  tickers); the daily/1y profile fallback + its dead transition caption removed (payload
  profile only — the fallback contradicted the S54 rationale); `_header_tiles` helper dedupes
  the live/non-live tile try/except; pill picks bypass the 2s debounce (explicit intent, no
  cache bust — Run remains the only force-refresh); live polling backs off after
  `LIVE_MISS_LIMIT`=3 consecutive empty Tradier quotes (fragment keeps ticking, a fresh
  generate/Run resets); deprecated `use_container_width` → `width="stretch"` (Streamlit 1.59).
- Deps: streamlit/ansi2html/plotly. `.claude/launch.json`: lens-web (8501, the user's) +
  lens-web-dev (8502, verification — never collide with the user's instance).
- **S60 — React + FastAPI successor (user-requested UI migration; Streamlit UNTOUCHED and
  parallel-runnable until the user retires it)**: `api/` (FastAPI backend — sanitize.py
  numpy/NaN→JSON boundary, reportgen.py asyncio-locked gather_report + LATEST per-ticker
  payload store, charts.py = _candle_fig/_iv_fig/chart_frame/event_markers ported VERBATIM
  (figs built server-side, sent as plotly JSON — the two-axis candle convention never
  re-implemented in JS; overlay toggles = /api/chart query params), cache.py cachetools
  TTLs mirroring st.cache_data + post-generate evict, loaders.py = tiles/econ/ledger/
  seasonality/reactions/snapshot-diff ports — snapshots SHARED with Streamlit under
  data/payload_history/) + `web/` (Vite+React 19+TS: TanStack Query, react-plotly.js on
  plotly.js-finance-dist-min, utils/colors.ts = ramp/heat/RSI/ordinal-percentile TS ports,
  components/sections/* = all 20 renderers w/ per-section error boundaries + anchor nav,
  2s debounce w/ Run-force + pill bypass, deep links + write-back, 10s live poll w/ 3-miss
  backoff, watchlist grid, FRED calendar grid, Δ-diff, scored ledger, as-of suppressions).
  Dev: uvicorn :8000 (`--reload-dir api` ONLY — data/ writes would restart mid-generate) +
  Vite :5173 (proxy /api → 8000, no CORS anywhere); prod: `npm run build` then FastAPI
  serves web/dist single-process on :8000. launch.json: lens-api + lens-react (cmd-wrapped
  npm — spawned procs lack the Node PATH). tests/test_api.py (14 offline; NB the asyncio
  GENERATE_LOCK test must drive concurrency via httpx.ASGITransport in ONE loop — sync
  TestClient threads each spin a loop and cross-loop lock waiters deadlock). JS gotcha
  class: `[]`/`0` truthiness differs from Python when porting payload guards. Node LTS
  winget-installed (was absent). web/FRONTEND.md = React orientation for the user +
  parity checklist.

- **S63 day-trader timeframes** (user request: read entry timing, not just swing structure):
  the multi-TF table splits into TREND (1M/1W/1D/4h/**2h**/1h) and, below a divider inside the
  SAME table, ENTRY TIMING (30m/15m/5m — `timeframes.INTRADAY_TFS`). `2h` is default-on and
  free (90min-offset resample of the cached 1h → session-anchored 09:30/11:30/13:30/15:30
  bins; NB *90* not 30 — pandas anchors bins at midnight+offset) and joins the alignment
  `lower` tuple. Sub-hourly is `--ltf` AND `session_open()`-gated (outside RTH: a "market
  closed" note, no fetch; never in as-of mode) — ONE Tradier 5min timesales fetch (~20d,
  real-time; yfinance 5m/60d fallback, 2min TTL cache) with 15m/30m as pure resamples.
  **Display-only is the whole contract**: filtered out of `multi_timeframe_summary` (the
  `higher`/`lower` tuples already ignored unknown keys, but `rsi_conflict`'s OB/OS lists swept
  every read), out of the risk scorecard's divergence factors (`lens._trend_divs` — applied at
  BOTH call sites; the S49-lifted one in `gather_report` is the live one, the `print_report`
  fallback alone is not enough), out of thesis blind spots, the squeeze line and setup check.
  Heat colouring uses a PER-BLOCK half-scale (one shared scale let 5m RVOL swings wash the
  trend rows to neutral). Web: `ltf` flag + `?ltf=1`, one `DataTable` with a new `divider`
  prop (colSpan separator row) — verified: single header, 9 columns, dashed border.
  Latent test bug fixed in passing: `test_s61_buzz_percentile_uses_full_history` built a
  100-element column against `pd.bdate_range(end=today-1d, periods=100)`, which returns 99 on
  pandas 3.x when `end` lands on a non-business day — it failed every Monday.

- **S64 overnight & futures context** (user request: incorporate overnight/futures markets;
  scoped display-only after the S20/S21 macro-feature rejections): `modules/overnight.py` +
  `sentiment.gap_gauges`. Three default-on surfaces, first two rendered ONLY off-hours
  (`not session_open()` — RTH runs make zero extra calls): (1) `fut ES … · NQ … (o/n vs prior
  settle, HH:MM ET)` MARKET BACKDROP segment — one batched yfinance ES=F/NQ=F daily download;
  the in-progress Globex row's Close IS the live print, and `fast_info.previous_close` matches
  NO settle (probed 2026-07-27) so prior settle comes from the history itself; cache TTL
  **20 min** (deliberate 6h-convention deviation — overnight tape decays in minutes, timestamp
  shown); (2) AH/pre-mkt line under the O/H/L/C — see the S64-FIX entry below, the price comes
  from the timesales tape, NOT the quote; (3) Gap at open +
  Gap vol (5d) VOL gauges off the indicators CSV's `gap_pct`/`gap_ma_5d`/`gap_vol_5d`
  (harvested since S1, previously orphaned — zero network); percentile of |gap|, rides
  `gather_context` AFTER the as-of truncation so it's historically valid for free. Futures/AH
  as-of-suppressed. NOT risk-scorecard factors (S43); never model features.
- **S64 FIX — the AH price could never move** (user-reported on SOFI the evening it shipped).
  Three separate defects, all now closed:
  · **Wrong source.** The module shipped asserting "`last` keeps updating on AH prints while
    `close` latches at the bell". **False.** Probed live 2026-07-27 16:34 ET, 34 min post-close
    with ~130k SOFI AH shares in: `last` 16.88 == `close` 16.88 and `trade_date` FROZEN at
    16:00:00.153 — while `bid_date`/`ask_date` were 8s old (quotes DO stay live) and
    `/markets/timesales?session_filter=all` showed 16.92. `last` latches exactly like `close`,
    so a quote-derived read is pinned to +0.00% forever. Now: `get_timesales(session_filter=)`
    (new param, default "open" so the S63 LTF/1h-topup grids are untouched) + `fetch_ext_print`
    → last **1min** bar outside RTH and strictly AFTER `_ext_window_start(now)` (= last completed
    session's 16:00 — ONE rule spanning tonight's post-market and tomorrow's pre-market). Two
    details that matter: `EXT_INTERVAL="1min"` not 5min (a 5min bar froze the tile's stamp for up
    to five minutes — on a "has it moved since the bell" surface that reads as broken); and the
    STRICT `>` drops the 16:00 closing-auction bar Tradier stamps at the bell, so a name with no
    real AH trade (VRTX tonight — one 16:00 bar, 437k shares) shows nothing instead of its own
    close. Verified a genuine 0.00% is still possible and correct (QQQ's 16:50 bar traded 38.6k
    shares and happened to close exactly at the official close). The quote is still used,
    but only for the reference `close`/`prevclose`, which was never wrong. `hhmm` is now the
    PRINT's time, not the wall clock, so a stale tape is visible. **No print → None → the tile
    is absent**, never a 0.00% placeholder.
  · **Never refreshed.** `payload["ah"]` is a generate-time snapshot and the report query has no
    refetchInterval → frozen at whenever Run was pressed. Now `GET /api/afterhours/{ticker}`
    (RTH short-circuit before any Tradier call, 10s `afterhours_cache`) polled every 30s by
    HeaderTiles, independent of the **live** checkbox.
  · **Live backoff killed it.** AH rode `LiveInfo.ah`, so it inherited CandleChart's
    `LIVE_MISS_LIMIT` counter — which counts `fetch_live_bar` misses, and that ALWAYS misses
    overnight/pre-market (`trade_date` isn't today). Polling stopped after ~30s. `ah` is off the
    live tick entirely now.
  · **Lesson (durable):** the S64 test passed throughout, because its fixture hand-built a quote
    with `last` 514.32 vs `close` 512.53 — a shape the API never returns. It validated the
    assumption, not the data source. Vendor-behavior assumptions must be probed against a live
    response and the fixture must be REAL-SHAPED; the regression guard is now "real quote +
    no ext print → None".

- **S65 four-track improvement pass** (user request: readability + entry timing + profitability
  + short opportunity; all four scoped display-only after the S20/S21/S28 history):
  (1) **PRICE LADDER** — `modules/levels.py` (pure): every level the report knows (profile
  POC/VA/HVN/LVN, GEX walls/flip/max-pain, EM band, numeric 1D/1W MA20/50/200 — `read_timeframe`
  now returns the VALUES, 52w hi/lo, prior-day H/L/C, `--level`) merged into one distance-sorted
  ladder; ±0.5% clusters = confluence zones (◆); nearest S/R; `--level` finally COMPUTED
  (distance/side/confluence, echoed in THESIS CHECK). Default-on, zero network, as-of-valid.
  (2) **SHORT SETUP** — `modules/shortside.py` (pure), `--short` auto-on under `--thesis
  bearish`: for/against factors, crowding verdict off --squeeze fuel/counter (unknown without —
  never fetches), short-side checklist (setupcheck rows 2/3/4 inverted THERE, setupcheck.py
  untouched → snapshot/diff/self-score meaning stable), lagging-sector pool (+ bottom-3 via new
  `sectors.bottom_performers_read`; sector_top cache shape-gated on "bottoms"). S21 conditions
  (VIX stress/backwardation — `S21_CONTRA_PREFIXES`, drift-guarded test) land on AGAINST and get
  ⚠ annotations in the bearish thesis confirmations (counts untouched — S43); S28 no-short-edge
  caveats print unconditionally. `levels.nearest_lvn_below` = the below-spot LVN-air mirror.
  (3) **UI verdict + readability** — `VerdictStrip.tsx` (regime pill · setup TallyBar · dd/rally
  balance · synthesis · Δ-badge that opens+scrolls the diff) above the chart; HeaderTiles moved
  ABOVE the fig; `TallyBar` in viz.tsx (also in SecSetup); multi-TF alignment strip (1M ↑ · …);
  grouped backdrop chips (known prefixes → bold labels, unknown unchanged); nav completed
  (Divergences/Price ladder/Short setup/Thesis/Notes — SecNotes gained a Sec header); DiffPanel
  "Δ N changes" title + defaultOpen when N>0; pc-oi expiry + GEX unusual tables folded
  (long-call table deliberately left open — it IS that section's deliverable); watchlist tiles
  gained pos52/staleness/risk-lean/regime (extended `load_tile`; no batch endpoint — per-ticker
  GETs fine at this scale).
  (4) **LENS SELF-SCORE** — `lens_score.py`: payload_history snapshots (unchanged format) joined
  to realized 15d/63d returns, aggregated by setup band/regime/risk lean, avg+median only,
  honesty note always printed (small N, non-independent, NO significance); `GET
  /api/lens_score/{ticker}` + `LensScore.tsx` expander (as-of hidden). First real run: 6 QQQ
  snapshots, all pending.
  NB the `--thesis bearish` overlay previously counted S21 contrarian-buy conditions as clean
  short confirmations — that was the motivating mislabel for track 2.

- **S66 chart timeframes** (user request): the web candle chart gets a TF pill row
  (5m/15m/30m/1h/2h/4h/1D/1W/1M) — `?tf=` on /api/chart, `charts.tf_frame` (1D = the original
  chart_frame path untouched; W/M resample the daily; 1h/2h/4h off the cached yfinance 60m
  frame — 2h keeps the 90min session offset; sub-hourly off `_load_ltf`, Tradier real-time).
  Per-TF view lengths (`TF_VIEW`), overlays/RSI/MACD compute on the selected frame.
  Gotchas encoded: intraday axes need an hour rangebreak to collapse the overnight gap and
  **4h must reopen at 08:00** (midnight-anchored bins — a 09:30 bound swallows the 08:00 bar);
  **W/M skip rangebreaks entirely** (the weekday-holiday diff would misread every non-period-end
  weekday as a holiday — hundreds of break values); event vlines are daily-dated (midnight =
  inside the overnight break) → 1D/1W/1M only; the live provisional bar appends on 1D only,
  and the live tick's `prev_close` comes from the DAILY frame on other TFs (an intraday
  iloc[-2] is just the prior bar); range52 always reads the daily frame; sub-hourly pills
  disabled in as-of mode (no historical source). uirevision includes tf.

- **S67 equal-weight index checks** (user request: "a check against equal weighted indexes as
  part of understanding the overall state of the market"; three tracks, all display-only):
  (1) **MARKET BREADTH section** (default-on, CLI + React, before SECTOR ROTATION) — the S45
  backdrop one-liner promoted: RSP−SPY / QQQE−QQQ at 20d+63d w/ spread percentile + ≤60-pt
  `spark` (sentiment.spark_of), an IWM−SPY small-cap PARTICIPATION pair (labeled "not equal
  weight"; NOT added to `PAIRS` — build_backdrop reads only "pairs" so the backdrop segment is
  byte-unchanged), and a two-sided pure `divergence_read(rel_20d, pct, cap_off_high)` →
  narrowing (cap leg ≤2% off its 252d high while EW spread < −dead-band or pct ≤ 0.25) / broad /
  repair (>5% off high + EW leading) / neutral. `fetch_breadth` now downloads 5 symbols in the
  same single batch and caches {"pairs", "participation"} with an S65-style TTL-fresh **shape
  gate** ("participation" in cached); the stale-FALLBACK path still serves old shapes → every
  consumer .get()s. Payload key `breadth`; as-of omitted (note extended). Web `SecBreadth`
  (misc.tsx): DataTable + PctBar + Sparkline, narrowing → Warning; nav `market-breadth`.
  (2) **EW−cap sector column** — `sectors.EW_TWIN` (XLK→RSPT … XLRE→RSPR, the 2023-renamed
  Invesco equal-weight suite, verified); `rotation_read` rows gain `ew_20d`/`ew_tag`
  (broad/narrow/mixed on ±ROT_DEAD, EW twin vs its OWN SPDR); `fetch_sectors` downloads 23
  symbols (still one batch) and FINALLY got a shape gate ("ew_tag" in rows[0] — it had none).
  CLI: EW−cap column + `tag · ew_tag`; web: conditional column, both `.get()`-safe vs stale rows.
  (3) **ticker vs the average stock** — pure `sectors.ew_comparator(ticker, own_sector_sym)`
  (QQQ→QQQE, SPY→RSP, SPDR/own-sector→RSP* twin, EW vehicle→None, else RSP);
  `setupcheck.fetch_rs(..., extra=[(sym,label)])` rides the SAME single yf.download as a symbol
  list (both MultiIndex and flat single-survivor shapes handled; extra=None → byte-identical
  pre-S67 shape, setupcheck row 4 untouched per the S65 frozen-rows rule) → out["extra"] →
  `breadth["ticker_ew"]` (scalar rs_20d/rs_63d keys — int keys would stringify over JSON) →
  one line in the breadth section ("AMD vs RSPT (average Technology stock): … — beating the
  average stock"). `_rs_cell` hoisted to lens module scope (color param) — shared by both
  tables. Tests 62–65 + test-36/s62 monkeypatch lists gained fetch_breadth/ew_comparator;
  snapshot/diff deliberately NOT extended (market-level data would duplicate per ticker).

- **S68 level projections** (user request: "when indicating a key level, what would a move to
  that price look like — % change + projected long-call profit"): `modules/levelproj.py` (pure,
  offline-testable, clock-injectable) rides INSIDE `ladder["projections"]` (payload contract
  untouched). KEY targets only — --level / nearest S/R / ≤2 nearest confluence zones, deduped
  ±0.5% (raw --level vs its cluster mid differ by construction). Per target: `travel_sessions`
  = |dist| ÷ (HV-20/√252), linear sigma-days capped 252 (caveat: first-passage would be slower);
  per contract TWO legs — instant (T unchanged) and paced (T − travel×365/252 calendar
  conversion, floor→intrinsic). Quoted path: --call this run OR the call2 session cache via new
  `callquote.cached_call_quote` (zero-network sibling of cached_liquidity); block dte REFRESHED
  from expiry vs today (cached dte is stamp-day). **STALE-cache honesty fix (probed live — the
  motivating bug)**: a stale cache's mids were struck at another spot (QQQ dropped 692→675
  post-cache; +3.6% target read −47%), so under `stale` the ENTRY is re-modeled at CURRENT spot
  (same strike/IV, ask leg dropped, `entry_modeled` flag, "entries re-modeled at current spot"
  header + `entry≈` prefix). Synthetic fallback when no quote: BS ATM call at 30d (harvested
  ATM IV 30d, else HV-20 proxy — labeled) + 180d (ATM IV 180d when present, the LEAPS tenor),
  "modeled, not a quote". RISK_FREE=0.04 (gex convention); bs arg order r-before-T guarded by
  exact-equality test. CLI: "level projections" sub-block under PRICE LADDER (non-user targets
  ATM-only, rows[:4]) + a one-line at-your-level summary in THESIS CHECK; caveat unconditional
  (IV constant, no skew/vol-path, straight-line pace, not advice). As-of: cache read gated →
  synthetic-only (as-of ctx gauges are historically valid). Web: `LadderProjections` in
  core.tsx (DataTable per target). Tests 66–70 (test 36 untouched — rides inside ladder).
- **S69 long tenors + expiry/strike pickers** (user request: "keep the current timeframe, but add
  ones for about 6 months out, and about a year out as well" → then "add a dropdown … selecting
  one or multiple strikes" and the same for expiries). The block was pricing 45/90 DTE while the
  user trades 6–12mo calls (sizing.py MIN_DTE=180/MAX_DTE=365), so:
  · `callquote.TARGET_DTES = (45, 90, 180, 365)`, SCOPEKEY `call2`→`call3`.
  · **Long-tenor selection is grid-aware** — the LEAPS ladder is sparse and ticker-specific, so a
    naive nearest-monthly mislabels: SOFI's monthlies run 169 → 232 → 505 (nearest to 365 is 133
    days off) while a NON-monthly 322d LEAP is the real 1-year contract; CRSP has 171 then 542
    and no 1-year tenor at all. Rule: prefer monthlies while one is inside `tenor_tol` =
    ±max(30, 0.35×target); past `LONG_DTE_MIN`=150 widen the pool to every listed expiry; OMIT a
    target with nothing inside tolerance. Verified against real grids — SOFI→322, CRSP→no row,
    QQQ→414 (the liquid monthly beats the closer 335d quarterly, since 414 is inside tolerance).
    Rows are ALWAYS labeled with the actual expiry+DTE, never the target.
  · **`strike_ladder`** — ≤`LADDER_MAX`=9 tradeable calls within ±`LADDER_PCT`=25% of spot, off
    the SAME parsed chain rows the ATM pick already used (zero extra network), tagged
    atm/otm/other + `moneyness`. Rides each block as `ladder`; `levelproj` reprices ALL of them
    server-side so the web pickers only FILTER — no Black-Scholes duplicated in TS (the
    api/charts.py precedent). Pre-S69 caches (atm/otm, no ladder) still reprice.
  · **Net chain calls unchanged (~7, measured both ways)**: the quote expiries seed `curve_pts`,
    so the two new tenors consume the curve's `CURVE_MAX_EXPIRIES` budget instead of adding to it
    — and the curve now reaches 322d instead of 232d for free.
  · Synthetic legs `(30, 180, 365)` with a real IV chain: harvested gauge → `curve_iv` (nearest
    curve point, `max_gap`=120d) → HV-20 proxy, each labeled. **The 180d synthetic row was dead
    code**: it was keyed to `atm_iv_180d`, which is empty in EVERY indicators CSV on disk.
  · CLI: one ATM row per tenor. The old `rows[:4]` sliced an expiry-ordered list and would have
    silently truncated away exactly the new long-dated rows — the trap this change had to dodge.
    Labels use `YY-MM-DD` + DTE (`expiry[2:]`); `[5:]` dropped the year and made a 2027 LEAP
    ambiguous.
  · **S70 custom-price stepper** (user: "add one more option for spot price … a number box with
    up and down arrows … and an option to select the increment amount"): a ± number box above the
    projections, defaulting to spot, with a step picker (`STEP_CHOICES`, default ≈0.5% of spot so
    a $16 and a $680 name both nudge sensibly), 250ms debounce, `placeholderData` to avoid
    blanking between steps, and a reset button. Backed by `levelproj.project_price` — which
    builds a one-target ladder and runs it through `project_targets`, so the stepper and the
    fixed-target table share EXACTLY one pricing path (a bit-equality test pins it; note
    110/100−1 is 0.10000000000000009, so the test must use the same expression or it near-misses
    through travel_sessions). Served by `GET /api/project/{tkr}?price=` off `reportgen.LATEST` +
    the `--call` session cache: no chain fetch, no regenerate, 409 when that ticker hasn't been
    generated in this process. **Deliberately a server round-trip, not TS math** — porting
    Black-Scholes to the browser is precisely how the stepper would drift from the table above
    it (same rule that keeps the candle fig in api/charts.py). CLI equivalent already exists:
    `--level`.
  · **S71 date picker** (user: "a date picker, ideally a dropdown calendar form, so we can see
    what the return will be for spot price on a particular date"): a THIRD leg per contract.
    `_legs` gained `hold_cal`, so instant / paced / dated are one repricing with three different
    amounts of time left — instant = T unchanged, paced = T minus the HV-20 travel ESTIMATE,
    dated = T minus a hold the USER chose (calendar days; a date is already calendar time, so no
    trading-day conversion). That makes "what does waiting cost me" answerable without the pace
    guess. Past a contract's own expiry the leg floors to intrinsic and sets `expired` (rendered
    `4.25 exp`); past dates are refused (422 at the API, None from the pure fn). Web: native
    `<input type="date">` (the dropdown calendar) + 1w/1m/3m/6m presets + clear; the two dated
    columns render ONLY when a date is set, so the fixed targets are unchanged. Verified live on
    SOFI: at no move held 91 days the 169d contract bleeds −38% vs the 322d's −19% (the tenor
    tradeoff, made visible); a +32.8% move reads instant +154% / paced +149% / on-date +119%.
  · **S70/S71 spot-drift fix (found BY the stepper)**: the stepper at spot read −19% at a
    zero-percent move. The math was right — BS reproduced the cached mids to ~1% — but the
    `--call` cache held spot 16.13 against a 15.25 report spot. S68 only re-modeled entries for a
    session-STALE cache; a cache from earlier the SAME session is "fresh" by that rule and just
    as un-enterable. `SPOT_DRIFT_TOL`=1% now triggers the same re-model, and both renderers name
    the reason ("quoted at 16.13 (+5.8% vs spot), entries re-modeled at current spot"). This
    corrected the FIXED targets too — every projection in the block had been understated by the
    drift. Lesson: a what-if control at the no-change point is a free invariant test; if
    "nothing moves" doesn't read ~0, something upstream is inconsistent.
- **S72 every-monthly expiry window** (user: "expand the available expiries, and only use
  monthlies … there are monthlies for SOFI that don't show up as a pill … the math picks a
  particular date range, lets make it a bit more flexible"). They were right: S69 quoted the
  nearest expiry to each of 4 target DTEs, so SOFI's 113/141/232-day monthlies never appeared.
  · `select_expiries` now takes EVERY monthly in `[EXPIRY_MIN_DTE=20, EXPIRY_MAX_DTE=550]`,
    capped `MAX_EXPIRIES=12` nearest-first. Measured live: 10 SOFI, 5 CRSP, 12 QQQ/AMD. The
    "~1yr" LABEL is gone with it — the label was the only thing that could lie, and with all
    expiries offered the user picks the tenor instead of the code guessing. `tenor_tol` /
    `LONG_DTE_MIN` / the omit-when-off-target rule are all deleted as no longer needed.
  · **HOLIDAY SHIFT — the trap in "only monthlies".** `pc_oi.is_monthly_expiry` is date-only
    (Friday, day 15-21), so it cannot see that a monthly moves to the Thursday before when the
    third Friday is a market holiday. Probed live 2026-07-30: SOFI/QQQ/AMD all list
    `2027-06-17` (Thu) and NOT `2027-06-18` — Juneteenth 2027 falls on a Saturday and is
    observed that Friday. A naive monthlies-only filter would have DROPPED the June-2027 LEAP,
    i.e. exactly the ~1yr contract S69 went to trouble to include. New list-aware
    `callquote.monthly_expiries`: per (year, month) take the third Friday if listed, else the
    day before. Deliberately not a bare "Thu in the 15-21 window" test — QQQ lists Thursday
    weeklies. `is_monthly_expiry` is left alone (pc_oi/gex/volquote/massive still use it; a
    date-only fn cannot do better without a holiday calendar).
  · CLI curation: `nearest_to_targets` + the surviving `TARGET_DTES` — a terminal has no picker
    and 12 expiries × 5 targets = 60 rows, so the CLI prints the 4 closest to 45/90/180/365d
    and states how many were quoted. Wording avoids tenor names because for CRSP the closest to
    365 is 540d.
  · Cost: chain calls = len(select_expiries) exactly (the separate curve-extension pass is
    deleted — every window monthly is already fetched, so the IV curve went from ≤7 points to
    all of them for free). ~0.55s per expiry; SOFI 10 calls/6.4s vs 7/~4.5s before. Payload
    23KB. SCOPEKEY call3→call4.
  · **Also found (NOT fixed, needs a session)**: the Massive harvest looks stalled —
    `atm_iv_30d` last stamped 2026-06-19 (SOFI) / 06-23 (QQQ), and `atm_iv_180d` has never been
    populated since S47 shipped. Degrades every IV gauge and the no---call synthetic path.

Modules the lens/web stack uses
-------------------------------
- `timeframes.py` — per-TF OHLCV (CSV else yfinance; 1h cached + Tradier timesales top-up in
  --live), `last_bar_partial` (calendar-aware S43), `fetch_live_bar`/`append_live_bar`;
  S63 adds `TF_ORDER` 2h/30m/15m/5m, `INTRADAY_TFS`/`TF_MINUTES`/`session_open`, an
  interval-parameterised `_load_intraday` and `_load_ltf` (Tradier 5min → yfinance fallback).
- `structure.py` — transparent per-TF reads (trend/RSI/Stoch/MACD — None states print "—" on
  thin frames; +S57 `ma20_run` signed MA20-side close streak), `read_volume` (partial-bar
  aware), divergences, confluence summary, `rally_drawdown_risk` two-sided scorecard
  (+S57 `regime` key via `trend_regime` — the overbought-stays-overbought fix, AMD Mar–Apr
  2026 motivating case; regime flips surface in the web Δ-diff), `read_squeeze` (BB-inside-KC).
- `volume_profile.py` — POC/value-area/HVN/LVN (+`with_hist=True` for the web histogram);
  `near_hvn_*` proximity-bounded ±`HVN_NEAR_PCT`=5% (S43 — "approaching" must mean near).
- `sentiment.py` — `gather_context()` gauges: IV/HV, ATM IV (30d) **real harvested IV**,
  ATM IV (180d) with "N.NNx front" label (S47 — the LEAPS tenor), 25Δ skew, term, P/C OI,
  HV-proxy gauges explicitly labeled `(HV-proxy)`, VIX complex. Percentiles need ≥63 obs
  (`percentile_of`); "(stale Nd)" labels when the harvest lags (S43); ctx notes now surface in
  lens output.
- `volsetup.py` + `volquote.py` — --vol: squeeze/expected-move/earnings scorecard (30d-based;
  the em factor was REMOVED S43 — it duplicated IV/HV and could flip the verdict alone) +
  earnings-aware ATM straddle / auto-strangle pricer (post-earnings expiries, liquidity-snapped
  wings, at-ask honesty lines, no-bid flags).
- `callquote.py` — --call: ATM + ~0.375Δ call quotes (BE move, theta/day as % of premium) at
  `TARGET_DTES`, IV-by-expiry curve to LEAPS tenors (≤400 DTE, S47), chain `liquidity_grade`
  (tight/ok/wide/dead) + `cached_liquidity` zero-network default-on line. **S69**: tenors are
  `(45, 90, 180, 365)` + a per-expiry `strike_ladder` — see the S69 entry below.
- `vol_history.py` — pre-earnings IV ramp/crush/straddle-P&L study off on-disk IV; prefers
  `atm_iv_event` when all three sessions have it (never mixes tenors); MIN_USABLE=3.
- `pc_oi.py` (--pc-oi), `shortint.py` (--squeeze; NASDAQ-listed only), `setupcheck.py`
  (default-on checklist + `fetch_rs` + `beta_corr`/`fetch_beta`), `fng.py` (F&G, ~6h cache),
  `breadth.py` (equal-weight breadth, drift-free short horizons), `insider.py` (--insider,
  EDGAR Form 4 cluster buys), `geocontext.py` (--geo).
- `sectors.py` **S59 movers**: opt-in `--movers` (+ web checkbox, `?movers=1`) adds top 3 of
  each sector's ~10 largest constituents by 63d ABSOLUTE return (20d fallback) under the
  rotation table — `YF_SECTOR_KEYS` (all 11 GICS sectors covered/probed), pure
  `top_performers_read`, `fetch_top_performers` (~11 yf.Sector lookups + 1 batched download,
  cached ~6h `data/sector_top_cache.json`); current-only → as-of note lists it. Caveat printed:
  Yahoo classification, biggest names ≠ full membership.
- `massive.py` — daily quote-based harvest via indicators.py: `atm_iv_30d` + skew/term/P-C,
  `atm_iv_event` (nearest post-earnings expiry when earnings ≤45d, S44 — the constant-maturity
  30d gauge blunts the true ramp), `atm_iv_180d` (S47, LEAPS tenor; percentile FORWARD-ONLY, no
  backfill possible at long tenors). `IV_EVENT_COLS`/`IV_LONG_COLS` ⊂ `IV_META_COLS` → auto-
  excluded from all models.
- `features.py` — `next_earnings`, `next_ex_dividend` (exact via yf calendar else cadence
  estimate `~`), HV features. `benchmarks.py` — `upcoming_catalysts` (catalysts.csv → KNOWN
  CATALYSTS; CRSP PDUFA dates), RS benchmarks. `tradier.py` — the ONLY real-time source (~4s);
  Massive = 15-min-delayed quote snapshots; yfinance = daily history + intermittently-throttled
  intraday.
- `backfill_iv.py` — historical IV via trades-only BS-inversion; **writes only NaN cells**
  (`_apply_result`, S44) so re-running over harvested history is safe. **CRSP backfill = proven
  dead end** (thin options, trades-only history — quotes exist, trades don't); its evidence
  accumulates via the daily harvest through earnings windows instead.

Durable rules & lessons
-----------------------
- **Display ≠ feature**: info that failed as a model feature (econ proximity, VIX regime,
  breadth, geo) is still valuable as HUMAN context — but never wire context into models.
- **User display rule (permanent)**: write "percentile" in full — never "%ile"; number without a
  % sign (`{x*100:.0f} percentile`).
- **No new default-on network calls** — opt-in flags or session caches only.
- Scorecard integrity (S43): no double-counted factors; proximity checks on "near" claims;
  None-states print "—", never a confident label; near-always-on factors don't belong in tallies.
- Stress/fear readings historically = contrarian BUY for this framework's signals (S21), and the
  stack is reactive not predictive of exogenous shocks — read IV/skew/term + --geo, don't size
  like the backtest average in a crisis.
- Cross-ticker validation is load-bearing for any MODEL change (QQQ + a non-secular validator);
  audit new features for calendar-time correlation (the S31 leak lesson).

Legacy ML framework (one paragraph)
-----------------------------------
The project began as an ML options-swing framework and still ships it intact: daily flow
`indicators.py → entry.py → sizing.py`, diagnostics `direction.py`/`volatility.py`/`exit.py`/
`backtest.py`, five-tier signal (STRONG ENTRY…STAY OUT) from logistic-regression phases with
vol-adjusted thresholds and an IV/HV ≥1.40 downgrade gate. After the S31 calendar-time-leak fix,
**QQQ is the only ticker with real, hierarchy-intact edge** (STRONG 1.6%/64% 15d · 8.9%/75% 6mo);
Ford and JPM are clean validators; NVDA is anti-predictive (unsuitable), AMD marginal, SPY
structurally unsuitable, CRSP = vol-plays only. All research flags (`--calibrate`,
`--iv-features`, `--econ-features`, `--p4-gate`, `--side put`, `--regime-gate`) failed
cross-ticker validation and stay default-OFF. `entry.py` writes a forward signal ledger
(`data/{ticker}_signal_ledger.csv`, since 2026-06-12) that NOTHING reads yet — a scorer joining
it to realized 15d/63d returns is the standing out-of-sample validation TODO. Full detail:
CLAUDE.md + git history.

Operational notes
-----------------
- Venv explicitly: `.\trade\Scripts\python.exe -X utf8 …` (+ `-X utf8` required on Windows).
  Piped runs: PowerShell tool, `cmd /c "(echo TICKER) | python -X utf8 script.py"`; prefer
  `--ticker` to skip prompts. Env vars ($PROFILE): MASSIVE_API_KEY, FRED_API_KEY, TRADIER_TOKEN.
- Smoke: `.\trade\Scripts\python.exe -m pytest tests/ -q` (52 tests, offline, ~3-9s).
- Percentile gauges need ≥63 harvested rows per ticker — thin history prints the value with an
  explanatory note instead (GOOG case: 2 rows → no percentile until backfill or ~3 months).

Outstanding / backlog
---------------------
- **User-run**: QQQ IV backfill (~15–25 min — restores the real-IV percentile path for the
  reference ticker); then SOFI/LYFT re-backfill + AAPL build. Safe post-S44 (per-cell writes).
- **CRSP watch**: PDUFA 2026-08-01 + earnings 2026-08-10 — keep the daily harvest running
  through the window (missed pre-earnings sessions cannot be backfilled; the lens warns ≤10d).
- ~~Signal-ledger scorer~~ LANDED S56 (`score_ledger.py`; verdicts mature as rows age past
  15/63 sessions). ~~NYSE short interest~~ LANDED S56 (FINRA consolidated, no auth).
- Optional --geo percentile-window normalization; Textual + textual-image TUI recorded as
  the deferred terminal-window alternative to lens_web.
