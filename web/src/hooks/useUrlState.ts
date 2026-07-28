// Deep links (S56/S57): ?ticker=QQQ&vol=1&pc_oi=near&asof=2026-03-10&from=2026-01-02
// prefills the controls and auto-runs once; after each successful generate the URL is
// written back so the current view is always shareable/bookmarkable.
import type { Flags, PcOiScope } from '../api/types'
import { DEFAULT_FLAGS } from '../api/types'
import { flagsToParams } from '../api/client'
import { localToday } from '../utils/dates'

const BOOLS = ['vol', 'call', 'gex', 'squeeze', 'insider', 'street', 'movers', 'geo', 'live', 'ltf', 'short'] as const

export interface UrlState {
  ticker: string
  flags: Flags
  chartFrom: string | null
}

/** Read the deep link once (call at mount / initial state). */
export function readUrl(): UrlState {
  const q = new URLSearchParams(window.location.search)
  const flags: Flags = { ...DEFAULT_FLAGS }
  for (const k of BOOLS) if (q.get(k) === '1') flags[k] = true
  const pc = q.get('pc_oi')
  if (pc && ['all', 'near', 'leaps', 'monthly'].includes(pc)) flags.pc_oi = pc as PcOiScope
  // thesis/level round-trip: writeUrl emits both (via flagsToParams) — dropping them here
  // silently reset the bias overlay on every reload/share of the app's own URLs
  const thesis = q.get('thesis')
  if (thesis === 'bullish' || thesis === 'bearish') flags.thesis = thesis
  const level = Number(q.get('level'))
  if (q.get('level') && isFinite(level) && level > 0) flags.level = level
  const asof = q.get('asof')
  if (asof) {
    // clamp to LOCAL today, mirroring the Streamlit guard (UTC "today" is already
    // tomorrow in a US evening — the clamp would admit a phantom session)
    const today = localToday()
    flags.as_of = asof > today ? today : asof
    flags.live = false
  }
  return {
    ticker: (q.get('ticker') ?? '').trim().toUpperCase(),
    flags,
    chartFrom: q.get('from'),
  }
}

/** Write the current view back into the address bar (no navigation). */
export function writeUrl(ticker: string, flags: Flags, chartFrom: string | null) {
  const p = flagsToParams(flags)
  p.set('ticker', ticker)
  if (flags.as_of) p.set('asof', flags.as_of)
  p.delete('as_of') // flagsToParams uses as_of; the public deep-link param is `asof`
  if (chartFrom) p.set('from', chartFrom)
  window.history.replaceState(null, '', `?${p.toString()}`)
}
