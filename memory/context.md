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
  --geo --live --thesis/--level --candle box|braille|sixel|none --no-refresh/--refresh).
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
scorecard · SETUP CHECK ✓/✗/– checklist (HTF alignment, momentum, volume, RS vs benchmark,
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
  `generate_report.clear(ticker, flags_key)`).
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
- Deps: streamlit/ansi2html/plotly. `.claude/launch.json`: lens-web (8501, the user's) +
  lens-web-dev (8502, verification — never collide with the user's instance).

Modules the lens/web stack uses
-------------------------------
- `timeframes.py` — per-TF OHLCV (CSV else yfinance; 1h cached + Tradier timesales top-up in
  --live), `last_bar_partial` (calendar-aware S43), `fetch_live_bar`/`append_live_bar`.
- `structure.py` — transparent per-TF reads (trend/RSI/Stoch/MACD — None states print "—" on
  thin frames), `read_volume` (partial-bar aware), divergences, confluence summary,
  `rally_drawdown_risk` two-sided scorecard, `read_squeeze` (BB-inside-KC).
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
- `callquote.py` — --call: 45/90-DTE monthly ATM + ~0.375Δ call quotes (BE move, theta/day as %
  of premium), IV-by-expiry curve to LEAPS tenors (≤400 DTE, S47), chain `liquidity_grade`
  (tight/ok/wide/dead) + `cached_liquidity` zero-network default-on line.
- `vol_history.py` — pre-earnings IV ramp/crush/straddle-P&L study off on-disk IV; prefers
  `atm_iv_event` when all three sessions have it (never mixes tenors); MIN_USABLE=3.
- `pc_oi.py` (--pc-oi), `shortint.py` (--squeeze; NASDAQ-listed only), `setupcheck.py`
  (default-on checklist + `fetch_rs` + `beta_corr`/`fetch_beta`), `fng.py` (F&G, ~6h cache),
  `breadth.py` (equal-weight breadth, drift-free short horizons), `insider.py` (--insider,
  EDGAR Form 4 cluster buys), `geocontext.py` (--geo).
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
- Smoke: `.\trade\Scripts\python.exe -m pytest tests/ -q` (33 tests, offline, ~2-7s).
- Percentile gauges need ≥63 harvested rows per ticker — thin history prints the value with an
  explanatory note instead (GOOG case: 2 rows → no percentile until backfill or ~3 months).

Outstanding / backlog
---------------------
- **User-run**: QQQ IV backfill (~15–25 min — restores the real-IV percentile path for the
  reference ticker); then SOFI/LYFT re-backfill + AAPL build. Safe post-S44 (per-cell writes).
- **CRSP watch**: PDUFA 2026-08-01 + earnings 2026-08-10 — keep the daily harvest running
  through the window (missed pre-earnings sessions cannot be backfilled; the lens warns ≤10d).
- Signal-ledger scorer (matures ~1–2 months of rows); NYSE short-interest coverage for
  --squeeze (FINRA Query API); optional --geo percentile-window normalization; Textual +
  textual-image TUI recorded as the deferred terminal-window alternative to lens_web.
