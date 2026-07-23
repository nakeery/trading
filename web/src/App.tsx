// LENS app shell: controlled TopBar + one report query driving the chart and sections.
// Flag/ticker changes auto-run after a 2s debounce (rapid toggles batch into one fetch);
// Run and pill/tile picks commit immediately (Run additionally force-refreshes past every
// cache). Deep links prefill + auto-run once; the URL is written back after each
// successful generate. As-of mode: live forced off, diff/ledger hidden (no lookahead).
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchReport, fetchTickers, flagsToParams } from './api/client'
import type { Flags } from './api/types'
import { readUrl, writeUrl } from './hooks/useUrlState'
import TopBar from './components/TopBar'
import StatusLog from './components/StatusLog'
import CandleChart from './components/CandleChart'
import AnsiReport from './components/AnsiReport'
import Sections, { SectionNav } from './components/sections'
import { EarningsReactions, IvHistoryChart, SeasonalityGrid } from './components/Extras'
import Watchlist from './components/Watchlist'
import EconCalendar from './components/EconCalendar'
import DiffPanel from './components/DiffPanel'
import SignalLedger from './components/SignalLedger'

const DEBOUNCE_MS = 2000

interface Submitted {
  ticker: string
  flags: Flags
  force: boolean
  nonce: number // bumped on explicit Run — forces a fresh fetch past every cache
}

export default function App() {
  // draft = what the controls show; req = what the report query runs on
  const [initial] = useState(readUrl)
  const [ticker, setTicker] = useState(initial.ticker)
  const [flags, setFlags] = useState<Flags>(initial.flags)
  const [chartFrom, setChartFrom] = useState<string | null>(initial.chartFrom)
  const [req, setReq] = useState<Submitted | null>(
    // deep link with a ticker auto-runs once (explicit intent — no debounce)
    initial.ticker ? { ticker: initial.ticker, flags: initial.flags, force: false, nonce: 0 } : null,
  )
  const [pendingIn, setPendingIn] = useState(false)

  const tickers = useQuery({ queryKey: ['tickers'], queryFn: fetchTickers })

  // 2s debounce: any draft change arms a timer; another change re-arms it, so rapid
  // clicks collapse into one fetch. Run/pills below commit immediately instead.
  const draftKey = `${ticker}|${flagsToParams(flags).toString()}`
  const reqKey = req ? `${req.ticker}|${flagsToParams(req.flags).toString()}` : ''
  useEffect(() => {
    if (!ticker || draftKey === reqKey) {
      setPendingIn(false)
      return
    }
    setPendingIn(true)
    const t = setTimeout(() => {
      setPendingIn(false)
      // functional update, re-checked at FIRE time: clicking Run doesn't change the draft, so
      // this timer keeps ticking with a stale closure — committing unconditionally would
      // overwrite Run's force-nonce request with a non-forced twin ~2s later (served from the
      // server's 120s cache, silently replacing the force-refreshed data)
      setReq((prev) => {
        const prevKey = prev ? `${prev.ticker}|${flagsToParams(prev.flags).toString()}` : ''
        if (prevKey === draftKey) return prev // Run/pill already committed this exact draft
        return { ticker, flags, force: false, nonce: prev?.nonce ?? 0 }
      })
    }, DEBOUNCE_MS)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey])

  const runNow = (force: boolean, t = ticker, f = flags) => {
    if (!t) return
    setPendingIn(false)
    setReq({ ticker: t, flags: f, force, nonce: force ? Date.now() : (req?.nonce ?? 0) })
  }
  const pickTicker = (t: string) => {
    // pill/tile pick = explicit intent like Run — skips the debounce, but NOT the caches
    setTicker(t)
    runNow(false, t)
  }

  const report = useQuery({
    queryKey: ['report', reqKey, req?.force ? req.nonce : 0],
    queryFn: () => fetchReport(req!.ticker, req!.flags, req!.force),
    enabled: req !== null,
  })
  const payload = report.data?.payload ?? null

  // shareable URL reflects the current view — written back after each successful generate
  useEffect(() => {
    if (payload && req) writeUrl(req.ticker, req.flags, chartFrom)
  }, [payload, req, chartFrom])

  const shownAsOf = (payload?.as_of_mode ?? null) as string | null
  const shownLive = Boolean(req?.flags.live) && !shownAsOf

  return (
    <div style={{ maxWidth: 1280, margin: '0 auto', padding: 16 }}>
      <h2 style={{ marginTop: 0 }}>🔭 LENS — multi-timeframe market-structure &amp; risk</h2>
      <TopBar
        ticker={ticker} flags={flags} chartFrom={chartFrom}
        known={tickers.data?.tickers ?? []}
        onTicker={setTicker} onFlags={setFlags} onChartFrom={setChartFrom}
        onRun={() => runNow(true)} onPill={pickTicker}
      />

      {pendingIn && (
        <p style={{ color: 'var(--faint)' }}>⏳ applying changes — keep clicking to batch…</p>
      )}
      {report.isFetching && (
        <p style={{ color: 'var(--amber)' }}>running the lens on {req?.ticker}…</p>
      )}
      {report.isError && (
        <p style={{ color: 'var(--red)' }}>lens failed: {String(report.error)}</p>
      )}

      {report.data && !report.isFetching && (
        <>
          <StatusLog preamble={report.data.preamble} />
          {payload === null ? (
            <p style={{ color: 'var(--red)' }}>
              {report.data.preamble || `could not load data for ${req?.ticker}`}
            </p>
          ) : (
            <>
              {shownAsOf && (
                <p style={{ color: 'var(--amber)' }}>
                  🕰 AS-OF {shownAsOf} — historical backtest view: report, chart, and gauges
                  reflect data through that session only (no lookahead); live-chain/
                  current-only blocks are disabled
                </p>
              )}
              <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <CandleChart
                    ticker={payload.ticker}
                    payload={payload}
                    asOf={shownAsOf}
                    start={chartFrom}
                    live={shownLive}
                  />
                  {!shownAsOf && <DiffPanel diff={report.data.diff} />}
                  <EconCalendar />
                  <IvHistoryChart ticker={payload.ticker} asOf={shownAsOf} />
                  <EarningsReactions ticker={payload.ticker} asOf={shownAsOf}
                    payload={payload} />
                  <SeasonalityGrid ticker={payload.ticker} asOf={shownAsOf} />
                  <Sections p={payload} />
                  {/* ledger hidden in as-of mode: its realized outcomes span dates after
                      the backtest as-of — showing them would defeat the no-lookahead point */}
                  {!shownAsOf && <SignalLedger ticker={payload.ticker} />}
                  <AnsiReport html={report.data.ansi_html} />
                </div>
                <div style={{ width: 180, flexShrink: 0 }}>
                  <SectionNav p={payload} />
                </div>
              </div>
            </>
          )}
        </>
      )}

      {!req && (
        <>
          <p style={{ color: 'var(--muted)', marginTop: 20 }}>
            Type a ticker (or pick one from the watchlist below) to run the lens. Checkbox
            blocks mirror the CLI flags; quotes are cached per session like the CLI.
          </p>
          <EconCalendar />
          <Watchlist known={tickers.data?.tickers ?? []} onPick={pickTicker} />
        </>
      )}
    </div>
  )
}
