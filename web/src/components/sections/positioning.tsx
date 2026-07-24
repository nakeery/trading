// Positioning/context sections: PUT/CALL OI (grouped bars + strike walls), GAMMA EXPOSURE,
// SHORT/SQUEEZE, RETAIL ATTENTION, INSIDER, STREET & NEWS — ports of the same-named sec_*
// renderers. The small Plotly charts here are composed client-side in TS (plain bar/scatter
// over payload data), unlike the candle/IV figures which come pre-built from the API.
import type { Payload, PlotlyFig } from '../../api/types'
import {
  BLUE, GOLD, GRAY, GREEN, INK, LEAPS_MAX_DTE, LEAPS_MIN_DTE, RED,
  ordinalPercentile, pcLabel,
} from '../../utils/colors'
import { Bullets, Caption, Collapsible, DataTable, Metric, MetricRow, Net, Pill, Sec } from '../shared'
import { DARK_LAYOUT, SPOT_GOLD } from '../../utils/plotly'
import { BalanceBar, PctBar, RangeStrip } from '../viz'
import Plot from '../Plot'

// ── PUT/CALL OI ──────────────────────────────────────────────────────────────
interface PcRow {
  expiry: string
  dte: number
  pc?: number | null
  pc_vol?: number | null
  call_oi?: number | null
  put_oi?: number | null
  call_vol?: number | null
  put_vol?: number | null
  by_strike?: [number, number, number][] | null
}
interface Pc {
  rows?: PcRow[]
  scope?: string
  as_of_str?: string
  stale?: boolean
  price?: number | null
  total?: { pc?: number | null; pc_vol?: number | null } | null
}

function pcOiFig(rows: PcRow[]): PlotlyFig | null {
  if (!rows.some((r) => r.call_oi != null || r.put_oi != null)) return null
  const x = rows.map((r) =>
    `${r.expiry}${r.dte >= LEAPS_MIN_DTE && r.dte <= LEAPS_MAX_DTE ? ' *' : ''}`)
  const hasVol = rows.some((r) => r.call_vol != null || r.put_vol != null)
  const data: object[] = [
    { type: 'bar', x, y: rows.map((r) => r.call_oi), name: 'Call OI', marker: { color: GREEN, line: { width: 0 } } },
    { type: 'bar', x, y: rows.map((r) => r.put_oi), name: 'Put OI', marker: { color: RED, line: { width: 0 } } },
  ]
  if (hasVol) {
    // latest-session FLOW beneath the POSITIONING pane — translucent (the price chart's
    // volume-pane convention) so the two panes aren't misread as one scale
    data.push(
      { type: 'bar', x, y: rows.map((r) => r.call_vol), name: 'Call Vol', yaxis: 'y2', marker: { color: 'rgba(94,196,94,0.55)', line: { width: 0 } } },
      { type: 'bar', x, y: rows.map((r) => r.put_vol), name: 'Put Vol', yaxis: 'y2', marker: { color: 'rgba(216,60,52,0.55)', line: { width: 0 } } },
    )
  }
  return {
    data,
    layout: {
      ...DARK_LAYOUT, barmode: 'group', bargroupgap: 0.08, height: hasVol ? 390 : 280,
      legend: { orientation: 'h', y: 1.08, x: 0, font: { size: 11 } },
      ...(hasVol
        ? {
            grid: { rows: 2, columns: 1, roworder: 'top to bottom' },
            yaxis: { title: { text: 'open interest', font: { size: 11 } }, domain: [0.45, 1] },
            yaxis2: { title: { text: 'volume', font: { size: 11 } }, domain: [0, 0.38] },
          }
        : { yaxis: { title: { text: 'open interest', font: { size: 11 } } } }),
    },
  }
}

function strikeWallsFig(pc: Pc): PlotlyFig | null {
  // OI-by-strike walls (S50): per-strike OI summed across the fetched scope
  const strikes = new Map<number, [number, number]>()
  for (const r of pc.rows ?? []) {
    for (const [k, cOi, pOi] of r.by_strike ?? []) {
      const agg = strikes.get(k) ?? [0, 0]
      strikes.set(k, [agg[0] + cOi, agg[1] + pOi])
    }
  }
  if (!strikes.size) return null
  const spot = pc.price
  let ks = [...strikes.keys()].sort((a, b) => a - b)
  if (spot && ks.length > 40) {
    ks = ks.sort((a, b) => Math.abs(a - spot) - Math.abs(b - spot)).slice(0, 40).sort((a, b) => a - b)
  }
  const calls = ks.map((k) => strikes.get(k)![0])
  const puts = ks.map((k) => -strikes.get(k)![1]) // negative x → diverging left
  const wallC = ks[calls.indexOf(Math.max(...calls))]
  const wallP = ks[puts.indexOf(Math.min(...puts))]
  return {
    data: [
      { type: 'bar', y: ks, x: calls, orientation: 'h', name: 'Call OI', marker: { color: GREEN, line: { width: 0 } }, hovertemplate: '%{y}: %{x:,.0f} calls<extra></extra>' },
      { type: 'bar', y: ks, x: puts, orientation: 'h', name: 'Put OI', marker: { color: RED, line: { width: 0 } }, customdata: puts.map(Math.abs), hovertemplate: '%{y}: %{customdata:,.0f} puts<extra></extra>' },
    ],
    layout: {
      ...DARK_LAYOUT, barmode: 'relative', bargap: 0.15,
      height: Math.max(300, 11 * ks.length), margin: { l: 10, r: 64, t: 10, b: 10 },
      legend: { orientation: 'h', y: 1.04, x: 0, font: { size: 11 } },
      xaxis: { showticklabels: false, title: { text: '← puts   ·   calls →', font: { size: 11 } } },
      yaxis: { title: { text: 'strike', font: { size: 11 } } },
      shapes: spot ? [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: spot, y1: spot, line: { dash: 'dot', width: 1, color: SPOT_GOLD } }] : [],
      annotations: [
        ...(spot ? [{ x: 1, xref: 'paper', xanchor: 'left', y: spot, text: `spot ${spot.toFixed(2)}`, showarrow: false, font: { color: SPOT_GOLD, size: 10 } }] : []),
        { y: wallC, x: 0, text: `call wall ${wallC}`, showarrow: false, xanchor: 'center', font: { color: GREEN, size: 10 }, bgcolor: 'rgba(14,17,23,0.75)' },
        { y: wallP, x: 0, text: `put wall ${wallP}`, showarrow: false, xanchor: 'center', font: { color: RED, size: 10 }, bgcolor: 'rgba(14,17,23,0.75)' },
      ],
    },
  }
}

export function SecPcOi({ p }: { p: Payload }) {
  const pc = p.pcoi as Pc | null
  if (!pc?.rows?.length) return null
  const rows = pc.rows
  let hdr = `PUT/CALL OI — live Tradier chain, by expiry  (${pc.scope ?? ''})`
  if (pc.as_of_str) hdr += ` · as of ${pc.as_of_str}${pc.stale ? '  (stale)' : ''}`
  const oiFig = pcOiFig(rows)
  const wallsFig = strikeWallsFig(pc)
  const isLeaps = (dte: number) => dte >= LEAPS_MIN_DTE && dte <= LEAPS_MAX_DTE
  const tbl = rows.map((r) => ({
    expiry: r.expiry, dte: String(r.dte),
    pcoi: r.pc != null ? r.pc.toFixed(2) : 'n/a',
    pcvol: r.pc_vol != null ? r.pc_vol.toFixed(2) : 'n/a',
    pos: pcLabel(r.pc) + (isLeaps(r.dte) ? ' *' : ''),
  }))
  if (rows.length > 1 && pc.total) {
    tbl.push({
      expiry: 'TOTAL', dte: '',
      pcoi: pc.total.pc != null ? pc.total.pc.toFixed(2) : 'n/a',
      pcvol: pc.total.pc_vol != null ? pc.total.pc_vol.toFixed(2) : 'n/a',
      pos: pcLabel(pc.total.pc),
    })
  }
  return (
    <>
      <Sec title={hdr} />
      {oiFig && <Plot fig={oiFig} />}
      {wallsFig ? (
        <>
          <Plot fig={wallsFig} />
          <Caption>
            open interest by strike (±20% of spot), summed across the {rows.length} fetched
            expiries — walls mark the heaviest strikes
          </Caption>
        </>
      ) : (
        <Caption>
          strike-level OI appears after the next chain refresh (tick live, or Run after a
          market close)
        </Caption>
      )}
      <DataTable
        rows={tbl}
        columns={[
          { key: 'expiry', header: 'Expiry' }, { key: 'dte', header: 'DTE' },
          { key: 'pcoi', header: 'P/C OI' }, { key: 'pcvol', header: 'P/C Vol' },
          { key: 'pos', header: 'Positioning' },
        ]}
      />
      <Caption>
        P/C OI = put OI / call OI (positioning) · P/C Vol = latest-session flow (lower pane)
        · * = LEAPS tenor
      </Caption>
    </>
  )
}

// ── GAMMA EXPOSURE ───────────────────────────────────────────────────────────
function gexFmt(v: number, sign = true): string {
  const s = sign && v >= 0 ? '+' : v < 0 ? '-' : ''
  const a = Math.abs(v)
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(2)}bn`
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(0)}m`
  return `${s}$${(a / 1e3).toFixed(0)}k`
}

interface Gex {
  by_strike?: { strike: number; call: number; put: number }[]
  expiries?: { dte: number }[]
  as_of_str?: string
  stale?: boolean
  net_gex: number
  spot?: number | null
  call_wall?: number | null
  call_wall_gex?: number
  put_wall?: number | null
  put_wall_gex?: number
  zero_gamma?: number | null
  max_pain?: { strike: number; expiry: string; dte: number } | null
  unusual?: { strike: number; type: string; expiry: string; dte: number; volume: number; oi: number; ratio: number | null }[]
}

export function SecGex({ p }: { p: Payload }) {
  const g = p.gex as Gex | null
  if (!g?.by_strike?.length) return null
  const exp = g.expiries ?? []
  // Math.max() over an empty spread is -Infinity — guard the payload-without-expiries case
  let hdr = `GAMMA EXPOSURE — dealer positioning, Tradier chain  `
    + (exp.length ? `(≤${Math.max(...exp.map((e) => e.dte))}d, ${exp.length} expiries)` : '')
  if (g.as_of_str) hdr += ` · as of ${g.as_of_str}${g.stale ? '  (stale)' : ''}`
  const regime = g.net_gex > 0
    ? 'dealers long gamma — stabilizing (sell rallies, buy dips)'
    : 'dealers short gamma — amplifying (buy rallies, sell dips)'
  const chips: [string, string][] = []
  if (g.call_wall != null) chips.push([`call wall ${g.call_wall}  (${gexFmt(g.call_wall_gex ?? 0, false)})`, GREEN])
  if (g.put_wall != null) chips.push([`put wall ${g.put_wall}  (${gexFmt(Math.abs(g.put_wall_gex ?? 0), false)})`, RED])
  if (g.zero_gamma != null) {
    chips.push([`zero-gamma ~${g.zero_gamma.toFixed(2)} (${g.zero_gamma < (g.spot ?? 0) ? 'below' : 'above'} spot)`, GOLD])
  }
  if (g.max_pain) chips.push([`max pain ${g.max_pain.strike} (${g.max_pain.expiry}, ${g.max_pain.dte}d)`, GRAY])

  const fig: PlotlyFig = {
    data: [
      { type: 'bar', x: g.by_strike.map((r) => r.strike), y: g.by_strike.map((r) => r.call), name: 'call GEX', marker: { color: GREEN, line: { width: 0 } } },
      { type: 'bar', x: g.by_strike.map((r) => r.strike), y: g.by_strike.map((r) => r.put), name: 'put GEX (dealer-short)', marker: { color: RED, line: { width: 0 } } },
    ],
    layout: {
      ...DARK_LAYOUT, barmode: 'relative', height: 280,
      yaxis: { title: { text: 'dealer $Γ / 1% move', font: { size: 11 } } },
      legend: { orientation: 'h', y: 1.08, x: 0, font: { size: 11 } },
      shapes: [
        { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { width: 0.8, color: '#4a5160' } },
        ...(g.spot ? [{ type: 'line', yref: 'paper', y0: 0, y1: 1, x0: g.spot, x1: g.spot, line: { dash: 'dot', width: 1, color: SPOT_GOLD } }] : []),
        ...(g.zero_gamma != null ? [{ type: 'line', yref: 'paper', y0: 0, y1: 1, x0: g.zero_gamma, x1: g.zero_gamma, line: { dash: 'dash', width: 1, color: GOLD } }] : []),
      ],
      annotations: [
        ...(g.spot ? [{ x: g.spot, yref: 'paper', y: 1, text: 'spot', showarrow: false, font: { color: SPOT_GOLD, size: 10 } }] : []),
        ...(g.zero_gamma != null ? [{ x: g.zero_gamma, yref: 'paper', y: 0, yanchor: 'bottom', text: 'zero-γ', showarrow: false, font: { color: GOLD, size: 10 } }] : []),
      ],
    },
  }
  return (
    <>
      <Sec title={hdr} />
      <Net label={`net GEX ${gexFmt(g.net_gex)}/1%`} text={regime} />
      {chips.length > 0 && (
        <div style={{ lineHeight: 2.3, margin: '4px 0', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {chips.map(([t, c], i) => <Pill key={i} text={t} color={c} />)}
        </div>
      )}
      <Plot fig={fig} />
      {!!g.unusual?.length && (
        <>
          <div style={{ color: INK, marginTop: 2 }}>
            unusual activity today (volume running a multiple of OI):
          </div>
          <DataTable
            rows={g.unusual.map((u) => ({
              strike: `${u.strike}${u.type[0]}`, expiry: u.expiry, dte: String(u.dte),
              volume: u.volume.toLocaleString(), oi: u.oi ? u.oi.toLocaleString() : '0',
              ratio: u.ratio != null ? `×${u.ratio.toFixed(1)}` : 'NEW',
            }))}
            columns={[
              { key: 'strike', header: 'Strike' }, { key: 'expiry', header: 'Expiry' },
              { key: 'dte', header: 'DTE' }, { key: 'volume', header: 'Volume' },
              { key: 'oi', header: 'OI' }, { key: 'ratio', header: 'Vol/OI' },
            ]}
          />
        </>
      )}
      <Caption>
        assumes dealers long calls / short puts (standard convention) — real inventory
        unknown · OI settles once daily (start-of-day); intraday flow shifts walls first ·
        levels also drawable on the price chart ("GEX levels" toggle)
      </Caption>
    </>
  )
}

// ── SHORT POSITIONING / SQUEEZE ──────────────────────────────────────────────
interface Buzz {
  rank: number
  rank_prev?: number | null
  mentions: number
  chg?: number | null
  pct?: number | null
  unranked?: boolean
  history?: { date: string; mentions: number }[] | null
}
interface Squeeze {
  si?: { interest?: number; settle_date?: string; chg?: number | null; dtc?: number | null; adv?: number | null } | null
  svr?: { now?: number | null; pct?: number | null; n?: number; avg5?: number | null; avg20?: number | null } | null
  read?: { net?: string; fuel?: string[]; counter?: string[]; caveats?: string[] } | null
  buzz?: Buzz | null
}

export function SecSqueeze({ p }: { p: Payload }) {
  const sq = p.squeeze as Squeeze | null
  if (!sq) return null
  const si = sq.si
  const sv = sq.svr ?? {}
  const read = sq.read ?? {}
  const bz = sq.buzz
  return (
    <>
      <Sec title="SHORT POSITIONING / SQUEEZE  (context, not a prediction)" />
      <MetricRow>
        {si?.interest ? (
          <>
            <Metric
              label={`Short interest (settled ${si.settle_date ?? '?'})`}
              value={`${(si.interest / 1e6).toFixed(1)}M sh`}
              delta={si.chg != null ? `${si.chg >= 0 ? '+' : ''}${(si.chg * 100).toFixed(1)}% vs prior` : null}
              deltaColor="off"
            />
            {si.dtc != null && (
              <Metric
                label="Days-to-cover" value={si.dtc.toFixed(1)}
                delta={si.adv ? `avg daily vol ${(si.adv / 1e6).toFixed(1)}M` : null} deltaColor="off"
              />
            )}
          </>
        ) : (
          <Caption>short interest n/a — no data from the NASDAQ API or FINRA's consolidated feed</Caption>
        )}
        {sv.now != null && (
          <div>
            <Metric label="Short-volume (latest)" value={`${(sv.now * 100).toFixed(0)}%`} />
            {sv.pct != null && (
              <div style={{ fontSize: 12.5, color: 'var(--faint)', display: 'flex', alignItems: 'center', gap: 6 }}>
                <PctBar pct={sv.pct} width={70} showText={false} />
                {ordinalPercentile(sv.pct)} of {sv.n} sessions
              </div>
            )}
          </div>
        )}
      </MetricRow>
      {sv.avg5 != null && sv.avg20 != null && (
        <Caption>short-volume 5d avg {(sv.avg5 * 100).toFixed(0)}% · 20d avg {(sv.avg20 * 100).toFixed(0)}%</Caption>
      )}
      {bz && !bz.unranked && (
        <div style={{ color: INK }}>
          retail buzz: <b>#{bz.rank}</b> on reddit stock boards
          {bz.rank_prev ? ` (was #${bz.rank_prev})` : ''} — {bz.mentions} mentions
          {bz.chg != null ? `, ${bz.chg >= 0 ? '+' : ''}${(bz.chg * 100).toFixed(0)}% vs prior 24h` : ''}
          {bz.pct != null ? `  [${ordinalPercentile(bz.pct)}]` : ''} (ApeWisdom)
        </div>
      )}
      <Net label="NET" text={read.net ?? 'n/a'} />
      <BalanceBar left={read.fuel?.length ?? 0} right={read.counter?.length ?? 0}
        leftLabel="squeeze fuel" rightLabel="counter" leftColor={GREEN} rightColor={RED} />
      {((read.fuel?.length ?? 0) + (read.counter?.length ?? 0)) > 0 && (
        <Collapsible title={`squeeze factors (${read.fuel?.length ?? 0} fuel · ${read.counter?.length ?? 0} counter)`}>
          <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
            {!!read.fuel?.length && (
              <div style={{ flex: 1, minWidth: 320 }}>
                <div style={{ color: GREEN, fontWeight: 600 }}>squeeze fuel</div>
                <Bullets items={read.fuel} />
              </div>
            )}
            {!!read.counter?.length && (
              <div style={{ flex: 1, minWidth: 320 }}>
                <div style={{ color: RED, fontWeight: 600 }}>counter</div>
                <Bullets items={read.counter} />
              </div>
            )}
          </div>
        </Collapsible>
      )}
      {/* caveats OUTSIDE the fold: squeeze_read always returns them even with zero
          fuel/counter factors — the CLI/Streamlit print them unconditionally */}
      {(read.caveats ?? []).map((c, i) => <Caption key={i}>· {c}</Caption>)}
      {bz && <Caption>· buzz = attention, not direction — crowded names gap on headlines both ways</Caption>}
    </>
  )
}

// ── RETAIL ATTENTION (renders only when the squeeze section is absent) ───────
export function SecBuzz({ p }: { p: Payload }) {
  const bz = p.buzz as Buzz | null
  if (!bz || p.squeeze) return null
  if (bz.unranked) {
    return (
      <>
        <Sec title="RETAIL ATTENTION  (reddit stock boards, ApeWisdom)" />
        <Caption>unranked — not in the top ~400 most-mentioned names (quiet is normal)</Caption>
      </>
    )
  }
  const chips: [string, string][] = [
    [`rank #${bz.rank}${bz.rank_prev ? ` (was #${bz.rank_prev})` : ''}`, GOLD],
    [`${bz.mentions} mentions${bz.chg != null ? `, ${bz.chg >= 0 ? '+' : ''}${(bz.chg * 100).toFixed(0)}% vs 24h` : ''}`, INK],
  ]
  if (bz.pct != null) chips.push([`${ordinalPercentile(bz.pct)} of own history`, BLUE])
  const hist = bz.history
  return (
    <>
      <Sec title="RETAIL ATTENTION  (reddit stock boards, ApeWisdom)" />
      <div style={{ lineHeight: 2.3, margin: '4px 0', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {chips.map(([t, c], i) => <Pill key={i} text={t} color={c} />)}
      </div>
      {hist && hist.length >= 5 && (
        <Plot fig={{
          data: [{
            type: 'scatter', x: hist.map((h) => h.date), y: hist.map((h) => h.mentions),
            mode: 'lines', line: { color: GOLD, width: 1.5 },
            fill: 'tozeroy', fillcolor: 'rgba(224,166,58,0.15)',
          }],
          layout: {
            ...DARK_LAYOUT, height: 120, margin: { l: 10, r: 10, t: 6, b: 6 }, showlegend: false,
            yaxis: { title: { text: 'mentions/day', font: { size: 10 } } },
            xaxis: { tickfont: { size: 9 } },
          },
        }} />
      )}
      <Caption>· buzz = attention, not direction — crowded names gap on headlines both ways</Caption>
    </>
  )
}

// ── INSIDER ACTIVITY ─────────────────────────────────────────────────────────
interface Insider {
  lookback_days?: number
  read?: {
    net_usd?: number | null
    n_buys?: number
    n_sells?: number
    n_owners?: number
    latest_buy?: { date: string; owner: string; role: string; shares: number; price?: number | null; usd?: number | null } | null
    net?: string
    positive?: string[]
    flags?: string[]
    caveats?: string[]
  } | null
}

export function SecInsider({ p }: { p: Payload }) {
  const ins = p.insider as Insider | null
  if (!ins) return null
  const rd = ins.read ?? {}
  const usd = rd.net_usd
  const lb = rd.latest_buy
  return (
    <>
      <Sec title={`INSIDER ACTIVITY — SEC Form 4, trailing ${ins.lookback_days ?? 90}d  (context, not a prediction)`} />
      <MetricRow>
        <Metric label="Net open-market flow"
          value={usd ? `$${usd >= 0 ? '+' : ''}${usd.toLocaleString('en-US', { maximumFractionDigits: 0 })}` : '$0'} />
        <Metric label="Buys / sells" value={`${rd.n_buys ?? 0} / ${rd.n_sells ?? 0}`} />
        <Metric label="Distinct insiders" value={String(rd.n_owners ?? 0)} />
      </MetricRow>
      {lb && (
        <Caption>
          latest buy — {lb.date}  {lb.owner} ({lb.role})  {lb.shares.toLocaleString()} sh
          {lb.price ? ` @ ${lb.price.toFixed(2)}` : ''}{lb.usd ? `  ($${lb.usd.toLocaleString('en-US', { maximumFractionDigits: 0 })})` : ''}
        </Caption>
      )}
      <Net label="NET" text={rd.net ?? 'n/a'} />
      <BalanceBar left={rd.n_buys ?? 0} right={rd.n_sells ?? 0}
        leftLabel="buys" rightLabel="sells" leftColor={GREEN} rightColor={RED} />
      {((rd.positive?.length ?? 0) + (rd.flags?.length ?? 0) + (rd.caveats?.length ?? 0)) > 0 && (
        <Collapsible title="insider detail">
          <Bullets items={rd.positive} color={GREEN} />
          <Bullets items={rd.flags} color="var(--amber)" marker="⚑" />
          {(rd.caveats ?? []).map((c, i) => <Caption key={i}>· {c}</Caption>)}
        </Collapsible>
      )}
    </>
  )
}

// ── STREET & NEWS ────────────────────────────────────────────────────────────
interface Street {
  pt?: { mean: number; median?: number | null; low?: number | null; high?: number | null; spot: number; upside_mean: number } | null
  revisions?: { label: string; chg30: number }[] | null
  rev_net?: string
  ud?: { window_days: number; n_up: number; n_down: number; pt_raises: number; pt_lowers: number } | null
  news?: { when: string; title: string; url?: string | null; provider: string }[] | null
}

export function SecStreet({ p }: { p: Payload }) {
  const stq = p.street as Street | null
  if (!stq) return null
  const { pt, revisions: revs, ud } = stq
  const news = stq.news ?? []
  return (
    <>
      <Sec title="STREET & NEWS  (analyst expectations + headlines — context, not advice)" />
      {(pt || revs || ud) ? (
        <MetricRow>
          {pt && (
            <div>
              <Metric
                label="Mean price target" value={`$${pt.mean.toLocaleString('en-US', { maximumFractionDigits: 0 })}`}
                delta={`${pt.upside_mean >= 0 ? '+' : ''}${(pt.upside_mean * 100).toFixed(1)}% vs spot $${pt.spot.toFixed(2)}`}
                deltaColor={pt.upside_mean >= 0 ? 'up' : 'down'}
              />
              {pt.low != null && pt.high != null && (
                <Caption>
                  range ${pt.low.toLocaleString('en-US', { maximumFractionDigits: 0 })}–
                  ${pt.high.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                  {pt.median ? ` · median $${pt.median.toLocaleString('en-US', { maximumFractionDigits: 0 })}` : ''}
                </Caption>
              )}
            </div>
          )}
          {revs && (
            <Metric label="EPS revisions (30d)" value={stq.rev_net ?? ''}
              delta={revs.map((r) => `${r.label} ${r.chg30 >= 0 ? '+' : ''}${(r.chg30 * 100).toFixed(1)}%`).join(' · ')}
              deltaColor="off" />
          )}
          {ud && (
            <Metric label={`Ratings (${ud.window_days}d)`} value={`${ud.n_up}↑ / ${ud.n_down}↓`}
              delta={`${ud.pt_raises} PT raises / ${ud.pt_lowers} PT lowers`} deltaColor="off" />
          )}
        </MetricRow>
      ) : (
        <Caption>no analyst coverage data (ETF or uncovered name) — headlines only</Caption>
      )}
      {pt && pt.low != null && pt.high != null && (() => {
        // PT range strip (S61): where spot sits inside the analyst low–high range. The
        // domain includes spot — a spot beyond the range IS the stale-ink tell.
        const all = [pt.low, pt.high, pt.spot, pt.mean]
        const span = Math.max(...all) - Math.min(...all) || 1
        return (
          <RangeStrip
            lo={Math.min(...all) - span * 0.05} hi={Math.max(...all) + span * 0.05} width={520}
            bands={[{ from: pt.low, to: pt.high, color: 'rgba(154,164,178,0.12)' }]}
            markers={[
              { value: pt.mean, label: `mean ${Math.round(pt.mean)}`, color: pt.upside_mean >= 0 ? GREEN : RED, shape: 'line' },
              ...(pt.median != null ? [{ value: pt.median, label: `med ${Math.round(pt.median)}`, color: GRAY, shape: 'line' as const }] : []),
              { value: pt.spot, label: `spot ${pt.spot.toFixed(0)}`, color: SPOT_GOLD, shape: 'tri' },
            ]}
            fmt={(v) => `$${Math.round(v)}`} />
        )
      })()}
      {ud && (
        <BalanceBar left={ud.n_up} right={ud.n_down}
          leftLabel="↑ upgrades" rightLabel="↓ downgrades" leftColor={GREEN} rightColor={RED} />
      )}
      {news.length > 0 && (
        <Collapsible title={`headlines (${news.length})`}>
          {news.map((n, i) => (
            <div key={i} style={{ margin: '2px 0', color: INK }}>
              · <span style={{ color: GRAY }}>{n.when}</span>{' '}
              {n.url
                ? <a href={n.url} target="_blank" rel="noreferrer" style={{ color: INK }}>{n.title}</a>
                : n.title}{' '}
              <span style={{ color: GRAY }}>({n.provider})</span>
            </div>
          ))}
        </Collapsible>
      )}
      {pt && (
        <Caption>
          · targets follow price — a wide "upside" right after a selloff is stale ink, not a signal
        </Caption>
      )}
    </>
  )
}
