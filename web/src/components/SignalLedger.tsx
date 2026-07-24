// Signal ledger (S30/S56): entry.py's forward ledger tail with realized-return scoring —
// ✓/✗ = fwd return vs the row's OWN stamped vol-adjusted threshold. Hidden in as-of mode
// (showing realized outcomes would defeat the no-lookahead point); App enforces that.
import { useQuery } from '@tanstack/react-query'
import { getJson } from '../api/client'
import { Caption, Collapsible } from './shared'

interface ScoreRow {
  date: string
  fwd15: number | null
  win15: boolean | null
  fwd63: number | null
  win63: boolean | null
}
interface Ledger {
  columns: string[]
  rows: Record<string, unknown>[]
  score: {
    rows: ScoreRow[]
    summary: Record<string, { scored15: number; avg15: number | null }>
    pending15: number
    pending63: number
  } | null
}

export default function SignalLedger({ ticker }: { ticker: string }) {
  const q = useQuery({
    queryKey: ['ledger', ticker],
    queryFn: async () =>
      (await getJson<{ ledger: Ledger | null }>(`/api/ledger/${ticker}`)).ledger,
  })
  const led = q.data
  if (!led?.rows?.length) return null
  const byDate = new Map((led.score?.rows ?? []).map((r) => [r.date, r]))
  const cell = (dateVal: unknown, k: 'fwd15' | 'fwd63', wk: 'win15' | 'win63') => {
    const r = byDate.get(String(dateVal).slice(0, 10))
    if (!r || r[k] == null) return 'pending'
    const mark = r[wk] == null ? '' : r[wk] ? ' ✓' : ' ✗'
    return `${r[k]! >= 0 ? '+' : ''}${(r[k]! * 100).toFixed(1)}%${mark}`
  }
  // insert the scored columns right after `signal` (CSV order: date, ticker,
  // signal_pre_gate, signal, …)
  const sigIdx = led.columns.indexOf('signal')
  const cols = [...led.columns]
  const scored = Boolean(led.score)
  if (scored) cols.splice(sigIdx + 1, 0, 'fwd 15d', 'fwd 63d')
  const segs = Object.entries(led.score?.summary ?? {})
    .filter(([, a]) => a.avg15 != null)
    .map(([sig, a]) => `${sig}: ${a.scored15} scored, avg 15d ${a.avg15! >= 0 ? '+' : ''}${(a.avg15! * 100).toFixed(1)}%`)
  return (
    <Collapsible title={`signal ledger — entry.py forward ledger, last ${led.rows.length} rows`
      + `${scored ? ' (scored vs realized returns)' : ' (unscored)'}`}>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c} style={{
                  textAlign: 'left', color: 'var(--muted)', fontWeight: 500,
                  borderBottom: '1px solid var(--border)', padding: '3px 9px 3px 2px',
                  whiteSpace: 'nowrap',
                }}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {led.rows.map((r, i) => (
              <tr key={i}>
                {cols.map((c) => {
                  const v = c === 'fwd 15d' ? cell(r.date, 'fwd15', 'win15')
                    : c === 'fwd 63d' ? cell(r.date, 'fwd63', 'win63')
                    : String(r[c] ?? '')
                  const color = v.includes('✓') ? 'var(--green)'
                    : v.includes('✗') ? 'var(--red)' : undefined
                  return (
                    <td key={c} style={{
                      padding: '2px 9px 2px 2px', borderBottom: '1px solid #1a1f29',
                      whiteSpace: 'nowrap', color,
                    }}>{v}</td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {scored ? (
        <Caption>
          one row per as-of run date (S30) · {segs.length ? `${segs.join(' · ')} · ` : ''}
          {led.score!.pending15} pending 15d / {led.score!.pending63} pending 63d · ✓/✗ = fwd
          return vs the row's OWN vol-adjusted threshold (every tier — on a STAY OUT row a ✗
          means staying out was right) · also: python score_ledger.py
        </Caption>
      ) : (
        <Caption>
          one row per as-of run date (S30); scoring needs the indicators CSV — run
          score_ledger.py for detail
        </Caption>
      )}
    </Collapsible>
  )
}
