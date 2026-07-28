// "Δ what changed" (S56): latest report vs the prior stored session's snapshot — the diff
// rides the /api/report response. Silent when there's no history; a one-line caption when
// nothing notable moved.
import type { ReportDiff } from '../api/types'
import { ordinalPercentile } from '../utils/colors'
import { Caption, Collapsible } from './shared'
import { diffCount } from './VerdictStrip'

export default function DiffPanel({ diff, forceOpen = false }: {
  diff: ReportDiff | null
  forceOpen?: boolean
}) {
  if (!diff) return null
  const chg = diff.close != null && diff.prev_close
    ? diff.close / diff.prev_close - 1 : null
  if (!diff.changes) {
    return (
      <Caption>
        Δ vs {diff.prev_as_of}: no notable state changes
        {chg != null ? ` · close ${chg >= 0 ? '+' : ''}${(chg * 100).toFixed(2)}%` : ''}
      </Caption>
    )
  }
  const d = diff.changes
  const n = diffCount(diff)
  return (
    <div id="diff-panel">
    {/* S65: badge count in the title; open by default when something actually changed */}
    <Collapsible title={`Δ ${n} change${n === 1 ? '' : 's'} since ${diff.prev_as_of}`}
      defaultOpen={forceOpen || n > 0}>
      {diff.close != null && diff.prev_close != null && (
        <Caption>
          close {diff.prev_close.toLocaleString('en-US', { minimumFractionDigits: 2 })} →{' '}
          {diff.close.toLocaleString('en-US', { minimumFractionDigits: 2 })}
          {chg != null ? ` (${chg >= 0 ? '+' : ''}${(chg * 100).toFixed(2)}%)` : ''}
        </Caption>
      )}
      {d.regime_flip && (
        <div><b>trend regime:</b> {d.regime_flip[0] ?? 'no regime'} → {d.regime_flip[1] ?? 'no regime'}</div>
      )}
      {d.flips.length > 0 && (
        <div>
          <b>setup-check flips:</b>{' '}
          {d.flips.map(([k, a, b]) => `${k}: ${a} → ${b}`).join(' · ')}
        </div>
      )}
      {([
        ['new drawdown-risk factors', d.dd_added],
        ['cleared drawdown-risk factors', d.dd_removed],
        ['new rally factors', d.rally_added],
        ['cleared rally factors', d.rally_removed],
      ] as [string, string[]][]).map(([label, items]) => items.length > 0 && (
        <div key={label}>
          <b>{label}:</b>
          {items.map((x, i) => <div key={i}>- {x}</div>)}
        </div>
      ))}
      {d.gauge_moves.length > 0 && (
        <div>
          <b>gauge percentile moves (≥10 points):</b>{' '}
          {d.gauge_moves.slice(0, 6)
            .map(([n, a, b]) => `${n} ${ordinalPercentile(a)} → ${ordinalPercentile(b)}`)
            .join(' · ')}
        </div>
      )}
      <Caption>
        state diff vs the prior stored session — snapshots accumulate per run under
        data/payload_history/
      </Caption>
    </Collapsible>
    </div>
  )
}
