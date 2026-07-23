// VOLATILITY SETUP + LONG CALL VIABILITY — ports of sec_vol/sec_call (straddle/strangle
// quote tables with at-ask honesty lines, expected-move tiles, IV-by-expiry curve).
import type { Payload, PlotlyFig } from '../../api/types'
import { AMBER, BLUE, GRAY, GREEN, RED, ordinalPercentile } from '../../utils/colors'
import { DARK_LAYOUT, SPOT_GOLD } from '../../utils/plotly'
import { Bullets, Caption, Collapsible, DataTable, Metric, MetricRow, Net, Pill, Sec, Warning } from '../shared'
import { BalanceBar, RangeStrip } from '../viz'
import type { Gauge } from './gauges'
import Plot from '../Plot'

const pctS = (v: number, digits = 1) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(digits)}%`

interface Leg { strike: number; oi?: number | null; bid: number; ask: number }
interface ComboQuote {
  cost: number
  lo: number
  hi: number
  dn_move: number
  up_move: number
  call_strike: number
  put_strike?: number
  width?: number
  dn_width?: number | null
  up_width?: number | null
  target_width?: number | null
  no_bid?: boolean
  cost_ask?: number | null
  lo_ask?: number
  hi_ask?: number
  dn_move_ask?: number
  up_move_ask?: number
  legs?: { put: Leg; call: Leg } | null
}

function quoteCaveats(cb: ComboQuote): string[] {
  const out: string[] = []
  if (cb.no_bid) out.push('⚠ a leg has no bid — the mid cost is indicative, not executable')
  if (cb.cost_ask != null && cb.cost_ask > cb.cost * 1.03) {
    out.push(`at ask: $${cb.cost_ask.toFixed(2)}/sh → BE ${cb.lo_ask!.toFixed(2)} / ${cb.hi_ask!.toFixed(2)}  `
      + `(need −${(cb.dn_move_ask! * 100).toFixed(1)}% / +${(cb.up_move_ask! * 100).toFixed(1)}%)`)
  }
  if (cb.legs) {
    const one = (o: Leg, cp: string) =>
      `${o.strike}${cp} OI ${o.oi != null ? Math.trunc(o.oi).toLocaleString() : '—'} bid/ask ${o.bid.toFixed(2)}/${o.ask.toFixed(2)}`
    out.push(`legs: ${one(cb.legs.put, 'p')}  ·  ${one(cb.legs.call, 'c')}`)
  }
  return out
}

interface Vol {
  setup?: { net?: string; notes?: string[]; long_vol?: string[]; short_vol?: string[]; hint?: string } | null
  em?: { dte: number; pct: number; dollars: number; lo: number; hi: number; hv_pct?: number | null } | null
  earnings?: { date?: string | null; days?: number; hist_move?: number | null } | null
  squeeze?: Record<string, { squeeze_on?: boolean }> | null
  history?: { status: string; usable?: number; summary?: string; ticker?: string } | null
  quote?: {
    spot: number
    as_of_str: string
    stale?: boolean
    notes?: string[]
    quotes: {
      expiry: string
      dte: number
      expiry_kind?: string
      days_after_earn?: number | null
      straddle?: ComboQuote | null
      strangle?: ComboQuote | null
    }[]
  } | null
}

export function SecVol({ p }: { p: Payload }) {
  const vol = p.vol as Vol | null
  if (!vol?.setup) return null
  const s = vol.setup
  const { em, earnings: eg } = vol
  const sq = vol.squeeze ?? {}
  const on = ['1M', '1W', '1D', '4h', '1h'].filter((tf) => sq[tf]?.squeeze_on)
  const hist = vol.history
  const q = vol.quote
  return (
    <>
      <Sec title="VOLATILITY SETUP — straddle/strangle context  (not a prediction)" />
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        compression:{' '}
        {on.length
          ? on.map((tf) => <Pill key={tf} text={`squeeze ON ${tf}`} color={AMBER} />)
          : <Pill text="no active squeeze" color={GRAY} />}
      </div>
      {em && (
        <MetricRow>
          <Metric label={`Expected move (~${em.dte}d)`} value={`±${(em.pct * 100).toFixed(1)}%`}
            delta={`±$${em.dollars.toFixed(2)}`} deltaColor="off" />
          <Metric label="Lower BE band" value={em.lo.toLocaleString('en-US', { minimumFractionDigits: 2 })} />
          <Metric label="Upper BE band" value={em.hi.toLocaleString('en-US', { minimumFractionDigits: 2 })} />
          {em.hv_pct != null && (
            <Metric label="Realized (HV)" value={`±${(em.hv_pct * 100).toFixed(1)}%`} deltaColor="off" />
          )}
        </MetricRow>
      )}
      {em && (() => {
        // EM band strip (S61): the IV-implied ±move vs the realized-vol band on one axis.
        // lo + hi = 2·spot exactly (symmetric bands), so the midpoint IS spot when the
        // live quote is absent.
        const spot = q?.spot ?? (em.lo + em.hi) / 2
        const hvLo = em.hv_pct != null ? spot * (1 - em.hv_pct) : null
        const hvHi = em.hv_pct != null ? spot * (1 + em.hv_pct) : null
        const all = [em.lo, em.hi, hvLo, hvHi].filter((v): v is number => v != null)
        const span = Math.max(...all) - Math.min(...all) || 1
        return (
          <>
            <RangeStrip
              lo={Math.min(...all) - span * 0.06} hi={Math.max(...all) + span * 0.06} width={520}
              bands={[
                { from: em.lo, to: em.hi, color: 'rgba(78,163,216,0.15)' },
                ...(hvLo != null && hvHi != null
                  ? [{ from: hvLo, to: hvHi, color: 'rgba(154,164,178,0.12)' }] : []),
              ]}
              markers={[
                { value: em.lo, label: `−${(em.pct * 100).toFixed(1)}%`, color: BLUE, shape: 'line' },
                { value: em.hi, label: `+${(em.pct * 100).toFixed(1)}%`, color: BLUE, shape: 'line' },
                { value: spot, label: 'spot', color: SPOT_GOLD, shape: 'tri' },
              ]} />
            <Caption>
              blue band = expected move (±{(em.pct * 100).toFixed(1)}%, ~{em.dte}d)
              {em.hv_pct != null ? ` · gray band = realized HV (±${(em.hv_pct * 100).toFixed(1)}%)` : ''}
            </Caption>
          </>
        )
      })()}
      {eg?.date && (
        <Caption>
          earnings: {eg.date} ({eg.days}d{eg.hist_move ? `, typ. ±${(eg.hist_move * 100).toFixed(1)}%` : ''})
        </Caption>
      )}
      {hist?.status === 'ok' && <Caption>history ({hist.usable} earnings): {hist.summary}</Caption>}
      {hist?.status === 'insufficient_iv' && (
        <Caption>
          history: IV history thin — accumulates via the daily harvest; `backfill_iv.py` can
          restore liquid names ({hist.ticker})
        </Caption>
      )}
      <Net label="NET" text={s.net ?? 'n/a'} />
      {(s.notes ?? []).map((n, i) => <Caption key={i}>· {n}</Caption>)}
      <BalanceBar left={s.long_vol?.length ?? 0} right={s.short_vol?.length ?? 0}
        leftLabel="buy vol" rightLabel="sell premium" leftColor={GREEN} rightColor={RED} />
      {((s.long_vol?.length ?? 0) + (s.short_vol?.length ?? 0)) > 0 && (
        <Collapsible title={`vol factors (${s.long_vol?.length ?? 0} buy · ${s.short_vol?.length ?? 0} sell)`}>
          <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
            {!!s.long_vol?.length && (
              <div style={{ flex: 1, minWidth: 320 }}>
                <div style={{ color: GREEN, fontWeight: 600 }}>favors BUYING vol</div>
                <Bullets items={s.long_vol} />
              </div>
            )}
            {!!s.short_vol?.length && (
              <div style={{ flex: 1, minWidth: 320 }}>
                <div style={{ color: RED, fontWeight: 600 }}>favors SELLING premium</div>
                <Bullets items={s.short_vol} />
              </div>
            )}
          </div>
        </Collapsible>
      )}
      {s.hint && <Caption>{s.hint}</Caption>}
      {q?.quotes?.length ? (
        <Collapsible
          title={`straddle/strangle quotes — spot ${q.spot.toFixed(2)}, as of ${q.as_of_str}${q.stale ? '  (stale)' : ''}`}
        >
          {(q.notes ?? []).map((n, i) => <Caption key={i}>· {n}</Caption>)}
          {q.quotes.map((blk, bi) => {
            const rows: Record<string, string>[] = []
            const caveats: string[] = []
            const stq = blk.straddle
            const sg = blk.strangle
            if (stq) {
              rows.push({
                vehicle: `ATM straddle ${stq.call_strike}`, cost: stq.cost.toFixed(2),
                lo: stq.lo.toFixed(2), hi: stq.hi.toFixed(2),
                need: `−${(stq.dn_move * 100).toFixed(1)}% / +${(stq.up_move * 100).toFixed(1)}%`,
              })
              caveats.push(...quoteCaveats(stq))
            }
            if (sg) {
              let wing: string
              if (sg.dn_width != null && sg.up_width != null) {
                const tw = sg.target_width
                const off = tw != null && (Math.abs(sg.dn_width - tw) >= 0.01 || Math.abs(sg.up_width - tw) >= 0.01)
                wing = `−${(sg.dn_width * 100).toFixed(1)}% / +${(sg.up_width * 100).toFixed(1)}%`
                  + (off ? `, target ±${(tw! * 100).toFixed(0)}%` : '')
              } else {
                wing = `≈±${((sg.width ?? 0) * 100).toFixed(0)}%`
              }
              rows.push({
                vehicle: `strangle (${wing}) ${sg.put_strike}p/${sg.call_strike}c`,
                cost: sg.cost.toFixed(2), lo: sg.lo.toFixed(2), hi: sg.hi.toFixed(2),
                need: `−${(sg.dn_move * 100).toFixed(1)}% / +${(sg.up_move * 100).toFixed(1)}%`,
              })
              caveats.push(...quoteCaveats(sg))
            }
            const after = blk.days_after_earn != null ? `; ${blk.days_after_earn}d after earnings` : ''
            return (
              <div key={bi} style={{ margin: '6px 0' }}>
                <div>
                  exp <b>{blk.expiry}</b> ({blk.expiry_kind ? `${blk.expiry_kind}, ` : ''}{blk.dte}d{after})
                </div>
                {rows.length > 0 && (
                  <DataTable rows={rows} columns={[
                    { key: 'vehicle', header: 'Vehicle' }, { key: 'cost', header: 'Cost $/sh' },
                    { key: 'lo', header: 'BE low' }, { key: 'hi', header: 'BE high' },
                    { key: 'need', header: 'Need' },
                  ]} />
                )}
                {caveats.map((c, i) => <Caption key={i}>{c}</Caption>)}
              </div>
            )
          })}
          <Caption>
            vega: straddle = max vega (enter close to the print) · strangle = cheaper + lower
            theta (enter earlier / run more names / vega convexity)
          </Caption>
        </Collapsible>
      ) : null}
    </>
  )
}

interface CallCandidate {
  strike: number
  delta?: number | null
  mid: number
  be: number
  be_move: number
  theta_pct?: number | null
  oi?: number | null
  spread_pct?: number | null
  ask?: number
  be_ask?: number | null
  be_move_ask?: number
}
interface CallQ {
  spot: number
  as_of_str: string
  stale?: boolean
  liquidity?: { grade: string; spread_pct: number | null; oi: number; volume: number } | null
  quotes: {
    expiry: string
    dte: number
    monthly?: boolean
    atm?: CallCandidate | null
    otm?: CallCandidate | null
    notes?: string[]
  }[]
  curve?: { points: { label: string; iv: number }[]; tag?: string } | null
}

export function SecCall({ p }: { p: Payload }) {
  const cq = p.callq as CallQ | null
  const ctx = p.ctx as { gauges?: Gauge[] } | null
  if (!cq?.quotes?.length) return null
  const cliq = cq.liquidity
  const rows: Record<string, string>[] = []
  const askLines: string[] = []
  for (const blk of cq.quotes) {
    const exp = `${blk.expiry} (${blk.monthly ? 'monthly, ' : ''}${blk.dte}d)`
    for (const kind of ['atm', 'otm'] as const) {
      const cnd = blk[kind]
      if (!cnd) continue
      rows.push({
        expiry: exp, type: kind.toUpperCase(), strike: `${cnd.strike}c`,
        delta: cnd.delta != null ? cnd.delta.toFixed(2) : '—',
        mid: cnd.mid.toFixed(2),
        be: `${cnd.be.toFixed(2)} (${pctS(cnd.be_move)})`,
        theta: cnd.theta_pct ? `${(cnd.theta_pct * 100).toFixed(1)}%` : 'n/a',
        oi: cnd.oi != null ? Math.trunc(cnd.oi).toLocaleString() : '—',
        spread: cnd.spread_pct != null ? `${(cnd.spread_pct * 100).toFixed(1)}%` : 'n/a',
      })
      if (cnd.be_ask != null) {
        askLines.push(`${exp} ${kind.toUpperCase()} at ask $${cnd.ask!.toFixed(2)} → `
          + `BE ${cnd.be_ask.toFixed(2)} (${pctS(cnd.be_move_ask!)})`)
      }
    }
  }
  const curve = cq.curve
  const ivp = (ctx?.gauges ?? []).find((g) => g.name === 'ATM IV (30d)')?.pct
  const curveFig: PlotlyFig | null = curve?.points?.length
    ? {
        data: [{
          type: 'scatter', x: curve.points.map((pt) => pt.label),
          y: curve.points.map((pt) => pt.iv * 100),
          mode: 'lines+markers', line: { color: BLUE, width: 2 }, marker: { size: 8, color: BLUE },
        }],
        layout: {
          ...DARK_LAYOUT,
          height: 220, margin: { l: 10, r: 10, t: 24, b: 10 },
          yaxis: { title: { text: 'ATM IV %' } },
          title: { text: `IV by expiry — ${curve.tag ?? ''}`, font: { size: 13 } },
        },
      }
    : null
  return (
    <>
      <Sec title="LONG CALL VIABILITY  (context, not advice)" />
      <Caption>spot {cq.spot.toFixed(2)}, as of {cq.as_of_str}{cq.stale ? '  (stale)' : ''}</Caption>
      {cliq && (
        <Caption>
          chain liquidity: {cliq.grade.toUpperCase()}  (ATM-region spread{' '}
          {cliq.spread_pct != null ? `${(cliq.spread_pct * 100).toFixed(1)}%` : 'n/a'}, OI{' '}
          {cliq.oi.toLocaleString()}, day vol {cliq.volume.toLocaleString()})
        </Caption>
      )}
      {rows.length > 0 && (
        <DataTable rows={rows} columns={[
          { key: 'expiry', header: 'Expiry' }, { key: 'type', header: 'Type' },
          { key: 'strike', header: 'Strike' }, { key: 'delta', header: 'Δ' },
          { key: 'mid', header: 'Mid $/sh' }, { key: 'be', header: 'BE' },
          { key: 'theta', header: 'Theta/day' }, { key: 'oi', header: 'OI' },
          { key: 'spread', header: 'Spread' },
        ]} />
      )}
      {askLines.map((ln, i) => <Caption key={i}>· {ln}</Caption>)}
      {cq.quotes.flatMap((blk) => (blk.notes ?? []).map((n, i) => (
        <Caption key={`${blk.expiry}-${i}`}>· {blk.expiry}: {n}</Caption>
      )))}
      {curveFig && <Plot fig={curveFig} />}
      {ivp != null && ivp >= 0.7 && (
        <Warning>
          ATM IV (30d) at the {ordinalPercentile(ivp)} of its history — paying up for a
          direction bet; debit spreads cut the vega/theta bill
        </Warning>
      )}
      <Caption>
        guide: more DTE = slower theta · 0.35–0.40Δ in trends, lower Δ in chop · BE move must
        be plausible within the tenor
      </Caption>
    </>
  )
}
