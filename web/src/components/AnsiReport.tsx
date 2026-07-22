// Full text report (CLI-identical) — the ANSI report converted to HTML server-side
// (ansi2html). Collapsed by default like the Streamlit expander. The HTML is our own
// backend's output rendered into a <pre>, so dangerouslySetInnerHTML is safe here.
import { useState } from 'react'

export default function AnsiReport({ html }: { html: string }) {
  const [open, setOpen] = useState(false)
  if (!html) return null
  return (
    <div style={{ margin: '14px 0' }}>
      <button onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} full text report (CLI-identical)
      </button>
      {open && (
        <div style={{
          background: '#0e1117', border: '1px solid var(--border)', borderRadius: 8,
          padding: 14, overflowX: 'auto', marginTop: 6,
        }}>
          <pre
            style={{
              fontFamily: 'Cascadia Mono, Consolas, monospace', fontSize: 13,
              lineHeight: 1.35, color: '#d8dee9', margin: 0,
            }}
            dangerouslySetInnerHTML={{ __html: html }}
          />
        </div>
      )}
    </div>
  )
}
