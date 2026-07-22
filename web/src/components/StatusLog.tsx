// Compute-phase preamble (refresh/progress notices the CLI would print) — collapsible,
// mirrors the st.status stage log.
import { useState } from 'react'

export default function StatusLog({ preamble }: { preamble: string }) {
  const [open, setOpen] = useState(false)
  const lines = preamble.split('\n').filter((l) => l.trim())
  if (!lines.length) return null
  return (
    <div style={{ margin: '6px 0' }}>
      <button onClick={() => setOpen(!open)} style={{ fontSize: 13 }}>
        {open ? '▾' : '▸'} compute log ({lines.length} lines)
      </button>
      {open && (
        <pre style={{
          background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 8,
          padding: 10, fontSize: 12.5, color: 'var(--muted)', whiteSpace: 'pre-wrap',
        }}>
          {lines.join('\n')}
        </pre>
      )}
    </div>
  )
}
