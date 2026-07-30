// Core report sections (print order): MARKET BACKDROP, MULTI-TIMEFRAME, DIVERGENCES,
// VOLUME PROFILE, RALLY vs DRAWDOWN, SETUP CHECK — ports of the same-named sec_* renderers
// in lens_web_sections.py, each mirroring its None/empty guard.
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'

import { fetchProjection } from '../../api/client'
import type { Payload } from '../../api/types'
import {
  AMBER, ARROW, BLUE, BLUEGRAY, GRAY, GREEN, HEAT_DEAD, INK, INTRADAY_TFS, OB, RED,
  heatHex, hexToRgba, rsiHex,
} from '../../utils/colors'
import { Caption, Collapsible, DataTable, FactorColumns, Metric, MetricRow, Net, Pill, Sec, Warning } from '../shared'
import { BalanceBar, RangeStrip, TallyBar, type StripMarker } from '../viz'
import { SPOT_GOLD } from '../../utils/plotly'

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

// S65 — known segment prefixes get a faint bold group label inside the chip so the eye can
// find "fut" or "COT" in the wrapped row; unknown prefixes render unchanged (robust to new
// segments). Order mirrors build_backdrop.
const BACKDROP_GROUPS = ['SPY', 'fut', 'breadth(20d)', 'F&G', 'COT lev-funds', 'sent', 'VIX regime']

export function SecBackdrop({ p }: { p: Payload }) {
  const b = p.backdrop as string | null
  if (!b) return null
  const segs = b.split('  |  ').map((s) => s.trim()).filter(Boolean)
  return (
    <>
      <Sec title="MARKET BACKDROP" />
      <div style={{ lineHeight: 2.1 }}>
        {segs.map((s, i) => {
          const g = BACKDROP_GROUPS.find((pre) => s.startsWith(pre))
          const rest = g ? s.slice(g.length).replace(/^[:\s]+/, '') : s
          return (
            <span key={i} style={{
              border: '1px solid var(--border)', borderRadius: 8, padding: '2px 9px',
              marginRight: 6, color: INK, fontSize: '0.9em', whiteSpace: 'nowrap',
              display: 'inline-block',
            }}>
              {g && (
                <span style={{
                  color: 'var(--muted)', fontWeight: 700, fontSize: '0.85em',
                  textTransform: 'uppercase', letterSpacing: 0.4, marginRight: 5,
                }}>
                  {g.replace('(20d)', '')}
                </span>
              )}
              {rest}
            </span>
          )
        })}
      </div>
    </>
  )
}

export function SecMultiTf({ p }: { p: Payload }) {
  const reads = (p.reads ?? {}) as Record<string, TfRead>
  const summary = (p.summary ?? {}) as Summary
  const tfs = Object.keys(reads)
  if (!tfs.length) return null

  // half-scale per heat column: max |value − neutral| − dead across the frames. Computed PER
  // BLOCK (S63, mirrors lens.print_report): a 5m bar's RVOL/ΔVol% swings dwarf a monthly's, so
  // one shared scale would wash every trend row toward neutral the moment ltf is on.
  const halfScale = (block: string[], key: keyof VolRead, neutral: number, dead: number) => {
    const vals = block.map((tf) => reads[tf]._vol?.[key] as number | null | undefined)
      .filter((x): x is number => x != null)
    const m = Math.max(...vals.map((x) => Math.abs(x - neutral) - dead), -Infinity)
    return m > 1e-12 ? m : null
  }
  const scales = (block: string[]) => ({
    dp: halfScale(block, 'price_chg_10', 0, HEAT_DEAD.price_chg_10),
    dv: halfScale(block, 'vol_trend_10', 0, HEAT_DEAD.vol_trend_10),
    rv: halfScale(block, 'rvol', 1, HEAT_DEAD.rvol),
  })
  const hs = {
    trend: scales(tfs.filter((tf) => !INTRADAY_TFS.includes(tf))),
    entry: scales(tfs.filter((tf) => INTRADAY_TFS.includes(tf))),
  }
  const firstEntry = tfs.find((tf) => INTRADAY_TFS.includes(tf))

  const rows = tfs.map((tf) => {
    const r = reads[tf]
    const v = r._vol ?? {}
    const { dp: dpHs, dv: dvHs, rv: rvHs } = hs[INTRADAY_TFS.includes(tf) ? 'entry' : 'trend']
    return {
      tf: r._partial ? `${tf}*` : tf,
      _sep: tf === firstEntry,
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

  // S65 — the 2-second alignment read before the 9-column table (trend frames only)
  const alignRow = tfs.filter((tf) => !INTRADAY_TFS.includes(tf)).map((tf) => ({
    tf, trend: reads[tf].trend ?? '',
  }))
  return (
    <>
      <Sec title="MULTI-TIMEFRAME  (longest → shortest)" />
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', margin: '2px 0 8px', fontSize: 15 }}>
        {alignRow.map(({ tf, trend }) => (
          <span key={tf} style={{
            color: { up: GREEN, down: RED, mixed: AMBER }[trend] ?? 'var(--muted)',
            fontWeight: 600,
          }}>
            {tf} {trend === 'up' ? '↑' : trend === 'down' ? '↓' : '~'}
          </span>
        ))}
      </div>
      <DataTable
        rows={rows}
        divider={(r) => (r._sep
          ? 'entry timing · intraday only — excluded from alignment, risk & setup check'
          : null)}
        columns={[
          { key: 'tf', header: 'TF' },
          { key: 'trend', header: 'Trend', style: heat('trend') },
          { key: 'rsi', header: 'RSI', style: heat('rsi') },
          { key: 'stoch', header: 'Stoch' },
          { key: 'macd', header: 'MACD' },
          { key: 'rvol', header: 'RVOL', style: heat('rvol'), align: 'right' },
          { key: 'dprc', header: 'ΔPrc%', style: heat('dprc'), align: 'right' },
          { key: 'dvol', header: 'ΔVol%', style: heat('dvol'), align: 'right' },
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
            {INTRADAY_TFS.includes(tf) && (
              <span style={{ color: 'var(--faint)' }}>   (intraday — not a risk factor)</span>
            )}
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
        <div style={{ alignSelf: 'center' }}><Pill text={locTxt} color={locCol} /></div>
      </MetricRow>
      {(() => {
        // level strip: value area band + POC/price markers, HVN shelves, LVN gaps (S61)
        const lvns = profile.lvns ?? []
        const all = [profile.va_low, profile.va_high, poc, price, ...hvns, ...lvns]
          .filter((v): v is number => v != null && isFinite(v))
        if (!all.length) return null
        const span = Math.max(...all) - Math.min(...all) || 1
        const [lo, hi] = [Math.min(...all) - span * 0.03, Math.max(...all) + span * 0.03]
        const markers: StripMarker[] = [
          ...(poc != null ? [{ value: poc, label: 'POC', color: AMBER, shape: 'line' as const }] : []),
          ...(price != null ? [{ value: price, label: fmt2(price), color: SPOT_GOLD, shape: 'tri' as const }] : []),
          ...hvns.map((h) => ({ value: h, color: BLUEGRAY, shape: 'dot' as const })),
          ...lvns.map((l) => ({ value: l, shape: 'tick' as const })),
        ]
        return (
          <>
            <RangeStrip lo={lo} hi={hi} width={520}
              bands={[{ from: profile.va_low, to: profile.va_high, color: hexToRgba(BLUE, 0.15) }]}
              markers={markers} />
            <Caption>
              blue band = value area · ▲ = price · dots = HVN shelves · ticks = LVN gaps ·
              drawn on the chart via the "vol profile" toggle above
            </Caption>
          </>
        )
      })()}
      <Collapsible title="levels detail (HVN shelves · LVN gaps)">
        <Caption>HVN shelves — above price: {lv(above)}  ·  below price: {lv(below)}</Caption>
        <Caption>
          LVN gaps: {lv(profile.lvns ?? [])}   ·   drawn on the chart via the "vol profile"
          toggle above
        </Caption>
      </Collapsible>
    </>
  )
}

// ── PRICE LADDER (S65) — every known level, one distance-sorted view ─────────
interface LadderRow {
  price: number
  dist_pct: number
  tags: string[]
  side: 'above' | 'below'
  zone: number | null
}
// S68 — level projections (all math server-side in modules/levelproj.py; render only)
interface ProjLeg {
  value: number
  pnl_mid_pct: number
  pnl_ask_pct?: number | null
  t_rem_days?: number
  expired?: boolean   // S71 dated leg — the hold date is past this contract's expiry
}
interface ProjRow {
  src: 'quoted' | 'modeled'
  kind?: 'atm' | 'otm' | 'other'
  expiry?: string | null
  dte: number
  strike: number
  moneyness?: number | null   // S69 — strike/spot − 1, labels the strike selector
  delta?: number | null
  iv?: number | null
  iv_src?: string
  entry_mid?: number
  entry_ask?: number | null
  entry_modeled?: boolean   // stale quote — entry re-modeled at current spot
  premium?: number
  instant: ProjLeg
  paced?: ProjLeg | null
  dated?: ProjLeg | null   // S71 — value if the price gets there on the chosen date
}
interface ProjTarget {
  price: number; dist_pct: number; kind: string; label?: string
  travel_sessions?: number | null
  contracts: ProjRow[]
  synthetic: ProjRow[]
}
interface QuoteMeta {
  as_of_str?: string
  age_str?: string
  stale?: boolean
  remodeled?: boolean          // S70 — entry re-modeled at current spot (stale OR spot drift)
  spot_drift?: number | null   // quote's spot / report's spot − 1
  quote_spot?: number | null
}
interface Projections {
  targets: ProjTarget[]
  quote_meta?: QuoteMeta | null
  pace_note?: string
}
interface Ladder {
  spot: number
  levels: LadderRow[]
  nearest_support?: LadderRow | null
  nearest_resistance?: LadderRow | null
  user_level?: {
    price: number; dist_pct: number; side: string
    zone: number | null; confluence?: string[]
  } | null
  projections?: Projections | null
}
const LADDER_MAX_SIDE = 6   // mirrors modules/levels.py MAX_SIDE

const pnlS = (v: number | null | undefined) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(0)}%`
const pnlStyle = (v: number | null | undefined): CSSProperties | undefined =>
  v == null ? undefined : { color: v >= 0 ? GREEN : RED, fontWeight: 600 }

/** S69 — expiry/strike multi-select. Every offered row is ALREADY repriced server-side
 *  (modules/levelproj.py), so this only filters — no refetch, no Black-Scholes in TS. */
function Picker({ label, options, selected, onChange }: {
  label: string
  options: { key: string; text: string }[]
  selected: Set<string>
  onChange: (s: Set<string>) => void
}) {
  if (options.length <= 1) return null
  const toggle = (k: string) => {
    const next = new Set(selected)
    if (next.has(k)) next.delete(k)
    else next.add(k)
    if (next.size) onChange(next)          // never allow an empty table
  }
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', margin: '4px 0' }}>
      <span style={{ color: 'var(--muted)', fontSize: 11.5, minWidth: 46 }}>{label}</span>
      {options.map((o) => {
        const on = selected.has(o.key)
        return (
          <button
            key={o.key}
            onClick={() => toggle(o.key)}
            style={{
              cursor: 'pointer', fontSize: 11.5, padding: '2px 8px', borderRadius: 999,
              border: `1px solid ${on ? BLUE : 'var(--border)'}`,
              background: on ? hexToRgba(BLUE, 0.18) : 'transparent',
              color: on ? 'var(--text)' : 'var(--muted)',
            }}
          >
            {o.text}
          </button>
        )
      })}
    </div>
  )
}

/** S70 — custom-price stepper. Steps are absolute dollars; the default is scaled to the
 *  ticker's price so a $16 name and a $680 name both get a sane first nudge. */
const STEP_CHOICES = [0.5, 1, 5, 10]
const defaultStep = (spot: number) =>
  STEP_CHOICES.reduce((best, s) =>
    (Math.abs(s - spot * 0.005) < Math.abs(best - spot * 0.005) ? s : best), STEP_CHOICES[0])

// S71 — hold-until date. Local (not UTC) so an evening in the US doesn't offer "tomorrow"
// as today's date, the same reason utils/dates.localToday exists for the as-of panel.
const isoInDays = (days: number) => {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const isoToday = () => isoInDays(0)
const DATE_PRESETS: [string, number][] = [['1w', 7], ['1m', 30], ['3m', 91], ['6m', 182]]

/** "What if it goes to X?" — an arbitrary price, repriced through the SAME server-side math as
 *  the fixed targets (GET /api/project). Deliberately not computed in the browser: duplicating
 *  Black-Scholes in TS would let this disagree with the table above it. */
function CustomPrice({ ticker, spot, render }: {
  ticker: string
  spot: number
  render: (t: ProjTarget, dateLabel?: string | null) => ReactNode
}) {
  const [step, setStep] = useState(() => defaultStep(spot))
  const [price, setPrice] = useState(() => Number(spot.toFixed(2)))
  const [onDate, setOnDate] = useState<string>('')       // '' = no dated leg
  const [debounced, setDebounced] = useState(price)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(price), 250)   // arrows fire fast; batch them
    return () => clearTimeout(id)
  }, [price])
  // a regenerate (new spot) re-seeds the box, but only while the user hasn't moved it
  const [touched, setTouched] = useState(false)
  useEffect(() => {
    if (!touched) {
      setPrice(Number(spot.toFixed(2)))
      setDebounced(Number(spot.toFixed(2)))
    }
  }, [spot, touched])

  const q = useQuery({
    queryKey: ['project', ticker, debounced, onDate],
    queryFn: () => fetchProjection(ticker, debounced, onDate || null),
    enabled: !!ticker && debounced > 0,
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,        // keep the old table while the next one lands
    retry: false,
  })
  const target = (q.data?.target ?? null) as ProjTarget | null
  const holdDays = q.data?.hold_days ?? null
  const bump = (dir: number) => {
    setTouched(true)
    // round to cents — float addition of 0.1 steps otherwise drifts (16.9 + 0.1 = 17.000000000000004)
    setPrice((p) => Math.max(0.01, Number((p + dir * step).toFixed(2))))
  }
  const btn: CSSProperties = {
    cursor: 'pointer', border: '1px solid var(--border)', background: 'transparent',
    color: 'var(--text)', borderRadius: 'var(--r-sm, 4px)', width: 26, height: 26,
    fontSize: 14, lineHeight: 1,
  }
  return (
    <div style={{ margin: '8px 0 2px' }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ color: 'var(--muted)', fontSize: 11.5, minWidth: 46 }}>price</span>
        <button style={btn} onClick={() => bump(-1)} aria-label="decrease price">−</button>
        <input
          type="number"
          value={price}
          step={step}
          min={0.01}
          onChange={(e) => {
            setTouched(true)
            const v = Number(e.target.value)
            if (Number.isFinite(v)) setPrice(v)
          }}
          style={{
            width: 96, textAlign: 'right', padding: '3px 6px', fontSize: 13,
            background: 'var(--bg)', color: 'var(--text)',
            border: '1px solid var(--border)', borderRadius: 'var(--r-sm, 4px)',
          }}
        />
        <button style={btn} onClick={() => bump(1)} aria-label="increase price">+</button>
        <span style={{ color: 'var(--faint)', fontSize: 11.5 }}>
          {pct1(price / spot - 1)} vs spot {fmt2(spot)}
        </span>
        {price !== Number(spot.toFixed(2)) && (
          <button
            style={{ ...btn, width: 'auto', padding: '0 8px', fontSize: 11.5 }}
            onClick={() => { setTouched(false); setPrice(Number(spot.toFixed(2))) }}
          >
            reset
          </button>
        )}
      </div>
      <Picker
        label="step"
        options={STEP_CHOICES.map((s) => ({ key: String(s), text: String(s) }))}
        selected={new Set([String(step)])}
        onChange={(sel) => {
          const next = [...sel].map(Number).find((n) => n !== step)
          if (next != null) setStep(next)
        }}
      />
      {/* S71 — hold-until date. Native <input type="date"> is the dropdown calendar; the
          presets cover the common horizons without opening it. */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', margin: '4px 0' }}>
        <span style={{ color: 'var(--muted)', fontSize: 11.5, minWidth: 46 }}>on date</span>
        <input
          type="date"
          value={onDate}
          min={isoToday()}
          onChange={(e) => setOnDate(e.target.value)}
          style={{
            padding: '3px 6px', fontSize: 12.5, background: 'var(--bg)', color: 'var(--text)',
            border: '1px solid var(--border)', borderRadius: 'var(--r-sm, 4px)',
            colorScheme: 'dark',
          }}
        />
        {DATE_PRESETS.map(([label, days]) => (
          <button
            key={label}
            style={{ ...btn, width: 'auto', padding: '0 8px', fontSize: 11.5 }}
            onClick={() => setOnDate(isoInDays(days))}
          >
            {label}
          </button>
        ))}
        {onDate && (
          <>
            <button
              style={{ ...btn, width: 'auto', padding: '0 8px', fontSize: 11.5 }}
              onClick={() => setOnDate('')}
            >
              clear
            </button>
            {holdDays != null && (
              <span style={{ color: 'var(--faint)', fontSize: 11.5 }}>
                {holdDays === 0 ? 'today' : `${holdDays} calendar day${holdDays === 1 ? '' : 's'} out`}
              </span>
            )}
          </>
        )}
      </div>
      {target ? render(target, onDate || null) : (
        <Caption>
          {q.isError
            ? 'custom price unavailable — generate the report for this ticker first'
            : '…'}
        </Caption>
      )}
    </div>
  )
}

/** S68 — "what would a move there look like": travel estimate + long-call repricing per
 *  key target. Purely additive under the ladder; absent projections render nothing.
 *  S69: four quoted tenors (~45d/~90d/~6mo/~1yr) and a per-expiry strike ladder, surfaced
 *  through the two pickers; defaults to the ATM row of every tenor (the CLI's view). */
function LadderProjections({ proj, ticker, spot }: {
  proj: Projections
  ticker?: string
  spot?: number | null
}) {
  const qm = proj.quote_meta
  // S70: entries are re-modeled when the cache is session-stale OR when the spot it was quoted
  // at has drifted from the report's — say which, so "entry ≈" is never unexplained
  const why = !(qm?.remodeled || qm?.stale) ? ''
    : qm.stale ? ' — STALE, entries re-modeled at current spot'
      : qm.spot_drift != null
        ? ` — quoted at ${fmt2(qm.quote_spot ?? 0)} (${pct1(qm.spot_drift)} vs spot), entries re-modeled at current spot`
        : ' — entries re-modeled at current spot'
  const src = qm ? `quoted contracts as of ${qm.as_of_str ?? '?'}${why}` : 'modeled, not a quote'
  // YY-MM-DD (slice 2, not 5): a 2027 LEAP is ambiguous without the year
  const expKey = (c: ProjRow) => (c.expiry ?? '') || `${c.dte.toFixed(0)}d`
  const expText = (c: ProjRow) => `${(c.expiry ?? '').slice(2) || `${c.dte.toFixed(0)}d`} · ${c.dte.toFixed(0)}d`
  const contractName = (c: ProjRow) => (c.src === 'quoted'
    ? `${(c.expiry ?? '').slice(2) || `${c.dte.toFixed(0)}d`} ${c.dte.toFixed(0)}d ${c.strike}C`
      + `${c.kind === 'atm' ? ' ATM' : c.kind === 'otm' ? ' OTMΔ' : ''}`
    : `~${c.dte.toFixed(0)}d ATM call (modeled${c.iv != null ? `, IV ${(c.iv * 100).toFixed(1)}% ${c.iv_src ?? ''}` : ''})`)

  // every quoted expiry / strike across all targets — the pickers are shared, so switching
  // target doesn't reset the selection
  const all = proj.targets.flatMap((t) => t.contracts)
  const expOpts = [...new Map(all.map((c) => [expKey(c), expText(c)])).entries()]
    .map(([key, text]) => ({ key, text, dte: all.find((c) => expKey(c) === key)?.dte ?? 0 }))
    .sort((a, b) => a.dte - b.dte)
  const strikeOpts = [...new Set(all.map((c) => c.strike))].sort((a, b) => a - b)
    .map((s) => {
      const c = all.find((x) => x.strike === s)
      const mny = c?.moneyness
      return { key: String(s), text: mny != null ? `${s} (${pct1(mny)})` : String(s) }
    })
  const [expSel, setExpSel] = useState<Set<string> | null>(null)
  const [strikeSel, setStrikeSel] = useState<Set<string> | null>(null)
  // defaults: every tenor, ATM strike only — recomputed from the payload, so a regenerate
  // (new spot → new ATM strike) doesn't leave a stale selection pinned
  const defExp = new Set(expOpts.filter((o) => o.dte >= 150).map((o) => o.key))   // ~6mo+ (ATM) only
  const defStrikes = new Set(all.filter((c) => c.kind === 'atm').map((c) => String(c.strike)))
  const exps = expSel ?? defExp
  const strikes = strikeSel ?? (defStrikes.size ? defStrikes : new Set(strikeOpts.map((o) => o.key)))

  // one target → header line + contract table. Shared by the ladder's fixed targets and the
  // custom-price stepper, so the two can never render or filter differently.
  const renderTarget = (t: ProjTarget, dateLabel?: string | null) => {
    let rows = t.contracts.length ? t.contracts : t.synthetic
    if (t.contracts.length) {
      rows = rows.filter((c) => exps.has(expKey(c)) && strikes.has(String(c.strike)))
    }
    const ts = t.travel_sessions
    // S71 — the dated leg only exists when a hold date was chosen, so its columns appear only
    // then (an always-present "—" column would just be noise on the fixed targets)
    const hasDated = !!dateLabel && rows.some((c) => c.dated)
    return (
      <div key={`${t.kind}-${t.price}`} style={{ margin: '6px 0' }}>
        <div style={{ fontSize: 13.5 }}>
          <span style={{ color: t.dist_pct >= 0 ? RED : GREEN, fontWeight: 600 }}>
            → {t.kind} {fmt2(t.price)} ({pct1(t.dist_pct)})
          </span>
          {t.label && <span style={{ color: 'var(--muted)' }}> · {t.label}</span>}
          {ts != null && (
            <span style={{ color: 'var(--faint)' }}>
              {' '}· ~{ts.toFixed(0)} session{ts >= 1.5 ? 's' : ''} at recent pace
            </span>
          )}
        </div>
        {rows.length ? (
          <DataTable
            rows={rows.map((c) => ({
              contract: contractName(c),
              delta: c.delta != null ? c.delta.toFixed(2) : '—',
              entry: c.src === 'quoted'
                ? (c.entry_modeled ? `entry ≈ ${fmt2(c.entry_mid ?? 0)}` : `mid ${fmt2(c.entry_mid ?? 0)}`)
                : `prem ≈ ${fmt2(c.premium ?? 0)}`,
              instant: fmt2(c.instant.value),
              paced: c.paced ? fmt2(c.paced.value) : '—',
              pnl: `${pnlS(c.instant.pnl_mid_pct)} / ${pnlS(c.paced?.pnl_mid_pct)}`,
              ask: c.instant.pnl_ask_pct != null
                ? `${pnlS(c.instant.pnl_ask_pct)} / ${pnlS(c.paced?.pnl_ask_pct)}` : '—',
              dated: c.dated ? (c.dated.expired ? `${fmt2(c.dated.value)} exp` : fmt2(c.dated.value)) : '—',
              datedPnl: c.dated ? pnlS(c.dated.pnl_mid_pct) : '—',
              _c: c,
            }))}
            columns={[
              { key: 'contract', header: 'Contract' },
              { key: 'delta', header: 'Δ', align: 'right' },
              { key: 'entry', header: 'Entry' },
              { key: 'instant', header: 'At level (instant)', align: 'right' },
              { key: 'paced', header: 'At level (paced)', align: 'right' },
              ...(hasDated ? [
                { key: 'dated', header: `On ${dateLabel}`, align: 'right' as const },
                { key: 'datedPnl', header: 'P&L on date', align: 'right' as const,
                  style: (r: { _c: ProjRow }) => pnlStyle(r._c.dated?.pnl_mid_pct) },
              ] : []),
              { key: 'pnl', header: 'P&L mid (inst/paced)', align: 'right',
                style: (r) => pnlStyle(r._c.instant.pnl_mid_pct) },
              { key: 'ask', header: 'P&L at ask', align: 'right',
                style: (r) => pnlStyle(r._c.instant.pnl_ask_pct) },
            ]}
          />
        ) : (
          <Caption>— (no IV available to model a call)</Caption>
        )}
      </div>
    )
  }

  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 4 }}>
        level projections ({src} · IV held constant)
      </div>
      {all.length > 0 && (
        <div style={{ margin: '2px 0 8px' }}>
          <Picker label="expiry" options={expOpts} selected={exps} onChange={setExpSel} />
          <Picker label="strike" options={strikeOpts} selected={strikes} onChange={setStrikeSel} />
        </div>
      )}
      {ticker && spot != null && (
        <CustomPrice ticker={ticker} spot={spot} render={renderTarget} />
      )}
      {/* wrapped, not passed by reference — .map would feed the index into dateLabel */}
      {proj.targets.map((t) => renderTarget(t))}
      <Caption>
        modeled: IV held constant, no skew/vol-path;{' '}
        {proj.pace_note ?? 'pace = |move| ÷ avg daily move (HV-20)'} — heuristic, not advice
      </Caption>
    </div>
  )
}

export function SecLadder({ p }: { p: Payload }) {
  const lad = p.ladder as Ladder | null
  if (!lad?.levels?.length) return null
  // levels arrive sorted by |dist| — take the nearest per side, then display top-down by price
  const above = lad.levels.filter((r) => r.side === 'above').slice(0, LADDER_MAX_SIDE)
    .sort((a, b) => b.price - a.price)
  const below = lad.levels.filter((r) => r.side === 'below').slice(0, LADDER_MAX_SIDE)
    .sort((a, b) => b.price - a.price)
  const maxDist = Math.max(...[...above, ...below].map((r) => Math.abs(r.dist_pct)), 1e-4)
  const row = (r: LadderRow) => (
    <div key={`${r.price}-${r.tags.join()}`}
      style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0', fontSize: 13.5 }}>
      <span className="num" style={{ width: 52, textAlign: 'right', color: r.side === 'above' ? RED : GREEN }}>
        {pct1(r.dist_pct)}
      </span>
      <span className="num" style={{ width: 78, textAlign: 'right', fontWeight: 600 }}>{fmt2(r.price)}</span>
      <div style={{ flex: '0 0 140px', height: 7, background: 'var(--bg)', borderRadius: 4 }}>
        <div style={{
          width: `${(Math.abs(r.dist_pct) / maxDist) * 100}%`, height: '100%', borderRadius: 4,
          background: hexToRgba(r.side === 'above' ? RED : GREEN, r.zone != null ? 0.7 : 0.3),
        }} />
      </div>
      <span style={{ color: 'var(--muted)' }}>
        {r.tags.join(' · ')}
        {r.zone != null && <span style={{ color: AMBER }}> ◆ confluence</span>}
      </span>
    </div>
  )
  const ul = lad.user_level
  return (
    <>
      <Sec title="PRICE LADDER" />
      {above.map(row)}
      <div className="num" style={{
        borderTop: `1px dashed ${SPOT_GOLD}`, color: SPOT_GOLD, fontSize: 13,
        margin: '3px 0', paddingTop: 1,
      }}>
        spot {fmt2(lad.spot)}
      </div>
      {below.map(row)}
      <Caption>
        {lad.nearest_resistance && `nearest resistance ${fmt2(lad.nearest_resistance.price)} (${pct1(lad.nearest_resistance.dist_pct)})`}
        {lad.nearest_resistance && lad.nearest_support && ' · '}
        {lad.nearest_support && `nearest support ${fmt2(lad.nearest_support.price)} (${pct1(lad.nearest_support.dist_pct)})`}
        {' · ◆ = ≥2 sources within ±0.5%'}
      </Caption>
      {ul && (
        <Caption>
          your level {fmt2(ul.price)}: {pct1(ul.dist_pct)} {ul.side} spot —{' '}
          {ul.confluence?.length ? `confluence with ${ul.confluence.join(' · ')}` : 'no other known level nearby'}
        </Caption>
      )}
      {lad.projections?.targets?.length
        ? <LadderProjections proj={lad.projections} ticker={String(p.ticker ?? '')} spot={lad.spot} />
        : null}
      {lad.levels.length > above.length + below.length && (
        <Collapsible title={`all ${lad.levels.length} levels`}>
          {lad.levels.map(row)}
        </Collapsible>
      )}
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
      <BalanceBar left={risk.drawdown?.length ?? 0} right={risk.rally?.length ?? 0}
        leftLabel="drawdown-risk" rightLabel="rally-favorable" leftColor={RED} rightColor={GREEN} />
      {((risk.drawdown?.length ?? 0) + (risk.rally?.length ?? 0)) > 0 && (
        <Collapsible title={`factor details (${risk.drawdown?.length ?? 0} drawdown · ${risk.rally?.length ?? 0} rally)`}>
          <FactorColumns columns={[
            { title: 'drawdown-risk factors', items: risk.drawdown, color: RED },
            { title: 'rally-favorable factors', items: risk.rally, color: GREEN },
          ]} />
        </Collapsible>
      )}
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
  const marks = rows.map((r) => r.mark)
  return (
    <>
      <Sec title="SETUP CHECK" />
      <Net label="NET" text={setup.net ?? 'n/a'} />
      {/* S65 — the setup score as a segmented tally, not just table rows */}
      <TallyBar segments={[
        { n: marks.filter((m) => m === '✓').length, color: GREEN, label: '✓ pass' },
        { n: marks.filter((m) => m === '–').length, color: GRAY, label: '– flagged' },
        { n: marks.filter((m) => m === '✗').length, color: RED, label: '✗ fail' },
      ]} />
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
