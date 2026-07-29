// Ordered section renderer — the render_all analogue. Every section is wrapped in a
// SectionBoundary so one bad payload slice degrades to a warning instead of a blank page
// (the ANSI report below stays the lossless fallback). SectionNav mirrors the sidebar
// quick-nav: an entry appears only when the payload carries that section.
import { useEffect, useState } from 'react'
import type { Payload } from '../../api/types'
import { SectionBoundary } from '../shared'
import {
  SecBackdrop, SecDivergences, SecLadder, SecMultiTf, SecRisk, SecSetup, SecVolumeProfile,
} from './core'
import { SecGeo, SecOptions } from './gauges'
import { SecBuzz, SecGex, SecInsider, SecPcOi, SecShort, SecSqueeze, SecStreet } from './positioning'
import { SecCall, SecVol } from './volcall'
import { SecBreadth, SecEvents, SecNotes, SecSectors, SecThesis, hasUpcomingEvents } from './misc'

// print_report order (sec_header is rendered by the chart block instead — skip_header)
const SECTIONS: [string, ({ p }: { p: Payload }) => React.ReactElement | null][] = [
  ['market backdrop', SecBackdrop],
  ['multi-timeframe', SecMultiTf],
  ['divergences', SecDivergences],
  ['volume profile', SecVolumeProfile],
  ['price ladder', SecLadder], // S65 — consolidated distance-sorted S/R view
  ['rally vs drawdown', SecRisk],
  ['setup check', SecSetup],
  ['short setup', SecShort], // S65 — --short / --thesis bearish
  ['options & vol', SecOptions],
  ['short/squeeze', SecSqueeze],
  ['retail attention', SecBuzz],
  ['insider activity', SecInsider],
  ['street & news', SecStreet],
  ['put/call OI', SecPcOi],
  ['gamma exposure', SecGex],
  ['volatility setup', SecVol],
  ['long call viability', SecCall],
  ['geo backdrop', SecGeo],
  ['market breadth', SecBreadth], // S67 — equal-weight vs cap-weight, before rotation (print order)
  ['sector rotation', SecSectors],
  ['upcoming events', SecEvents], // S61 — merges the catalysts + macro tables onto one timeline
  ['thesis check', SecThesis],
  ['notes', SecNotes],
]

export default function Sections({ p }: { p: Payload }) {
  return (
    <>
      {SECTIONS.map(([name, Fn]) => (
        // a renderer that returns null leaves the card empty — .card:empty hides it
        <section className="card" key={name}>
          <SectionBoundary name={name}>
            <Fn p={p} />
          </SectionBoundary>
        </section>
      ))}
    </>
  )
}

// (label, anchor slug, payload presence check) — mirrors the Streamlit sidebar list
const NAV: [string, string, (p: Payload) => unknown][] = [
  ['Market backdrop', 'market-backdrop', (p) => p.backdrop],
  ['Multi-timeframe', 'multi-timeframe', (p) => p.reads],
  ['Divergences', 'divergences',
    (p) => p.divs && Object.keys(p.divs as object).length],
  ['Volume profile', 'volume-profile', (p) => p.profile],
  ['Price ladder', 'price-ladder',
    (p) => (p.ladder as { levels?: unknown[] } | null)?.levels?.length],
  ['Rally vs drawdown', 'rally-vs-drawdown-risk', (p) => p.risk],
  ['Setup check', 'setup-check', (p) => p.setup],
  ['Short setup', 'short-setup', (p) => p.short],
  ['Options & vol', 'options-vol-context', (p) => p.ctx],
  ['Short/squeeze', 'short-positioning-squeeze', (p) => p.squeeze],
  ['Retail attention', 'retail-attention', (p) => p.buzz && !p.squeeze],
  ['Insider activity', 'insider-activity', (p) => p.insider],
  ['Street & news', 'street-news', (p) => p.street],
  ['Put/call OI', 'put-call-oi', (p) => p.pcoi],
  // gex/sectors: length-check the array the renderer null-guards on — a truthy object
  // with an empty by_strike/rows would otherwise emit a dead anchor
  ['Gamma exposure', 'gamma-exposure',
    (p) => (p.gex as { by_strike?: unknown[] } | null)?.by_strike?.length],
  ['Volatility setup', 'volatility-setup', (p) => p.vol],
  ['Long call viability', 'long-call-viability', (p) => p.callq],
  ['Geo backdrop', 'geopolitical-cross-asset-backdrop', (p) => p.geo],
  // predicate mirrors SecBreadth's null-guard exactly (dead-anchor rule)
  ['Market breadth', 'market-breadth', (p) => {
    const b = p.breadth as { pairs?: object | null; participation?: object | null } | null
    return b && (Object.keys(b.pairs ?? {}).length || Object.keys(b.participation ?? {}).length)
  }],
  ['Sector rotation', 'sector-rotation',
    (p) => (p.sectors as { rows?: unknown[] } | null)?.rows?.length],
  // shared predicate: SecEvents can render null even when earn/exd/macro keys exist (all
  // beyond horizon) — the old inline check emitted a dead anchor for that case
  ['Upcoming events', 'upcoming-events', hasUpcomingEvents],
  ['Thesis check', 'thesis-check', (p) => p.thesis],
  ['Notes', 'notes', (p) => (p.notes as unknown[] | null)?.length],
]

export function SectionNav({ p }: { p: Payload }) {
  const items = NAV.filter(([, , present]) => present(p))
  const [active, setActive] = useState<string | null>(null)

  // scrollspy: the active section is the last one whose header sits above the upper
  // third of the viewport — tracks what you're reading, not what crossed the bottom edge
  const anchorsKey = items.map(([, a]) => a).join(',')
  useEffect(() => {
    const anchors = anchorsKey ? anchorsKey.split(',') : []
    if (!anchors.length) return
    // cheap enough (≤ ~16 rect reads) to run unthrottled per scroll event
    const spy = () => {
      const line = window.innerHeight * 0.33
      let current: string | null = null
      for (const a of anchors) {
        const el = document.getElementById(a)
        if (el && el.getBoundingClientRect().top <= line) current = a
      }
      setActive(current)
    }
    spy()
    window.addEventListener('scroll', spy, { passive: true })
    window.addEventListener('resize', spy, { passive: true })
    return () => {
      window.removeEventListener('scroll', spy)
      window.removeEventListener('resize', spy)
    }
    // p.ticker: same anchor set for a new ticker still re-runs the spy against the
    // freshly mounted section elements
  }, [anchorsKey, p.ticker])

  if (!items.length) return null
  return (
    <nav style={{
      position: 'sticky', top: 12, fontSize: 13, lineHeight: 1.4,
      // the fix: a sticky nav taller than the viewport was clipped with no way to
      // reach the lower entries — cap it to the viewport and scroll inside
      maxHeight: 'calc(100vh - 24px)', overflowY: 'auto',
      borderLeft: '1px solid var(--border)', padding: '2px 6px 8px 0',
    }}>
      <div style={{ fontWeight: 600, margin: '0 0 6px 14px', color: 'var(--text)' }}>
        {p.ticker} — sections
      </div>
      {items.map(([label, anchor]) => {
        const on = anchor === active
        return (
          <div key={anchor} style={{
            borderLeft: `2px solid ${on ? 'var(--accent)' : 'transparent'}`,
            marginLeft: -1.5, transition: 'border-color 0.15s',
          }}>
            <a href={`#${anchor}`} style={{
              display: 'block', padding: '3px 6px 3px 12px', borderRadius: '0 6px 6px 0',
              color: on ? 'var(--text)' : 'var(--muted)',
              fontWeight: on ? 600 : 400,
              transition: 'color 0.15s',
            }}>
              {label}
            </a>
          </div>
        )
      })}
    </nav>
  )
}
