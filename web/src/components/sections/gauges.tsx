// Gauge-table sections: OPTIONS & VOL CONTEXT and the GEO backdrop — ports of
// sec_options/sec_geo + the shared _gauge_table (value via the gauge's own format, read
// label, ordinal percentile, inline sparkline when the gauge carries its trailing series).
import type { Payload } from '../../api/types'
import { ordinalPercentile } from '../../utils/colors'
import { Caption, DataTable, Net, Sec, Sparkline } from '../shared'

export interface Gauge {
  group?: string
  name: string
  value: number | null
  fmt: string // python str.format spec, e.g. "{:.2f}" / "{:.1%}"
  label?: string | null
  pct?: number | null
  spark?: number[] | null
}

/** Apply the gauge's python format spec ({:.2f}, {:.1%}, {:+.1%}, {:,.0f}) to its value. */
export function pyFormat(fmt: string, value: number | null): string {
  if (value == null) return '—'
  const m = fmt.match(/\{:([+,]*)\.?(\d*)([f%])?\}/)
  if (!m) return String(value)
  const [, flags, digits, kind] = m
  const d = digits === '' ? (kind === '%' ? 0 : 2) : Number(digits)
  const sign = flags.includes('+') && value >= 0 ? '+' : ''
  if (kind === '%') return `${sign}${(value * 100).toFixed(d)}%`
  const s = flags.includes(',')
    ? value.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
    : value.toFixed(d)
  return `${sign}${s}`
}

export function GaugeTable({ gauges, groups }: { gauges: Gauge[]; groups?: string[] }) {
  const rows = gauges
    .filter((g) => !groups || groups.includes(g.group ?? ''))
    .map((g) => ({
      group: g.group ?? '',
      name: g.name,
      value: pyFormat(g.fmt, g.value),
      read: g.label ?? '',
      pct: g.pct != null ? ordinalPercentile(g.pct, false) : '—',
      spark: g.spark ?? null,
    }))
  if (!rows.length) return null
  const hasSpark = rows.some((r) => r.spark?.length)
  return (
    <DataTable
      rows={rows}
      columns={[
        { key: 'group', header: 'Group' },
        { key: 'name', header: 'Gauge' },
        { key: 'value', header: 'Value' },
        { key: 'read', header: 'Read', style: () => ({ whiteSpace: 'normal' }) },
        { key: 'pct', header: 'Percentile' },
        ...(hasSpark
          ? [{
              key: 'spark', header: '1y',
              cell: (r: (typeof rows)[number]) =>
                r.spark?.length ? <Sparkline values={r.spark} /> : null,
            }]
          : []),
      ]}
    />
  )
}

interface Liq {
  grade: string
  spread_pct: number | null
  oi: number
  as_of_str: string
  stale?: boolean
}

export function SecOptions({ p }: { p: Payload }) {
  const ctx = p.ctx as { gauges?: Gauge[]; regime?: string; net?: string } | null
  const liq = p.liq as Liq | null
  if (!ctx?.gauges?.length) return null
  const spr = liq?.spread_pct != null ? `${(liq.spread_pct * 100).toFixed(1)}%` : 'n/a'
  return (
    <>
      <Sec title={`OPTIONS & VOL CONTEXT  (regime: ${ctx.regime ?? 'n/a'})`} />
      <GaugeTable gauges={ctx.gauges} groups={['OPTIONS', 'VOL', 'MARKET']} />
      {liq && (
        <Caption>
          options liquidity: {liq.grade}  (ATM spread {spr}, OI {liq.oi.toLocaleString()}) —
          as of {liq.as_of_str}{liq.stale ? '  (stale)' : ''}
        </Caption>
      )}
      <Net label="NET" text={ctx.net ?? 'n/a'} />
    </>
  )
}

export function SecGeo({ p }: { p: Payload }) {
  const geo = p.geo as { gauges?: Gauge[]; composite?: string; notes?: string[] } | null
  if (!geo?.gauges?.length) return null
  return (
    <>
      <Sec title="GEOPOLITICAL / CROSS-ASSET BACKDROP  (context, not a prediction)" />
      <GaugeTable gauges={geo.gauges} />
      <Net label="NET" text={geo.composite ?? 'n/a'} />
      {(geo.notes ?? []).map((n, i) => <Caption key={i}>· {n}</Caption>)}
    </>
  )
}
