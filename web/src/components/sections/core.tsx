// Core report sections (print order): MARKET BACKDROP, MULTI-TIMEFRAME, DIVERGENCES,
// VOLUME PROFILE, RALLY vs DRAWDOWN, SETUP CHECK — ports of the same-named sec_* renderers
// in lens_web_sections.py, each mirroring its None/empty guard.
import type { CSSProperties } from 'react'
import type { Payload } from '../../api/types'
import {
  AMBER, ARROW, BLUE, GRAY, GREEN, HEAT_DEAD, INK, OB, RED,
  heatHex, rsiHex,
} from '../../utils/colors'
import { Bullets, Caption, DataTable, Metric, MetricRow, Net, Pill, Sec, Warning } from '../shared'

// ── payload slices (typed just enough for rendering) ─────────────────────────
interface VolRead {
  ok?: boolean
  rvol?: number | null
  price_chg_10?: number | null
  vol_trend_10?: number | null
  tag?: string | null
  unconfirmed?: boolean
}
interface TfRead {
  trend?: string
  rsi?: number | null
  rsi_state?: string | null
  stoch_state?: string | null
  macd_state?: string | null
  _partial?: boolean
  _vol?: VolRead | null
}
interface Summary {
  synthesis?: string
  rsi_conflict?: string
  conflict?: string
}

const fmt2 = (v: number) => v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const pct1 = (v: number, sign = true) => `${sign && v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`

export function SecBackdrop({ p }: { p: Payload }) {
  const b = p.backdrop as string | null
  if (!b) return null
  const segs = b.split('  |  ').map((s) => s.trim()).filter(Boolean)
  return (
    <>
      <Sec title="MARKET BACKDROP" />
      <div style={{ lineHeight: 2.1 }}>
        {segs.map((s, i) => (
          <span key={i} style={{
            border: '1px solid var(--border)', borderRadius: 8, padding: '2px 9px',
            marginRight: 6, color: INK, fontSize: '0.9em', whiteSpace: 'nowrap',
            display: 'inline-block',
          }}>
            {s}
          </span>
        ))}
      </div>
    </>
  )
}

export function SecMultiTf({ p }: { p: Payload }) {
  const reads = (p.reads ?? {}) as Record<string, TfRead>
  const summary = (p.summary ?? {}) as Summary
  const tfs = Object.keys(reads)
  if (!tfs.length) return null

  // shared half-scale per heat column: max |value − neutral| − dead across the frames
  const halfScale = (key: keyof VolRead, neutral: number, dead: number) => {
    const vals = tfs.map((tf) => reads[tf]._vol?.[key] as number | null | undefined)
      .filter((x): x is number => x != null)
    const m = Math.max(...vals.map((x) => Math.abs(x - neutral) - dead), -Infinity)
    return m > 1e-12 ? m : null
  }
  const dpHs = halfScale('price_chg_10', 0, HEAT_DEAD.price_chg_10)
  const dvHs = halfScale('vol_trend_10', 0, HEAT_DEAD.vol_trend_10)
  const rvHs = halfScale('rvol', 1, HEAT_DEAD.rvol)

  const rows = tfs.map((tf) => {
    const r = reads[tf]
    const v = r._vol ?? {}
    return {
      tf: r._partial ? `${tf}*` : tf,
      trend: ARROW[r.trend ?? ''] ?? '?',
      rsi: r.rsi != null ? `${r.rsi.toFixed(0)} ${OB[r.rsi_state ?? ''] ?? r.rsi_state ?? '—'}` : '—',
      stoch: OB[r.stoch_state ?? ''] ?? r.stoch_state ?? '—',
      macd: r.macd_state ?? '—',
      rvol: v.rvol ? `${v.rvol.toFixed(1)}x` : '—',
      dprc: v.price_chg_10 != null ? pct1(v.price_chg_10) : '—',
      dvol: v.vol_trend_10 != null ? pct1(v.vol_trend_10) : '—',
      voltrend: v.ok ? (v.tag ?? '—') : '—',
      _c: {
        trend: { up: GREEN, down: RED, mixed: AMBER }[r.trend ?? ''] ?? null,
        rsi: rsiHex(r.rsi),
        rvol: heatHex(v.rvol, 1, rvHs, HEAT_DEAD.rvol),
        dprc: heatHex(v.price_chg_10, 0, dpHs, HEAT_DEAD.price_chg_10),
        dvol: heatHex(v.vol_trend_10, 0, dvHs, HEAT_DEAD.vol_trend_10),
      } as Record<string, string | null>,
    }
  })

  const heat = (key: string) => (row: (typeof rows)[number]): CSSProperties | undefined =>
    row._c[key] ? { color: row._c[key]!, fontWeight: 600 } : undefined

  let legend = 'RVOL = latest bar vs 20-bar avg (1.0 = normal) · ΔPrc% = price move over last '
    + '10 bars · ΔVol% = 10-bar change in the 20-bar avg volume → VolTrend'
  if (tfs.some((tf) => reads[tf]._partial)) {
    legend += ' · * in-progress bar — RVOL/ΔVol%/VolTrend use the last completed bar '
      + '(price/RSI/ΔPrc% stay live)'
  }

  return (
    <>
      <Sec title="MULTI-TIMEFRAME  (longest → shortest)" />
      <DataTable
        rows={rows}
        columns={[
          { key: 'tf', header: 'TF' },
          { key: 'trend', header: 'Trend', style: heat('trend') },
          { key: 'rsi', header: 'RSI', style: heat('rsi') },
          { key: 'stoch', header: 'Stoch' },
          { key: 'macd', header: 'MACD' },
          { key: 'rvol', header: 'RVOL', style: heat('rvol') },
          { key: 'dprc', header: 'ΔPrc%', style: heat('dprc') },
          { key: 'dvol', header: 'ΔVol%', style: heat('dvol') },
          { key: 'voltrend', header: 'VolTrend' },
        ]}
      />
      {summary.synthesis && <div style={{ fontWeight: 600, margin: '6px 0' }}>→ {summary.synthesis}</div>}
      {summary.rsi_conflict && <Warning>{summary.rsi_conflict}</Warning>}
      <Caption>{legend}</Caption>
    </>
  )
}

export function SecDivergences({ p }: { p: Payload }) {
  const divs = p.divs as Record<string, [string, string]> | null
  if (!divs || !Object.keys(divs).length) return null
  return (
    <>
      <Sec title="DIVERGENCES" />
      {Object.entries(divs).map(([tf, [kind, why]]) => {
        const c = String(kind).toLowerCase().includes('bull') ? GREEN
          : String(kind).toLowerCase().includes('bear') ? RED : INK
        return (
          <div key={tf}>
            • <b>{tf}</b>: <span style={{ color: c, fontWeight: 600 }}>{String(kind)}</span>
            {' '}— {String(why)}
          </div>
        )
      })}
    </>
  )
}

interface Profile {
  n_bars?: number
  price?: number | null
  poc?: number | null
  va_low: number
  va_high: number
  price_location?: string
  hvns?: number[]
  lvns?: number[]
}

export function SecVolumeProfile({ p }: { p: Payload }) {
  const profile = p.profile as Profile | null
  if (!profile) return null
  const locTxt = {
    in_value: 'inside value', above_value: 'ABOVE value (extended)',
    below_value: 'BELOW value (discount)',
  }[profile.price_location ?? ''] ?? '?'
  const locCol = { in_value: GRAY, above_value: AMBER, below_value: BLUE }[profile.price_location ?? ''] ?? GRAY
  const { price, poc } = profile
  const hvns = profile.hvns ?? []
  const above = hvns.filter((h) => price != null && h > price).sort((a, b) => a - b)
  const below = hvns.filter((h) => price != null && h <= price).sort((a, b) => b - a)
  const lv = (vals: number[]) => vals.length
    ? vals.map((x) => `${fmt2(x)}${poc != null && Math.abs(x - poc) < 1e-6 ? ' (POC)' : ''}`).join('  ')
    : 'none'
  return (
    <>
      <Sec title={`VOLUME PROFILE  (${profile.n_bars ?? '?'} bars)`} />
      <MetricRow>
        <Metric label="POC (fair value)" value={poc != null ? fmt2(poc) : '—'} />
        <Metric label="Value area" value={`${fmt2(profile.va_low)} – ${fmt2(profile.va_high)}`} />
        <div style={{ marginTop: '1.6em' }}><Pill text={locTxt} color={locCol} /></div>
      </MetricRow>
      <Caption>HVN shelves — above price: {lv(above)}  ·  below price: {lv(below)}</Caption>
      <Caption>
        LVN gaps: {lv(profile.lvns ?? [])}   ·   drawn on the chart via the "vol profile"
        toggle above
      </Caption>
    </>
  )
}

interface Risk {
  net?: string
  regime?: { state?: string; label?: string; why?: string[]; note?: string } | null
  drawdown?: string[]
  rally?: string[]
}

export function SecRisk({ p }: { p: Payload }) {
  const risk = p.risk as Risk | null
  if (!risk) return null
  const reg = risk.regime
  return (
    <>
      <Sec title="RALLY vs DRAWDOWN RISK  (current conditions, not a forecast)" />
      <Net label="NET" text={risk.net ?? 'n/a'} />
      {reg && (
        <div style={{ margin: '4px 0' }}>
          <Pill text={reg.label ?? ''} color={reg.state === 'up' ? GREEN : RED} />{' '}
          <span style={{ color: INK }}>{(reg.why ?? []).join(' · ')}</span>
          {reg.note && <Caption>↳ {reg.note}</Caption>}
        </div>
      )}
      <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
        {!!risk.drawdown?.length && (
          <div style={{ flex: 1, minWidth: 320 }}>
            <div style={{ color: RED, fontWeight: 600, marginTop: 6 }}>drawdown-risk factors</div>
            <Bullets items={risk.drawdown} />
          </div>
        )}
        {!!risk.rally?.length && (
          <div style={{ flex: 1, minWidth: 320 }}>
            <div style={{ color: GREEN, fontWeight: 600, marginTop: 6 }}>rally-favorable factors</div>
            <Bullets items={risk.rally} />
          </div>
        )}
      </div>
    </>
  )
}

interface Setup {
  net?: string
  footer?: string
  rows?: [string, string, string][]
}

export function SecSetup({ p }: { p: Payload }) {
  const setup = p.setup as Setup | null
  if (!setup?.rows?.length) return null
  const rows = setup.rows.map(([label, mark, detail]) => ({ mark, label, detail }))
  return (
    <>
      <Sec title="SETUP CHECK" />
      <Net label="NET" text={setup.net ?? 'n/a'} />
      <DataTable
        rows={rows}
        columns={[
          {
            key: 'mark', header: '',
            style: (r) => ({
              color: r.mark === '✓' ? GREEN : r.mark === '✗' ? RED : GRAY, fontWeight: 700,
            }),
          },
          { key: 'label', header: 'Check' },
          { key: 'detail', header: 'Detail', style: () => ({ whiteSpace: 'normal' }) },
        ]}
      />
      {setup.footer && <Caption>{setup.footer}</Caption>}
    </>
  )
}
