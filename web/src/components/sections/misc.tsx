// SECTOR ROTATION (RRG quadrant scatter), UPCOMING EVENTS (merged catalysts/macro/earnings
// timeline), THESIS CHECK, notes — ports of the same-named sec_* renderers, visual-first
// since S61 (tables fold into expanders, nothing dropped).
import type { CSSProperties } from 'react'
import type { Payload, PlotlyFig } from '../../api/types'
import { AMBER, BLUE, FAINT, GRAY, GREEN, GRID, MUTED, RED, hexToRgba } from '../../utils/colors'
import { DARK_LAYOUT, SPOT_GOLD } from '../../utils/plotly'
import { Caption, Collapsible, DataTable, FactorColumns, Sec, Warning } from '../shared'
import { BalanceBar, TimelineStrip, type TimelineEvent } from '../viz'
import Plot from '../Plot'

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

/** RRG-style quadrant scatter: x = 63d RS (the ranking horizon), y = 20d RS (recent
 *  momentum) — quadrant signs then match the tag definitions exactly. */
function rrgFig(rows: SectorRow[], own?: string | null): PlotlyFig | null {
  const pts = rows.filter((r): r is SectorRow & { rel_63d: number } => r.rel_63d != null)
  if (!pts.length) return null
  const maxAbs = Math.max(...pts.map((r) => Math.max(Math.abs(r.rel_63d), Math.abs(r.rel_20d))))
  const R = Math.max(0.02, maxAbs * 1.2)
  // 'in line' is _quadrant's 5th tag (both horizons inside the ±0.5% dead band) — without
  // its own trace those sectors would silently vanish from the scatter
  const data = [...Object.keys(TAG_COLOR), 'in line']
    .map((tag) => {
      const sub = pts.filter((r) => r.tag === tag)
      const color = TAG_COLOR[tag] ?? GRAY
      return {
        type: 'scatter', mode: 'markers+text', name: tag,
        x: sub.map((r) => r.rel_63d), y: sub.map((r) => r.rel_20d),
        text: sub.map((r) => (own && r.sym === own ? `► ${r.sym}` : r.sym)),
        textposition: 'top center',
        textfont: { size: 10.5, color },
        marker: {
          size: sub.map((r) => (own && r.sym === own ? 12 : 9)),
          color,
          line: { width: sub.map((r) => (own && r.sym === own ? 2 : 0)), color: SPOT_GOLD },
        },
        customdata: sub.map((r) => [r.name, r.tag]),
        hovertemplate: '<b>%{customdata[0]}</b><br>63d %{x:+.1%} · 20d %{y:+.1%} · %{customdata[1]}<extra></extra>',
      }
    })
    .filter((t) => t.x.length)
  const quad = (x0: number, x1: number, y0: number, y1: number, fill: string) => ({
    type: 'rect', x0, x1, y0, y1, line: { width: 0 }, fillcolor: fill, layer: 'below',
  })
  return {
    data,
    layout: {
      ...DARK_LAYOUT, height: 380, showlegend: false,
      margin: { l: 10, r: 10, t: 18, b: 10 },
      xaxis: { title: { text: 'RS vs SPY — 63d', font: { size: 11 } }, tickformat: '+.0%', range: [-R, R], zeroline: false },
      yaxis: { title: { text: '20d', font: { size: 11 } }, tickformat: '+.0%', range: [-R, R], zeroline: false },
      shapes: [
        quad(0, R, 0, R, hexToRgba(GREEN, 0.05)),
        quad(-R, 0, 0, R, hexToRgba(BLUE, 0.05)),
        quad(0, R, -R, 0, hexToRgba(AMBER, 0.05)),
        quad(-R, 0, -R, 0, hexToRgba(RED, 0.05)),
        // the ±0.5% flat band the table's tint also uses — inside it, RS is noise.
        // NB a point flat on ONE axis is tagged by the other axis's sign (_quadrant),
        // so its marker color can differ from the quadrant tint it sits in — inherent
        // to overlaying a hard tag on a continuous scatter; these stripes are the cue
        { type: 'rect', x0: -0.005, x1: 0.005, y0: -R, y1: R, line: { width: 0 }, fillcolor: hexToRgba(GRAY, 0.06), layer: 'below' },
        { type: 'rect', x0: -R, x1: R, y0: -0.005, y1: 0.005, line: { width: 0 }, fillcolor: hexToRgba(GRAY, 0.06), layer: 'below' },
        { type: 'line', x0: 0, x1: 0, y0: -R, y1: R, line: { width: 0.8, color: GRID } },
        { type: 'line', x0: -R, x1: R, y0: 0, y1: 0, line: { width: 0.8, color: GRID } },
      ],
      annotations: ([
        ['leading', 0.99, 0.99, 'right', 'top'],
        ['improving', 0.01, 0.99, 'left', 'top'],
        ['weakening', 0.99, 0.01, 'right', 'bottom'],
        ['lagging', 0.01, 0.01, 'left', 'bottom'],
      ] as const).map(([tag, ax, ay, xa, ya]) => ({
        xref: 'paper', yref: 'paper', x: ax, y: ay, xanchor: xa, yanchor: ya,
        text: tag, showarrow: false, font: { size: 10, color: TAG_COLOR[tag] }, opacity: 0.8,
      })),
    },
  }
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
  const fig = rrgFig(rows, own)
  return (
    <>
      <Sec title="SECTOR ROTATION  (RS vs SPY, ranked by 63d)" />
      {fig && <Plot fig={fig} />}
      {ownRow && (
        <Caption>
          · {String(p.ticker ?? '')} sector: {own} — rank {ownRow.rank}/{rows.length}, {ownRow.tag}
        </Caption>
      )}
      <Collapsible title="sector table (RS vs SPY, ranked by 63d)" defaultOpen={!fig}>
        <DataTable
          rows={data}
          rowStyle={(r) => (own && r._r.sym === own
            ? { backgroundColor: hexToRgba(BLUE, 0.12) } : undefined)}
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
        {hasTop && (
          <Caption>
            top performers = 63d ABSOLUTE return among the sector's ~10 largest constituents
            (Yahoo classification) — biggest names, not full membership
          </Caption>
        )}
      </Collapsible>
    </>
  )
}

// ── UPCOMING EVENTS (S61: catalysts + macro + earnings + ex-div on one timeline) ──
const TIER1 = new Set(['FOMC', 'CPI', 'NFP', 'PCE'])
const EVENTS_HORIZON = 30

interface EarnLike { date?: string | null; days?: number | null }
interface ExdLike extends EarnLike { est?: boolean }

/** Mirrors SecEvents' render-vs-null decision — the nav must not link a section that
 *  renders nothing (e.g. earnings 60d out, no catalysts, macro cache empty). Keep in
 *  sync with the null-check at the top of SecEvents' return. */
export function hasUpcomingEvents(p: Payload): boolean {
  const cats = (p.cats as unknown[] | null) ?? []
  if (cats.length) return true // even beyond-horizon catalysts render (the table)
  const earn = p.earn as EarnLike | null
  const exd = p.exd as ExdLike | null
  if (earn?.days != null && earn.days <= EVENTS_HORIZON) return true
  if (exd?.days != null && exd.days <= EVENTS_HORIZON) return true
  const macro = (p.macro_events as Record<string, [string | null, number | null]> | null) ?? {}
  for (const [name, [d, days]] of Object.entries(macro)) {
    if (d == null || days == null) continue
    if (days <= (TIER1.has(name) ? EVENTS_HORIZON : 10)) return true
  }
  return false
}

export function SecEvents({ p }: { p: Payload }) {
  const cats = (p.cats as [string, number, string, string][] | null) ?? []
  const macro = (p.macro_events as Record<string, [string | null, number | null]> | null) ?? {}
  const earn = p.earn as EarnLike | null
  const exd = p.exd as ExdLike | null

  const events: TimelineEvent[] = []
  let beyond = 0
  let beyondCats = 0
  for (const [d, days, typ, desc] of cats) {
    if (days == null) continue
    if (days > EVENTS_HORIZON) { beyond += 1; beyondCats += 1; continue }
    events.push({ label: typ, days, date: d, color: RED, title: desc })
  }
  for (const [name, [d, days]] of Object.entries(macro)) {
    if (d == null || days == null) continue
    const tier1 = TIER1.has(name)
    if (days > (tier1 ? EVENTS_HORIZON : 10)) {
      if (tier1) beyond += 1
      continue
    }
    events.push({
      label: name, days, date: String(d).slice(0, 10),
      color: tier1 ? MUTED : FAINT,
    })
  }
  if (earn?.days != null && earn.days <= EVENTS_HORIZON) {
    events.push({ label: 'earnings', days: earn.days, date: earn.date ?? undefined, color: AMBER })
  } else if (earn?.days != null) beyond += 1
  if (exd?.days != null && exd.days <= EVENTS_HORIZON) {
    events.push({ label: `ex-div${exd.est ? '~' : ''}`, days: exd.days, date: exd.date ?? undefined, color: GRAY })
  }

  const macroSoon = Object.entries(macro)
    // days >= 0: the timeline drops already-released dates, the table must match
    .filter(([, [d, days]]) => d != null && days != null && days >= 0 && days <= 10)
    .map(([name, [d, days]]) => ({ name, date: String(d).slice(0, 10), days: days! }))
    .sort((a, b) => a.days - b.days)

  if (!events.length && !cats.length && !macroSoon.length) return null
  return (
    <>
      <Sec title={`UPCOMING EVENTS (next ${EVENTS_HORIZON}d)`} />
      <TimelineStrip events={events} horizon={EVENTS_HORIZON} />
      {/* only the catalysts table lists beyond-horizon dates — don't promise tables for
          a far-out earnings/FOMC that no table here shows */}
      {beyond > 0 && (
        <Caption>
          +{beyond} further out{beyondCats > 0 ? ' (catalysts table shows all dates)' : ''}
        </Caption>
      )}
      {!!cats.length && (
        <Collapsible title="catalysts table (catalysts.csv)">
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
        </Collapsible>
      )}
      {!!macroSoon.length && (
        <Collapsible title="macro releases (next 10d)">
          <DataTable
            rows={macroSoon.map((s) => ({ release: s.name, date: s.date, days: String(s.days) }))}
            columns={[
              { key: 'release', header: 'Release' }, { key: 'date', header: 'Date' },
              { key: 'days', header: 'Days' },
            ]}
          />
        </Collapsible>
      )}
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
  const nC = confirm?.length ?? 0
  const nX = contra?.length ?? 0
  return (
    <>
      <Sec title={`THESIS CHECK — you are ${thesis.toUpperCase()}${level ? ` (level ${level})` : ''}`} />
      <BalanceBar left={nC} right={nX} leftLabel="confirmations" rightLabel="contradictions"
        leftColor={GREEN} rightColor={RED} />
      <Collapsible title={`detail — ✓ ${nC} confirmations · ✗ ${nX} contradictions`}>
        <FactorColumns columns={[
          { title: `CONFIRMATIONS (${nC})`, items: confirm?.length ? confirm : ['— none'], color: GREEN, marker: '✓' },
          { title: `CONTRADICTIONS (${nX})`, items: contra?.length ? contra : ['— none'], color: RED, marker: '✗' },
        ]} />
      </Collapsible>
      {blind.map((b, i) => <Warning key={i}>blind spot: {b}</Warning>)}
    </>
  )
}

export function SecNotes({ p }: { p: Payload }) {
  const notes = p.notes as string[] | null
  if (!notes?.length) return null
  return <>{notes.map((n, i) => <Caption key={i}>note: {n}</Caption>)}</>
}
