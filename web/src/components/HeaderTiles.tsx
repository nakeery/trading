// Header metric tiles — close + Δ vs prior close, OHL, 52-week range position, as-of date.
// M1 version renders the essentials from the payload's last_bar + the chart's range52;
// the faithful sec_header port (live labeling nuances) lands with the M2 section pass.
import type { LastBar, LiveInfo, Payload, Range52 } from '../api/types'

function Tile({ label, value, sub, color }: {
  label: string
  value: string
  sub?: string
  color?: string
}) {
  return (
    <div style={{
      background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 8,
      padding: '8px 14px', minWidth: 120,
    }}>
      <div style={{ color: 'var(--muted)', fontSize: 12 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 600, color: color ?? 'var(--text)' }}>{value}</div>
      {sub && <div style={{ color: 'var(--faint)', fontSize: 12 }}>{sub}</div>}
    </div>
  )
}

const fmt = (v: number | null | undefined, digits = 2) =>
  v == null ? '—' : v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })

export default function HeaderTiles({ payload, range52, live: liveTick }: {
  payload: Payload
  range52: Range52 | null
  live?: LiveInfo | null
}) {
  let lb = (payload.last_bar ?? {}) as LastBar
  const live = payload.live as Payload['live']
  let when = live?.applied ? `LIVE ${live.hhmm ?? ''} ET` : `close · ${payload.as_of}`
  // a fresh chart-poll tick (live mode) overrides the report's bar — the tiles ride it
  if (liveTick?.found && liveTick.close != null) {
    lb = {
      close: liveTick.close, prev_close: liveTick.prev_close ?? lb.prev_close,
      open: liveTick.open ?? lb.open, high: liveTick.high ?? lb.high, low: liveTick.low ?? lb.low,
    }
    when = `LIVE ${liveTick.hhmm ?? ''} ET`
  }
  const chg = lb.close != null && lb.prev_close ? lb.close / lb.prev_close - 1 : null
  return (
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', margin: '10px 0' }}>
      <Tile
        label={when}
        value={fmt(lb.close)}
        sub={chg != null ? `${chg >= 0 ? '+' : ''}${(chg * 100).toFixed(2)}% vs prior` : undefined}
        color={chg == null ? undefined : chg >= 0 ? 'var(--green)' : 'var(--red)'}
      />
      <Tile label="open" value={fmt(lb.open)} />
      <Tile label="high / low" value={`${fmt(lb.high)} / ${fmt(lb.low)}`} />
      {range52 && (
        <Tile
          label="52-week range"
          value={`${(range52.pos * 100).toFixed(0)}%`}
          sub={`${fmt(range52.lo)} – ${fmt(range52.hi)} · ${(range52.off_hi * 100).toFixed(1)}% off high`}
        />
      )}
      {payload.as_of_mode && (
        <Tile label="🕰 as-of mode" value={String(payload.as_of_mode)} color="var(--amber)" />
      )}
    </div>
  )
}
