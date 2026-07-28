// Lens self-score (S65): the lens' OWN snapshots (setup score, risk lean, trend regime —
// data/payload_history/) joined to realized 15d/63d forward returns. Averages/medians only;
// the honesty caption rides the API payload verbatim. Hidden in as-of mode (App enforces —
// realized outcomes after the as-of date would be lookahead).
import { useQuery } from '@tanstack/react-query'
import { getJson } from '../api/client'
import { Caption, Collapsible, DataTable } from './shared'

interface Cell {
  n: number
  scored15: number
  avg15: number | null
  med15: number | null
  scored63: number
  avg63: number | null
  med63: number | null
}
interface LensScoreRes {
  status: string
  n?: number
  first?: string
  last?: string
  pending15?: number
  pending63?: number
  bands?: Record<string, Cell>
  regimes?: Record<string, Cell>
  leans?: Record<string, Cell>
  note?: string
}

const pct = (v: number | null | undefined) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`

function GroupTable({ title, cells }: { title: string; cells?: Record<string, Cell> }) {
  const rows = Object.entries(cells ?? {}).map(([k, c]) => ({
    k, n: String(c.n), avg15: pct(c.avg15), med15: pct(c.med15),
    avg63: pct(c.avg63), med63: pct(c.med63),
  }))
  if (!rows.length) return null
  return (
    <div style={{ marginBottom: 8 }}>
      <DataTable rows={rows} columns={[
        { key: 'k', header: title }, { key: 'n', header: 'n', align: 'right' },
        { key: 'avg15', header: 'avg 15d', align: 'right' },
        { key: 'med15', header: 'med 15d', align: 'right' },
        { key: 'avg63', header: 'avg 63d', align: 'right' },
        { key: 'med63', header: 'med 63d', align: 'right' },
      ]} />
    </div>
  )
}

export default function LensScore({ ticker }: { ticker: string }) {
  const q = useQuery({
    queryKey: ['lens_score', ticker],
    queryFn: async () =>
      (await getJson<{ score: LensScoreRes | null }>(`/api/lens_score/${ticker}`)).score,
  })
  const s = q.data
  if (!s || s.status !== 'ok') return null   // silent until snapshots accumulate
  return (
    <Collapsible title={`lens self-score — ${s.n} snapshots vs realized returns `
      + `(${s.pending15} pending 15d / ${s.pending63} pending 63d)`}>
      <GroupTable title="setup band" cells={s.bands} />
      <GroupTable title="trend regime" cells={s.regimes} />
      <GroupTable title="risk lean" cells={s.leans} />
      {s.note && <Caption>· {s.note}</Caption>}
      <Caption>· also: python lens_score.py --ticker {ticker}</Caption>
    </Collapsible>
  )
}
