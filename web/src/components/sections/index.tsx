// Ordered section renderer — the render_all analogue. Every section is wrapped in a
// SectionBoundary so one bad payload slice degrades to a warning instead of a blank page
// (the ANSI report below stays the lossless fallback). SectionNav mirrors the sidebar
// quick-nav: an entry appears only when the payload carries that section.
import type { Payload } from '../../api/types'
import { SectionBoundary } from '../shared'
import {
  SecBackdrop, SecDivergences, SecMultiTf, SecRisk, SecSetup, SecVolumeProfile,
} from './core'
import { SecGeo, SecOptions } from './gauges'
import { SecBuzz, SecGex, SecInsider, SecPcOi, SecSqueeze, SecStreet } from './positioning'
import { SecCall, SecVol } from './volcall'
import { SecCatalysts, SecMacro, SecNotes, SecSectors, SecThesis } from './misc'

// print_report order (sec_header is rendered by the chart block instead — skip_header)
const SECTIONS: [string, ({ p }: { p: Payload }) => React.ReactElement | null][] = [
  ['market backdrop', SecBackdrop],
  ['multi-timeframe', SecMultiTf],
  ['divergences', SecDivergences],
  ['volume profile', SecVolumeProfile],
  ['rally vs drawdown', SecRisk],
  ['setup check', SecSetup],
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
  ['sector rotation', SecSectors],
  ['known catalysts', SecCatalysts],
  ['macro', SecMacro],
  ['thesis check', SecThesis],
  ['notes', SecNotes],
]

export default function Sections({ p }: { p: Payload }) {
  return (
    <>
      {SECTIONS.map(([name, Fn]) => (
        <SectionBoundary key={name} name={name}>
          <Fn p={p} />
        </SectionBoundary>
      ))}
    </>
  )
}

// (label, anchor slug, payload presence check) — mirrors the Streamlit sidebar list
const NAV: [string, string, (p: Payload) => unknown][] = [
  ['Market backdrop', 'market-backdrop', (p) => p.backdrop],
  ['Multi-timeframe', 'multi-timeframe', (p) => p.reads],
  ['Volume profile', 'volume-profile', (p) => p.profile],
  ['Rally vs drawdown', 'rally-vs-drawdown-risk', (p) => p.risk],
  ['Setup check', 'setup-check', (p) => p.setup],
  ['Options & vol', 'options-vol-context', (p) => p.ctx],
  ['Short/squeeze', 'short-positioning-squeeze', (p) => p.squeeze],
  ['Retail attention', 'retail-attention', (p) => p.buzz && !p.squeeze],
  ['Insider activity', 'insider-activity', (p) => p.insider],
  ['Street & news', 'street-news', (p) => p.street],
  ['Put/call OI', 'put-call-oi', (p) => p.pcoi],
  ['Gamma exposure', 'gamma-exposure', (p) => p.gex],
  ['Volatility setup', 'volatility-setup', (p) => p.vol],
  ['Long call viability', 'long-call-viability', (p) => p.callq],
  ['Geo backdrop', 'geopolitical-cross-asset-backdrop', (p) => p.geo],
  ['Sector rotation', 'sector-rotation', (p) => p.sectors],
  // NB: [] is truthy in JS (falsy in Python) — length-check array-valued sections
  ['Known catalysts', 'known-catalysts', (p) => (p.cats as unknown[] | null)?.length],
]

export function SectionNav({ p }: { p: Payload }) {
  const items = NAV.filter(([, , present]) => present(p))
  if (!items.length) return null
  return (
    <nav style={{
      position: 'sticky', top: 12, fontSize: 13, lineHeight: 1.9,
      borderLeft: '1px solid var(--border)', paddingLeft: 12,
    }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{p.ticker} — sections</div>
      {items.map(([label, anchor]) => (
        <div key={anchor}>
          <a href={`#${anchor}`} style={{ color: 'var(--muted)' }}>{label}</a>
        </div>
      ))}
    </nav>
  )
}
