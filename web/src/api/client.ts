// Typed fetchers for the LENS API. Always relative "/api/..." URLs — the Vite dev proxy
// (vite.config.ts) forwards them to FastAPI on :8000; in prod both share one origin.

import type {
  AhRead, ChartResponse, Flags, IvHistoryResponse, ProjectionResponse, ReportBundle,
} from './types'

export async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${url} → HTTP ${res.status}`)
  return res.json()
}

export function fetchTickers(): Promise<{ tickers: string[] }> {
  return getJson('/api/tickers')
}

/** Extended-hours print (S64 fix). Safe to poll unconditionally — the server short-circuits to
 *  null during regular hours, so the client never needs its own session clock. */
export function fetchAfterhours(ticker: string): Promise<{ ah: AhRead | null }> {
  return getJson(`/api/afterhours/${encodeURIComponent(ticker)}`)
}

/** Level projections repriced at an arbitrary price (S70 custom-price stepper). Server-side on
 *  purpose — Black-Scholes lives in modules/levelproj.py and is never duplicated here, so the
 *  stepper cannot drift from the table above it. Cheap: no chain fetch, no regenerate. */
export function fetchProjection(
  ticker: string, price: number, date?: string | null,
): Promise<ProjectionResponse> {
  const q = new URLSearchParams({ price: String(price) })
  if (date) q.set('date', date)   // S71 dated leg — what the wait costs in theta
  return getJson(`/api/project/${encodeURIComponent(ticker)}?${q}`)
}

/** Query string for the report flags — omits defaults so URLs stay short/shareable. */
export function flagsToParams(flags: Flags): URLSearchParams {
  const p = new URLSearchParams()
  for (const k of ['vol', 'call', 'gex', 'squeeze', 'insider', 'street', 'movers', 'geo', 'live', 'ltf', 'short'] as const) {
    if (flags[k]) p.set(k, '1')
  }
  if (flags.pc_oi !== 'off') p.set('pc_oi', flags.pc_oi)
  if (flags.thesis) p.set('thesis', flags.thesis)
  if (flags.level) p.set('level', String(flags.level))
  if (flags.as_of) p.set('as_of', flags.as_of)
  return p
}

export function fetchReport(ticker: string, flags: Flags, force = false): Promise<ReportBundle> {
  const p = flagsToParams(flags)
  if (force) p.set('force', '1')
  const qs = p.toString()
  return getJson(`/api/report/${encodeURIComponent(ticker)}${qs ? `?${qs}` : ''}`)
}

export interface ChartOpts {
  asOf?: string | null
  start?: string | null
  live?: boolean
  tf?: string // chart timeframe (S66): 5m 15m 30m 1h 2h 4h 1D 1W 1M — default 1D
  overlays: string[] // tokens: ma20 ma50 ma200 ema9 bb volume rsi macd pline vp gex
  aspects: string[] // vol-profile aspects when "vp" is on
}

export function fetchChart(ticker: string, opts: ChartOpts): Promise<ChartResponse> {
  const p = new URLSearchParams({ overlays: opts.overlays.join(',') })
  if (opts.aspects.length) p.set('aspects', opts.aspects.join(','))
  if (opts.asOf) p.set('as_of', opts.asOf)
  if (opts.start) p.set('start', opts.start)
  if (opts.live) p.set('live', '1')
  if (opts.tf && opts.tf !== '1D') p.set('tf', opts.tf)
  return getJson(`/api/chart/${encodeURIComponent(ticker)}?${p}`)
}

export function fetchIvHistory(ticker: string, asOf?: string | null): Promise<IvHistoryResponse> {
  const p = asOf ? `?asof=${asOf}` : ''
  return getJson(`/api/iv_history/${encodeURIComponent(ticker)}${p}`)
}
