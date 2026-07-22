// Empty-state landing grid (S56): one compact tile per known ticker (CSV only, zero
// network) — sparkline, last close + Δ, MA20/50 arrows, latest snapshot's setup score.
// Tile click = pill semantics (immediate run, no cache bust).
import { useQuery } from '@tanstack/react-query'
import { Caption } from './shared'

interface Tile {
  ticker: string
  closes: number[]
  last: number
  chg: number
  ma20_up: boolean
  ma50_up: boolean | null
  as_of: string
  setup: { ok: number; total: number } | null
}

function TileSpark({ closes }: { closes: number[] }) {
  if (closes.length < 2) return null
  const [min, max] = [Math.min(...closes), Math.max(...closes)]
  const span = max - min || 1
  const w = 220
  const h = 44
  const up = closes[closes.length - 1] >= closes[0]
  const pts = closes.map((v, i) =>
    `${((i / (closes.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - min) / span) * (h - 4)).toFixed(1)}`)
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"
      style={{ display: 'block' }}>
      <polyline points={pts.join(' ')} fill="none"
        stroke={up ? 'var(--green)' : 'var(--red)'} strokeWidth={1.4} />
    </svg>
  )
}

function WatchTile({ ticker, onPick }: { ticker: string; onPick: (t: string) => void }) {
  const q = useQuery({
    queryKey: ['tile', ticker],
    queryFn: async () => {
      const res = await fetch(`/api/tile/${ticker}`)
      return (await res.json() as { tile: Tile | null }).tile
    },
    staleTime: 10 * 60_000,
  })
  const t = q.data
  return (
    <div style={{
      border: '1px solid var(--border)', borderRadius: 10, padding: 10,
      background: 'var(--panel)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <button onClick={() => onPick(ticker)} style={{ fontWeight: 700 }}>{ticker}</button>
        {t && (
          <div style={{ textAlign: 'right', lineHeight: 1.25 }}>
            <span style={{ fontWeight: 600 }}>
              {t.last.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
            <br />
            <span style={{ color: t.chg >= 0 ? 'var(--green)' : 'var(--red)', fontSize: '0.85em' }}>
              {t.chg >= 0 ? '+' : ''}{(t.chg * 100).toFixed(2)}%
            </span>
          </div>
        )}
      </div>
      {t ? (
        <>
          <TileSpark closes={t.closes} />
          <Caption>
            MA20 {t.ma20_up ? '▲' : '▼'}
            {t.ma50_up != null && <> · MA50 {t.ma50_up ? '▲' : '▼'}</>}
            {t.setup && <> · setup {t.setup.ok}/{t.setup.total}</>}
            {' · '}{t.as_of}
          </Caption>
        </>
      ) : (
        <Caption>{q.isLoading ? 'loading…' : 'no data'}</Caption>
      )}
    </div>
  )
}

export default function Watchlist({ known, onPick }: {
  known: string[]
  onPick: (t: string) => void
}) {
  if (!known.length) return null
  return (
    <div style={{ marginTop: 18 }}>
      <Caption>
        watchlist — every ticker with indicators data on disk; click one to run the lens
      </Caption>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 10,
      }}>
        {known.map((t) => <WatchTile key={t} ticker={t} onPick={onPick} />)}
      </div>
    </div>
  )
}
