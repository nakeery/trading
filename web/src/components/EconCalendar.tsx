// Economic calendar (S51/S52): two-month Mon–Fri grid of FRED release chips — tier-colored,
// linked to the FRED graph of the headline series, headline print shown once it's out.
// Zero network server-side; the refresh button is the only network path (FRED key needed).
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getJson } from '../api/client'
import { AMBER, BLUE, BLUEGRAY, hexToRgba } from '../utils/colors'
import { Caption, Collapsible } from './shared'

interface EconEvent {
  date: string
  series: string
  tier: number
  url: string | null
  result: string | null
  release_name: string
}
interface Calendar {
  events: EconEvent[]
  coverage: Record<string, string | null>
  age_days: number | null
  months: { year: number; month: number }[]
  today: string
  grid_end: string
}

const TIER_STYLE: Record<number, { bg: string; fg: string }> = {
  1: { bg: hexToRgba(AMBER, 0.18), fg: AMBER },   // Tier 1 — amber (FOMC/CPI/NFP/PCE)
  2: { bg: hexToRgba(BLUE, 0.15), fg: BLUEGRAY }, // Tier 2 — blue-gray
}

const MONTH_NAME = ['', 'January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December']

function Chip({ ev }: { ev: EconEvent }) {
  const s = TIER_STYLE[ev.tier] ?? TIER_STYLE[2]
  const chip = (
    <div
      title={`${ev.release_name} — ${ev.result ?? 'scheduled'}`}
      style={{
        background: s.bg, color: s.fg, borderRadius: 4, fontSize: '0.7em',
        padding: '0 3px', marginTop: 2, textAlign: 'center', overflow: 'hidden',
      }}
    >
      {ev.series}
      {ev.result && (
        <div style={{ color: 'var(--text)', fontSize: '0.92em', fontWeight: 400 }}>{ev.result}</div>
      )}
    </div>
  )
  return ev.url
    ? <a href={ev.url} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>{chip}</a>
    : chip
}

function MonthGrid({ year, month, byDay, today }: {
  year: number
  month: number
  byDay: Map<string, EconEvent[]>
  today: string
}) {
  // Mon–Fri weeks (releases never land on weekends)
  const first = new Date(Date.UTC(year, month - 1, 1))
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate()
  const weeks: (number | null)[][] = []
  let week: (number | null)[] = []
  // pad to Monday of the first week — but NOT for Sat/Sun-start months (their first
  // weekday IS Monday; a full-width null pad rendered a leading all-blank week row)
  const startDow = (first.getUTCDay() + 6) % 7 // 0 = Monday
  if (startDow < 5) for (let i = 0; i < startDow; i++) week.push(null)
  for (let day = 1; day <= daysInMonth; day++) {
    const dow = (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7
    if (dow >= 5) continue // skip weekends
    if (dow === 0 && week.length) {
      weeks.push(week)
      week = []
    }
    while (week.length < dow) week.push(null)
    week.push(day)
  }
  if (week.length) weeks.push(week)
  return (
    <div style={{ flex: 1, minWidth: 320 }}>
      <div style={{ color: 'var(--text)', fontSize: '0.88em', margin: '2px 0 4px' }}>
        {MONTH_NAME[month]} {year}
      </div>
      <table style={{ borderCollapse: 'collapse', width: '100%', tableLayout: 'fixed' }}>
        <thead>
          <tr>
            {['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].map((d) => (
              <th key={d} style={{ color: 'var(--muted)', fontSize: '0.7em', fontWeight: 400, padding: 2 }}>
                {d}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((w, wi) => (
            <tr key={wi}>
              {[0, 1, 2, 3, 4].map((di) => {
                const day = w[di]
                if (!day) return <td key={di} style={{ border: '1px solid transparent' }} />
                const iso = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
                return (
                  <td key={di} style={{
                    border: iso === today ? '1.5px solid var(--yellow)' : '1px solid var(--border)',
                    verticalAlign: 'top', padding: 3, height: 54,
                  }}>
                    <div style={{ color: 'var(--muted)', fontSize: '0.7em' }}>{day}</div>
                    {(byDay.get(iso) ?? []).map((ev, i) => <Chip key={i} ev={ev} />)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function EconCalendar() {
  const qc = useQueryClient()
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const q = useQuery({
    queryKey: ['econ_calendar'],
    queryFn: async () =>
      (await getJson<{ calendar: Calendar | null }>('/api/econ_calendar')).calendar,
    staleTime: 10 * 60_000,
  })
  const cal = q.data
  const refresh = async () => {
    setRefreshing(true)
    try {
      const d = await getJson<{ refresh: { status: string; message: string } | null }>(
        '/api/econ_calendar?refresh=1')
      setRefreshMsg(d.refresh ? `${d.refresh.status}: ${d.refresh.message}` : null)
      qc.invalidateQueries({ queryKey: ['econ_calendar'] })
    } catch (e) {
      setRefreshMsg(`refresh failed: ${String(e)}`)
    } finally {
      setRefreshing(false)
    }
  }
  const byDay = new Map<string, EconEvent[]>()
  for (const ev of cal?.events ?? []) {
    if (!byDay.has(ev.date)) byDay.set(ev.date, [])
    byDay.get(ev.date)!.push(ev)
  }
  const short = Object.entries(cal?.coverage ?? {})
    .filter(([, v]) => v == null || (cal && v < cal.grid_end))
    .map(([k, v]) => `${k}: ${v ?? 'no data'}`)
    .sort()
  return (
    <Collapsible title="📅 economic calendar — FRED release dates">
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <button onClick={refresh} disabled={refreshing}>
          {refreshing ? 'refreshing…' : '↻ refresh from FRED'}
        </button>
        {cal?.age_days != null && (
          <Caption>
            cache refreshed {cal.age_days.toFixed(1)}d ago · amber = Tier 1 (FOMC/CPI/NFP/PCE),
            blue = Tier 2 · chips link to the FRED graph of the headline series; past chips
            show the headline print · the price chart marks Tier-1 dates ≤30d
          </Caption>
        )}
      </div>
      {refreshMsg && <Caption>{refreshMsg}</Caption>}
      {cal == null && !q.isLoading && (
        <Caption>econ calendar unavailable (module import / cache read failed)</Caption>
      )}
      {cal && !cal.events.length && (
        <Caption>
          no release dates in the two-month window — the cache has likely gone stale; refresh
          from FRED (needs $env:FRED_API_KEY, weekly cadence)
        </Caption>
      )}
      {cal && (
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 6 }}>
          {cal.months.map((m) => (
            <MonthGrid key={`${m.year}-${m.month}`} year={m.year} month={m.month}
              byDay={byDay} today={cal.today} />
          ))}
        </div>
      )}
      {short.length > 0 && (
        <Caption>
          series whose forward coverage ends inside the grid — {short.join(' · ')}
        </Caption>
      )}
    </Collapsible>
  )
}
