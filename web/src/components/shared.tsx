// Shared building blocks for the section renderers — the React analogues of
// lens_web_sections.py's _sec/_pill/_net/_bullets/_df/st.metric helpers.
import { Component, type CSSProperties, type ReactNode } from 'react'
import { GRAY, INK, netColor } from '../utils/colors'

/** Stable anchor slug from a section title — the part before any '—'/'(' qualifier,
 *  lowercased, non-alnum → '-'. The sidebar nav links against these. */
export function slug(title: string): string {
  const base = title.split(/—|\(/)[0]
  return base.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}

/** Section header (uppercase, bordered) with the anchor id the sidebar nav targets. */
export function Sec({ title }: { title: string }) {
  return (
    <div
      id={slug(title)}
      style={{
        margin: '1.1em 0 0.35em', color: 'var(--muted)', fontSize: '0.82em',
        letterSpacing: '0.06em', textTransform: 'uppercase',
        borderBottom: '1px solid var(--border)', paddingBottom: 3, scrollMarginTop: 8,
      }}
    >
      {title}
    </div>
  )
}

export function Pill({ text, color = GRAY }: { text: string; color?: string }) {
  return (
    <span style={{
      border: `1px solid ${color}`, color, padding: '1px 10px', borderRadius: 10,
      fontSize: '0.85em', fontWeight: 600, whiteSpace: 'nowrap',
    }}>
      {text}
    </span>
  )
}

/** NET verdict line: colored pill + text (color keyed off the verdict's keywords). */
export function Net({ label, text }: { label: string; text: string }) {
  return (
    <div style={{ margin: '4px 0' }}>
      <Pill text={label} color={netColor(text)} />{' '}
      <span style={{ color: INK }}>{text}</span>
    </div>
  )
}

export function Bullets({ items, color = INK, marker = '•' }: {
  items?: string[] | null
  color?: string
  marker?: string
}) {
  if (!items?.length) return null
  return (
    <>
      {items.map((f, i) => (
        <div key={i} style={{ margin: '1px 0', color }}>{marker} {String(f)}</div>
      ))}
    </>
  )
}

export function Caption({ children }: { children: ReactNode }) {
  return <div style={{ color: 'var(--faint)', fontSize: 13, margin: '3px 0' }}>{children}</div>
}

/** st.metric analogue: small label, big value, optional colored delta line. */
export function Metric({ label, value, delta, deltaColor }: {
  label: string
  value: string
  delta?: string | null
  deltaColor?: 'up' | 'down' | 'off'
}) {
  const dc = deltaColor === 'up' ? 'var(--green)' : deltaColor === 'down' ? 'var(--red)' : 'var(--faint)'
  return (
    <div style={{ minWidth: 110 }}>
      <div style={{ color: 'var(--muted)', fontSize: 12.5 }}>{label}</div>
      <div style={{ fontSize: 21, fontWeight: 600 }}>{value}</div>
      {delta && <div style={{ color: dc, fontSize: 12.5 }}>{delta}</div>}
    </div>
  )
}

export function MetricRow({ children }: { children: ReactNode }) {
  return <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', margin: '6px 0' }}>{children}</div>
}

export interface Column<Row> {
  key: string
  header: string
  /** cell renderer; defaults to String(row[key]) */
  cell?: (row: Row, i: number) => ReactNode
  /** per-cell style (color/weight) */
  style?: (row: Row, i: number) => CSSProperties | undefined
}

/** Plain styled table — the st.dataframe analogue (rows are pre-formatted strings/nodes). */
export function DataTable<Row extends Record<string, unknown>>({ columns, rows, rowStyle }: {
  columns: Column<Row>[]
  rows: Row[]
  rowStyle?: (row: Row, i: number) => CSSProperties | undefined
}) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 14 }}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={{
                textAlign: 'left', color: 'var(--muted)', fontWeight: 500,
                borderBottom: '1px solid var(--border)', padding: '4px 10px 4px 2px',
              }}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={rowStyle?.(r, i)}>
              {columns.map((c) => (
                <td key={c.key} style={{
                  padding: '3px 10px 3px 2px', borderBottom: '1px solid #1a1f29',
                  whiteSpace: 'nowrap', ...c.style?.(r, i),
                }}>
                  {c.cell ? c.cell(r, i) : String(r[c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Tiny inline-SVG sparkline — the LineChartColumn analogue for gauge trailing series. */
export function Sparkline({ values, width = 90, height = 22, color = 'var(--blue)' }: {
  values: number[]
  width?: number
  height?: number
  color?: string
}) {
  const vs = values.filter((v) => v != null && isFinite(v))
  if (vs.length < 2) return null
  const [min, max] = [Math.min(...vs), Math.max(...vs)]
  const span = max - min || 1
  const pts = vs.map((v, i) =>
    `${((i / (vs.length - 1)) * width).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`)
  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <polyline points={pts.join(' ')} fill="none" stroke={color} strokeWidth={1.2} />
    </svg>
  )
}

/** st.expander analogue — collapsed by default. */
export function Collapsible({ title, children, defaultOpen = false }: {
  title: string
  children: ReactNode
  defaultOpen?: boolean
}) {
  return (
    <details open={defaultOpen} style={{ margin: '10px 0' }}>
      <summary style={{
        cursor: 'pointer', color: 'var(--text)', fontSize: 14.5,
        border: '1px solid var(--border)', borderRadius: 8, padding: '6px 12px',
        background: 'var(--panel)', userSelect: 'none',
      }}>
        {title}
      </summary>
      <div style={{ padding: '8px 4px' }}>{children}</div>
    </details>
  )
}

/** Per-section error boundary: a failing section shows a warning instead of killing the
 *  page — the ANSI report below stays the lossless fallback (mirrors render_all's try). */
export class SectionBoundary extends Component<
  { name: string; children: ReactNode }, { error: Error | null }
> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          color: 'var(--amber)', border: '1px solid var(--border)', borderRadius: 8,
          padding: '6px 12px', margin: '6px 0', fontSize: 13.5,
        }}>
          {this.props.name} failed to render ({String(this.state.error)}) —
          see the full text report below
        </div>
      )
    }
    return this.props.children
  }
}

export function Warning({ children }: { children: ReactNode }) {
  return (
    <div style={{
      background: 'rgba(224,166,58,0.10)', border: '1px solid rgba(224,166,58,0.4)',
      borderRadius: 8, padding: '6px 12px', margin: '6px 0', color: 'var(--amber)', fontSize: 14,
    }}>
      {children}
    </div>
  )
}
