// Above-the-fold verdict (S65): the syntheses the engine already computes — trend regime,
// setup score, drawdown-vs-rally balance, the multi-TF synthesis line, and a Δ-changes badge —
// surfaced in one strip between the TopBar and the chart. Zero new backend compute: everything
// here rides the report payload + the diff that /api/report already returns.
import type { Payload, ReportDiff } from '../api/types'
import { AMBER, GRAY, GREEN, RED } from '../utils/colors'
import { Pill } from './shared'
import { BalanceBar, TallyBar } from './viz'

export function diffCount(diff: ReportDiff | null): number {
  const c = diff?.changes
  if (!c) return 0
  return c.flips.length + (c.regime_flip ? 1 : 0)
    + c.dd_added.length + c.dd_removed.length
    + c.rally_added.length + c.rally_removed.length + c.gauge_moves.length
}

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ color: 'var(--muted)', fontSize: 11.5, marginBottom: 2 }}>{label}</div>
      {children}
    </div>
  )
}

export default function VerdictStrip({ payload, diff, onDiffClick }: {
  payload: Payload
  diff: ReportDiff | null
  onDiffClick: () => void
}) {
  const risk = payload.risk as {
    net?: string
    regime?: { state?: string; label?: string } | null
    drawdown?: string[]
    rally?: string[]
  } | null
  const setup = payload.setup as { rows?: [string, string, string][] } | null
  const synthesis = (payload.summary as { synthesis?: string } | null)?.synthesis
  const reg = risk?.regime
  const marks = (setup?.rows ?? []).map((r) => r[1])
  const nOk = marks.filter((m) => m === '✓').length
  const nMid = marks.filter((m) => m === '–').length
  const nBad = marks.filter((m) => m === '✗').length
  const nDiff = diffCount(diff)
  if (!risk && !setup && !synthesis) return null
  return (
    <section className="card" style={{
      display: 'flex', flexWrap: 'wrap', gap: 22, alignItems: 'center', padding: '10px 16px',
    }}>
      <Cell label="trend regime">
        <Pill
          text={reg?.label ?? 'no established regime'}
          color={reg ? (reg.state === 'up' ? GREEN : RED) : GRAY}
        />
      </Cell>
      {marks.length > 0 && (
        <Cell label={`setup ${nOk}/${marks.length} ✓`}>
          <TallyBar width={170} segments={[
            { n: nOk, color: GREEN, label: '✓' },
            { n: nMid, color: GRAY, label: '–' },
            { n: nBad, color: RED, label: '✗' },
          ]} />
        </Cell>
      )}
      {risk && ((risk.drawdown?.length ?? 0) + (risk.rally?.length ?? 0)) > 0 && (
        <Cell label="risk balance">
          <BalanceBar width={180} left={risk.drawdown?.length ?? 0} right={risk.rally?.length ?? 0}
            leftLabel="dd" rightLabel="rally" leftColor={RED} rightColor={GREEN} />
        </Cell>
      )}
      {synthesis && (
        <Cell label="synthesis">
          <span style={{ color: 'var(--text)', fontSize: 13.5 }}>{synthesis}</span>
        </Cell>
      )}
      {nDiff > 0 && (
        <button onClick={onDiffClick} title="jump to the Δ what-changed panel" style={{
          marginLeft: 'auto', background: 'transparent', border: `1px solid ${AMBER}`,
          color: AMBER, borderRadius: 999, padding: '4px 12px', cursor: 'pointer',
          fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap',
        }}>
          Δ {nDiff} change{nDiff === 1 ? '' : 's'}
        </button>
      )}
    </section>
  )
}
