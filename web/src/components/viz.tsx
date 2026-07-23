// Inline micro-visualizations for the section renderers (S61 readability pass).
// SVG/div-based like Sparkline — NOT per-instance Plotly (a dozen gauge rows × a plotly
// canvas each would be felt; none of these need axes, zoom, or hover). Every component
// returns null (or a '—' placeholder) when its inputs can't render — the sanitizer maps
// NaN → null, so every number here can be null.
//
// Shared axis language (keep new callers consistent):
//   · min/max/tick labels: var(--faint) 11px
//   · the current price/spot marker is ALWAYS a gold ▲ (SPOT_GOLD — the price-line color)
//   · reference levels are 1px vertical lines; shaded bands at ~0.15 alpha
//   · color never carries meaning alone — counts/labels/position always ride along
import type { ReactNode } from 'react'
import { BLUE, GREEN, RED, ordinalPercentile } from '../utils/colors'

const TRACK = '#1a1f29' // the DataTable row-border tone

// ── PctBar — percentile bullet bar ───────────────────────────────────────────
/** 0–1 percentile as a small filled track + ordinal text. Neutral BLUE by default —
 *  a high percentile is not universally "good" (rich IV vs strong breadth). */
export function PctBar({ pct, width = 90, height = 8, color = BLUE, showText = true }: {
  pct: number | null | undefined
  width?: number
  height?: number
  color?: string
  showText?: boolean
}) {
  if (pct == null || !isFinite(pct)) {
    return showText ? <span style={{ color: 'var(--faint)' }}>—</span> : null
  }
  const t = Math.min(1, Math.max(0, pct))
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, whiteSpace: 'nowrap' }}>
      <span style={{
        width, height, background: TRACK, border: '1px solid var(--border)',
        borderRadius: 3, display: 'inline-block', position: 'relative', flexShrink: 0,
      }}>
        <span style={{
          position: 'absolute', left: 0, top: 0, bottom: 0,
          width: `${(t * 100).toFixed(1)}%`, background: color, borderRadius: 2,
          minWidth: t > 0 ? 2 : 0,
        }} />
      </span>
      {showText && <span>{ordinalPercentile(t, false)}</span>}
    </span>
  )
}

// ── BalanceBar — two-sided count tug-of-war ──────────────────────────────────
/** Diverging factor tally: left vs right segments sized by count, with labeled counts
 *  (identity is never color-alone). Zero total → null. */
export function BalanceBar({ left, right, leftLabel, rightLabel,
  leftColor = GREEN, rightColor = RED, width = 320 }: {
  left: number
  right: number
  leftLabel: string
  rightLabel: string
  leftColor?: string
  rightColor?: string
  width?: number
}) {
  const l = Math.max(0, left | 0)
  const r = Math.max(0, right | 0)
  const total = l + r
  if (total === 0) return null
  // proportional split with a 4% floor so a 1-vs-9 side stays visible
  const lFrac = l === 0 ? 0 : r === 0 ? 1 : Math.min(0.96, Math.max(0.04, l / total))
  return (
    <div style={{ maxWidth: width, margin: '6px 0' }}>
      <div style={{ display: 'flex', gap: 2, height: 12 }}>
        {l > 0 && (
          <div style={{
            flexGrow: lFrac, background: leftColor, borderRadius: '3px 0 0 3px',
            minWidth: 4,
          }} />
        )}
        {r > 0 && (
          <div style={{
            flexGrow: 1 - lFrac, background: rightColor,
            borderRadius: l > 0 ? '0 3px 3px 0' : 3, minWidth: 4,
          }} />
        )}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginTop: 2 }}>
        <span style={{ color: leftColor, fontWeight: 600 }}>{l} {leftLabel}</span>
        <span style={{ color: rightColor, fontWeight: 600 }}>{r} {rightLabel}</span>
      </div>
    </div>
  )
}

// ── RangeStrip — horizontal domain with bands + markers ──────────────────────
export interface StripMarker {
  value: number | null | undefined
  label?: string
  color?: string
  /** tri = the gold spot ▲ · line = reference level · dot = shelf · tick = minor level */
  shape?: 'tri' | 'line' | 'dot' | 'tick'
}
export interface StripBand { from: number; to: number; color: string }

const fmtDefault = (v: number) =>
  v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Min→max strip with translucent bands and point markers — the shared read for
 *  "where is X inside this range" (value area, expected move, PT range). */
export function RangeStrip({ lo, hi, bands = [], markers = [], fmt = fmtDefault, width = 420 }: {
  lo: number | null | undefined
  hi: number | null | undefined
  bands?: StripBand[]
  markers?: StripMarker[]
  fmt?: (v: number) => string
  width?: number
}) {
  if (lo == null || hi == null || !isFinite(lo) || !isFinite(hi) || lo >= hi) return null
  const PAD = 6
  const LABEL_H = 13   // label lane above the track
  const TRACK_Y = LABEL_H + 10
  const H = TRACK_Y + 22
  const x = (v: number) => PAD + ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * (width - 2 * PAD)

  const ms = markers
    .filter((m): m is StripMarker & { value: number } => m.value != null && isFinite(m.value))
    .sort((a, b) => a.value - b.value)

  // label collision: walk left→right, drop a labeled marker below the track when its
  // label would overlap the previous one's
  let prevEnd = -Infinity
  const placed = ms.map((m) => {
    if (!m.label) return { ...m, below: false }
    const w = m.label.length * 6.2
    const start = x(m.value) - w / 2
    const below = start < prevEnd + 4
    if (!below) prevEnd = start + w
    return { ...m, below }
  })

  const glyph: ReactNode[] = placed.map((m, i) => {
    const cx = x(m.value)
    const color = m.color ?? 'var(--muted)'
    const clampedLeft = m.value < lo
    const clampedRight = m.value > hi
    const parts: ReactNode[] = []
    if (m.shape === 'tri' || m.shape === undefined) {
      parts.push(<polygon key="p" points={`${cx - 5},${TRACK_Y + 7} ${cx + 5},${TRACK_Y + 7} ${cx},${TRACK_Y - 1}`} fill={color} />)
    } else if (m.shape === 'line') {
      parts.push(<line key="p" x1={cx} x2={cx} y1={TRACK_Y - 8} y2={TRACK_Y + 8} stroke={color} strokeWidth={1.6} />)
    } else if (m.shape === 'dot') {
      parts.push(<circle key="p" cx={cx} cy={TRACK_Y} r={3} fill={color} />)
    } else {
      parts.push(<line key="p" x1={cx} x2={cx} y1={TRACK_Y - 4} y2={TRACK_Y + 4} stroke={color} strokeWidth={1} opacity={0.75} />)
    }
    if (clampedLeft || clampedRight) {
      parts.push(
        <text key="c" x={cx + (clampedLeft ? -8 : 8)} y={TRACK_Y + 4} fontSize={11}
          fill={color} textAnchor="middle">{clampedLeft ? '‹' : '›'}</text>,
      )
    }
    if (m.label) {
      parts.push(
        <text key="t" x={cx} y={m.below ? TRACK_Y + 19 : LABEL_H - 2} fontSize={10.5}
          fill={color} textAnchor="middle">{m.label}</text>,
      )
    }
    return <g key={i}>{parts}</g>
  })

  return (
    <svg width={width} height={H} style={{ display: 'block', margin: '6px 0', maxWidth: '100%' }}>
      <line x1={PAD} x2={width - PAD} y1={TRACK_Y} y2={TRACK_Y} stroke="var(--border)" strokeWidth={1} />
      {bands.map((b, i) => (
        <rect key={i} x={x(b.from)} y={TRACK_Y - 6} width={Math.max(0, x(b.to) - x(b.from))}
          height={12} fill={b.color} rx={2} />
      ))}
      {glyph}
      <text x={PAD} y={H - 2} fontSize={11} fill="var(--faint)" textAnchor="start">{fmt(lo)}</text>
      <text x={width - PAD} y={H - 2} fontSize={11} fill="var(--faint)" textAnchor="end">{fmt(hi)}</text>
    </svg>
  )
}

// ── TimelineStrip — days-until events on one axis ────────────────────────────
export interface TimelineEvent {
  label: string
  days: number
  date?: string
  color: string
  /** longer tooltip (native SVG <title>) — e.g. the catalyst description */
  title?: string
}

/** 0..horizon days-until axis with greedy label lane-packing (stacked lanes instead of
 *  collided labels). Filters to finite 0..horizon; dedupes identical (label, days). */
export function TimelineStrip({ events, horizon = 30, width = 640 }: {
  events: TimelineEvent[]
  horizon?: number
  width?: number
}) {
  const seen = new Set<string>()
  const evs = events
    .filter((e) => e.days != null && isFinite(e.days) && e.days >= 0 && e.days <= horizon)
    .filter((e) => {
      const k = `${e.label}|${e.days}`
      if (seen.has(k)) return false
      seen.add(k)
      return true
    })
    .sort((a, b) => a.days - b.days)
  if (!evs.length) return null

  const PAD = 14
  const x = (d: number) => PAD + (d / horizon) * (width - 2 * PAD)

  // greedy lane packing for the labels (lane 0 sits closest to the axis)
  const laneEnd: number[] = []
  const placed = evs.map((e) => {
    const w = e.label.length * 6.5 + 8
    const start = Math.min(width - PAD - w, Math.max(PAD, x(e.days) - w / 2))
    let lane = laneEnd.findIndex((end) => start > end + 4)
    if (lane === -1) {
      lane = laneEnd.length
      laneEnd.push(start + w)
    } else {
      laneEnd[lane] = start + w
    }
    return { ...e, lane, labelX: start + w / 2 }
  })
  const lanes = laneEnd.length
  const LANE_H = 16
  const axisY = 10 + lanes * LANE_H + 6
  const H = axisY + 20
  const laneY = (lane: number) => 10 + (lanes - 1 - lane) * LANE_H + 10

  const ticks = [0, 7, 14, 21, horizon].filter((t, i, a) => a.indexOf(t) === i && t <= horizon)

  return (
    <svg width={width} height={H} style={{ display: 'block', margin: '6px 0', maxWidth: '100%' }}>
      <line x1={PAD} x2={width - PAD} y1={axisY} y2={axisY} stroke="var(--border)" strokeWidth={1} />
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={axisY - 3} y2={axisY + 3} stroke="var(--border)" strokeWidth={1} />
          <text x={x(t)} y={axisY + 15} fontSize={11} fill="var(--faint)" textAnchor="middle">
            {t === 0 ? 'today' : `+${t}d`}
          </text>
        </g>
      ))}
      {placed.map((e, i) => (
        <g key={i}>
          <title>{`${e.label}${e.date ? ` — ${e.date}` : ''} (${e.days}d)${e.title ? ` · ${e.title}` : ''}`}</title>
          <line x1={x(e.days)} x2={x(e.days)} y1={laneY(e.lane) + 3} y2={axisY - 3}
            stroke={e.color} strokeWidth={0.8} opacity={0.45} />
          <circle cx={x(e.days)} cy={axisY} r={4.5} fill={e.color} />
          <text x={e.labelX} y={laneY(e.lane)} fontSize={10.5} fill={e.color} textAnchor="middle">
            {e.label}
          </text>
        </g>
      ))}
    </svg>
  )
}
