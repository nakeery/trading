# LENS frontend — orientation for a Python developer

The React app in this folder is the LENS UI (S60), replacing the Streamlit app
(`lens_web.py`) once it reaches parity. Python still does ALL the computing — the FastAPI
backend in `../api/` serves `lens.gather_report()`'s payload as JSON; React only renders it.

## Running it (dev)

Two servers, both from the repo root:

```powershell
# 1. API (FastAPI on :8000; --reload-dir api = only api/ edits restart it)
.\trade\Scripts\python.exe -m uvicorn api.main:app --port 8000 --reload --reload-dir api

# 2. Frontend (Vite dev server on :5173 — open this one in the browser)
npm run dev --prefix web
```

(PowerShell note: `npm` must be on PATH — any terminal opened after the Node install has
it. If you ever call the exe by its quoted full path, PowerShell needs the call operator:
`& "C:\Program Files\nodejs\npm.cmd" run dev --prefix web` — without `&` it errors with
"unexpected token".)

Vite proxies every `/api/...` request to :8000 (`vite.config.ts`), so the frontend code always
uses relative URLs and there is no CORS anywhere. Edits to `web/src/` hot-reload instantly in
the browser (no restart, no rerun — unlike Streamlit).

## React ↔ Python mental map

| React thing | Closest Python/Streamlit idea |
|---|---|
| A component (`function App() { return <div>…</div> }`) | A render function — but it RE-RUNS only when its own state/props change, not the whole script |
| JSX (`<div>{x}</div>`) | An f-string that builds real UI elements; `{}` interpolates any JS expression |
| `useState(0)` | A `st.session_state` slot scoped to one component |
| Props | Function arguments passed from parent to child component |
| `useQuery({queryKey, queryFn})` (TanStack Query) | `@st.cache_data` + the fetch itself: cached under `queryKey`, deduped, gives `isLoading`/`isError`/`data` |
| `useEffect` | "run this side effect after render" — rarely needed here; data fetching goes through useQuery |
| TypeScript types (`src/api/types.ts`, from M1) | The payload dict contract, written down — the compiler yells when a key is misspelled |

Key difference from Streamlit: there is NO rerun-the-whole-script model. State changes re-render
only the components that read that state. That's why the app needs no debounce hacks for
checkbox toggles and no `st.fragment` for the live chart — a 10-second poll just updates one
component's data.

## Layout

```
web/
├── vite.config.ts            # dev server + /api proxy
└── src/
    ├── main.tsx              # entry point: mounts <App/> with the QueryClient provider
    ├── App.tsx               # state owner: ticker/flags/as-of drafts, 2s debounce,
    │                         #   deep-link read/write-back, report query, page layout
    ├── theme.css             # dark palette as CSS variables (--bg, --green, --amber, …)
    ├── api/
    │   ├── types.ts          # TS mirror of the payload / API contracts
    │   └── client.ts         # typed fetchers (always relative /api/… URLs)
    ├── utils/colors.ts       # CLI color math ported: ramp/heat/RSI tints, ordinal
    │                         #   percentiles ("97ᵗʰ"), pc labels
    ├── hooks/useUrlState.ts  # ?ticker=QQQ&gex=1&asof=…&from=… read + write-back
    └── components/
        ├── TopBar.tsx        # search, pills, flag checkboxes, thesis/as-of panels, Run
        ├── CandleChart.tsx   # server-built fig + overlay toggles + 10s live poll
        ├── HeaderTiles.tsx   # close/OHL/52w tiles (rides the live tick)
        ├── Plot.tsx          # react-plotly wrapper (finance partial bundle)
        ├── shared.tsx        # Sec/Pill/Net/Bullets/DataTable/Metric/Collapsible/
        │                     #   Sparkline/SectionBoundary
        ├── sections/         # the 20 report sections (core/gauges/positioning/
        │                     #   volcall/misc + index with nav + error boundaries)
        ├── Extras.tsx        # IV-vs-HV history, earnings reactions, seasonality
        ├── Watchlist.tsx     # landing grid (CSV-only tiles)
        ├── EconCalendar.tsx  # FRED release grid + refresh button
        ├── DiffPanel.tsx     # Δ what changed vs prior session
        └── SignalLedger.tsx  # scored forward ledger
```

## How data flows

1. `App` commits `{ticker, flags}` (after the 2s debounce, or immediately on Run/pill).
2. `useQuery(['report', …])` → `GET /api/report/{ticker}?flags…` — the backend runs
   `lens.gather_report` under a lock, returns `{payload, preamble, ansi_html, diff}`.
3. The payload drives everything else: `<Sections p={payload}/>` renders the 20 report
   sections natively; `<CandleChart>` asks `/api/chart` for the figure (built server-side
   from the same payload's profile/GEX/events); the ANSI report is the lossless fallback.
4. Live mode: the chart query polls every 10s with `live=1` — one Tradier quote per tick,
   pausing after 3 empty responses.

Two rules worth knowing when editing:
- **Never restyle the candle fig** — it arrives complete from `api/charts.py`; the
  two-axis hollow-candle convention lives there, not in TS.
- **`[]` is truthy in JS** (falsy in Python) — length-check array-valued payload slices
  when porting guards from the Streamlit renderers.

## Production (single command)

```powershell
npm run build --prefix web
```

builds to `web/dist/`; `api/main.py` auto-mounts that folder, so
`.\trade\Scripts\python.exe -m uvicorn api.main:app --port 8000` then serves the whole app on
http://localhost:8000 — one process, no Vite needed.

## Parity with the Streamlit app (verified 2026-07-21)

The Streamlit app (`lens_web.py`, :8501) stays untouched and runnable in parallel until
you retire it. Feature parity checklist against it:

| Feature | Status |
|---|---|
| Report generation (all flags, pc-oi scopes, thesis/level) | ✅ same engine, same payload |
| Candlestick chart (two-axis hollow candles, MA/EMA/BB/RSI/MACD/volume overlays, price line, vol-profile aspects, GEX levels, event markers, rangebreaks) | ✅ fig built by the SAME Python code, ported into `api/charts.py` |
| Header tiles + 52-week range | ✅ |
| Entry-timing rows (`ltf`: 30m/15m/5m below a divider in the multi-TF table, live session only) | ✅ same divider + per-block heat scale as the CLI |
| All 20 native sections (multi-TF heat table, risk/setup panels, gauges w/ sparklines + ordinal percentiles, PC/OI bars + strike walls, GEX bars, straddle/strangle + long-call tables, IV curve, sectors, street, insider, squeeze/buzz, catalysts, macro, thesis) | ✅ verified vs the ANSI report (QQQ + AMD, all flags) |
| Full ANSI text report expander | ✅ server-side ansi2html |
| IV-vs-HV history (+25Δ skew pane, pre-earnings shading) | ✅ |
| Earnings reactions + seasonality expanders | ✅ |
| Watchlist landing grid + setup chips | ✅ |
| Econ calendar grid + FRED refresh button | ✅ |
| Day-over-day Δ diff (snapshots shared with Streamlit under data/payload_history/) | ✅ |
| Scored signal ledger | ✅ |
| Deep links (?ticker&flags&asof&from) + URL write-back | ✅ |
| As-of backtest mode (banner, truncation, block/diff/ledger suppression, live off) | ✅ |
| Live mode (10s tick, provisional today-bar, tiles ride the tick, 3-miss backoff) | ✅ |
| 2s debounce on flag changes; Run = force-fresh; pills bypass debounce | ✅ |
| Overnight context (S64: `fut` backdrop chip — automatic via the chip split; gap gauges — automatic via the VOL gauge table; AH/pre-mkt header tile — its OWN `GET /api/afterhours/{ticker}` poll every 30s, 🔴-prefixed once the poll answers, `payload.ah` only as the first paint. Independent of the **live** checkbox; the server returns null during RTH so the client polls unconditionally. It used to ride `LiveInfo.ah` on the live tick, which coupled it to the miss-counter and froze it overnight — do not put it back there. Polling still pauses when the tab is unfocused, TanStack default) | ✅ React-only tile in HeaderTiles.tsx; Streamlit (archived) intentionally skipped |
| Chart timeframes (S66: 5m/15m/30m/1h/2h/4h/1D/1W/1M pill row on the chart card — `?tf=` on /api/chart, `charts.tf_frame` behind it: daily CSV for D/W/M, cached yfinance 60m for 1h/2h/4h, Tradier 5m loader for sub-hourly; overlays/RSI/MACD compute per-TF; intraday axes collapse the overnight gap (4h reopens 08:00 — its bins are midnight-anchored); W/M skip rangebreaks (the weekday-holiday diff would misread non-period-end weekdays); event vlines on 1D/1W/1M only; live-bar append 1D-only with the tick's prev_close taken from the daily frame elsewhere; range52 always daily; sub-hourly pills disabled in as-of mode) | ✅ React-only |

**Parity is one-way (S61):** nothing from Streamlit is missing, but React now EXCEEDS it
visually — the S61 readability pass made sections visual-first (gauge percentile bars,
two-sided balance bars, range/level strips, a sector-rotation RRG quadrant scatter, and a
merged UPCOMING EVENTS timeline replacing the catalysts + macro tables), with every
original table/factor list preserved inside "details" expanders. These are React-only
extras (`src/components/viz.tsx` + section rewiring); the Streamlit app intentionally does
not get them.

---
*Written for the S60 migration. The Streamlit entries in .claude/launch.json (lens-web /
lens-web-dev) are now legacy but intentionally kept until you retire lens_web.py.*
