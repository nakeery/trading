// TypeScript mirror of the API contracts (the gather_report payload subset the M1 UI
// reads, plus the /api/chart and /api/report response shapes). Grows in M2 as the native
// sections land. Python None → null; every number can be null (the sanitizer maps NaN).

export type PcOiScope = 'off' | 'all' | 'near' | 'leaps' | 'monthly'

export interface Flags {
  vol: boolean
  call: boolean
  gex: boolean
  squeeze: boolean
  insider: boolean
  street: boolean
  movers: boolean
  geo: boolean
  live: boolean
  ltf: boolean
  short: boolean
  pc_oi: PcOiScope
  thesis: 'bullish' | 'bearish' | null
  level: number | null
  as_of: string | null // ISO date — S57 backtest mode
}

export const DEFAULT_FLAGS: Flags = {
  vol: false, call: false, gex: false, squeeze: false, insider: false,
  street: false, movers: false, geo: false, live: false, ltf: false, short: false,
  pc_oi: 'off', thesis: null, level: null, as_of: null,
}

export interface LastBar {
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  prev_close: number | null
}

// The payload is large and section-shaped; M1 types only what it touches and keeps the
// rest indexable. M2 narrows section by section.
export interface Payload {
  ticker: string
  as_of: string
  as_of_mode: string | null
  last_bar: LastBar
  live: { applied?: boolean; in_progress?: boolean; hhmm?: string } | null
  // declared explicitly (not left to the index signature) so a rename on either side is a
  // TS error rather than a silently-absent tile
  ah?: AhRead | null
  [section: string]: unknown
}

export interface DiffChanges {
  flips: [string, string, string][]
  regime_flip: [string | null, string | null] | null
  dd_added: string[]
  dd_removed: string[]
  rally_added: string[]
  rally_removed: string[]
  gauge_moves: [string, number, number][]
}

export interface ReportDiff {
  prev_as_of: string | null
  prev_close: number | null
  close: number | null
  changes: DiffChanges | null
}

export interface ReportBundle {
  payload: Payload | null
  preamble: string
  ansi_html: string
  diff: ReportDiff | null
}

// Plotly figure JSON built server-side — opaque to the frontend (never restyle the candle
// traces; the two-axis hollow convention lives in api/charts.py).
export interface PlotlyFig {
  data: object[]
  layout: object
}

// S70 — /api/project envelope (custom-price stepper). `target` carries the same shape as a
// payload projections target; the render-side interfaces live in sections/core.tsx alongside
// the component that consumes them, so this stays an envelope only.
export interface ProjectionResponse {
  target: unknown | null
  quote_meta?: { as_of_str?: string; age_str?: string; stale?: boolean } | null
  pace_note?: string
  on_date?: string | null    // S71 — the held-until date, echoed back
  hold_days?: number | null  // calendar days from today to that date
}

export interface Range52 {
  hi: number
  lo: number
  pos: number
  off_hi: number
}

// S64 extended-hours read — a snapshot on the payload (generate time) plus /api/afterhours,
// which HeaderTiles polls every 30s off-hours. Deliberately NOT on LiveInfo any more: riding
// the live tick coupled it to a miss-counter driven by fetch_live_bar, which always misses
// overnight, so the poll died after ~30s and froze the tile.
export interface AhRead {
  label?: string
  last?: number
  ref?: number
  chg_pct?: number
  hhmm?: string
}

export interface LiveInfo {
  found: boolean
  hhmm?: string
  in_progress?: boolean
  close?: number
  prev_close?: number
  chg?: number
  open?: number
  high?: number
  low?: number
}

export interface ChartResponse {
  fig: PlotlyFig | null
  range52: Range52 | null
  live: LiveInfo | null
  as_of: string
}

export interface IvHistoryResponse {
  fig: PlotlyFig | null
  caption?: string
}
