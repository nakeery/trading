// Candlestick section: overlay toggle row + the server-built Plotly figure.
// The figure (two-axis hollow-candle convention, profile aspects, GEX levels, event
// vlines) is composed in api/charts.py — toggling an overlay refetches the fig with new
// `overlays=` params; the daily frame behind it is cached server-side so this is cheap.
// Live mode: the query polls every 10s with live=1 — each tick fetches ONE Tradier quote
// server-side and appends it as a provisional today-bar; after LIVE_MISS_LIMIT consecutive
// empty quotes polling pauses (market closed / no token — don't hit Tradier all night).
import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchChart } from '../api/client'
import type { Payload } from '../api/types'
import HeaderTiles from './HeaderTiles'
import Plot from './Plot'

const LIVE_EVERY_MS = 10_000
const LIVE_MISS_LIMIT = 3

const OVERLAYS: { token: string; label: string; default: boolean }[] = [
  { token: 'ma20', label: 'MA20', default: true },
  { token: 'ma50', label: 'MA50', default: true },
  { token: 'ma200', label: 'MA200', default: false },
  { token: 'ema9', label: 'EMA9', default: false },
  { token: 'bb', label: 'BB(20,2σ)', default: false },
  { token: 'volume', label: 'volume', default: true },
  { token: 'rsi', label: 'RSI', default: false },
  { token: 'macd', label: 'MACD', default: false },
  { token: 'pline', label: 'price line', default: true },
  { token: 'vp', label: 'vol profile', default: false },
]
const VP_ASPECTS = ['value area', 'POC', 'HVN', 'LVN', 'histogram']

export default function CandleChart({ ticker, payload, asOf, start, live = false }: {
  ticker: string
  payload: Payload
  asOf?: string | null
  start?: string | null
  live?: boolean
}) {
  const misses = useRef(0)
  const [on, setOn] = useState<Set<string>>(
    () => new Set(OVERLAYS.filter((o) => o.default).map((o) => o.token)),
  )
  const [aspects, setAspects] = useState<Set<string>>(() => new Set(VP_ASPECTS))
  const hasGex = Boolean(payload.gex)
  const [gexOn, setGexOn] = useState(true)

  const toggle = (token: string) =>
    setOn((prev) => {
      const next = new Set(prev)
      if (next.has(token)) next.delete(token)
      else next.add(token)
      return next
    })

  const overlays = [...on, ...(hasGex && gexOn ? ['gex'] : [])]
  const isLive = live && !asOf // a real-time quote on a historical report is a contradiction
  const chart = useQuery({
    // payload.as_of in the key: a fresh report (new data vintage) refetches the fig
    queryKey: ['chart', ticker, payload.as_of, asOf, start, overlays.sort().join(','),
      on.has('vp') ? [...aspects].sort().join(',') : '', isLive],
    queryFn: async () => {
      const d = await fetchChart(ticker, {
        asOf, start, overlays, aspects: on.has('vp') ? [...aspects] : [], live: isLive,
      })
      if (isLive) misses.current = d.live?.found ? 0 : misses.current + 1
      return d
    },
    refetchInterval: isLive && misses.current < LIVE_MISS_LIMIT ? LIVE_EVERY_MS : false,
  })
  const liveInfo = chart.data?.live ?? null

  return (
    <div>
      {isLive && liveInfo?.found && (
        <div style={{ color: 'var(--red)', fontSize: 13.5, margin: '2px 0' }}>
          🔴 LIVE — {ticker} ${liveInfo.close?.toFixed(2)}
          {liveInfo.chg != null && ` (${liveInfo.chg >= 0 ? '+' : ''}${(liveInfo.chg * 100).toFixed(2)}% vs prior close)`}
          {' · '}{liveInfo.in_progress ? 'session in progress' : 'session closed'}
          {' · chart updates every 10s'}
        </div>
      )}
      {isLive && liveInfo && !liveInfo.found && (
        <div style={{ color: 'var(--faint)', fontSize: 13.5, margin: '2px 0' }}>
          {misses.current >= LIVE_MISS_LIMIT
            ? `live: polling paused after ${LIVE_MISS_LIMIT} empty Tradier responses (market closed / no token?) — showing last close; Run resumes`
            : 'live: no Tradier session data right now (market closed / no token?) — showing last close'}
        </div>
      )}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', color: 'var(--muted)', fontSize: 14 }}>
        {OVERLAYS.map((o) => (
          <label key={o.token} style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <input type="checkbox" checked={on.has(o.token)} onChange={() => toggle(o.token)} />
            {o.label}
          </label>
        ))}
        {hasGex && (
          <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <input type="checkbox" checked={gexOn} onChange={(e) => setGexOn(e.target.checked)} />
            GEX levels
          </label>
        )}
      </div>
      {on.has('vp') && (
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', color: 'var(--faint)', fontSize: 13, marginTop: 4 }}>
          profile aspects:
          {VP_ASPECTS.map((a) => (
            <label key={a} style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              <input
                type="checkbox"
                checked={aspects.has(a)}
                onChange={() => setAspects((prev) => {
                  const next = new Set(prev)
                  if (next.has(a)) next.delete(a)
                  else next.add(a)
                  return next
                })}
              />
              {a}
            </label>
          ))}
        </div>
      )}
      {chart.isLoading && <p style={{ color: 'var(--muted)' }}>loading chart…</p>}
      {chart.isError && <p style={{ color: 'var(--red)' }}>chart failed: {String(chart.error)}</p>}
      {chart.data?.fig && <Plot fig={chart.data.fig} />}
      {/* header tiles ride below the chart (mirrors the Streamlit layout: draw_chart then
          _header_tiles); range52 comes from the chart's warm-up frame; in live mode the
          tiles ride each fresh Tradier tick */}
      <HeaderTiles payload={payload} range52={chart.data?.range52 ?? null}
        live={isLive ? liveInfo : null} />
    </div>
  )
}
