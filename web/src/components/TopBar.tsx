// Ticker search + recent-data pills + flag checkboxes + pc-oi scope + thesis/as-of panels
// + Run. Controlled component: App owns the state (deep links + debounce + pills live
// there); flag changes auto-run after a 2s debounce, Run/pills commit immediately.
import type { Flags, PcOiScope } from '../api/types'

const BOOL_FLAGS = ['vol', 'call', 'gex', 'squeeze', 'insider', 'street', 'movers', 'geo', 'live'] as const

export default function TopBar({ ticker, flags, chartFrom, known, onTicker, onFlags, onChartFrom, onRun, onPill }: {
  ticker: string
  flags: Flags
  chartFrom: string | null
  known: string[]
  onTicker: (t: string) => void
  onFlags: (f: Flags) => void
  onChartFrom: (d: string | null) => void
  onRun: () => void
  onPill: (t: string) => void
}) {
  const setFlag = (k: keyof Flags, v: Flags[keyof Flags]) => onFlags({ ...flags, [k]: v })
  const today = new Date().toISOString().slice(0, 10)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          value={ticker}
          onChange={(e) => onTicker(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === 'Enter' && onRun()}
          placeholder="e.g. CRSP"
          maxLength={8}
          style={{ width: 110, fontSize: 17 }}
        />
        {BOOL_FLAGS.map((k) => (
          <label key={k} style={{ display: 'flex', gap: 4, alignItems: 'center', color: 'var(--muted)' }}>
            <input
              type="checkbox"
              checked={flags[k]}
              onChange={(e) => setFlag(k, e.target.checked)}
            />
            {k}
          </label>
        ))}
        <select
          value={flags.pc_oi}
          onChange={(e) => setFlag('pc_oi', e.target.value as PcOiScope)}
          title="put/call OI scope"
        >
          {['off', 'all', 'near', 'leaps', 'monthly'].map((s) => (
            <option key={s} value={s}>pc-oi: {s}</option>
          ))}
        </select>
        <button className="primary" onClick={onRun} title="run now — bypasses the debounce and every cache">
          Run
        </button>
      </div>

      {known.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ color: 'var(--faint)', fontSize: 13 }}>recent data:</span>
          {known.map((t) => (
            <button
              key={t}
              onClick={() => onPill(t)}
              style={{
                fontSize: 12.5, padding: '1px 9px', borderRadius: 10,
                borderColor: t === ticker ? 'var(--blue)' : 'var(--border)',
                color: t === ticker ? 'var(--blue)' : 'var(--muted)',
              }}
            >
              {t}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap', color: 'var(--muted)' }}>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          bias
          <select
            value={flags.thesis ?? 'none'}
            onChange={(e) => setFlag('thesis', e.target.value === 'none' ? null : (e.target.value as Flags['thesis']))}
          >
            <option value="none">none</option>
            <option value="bullish">bullish</option>
            <option value="bearish">bearish</option>
          </select>
        </label>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          key level
          <input
            type="number"
            step={1}
            style={{ width: 90 }}
            value={flags.level ?? ''}
            onChange={(e) => setFlag('level', e.target.value ? Number(e.target.value) : null)}
          />
        </label>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <input
            type="checkbox"
            checked={flags.as_of != null}
            onChange={(e) => setFlag('as_of', e.target.checked ? today : null)}
          />
          🕰 as-of backtest
        </label>
        {flags.as_of != null && (
          <>
            <input
              type="date"
              max={today}
              value={flags.as_of}
              onChange={(e) => setFlag('as_of', e.target.value || null)}
              title="rewind the whole report to a past date — no lookahead"
            />
            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              chart from
              <input
                type="date"
                max={flags.as_of}
                value={chartFrom ?? ''}
                onChange={(e) => onChartFrom(e.target.value || null)}
                title="widen the chart window only — display-only, never regenerates"
              />
            </label>
          </>
        )}
        {flags.as_of && (
          <span style={{ color: 'var(--amber)', fontSize: 13.5 }}>
            historical mode — live-chain blocks (pc-oi, gex, vol quote, call, squeeze,
            insider, street, geo, live) are disabled
          </span>
        )}
      </div>
    </div>
  )
}
