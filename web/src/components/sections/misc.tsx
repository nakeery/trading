// SECTOR ROTATION, KNOWN CATALYSTS, MACRO (next 10d), THESIS CHECK, notes — ports of the
// same-named sec_* renderers.
import type { CSSProperties } from 'react'
import type { Payload } from '../../api/types'
import { AMBER, BLUE, GRAY, GREEN, RED } from '../../utils/colors'
import { Bullets, Caption, DataTable, Sec, Warning } from '../shared'

const pctS = (v: number) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`

// ── SECTOR ROTATION ──────────────────────────────────────────────────────────
interface SectorRow {
  sym: string
  name: string
  rel_20d: number
  rel_63d?: number | null
  tag: string
  rank: number
}
interface Mover { sym: string; r63?: number | null; r20?: number | null }
interface Sectors {
  rows?: SectorRow[]
  own?: string | null
  top?: Record<string, Mover[]> | null
}

const TAG_COLOR: Record<string, string> = {
  leading: GREEN, improving: BLUE, weakening: AMBER, lagging: RED,
}

export function SecSectors({ p }: { p: Payload }) {
  const sec = p.sectors as Sectors | null
  if (!sec?.rows?.length) return null
  const { own } = sec
  const rows = sec.rows
  const top = sec.top ?? {}
  const hasTop = Object.keys(top).length > 0
  const topTxt = (lst?: Mover[]) => {
    if (!lst?.length) return '—'
    return lst.map((m) => {
      const v = m.r63 ?? m.r20
      return v != null ? `${m.sym} ${pctS(v)}` : m.sym
    }).join(' · ')
  }
  const data = rows.map((r) => ({
    sector: `${own && r.sym === own ? '► ' : ''}${r.sym} ${r.name}`,
    d20: pctS(r.rel_20d),
    d63: r.rel_63d != null ? pctS(r.rel_63d) : '—',
    tag: r.tag,
    top: hasTop ? topTxt(top[r.sym]) : '',
    _r: r,
  }))
  const rsStyle = (v: number | null | undefined): CSSProperties | undefined =>
    v == null || Math.abs(v) <= 0.005 ? undefined // mirror the CLI ±0.5% noise band
      : { color: v > 0 ? GREEN : RED, fontWeight: 600 }
  const ownRow = own ? rows.find((r) => r.sym === own) : null
  return (
    <>
      <Sec title="SECTOR ROTATION  (RS vs SPY, ranked by 63d)" />
      <DataTable
        rows={data}
        rowStyle={(r) => (own && r._r.sym === own
          ? { backgroundColor: 'rgba(78,163,216,0.12)' } : undefined)}
        columns={[
          { key: 'sector', header: 'Sector' },
          { key: 'd20', header: '20d', style: (r) => rsStyle(r._r.rel_20d) },
          { key: 'd63', header: '63d', style: (r) => rsStyle(r._r.rel_63d) },
          { key: 'tag', header: 'Tag', style: (r) => ({ color: TAG_COLOR[r._r.tag] ?? GRAY }) },
          ...(hasTop
            ? [{ key: 'top', header: 'Top performers (63d)',
                 style: () => ({ whiteSpace: 'normal' as const }) }]
            : []),
        ]}
      />
      {ownRow && (
        <Caption>
          · {String(p.ticker ?? '')} sector: {own} — rank {ownRow.rank}/{rows.length}, {ownRow.tag}
        </Caption>
      )}
      {hasTop && (
        <Caption>
          top performers = 63d ABSOLUTE return among the sector's ~10 largest constituents
          (Yahoo classification) — biggest names, not full membership
        </Caption>
      )}
    </>
  )
}

// ── KNOWN CATALYSTS ──────────────────────────────────────────────────────────
export function SecCatalysts({ p }: { p: Payload }) {
  const cats = p.cats as [string, number, string, string][] | null
  if (!cats?.length) return null
  return (
    <>
      <Sec title="KNOWN CATALYSTS (catalysts.csv)" />
      <DataTable
        rows={cats.map(([d, days, typ, desc]) => ({
          date: d, days: String(days), type: typ, desc,
        }))}
        columns={[
          { key: 'date', header: 'Date' }, { key: 'days', header: 'Days' },
          { key: 'type', header: 'Type' },
          { key: 'desc', header: 'Description', style: () => ({ whiteSpace: 'normal' }) },
        ]}
      />
    </>
  )
}

// ── MACRO (next 10d) ─────────────────────────────────────────────────────────
export function SecMacro({ p }: { p: Payload }) {
  const ev = p.macro_events as Record<string, [string | null, number | null]> | null
  if (!ev) return null
  const soon = Object.entries(ev)
    .filter(([, [d, days]]) => d != null && days != null && days <= 10)
    .map(([name, [d, days]]) => ({ name, date: String(d).slice(0, 10), days: days! }))
    .sort((a, b) => a.days - b.days)
  if (!soon.length) return null
  return (
    <>
      <Sec title="MACRO (next 10d)" />
      <DataTable
        rows={soon.map((s) => ({ release: s.name, date: s.date, days: String(s.days) }))}
        columns={[
          { key: 'release', header: 'Release' }, { key: 'date', header: 'Date' },
          { key: 'days', header: 'Days' },
        ]}
      />
    </>
  )
}

// ── THESIS CHECK ─────────────────────────────────────────────────────────────
export function SecThesis({ p }: { p: Payload }) {
  const thesis = p.thesis as string | null
  if (!thesis) return null
  const risk = (p.risk ?? {}) as { rally?: string[]; drawdown?: string[] }
  const level = p.level as number | null
  const confirm = thesis === 'bullish' ? risk.rally : risk.drawdown
  const contra = thesis === 'bullish' ? risk.drawdown : risk.rally
  const summary = (p.summary ?? {}) as { conflict?: string }
  const reads = (p.reads ?? {}) as Record<string, { _vol?: { unconfirmed?: boolean } | null }>
  const blind: string[] = []
  if (summary.conflict) blind.push(summary.conflict)
  for (const tf of Object.keys(reads)) {
    if (reads[tf]._vol?.unconfirmed) blind.push(`${tf} move is on falling volume (unconfirmed)`)
  }
  return (
    <>
      <Sec title={`THESIS CHECK — you are ${thesis.toUpperCase()}${level ? ` (level ${level})` : ''}`} />
      <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 320 }}>
          <div style={{ color: GREEN, fontWeight: 600 }}>CONFIRMATIONS ({confirm?.length ?? 0})</div>
          <Bullets items={confirm?.length ? confirm : ['— none']} marker="✓" />
        </div>
        <div style={{ flex: 1, minWidth: 320 }}>
          <div style={{ color: RED, fontWeight: 600 }}>CONTRADICTIONS ({contra?.length ?? 0})</div>
          <Bullets items={contra?.length ? contra : ['— none']} marker="✗" />
        </div>
      </div>
      {blind.map((b, i) => <Warning key={i}>blind spot: {b}</Warning>)}
    </>
  )
}

export function SecNotes({ p }: { p: Payload }) {
  const notes = p.notes as string[] | null
  if (!notes?.length) return null
  return <>{notes.map((n, i) => <Caption key={i}>note: {n}</Caption>)}</>
}
