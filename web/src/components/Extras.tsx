// Below-the-sections extras (S50/S53 web-only additions): IV-vs-HV history figure,
// earnings-reaction table, monthly-seasonality grid — ports of the same blocks in
// lens_web.py's display path. All zero-network on the server (CSV reads, cached).
import { useQuery } from '@tanstack/react-query'
import { fetchIvHistory, getJson } from '../api/client'
import type { Payload } from '../api/types'
import { GREEN, RED, rampHex } from '../utils/colors'
import { Caption, Collapsible, DataTable, Sec } from './shared'
import Plot from './Plot'

export function IvHistoryChart({ ticker, asOf }: { ticker: string; asOf?: string | null }) {
  const q = useQuery({
    queryKey: ['ivhist', ticker, asOf],
    queryFn: () => fetchIvHistory(ticker, asOf),
  })
  if (!q.data?.fig) return null // silently skipped for tickers without harvested IV
  return (
    <>
      <Sec title={`IV vs REALIZED VOL — trailing year${asOf ? ` to ${asOf}` : ''}`} />
      <Plot fig={q.data.fig} />
      {q.data.caption && <Caption>{q.data.caption}</Caption>}
    </>
  )
}

interface Reaction {
  date: string
  gap: number | null
  d1: number
  d5: number | null
  pre_iv: number | null
}
interface Reactions {
  rows?: Reaction[] | null
  med_abs_d1?: number
  up?: number
  dn?: number
}

const sPct = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(d)}%`
const upDn = (v: number | null): React.CSSProperties | undefined =>
  v == null ? undefined : { color: v > 0 ? GREEN : RED, fontWeight: 600 }

export function EarningsReactions({ ticker, asOf, payload }: {
  ticker: string
  asOf?: string | null
  payload: Payload
}) {
  const q = useQuery({
    queryKey: ['reactions', ticker, asOf],
    queryFn: () =>
      getJson<Reactions>(`/api/earnings_reactions/${ticker}${asOf ? `?asof=${asOf}` : ''}`),
  })
  const rx = q.data
  if (!rx?.rows?.length) return null
  const em = ((payload.vol as { em?: { pct?: number; dte?: number } } | null)?.em) ?? {}
  let line = `median |print move| ${((rx.med_abs_d1 ?? 0) * 100).toFixed(1)}% · up ${rx.up} / down ${rx.dn}`
  if (em.pct) line += ` · current expected move ±${(em.pct * 100).toFixed(1)}% (~${em.dte ?? '?'}d)`
  return (
    <Collapsible title={`📊 earnings reactions — last ${rx.rows.length} prints`}>
      <DataTable
        rows={rx.rows.map((r) => ({
          print: r.date,
          gap: r.gap != null ? sPct(r.gap) : '—',
          d1: sPct(r.d1),
          d5: r.d5 != null ? sPct(r.d5) : '—',
          iv: r.pre_iv != null ? `${(r.pre_iv * 100).toFixed(0)}%` : '—',
          _r: r,
        }))}
        columns={[
          { key: 'print', header: 'Print' },
          { key: 'gap', header: 'Gap', style: (r) => upDn(r._r.gap) },
          { key: 'd1', header: '1d', style: (r) => upDn(r._r.d1) },
          { key: 'd5', header: '5d', style: (r) => upDn(r._r.d5) },
          { key: 'iv', header: 'pre-print IV' },
        ]}
      />
      <Caption>
        {line} · realized close-to-close moves; the --vol study covers the implied side
        (ramp/crush/straddle P&L)
      </Caption>
    </Collapsible>
  )
}

interface MonthStat {
  n: number
  up: number
  win: number | null
  median: number | null
}
interface Seasonality {
  status: string
  years?: number
  months?: MonthStat[]
  recent?: MonthStat[]
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTH_FULL = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December']

export function SeasonalityGrid({ ticker, asOf }: { ticker: string; asOf?: string | null }) {
  const q = useQuery({
    queryKey: ['seasonality', ticker, asOf],
    queryFn: () =>
      getJson<Seasonality>(`/api/seasonality/${ticker}${asOf ? `?asof=${asOf}` : ''}`),
  })
  const seas = q.data
  if (!seas) return null
  if (seas.status === 'insufficient') {
    // quiet should be visible, not silent (the S58 buzz lesson)
    return (
      <Caption>
        seasonality: only {seas.years?.toFixed(1)}y of history{asOf ? ` through ${asOf}` : ''} —
        monthly base rates need ≥10y (~10 observations per calendar month)
      </Caption>
    )
  }
  if (seas.status !== 'ok' || !seas.months || !seas.recent) return null
  // 0-based; highlights the AS-OF month. Parse the month straight off the ISO string —
  // new Date("YYYY-MM-DD") is UTC midnight, so .getMonth() reads the PREVIOUS month for
  // 1st-of-month as-of dates in any US timezone
  const cur = asOf ? Number(asOf.slice(5, 7)) - 1 : new Date().getMonth()
  const winTxt = (s: MonthStat) => (s.n ? `${s.up}/${s.n}` : '—')
  const medTxt = (s: MonthStat) => (s.median != null ? sPct(s.median) : '—')
  const winStyle = (s: MonthStat): React.CSSProperties | undefined =>
    s.win != null ? { color: rampHex(s.win), fontWeight: 600 } : undefined
  const medStyle = (s: MonthStat): React.CSSProperties | undefined => {
    if (s.median == null) return undefined
    const t = 0.5 + Math.max(-0.5, Math.min(0.5, s.median / 0.08))
    return { color: rampHex(t) }
  }
  const bands: [string, MonthStat[], (s: MonthStat) => string, (s: MonthStat) => React.CSSProperties | undefined][] = [
    [`win (${seas.years?.toFixed(0)}y)`, seas.months, winTxt, winStyle],
    [`median (${seas.years?.toFixed(0)}y)`, seas.months, medTxt, medStyle],
    ['win (10y)', seas.recent, winTxt, winStyle],
    ['median (10y)', seas.recent, medTxt, medStyle],
  ]
  const cs = seas.months[cur]
  const cr = seas.recent[cur]
  return (
    <Collapsible title={`📈 seasonality — monthly base rates over ${seas.years?.toFixed(0)}y (display-only)`}>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13.5 }}>
          <thead>
            <tr>
              <th />
              {MONTHS.map((m, j) => (
                <th key={m} style={{
                  color: 'var(--muted)', fontWeight: 500, padding: '3px 8px',
                  background: j === cur ? 'rgba(232,197,71,0.10)' : undefined,
                }}>{m}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bands.map(([label, stats, txt, style]) => (
              <tr key={label}>
                <td style={{ color: 'var(--muted)', padding: '2px 8px', whiteSpace: 'nowrap' }}>{label}</td>
                {stats.map((s, j) => (
                  <td key={j} style={{
                    padding: '2px 8px', textAlign: 'center',
                    background: j === cur ? 'rgba(232,197,71,0.10)' : undefined,
                    ...style(s),
                  }}>{txt(s)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Caption>
        {MONTH_FULL[cur]} historically: {winTxt(cs)} up, median {medTxt(cs)} (full) ·{' '}
        {winTxt(cr)} up, median {medTxt(cr)} (last 10y — a month strong in both windows is a
        real prior; one that flips is noise) · base rates, NOT edge; stays display-only (S31)
      </Caption>
    </Collapsible>
  )
}
