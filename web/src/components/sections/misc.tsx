// SECTOR ROTATION (RRG quadrant scatter), UPCOMING EVENTS (merged catalysts/macro/earnings
// timeline), THESIS CHECK, notes — ports of the same-named sec_* renderers, visual-first
// since S61 (tables fold into expanders, nothing dropped).
import type { CSSProperties } from 'react'
import type { Payload, PlotlyFig } from '../../api/types'
import { AMBER, BLUE, FAINT, GRAY, GREEN, GRID, INTRADAY_TFS, MUTED, RED, hexToRgba } from '../../utils/colors'
import { DARK_LAYOUT, SPOT_GOLD } from '../../utils/plotly'
import { Caption, Collapsible, DataTable, FactorColumns, Sec, Sparkline, Warning } from '../shared'
import { BalanceBar, PctBar, TimelineStrip, type TimelineEvent } from '../viz'
import Plot from '../Plot'

const pctS = (v: number) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`

// mirror the CLI ±0.5% noise band (shared by SecBreadth + SecSectors)
const rsStyle = (v: number | null | undefined): CSSProperties | undefined =>
  v == null || Math.abs(v) <= 0.005 ? undefined
    : { color: v > 0 ? GREEN : RED, fontWeight: 600 }

// ── MARKET BREADTH (S67) ─────────────────────────────────────────────────────
interface BreadthPair {
  rel_20d?: number | null
  rel_63d?: number | null
  pct?: number | null
  tag?: string | null
  spark?: number[] | null
  cap_off_high?: number | null
  div_state?: string | null
  div_desc?: string | null
}
interface Breadth {
  pairs?: Record<string, BreadthPair> | null
  participation?: Record<string, BreadthPair> | null
  ticker_ew?: { sym: string; label?: string | null; rs_20d?: number | null; rs_63d?: number | null } | null
}
const BREADTH_TAG_COLOR: Record<string, string> = { 'broad-led': GREEN, narrow: RED }

export function SecBreadth({ p }: { p: Payload }) {
  const b = p.breadth as Breadth | null
  const pairs = Object.entries(b?.pairs ?? {})
  const part = Object.entries(b?.participation ?? {})
  if (!pairs.length && !part.length) return null
  const rows = [
    ...pairs.map(([lbl, d]) => ({ lbl, d, isPart: false })),
    ...part.map(([lbl, d]) => ({ lbl, d, isPart: true })),
  ].map((r) => ({
    pair: r.isPart ? `${r.lbl} (small-cap participation)` : r.lbl,
    d20: r.d.rel_20d != null ? pctS(r.d.rel_20d) : '—',
    d63: r.d.rel_63d != null ? pctS(r.d.rel_63d) : '—',
    pct: '', spark: '',
    tag: r.d.tag ?? '—',
    _d: r.d,
  }))
  // divergence lines for the equal-weight pairs only (participation is a different read)
  const divs = pairs.filter(([, d]) => d.div_state && d.div_state !== 'neutral' && d.div_desc)
  const te = b?.ticker_ew
  const teVals = [te?.rs_20d, te?.rs_63d].filter((v): v is number => v != null)
  const teVerdict = teVals.length
    ? (teVals.every((v) => v > 0) ? 'beating the average stock'
      : teVals.every((v) => v < 0) ? 'lagging the average stock'
        : 'mixed vs the average stock')
    : null
  return (
    <>
      <Sec title="MARKET BREADTH  (equal-weight vs cap-weight)" />
      <DataTable
        rows={rows}
        columns={[
          { key: 'pair', header: 'Pair' },
          { key: 'd20', header: '20d', style: (r) => rsStyle(r._d.rel_20d) },
          { key: 'd63', header: '63d', style: (r) => rsStyle(r._d.rel_63d) },
          { key: 'pct', header: 'Spread percentile', cell: (r) => <PctBar pct={r._d.pct} /> },
          { key: 'spark', header: '20d spread (1y)', cell: (r) => <Sparkline values={r._d.spark ?? []} /> },
          { key: 'tag', header: 'Tag', style: (r) => ({ color: BREADTH_TAG_COLOR[r._d.tag ?? ''] ?? GRAY }) },
        ]}
      />
      {divs.map(([lbl, d]) => {
        const cap = lbl.split('−').pop()
        const off = d.cap_off_high != null
          ? `${Math.abs(d.cap_off_high * 100).toFixed(1)}% off its 52w high` : 'n/a'
        const line = `${cap} ${off} — ${(d.div_state ?? '').toUpperCase()}: ${d.div_desc}`
        return d.div_state === 'narrowing'
          ? <Warning key={lbl}>{line}</Warning>
          : <Caption key={lbl}>· {line}</Caption>
      })}
      {te && teVerdict && (
        <Caption>
          · {String(p.ticker ?? '')} vs {te.sym}{te.label ? ` (${te.label})` : ''}:{' '}
          {[te.rs_20d != null ? `${pctS(te.rs_20d)} 20d` : null,
            te.rs_63d != null ? `${pctS(te.rs_63d)} 63d` : null]
            .filter(Boolean).join(' / ')} — {teVerdict}
        </Caption>
      )}
      <Caption>
        context, not a signal — narrow breadth is fragility, not a sell trigger;
        IWM−SPY reads small-cap participation, not equal weighting
      </Caption>
    </>
  )
}

// ── SECTOR ROTATION ──────────────────────────────────────────────────────────
interface SectorRow {
  sym: string
  name: string
  rel_20d: number
  rel_63d?: number | null
  tag: string
  rank: number
  ew_20d?: number | null // S67 — equal-weight twin minus cap-weight sector, 20d
  ew_tag?: string | null // broad / narrow / mixed (absent on stale pre-S67 caches)
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
  const hasEw = rows.some((r) => r.ew_20d != null)
  const data = rows.map((r) => ({
    sector: `${own && r.sym === own ? '► ' : ''}${r.sym} ${r.name}`,
    d20: pctS(r.rel_20d),
    d63: r.rel_63d != null ? pctS(r.rel_63d) : '—',
    ew: r.ew_20d != null ? pctS(r.ew_20d) : '—',
    tag: r.ew_tag ? `${r.tag} · ${r.ew_tag}` : r.tag,
    top: hasTop ? topTxt(top[r.sym]) : '',
    _r: r,
  }))
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
            ...(hasEw
              ? [{ key: 'ew', header: 'EW−cap 20d',
                   style: (r: typeof data[number]) => rsStyle(r._r.ew_20d) }]
              : []),
            { key: 'tag', header: 'Tag', style: (r) => ({ color: TAG_COLOR[r._r.tag] ?? GRAY }) },
            ...(hasTop
              ? [{ key: 'top', header: 'Top performers (63d)',
                   style: () => ({ whiteSpace: 'normal' as const }) }]
              : []),
          ]}
        />
        {hasEw && (
          <Caption>
            EW−cap = 20d equal-weight (RSP*) minus cap-weight sector return —
            narrow = mega-cap-driven inside the sector
          </Caption>
        )}
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

interface EarnLike { date?: string | null; days?: number | null; est?: boolean }
interface ExdLike extends EarnLike {}

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
    // S74: est = cadence-estimated date (yfinance has no future date) — the ex-div '~' convention
    events.push({ label: `earnings${earn.est ? '~' : ''}`, days: earn.days, date: earn.date ?? undefined, color: AMBER })
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
// mirrors modules/shortside.py S21_CONTRA_PREFIXES — a bearish thesis must not read S21
// contrarian-BUY conditions (VIX stress, backwardation) as clean short confirmations (S65)
const S21_PREFIXES = ['VIX stress regime', 'term backwardation']
const isS21 = (f: string) => S21_PREFIXES.some((pre) => f.startsWith(pre))

export function SecThesis({ p }: { p: Payload }) {
  const thesis = p.thesis as string | null
  if (!thesis) return null
  const risk = (p.risk ?? {}) as { rally?: string[]; drawdown?: string[] }
  const level = p.level as number | null
  const rawConfirm = thesis === 'bullish' ? risk.rally : risk.drawdown
  const nS21 = thesis === 'bearish' ? (rawConfirm ?? []).filter(isS21).length : 0
  const confirm = thesis === 'bearish'
    ? (rawConfirm ?? []).map((f) => isS21(f)
      ? `${f}  ⚠ S21: historically contrarian-BUY — weak short evidence` : f)
    : rawConfirm
  const contra = thesis === 'bullish' ? risk.drawdown : risk.rally
  const userLevel = (p.ladder as {
    user_level?: { price: number; dist_pct: number; side: string; confluence?: string[] } | null
  } | null)?.user_level
  const summary = (p.summary ?? {}) as { conflict?: string }
  const reads = (p.reads ?? {}) as Record<string, { _vol?: { unconfirmed?: boolean } | null }>
  const blind: string[] = []
  if (summary.conflict) blind.push(summary.conflict)
  for (const tf of Object.keys(reads)) {
    if (INTRADAY_TFS.includes(tf)) continue      // entry-timing frames are display-only (S63)
    if (reads[tf]._vol?.unconfirmed) blind.push(`${tf} move is on falling volume (unconfirmed)`)
  }
  const nC = confirm?.length ?? 0
  const nX = contra?.length ?? 0
  return (
    <>
      <Sec title={`THESIS CHECK — you are ${thesis.toUpperCase()}${level ? ` (level ${level})` : ''}`} />
      {userLevel && (
        <Caption>
          your level {userLevel.price}: {userLevel.dist_pct >= 0 ? '+' : ''}
          {(userLevel.dist_pct * 100).toFixed(1)}% {userLevel.side} spot —{' '}
          {userLevel.confluence?.length
            ? `confluence with ${userLevel.confluence.join(' · ')}`
            : 'no other known level nearby'}
        </Caption>
      )}
      <BalanceBar left={nC} right={nX} leftLabel="confirmations" rightLabel="contradictions"
        leftColor={GREEN} rightColor={RED} />
      {nS21 > 0 && (
        <Warning>
          {nS21} of {nC} confirmations are S21 contrarian-buy conditions — treat as bounce
          fuel, not short confirmation
        </Warning>
      )}
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
  return (
    <>
      {/* S65 — a real header so the sidebar nav can anchor here */}
      <Sec title="NOTES" />
      {notes.map((n, i) => <Caption key={i}>note: {n}</Caption>)}
    </>
  )
}
