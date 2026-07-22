// Port of the CLI/Streamlit color math (lens.py _ramp/_heat/_rsi_tint stops and
// lens_web_sections.py _ramp_hex/_heat_hex/_rsi_hex/_net_color) — pure functions, so the
// web tables read exactly like the terminal ones.

export const GREEN = '#5ec45e'
export const RED = '#d83c34'
export const AMBER = '#d6ba2e'
export const BLUE = '#4ea3d8'
export const GOLD = '#e0a63a'
export const GRAY = '#9aa4b2'
export const INK = '#d8dee9'

// red · amber · green — identical stops to lens._ramp
const RAMP_STOPS: [number, number, number][] = [[216, 60, 52], [214, 186, 46], [94, 196, 94]]

// dead zones for the multi-TF heat columns (lens.HEAT_DEAD)
export const HEAT_DEAD = { rvol: 0.10, price_chg_10: 0.01, vol_trend_10: 0.05 }
export const RSI_NEUTRAL = 50.0
export const RSI_FULL = 20.0
export const RSI_DEAD = 10.0

export const ARROW: Record<string, string> = { up: '↑ up', down: '↓ dn', mixed: '~ mix' }
export const OB: Record<string, string> = { overbought: 'OB', oversold: 'OS', neutral: 'neut' }

export function rampHex(t: number): string {
  t = t < 0 ? 0 : t > 1 ? 1 : t
  const s = t < 0.5 ? 0 : 1
  const u = (t - s * 0.5) / 0.5
  const [lo, hi] = [RAMP_STOPS[s], RAMP_STOPS[s + 1]]
  const c = lo.map((l, i) => Math.round(l + (hi[i] - l) * u))
  return `#${c.map((v) => v.toString(16).padStart(2, '0')).join('')}`
}

/** Heat color with dead-zone/half-scale logic (null → no color). */
export function heatHex(
  val: number | null | undefined, neutral: number,
  halfScale: number | null, dead = 0.0,
): string | null {
  if (val == null) return null
  let d = val - neutral
  if (halfScale == null || halfScale < 1e-12 || (dead > 0 && Math.abs(d) <= dead + 1e-9)) {
    return rampHex(0.5)
  }
  d = d > 0 ? d - dead : d + dead
  return rampHex(0.5 + (0.5 * d) / halfScale)
}

/** RSI tint: oversold → green, overbought → red (contrarian), 40–60 flat amber. */
export function rsiHex(rsi: number | null | undefined): string | null {
  if (rsi == null) return null
  let d = rsi - RSI_NEUTRAL
  if (Math.abs(d) <= RSI_DEAD + 1e-9) return rampHex(0.5)
  d = d > 0 ? d - RSI_DEAD : d + RSI_DEAD
  return rampHex(0.5 - (0.5 * d) / Math.max(RSI_FULL - RSI_DEAD, 1e-9))
}

/** Verdict pill color from NET-line keywords; gray when the tilt isn't obvious. */
export function netColor(text: string | null | undefined): string {
  const t = (text ?? '').toLowerCase()
  if (['drawdown', 'risk-tilted', 'rich', 'bearish', 'selling', 'stress'].some((k) => t.includes(k))) return RED
  if (['rally', 'favorable', 'cheap', 'bullish', 'fuel', 'buying'].some((k) => t.includes(k))) return GREEN
  return GRAY
}

const SUP: Record<string, string> = { st: 'ˢᵗ', nd: 'ⁿᵈ', rd: 'ʳᵈ', th: 'ᵗʰ' }

/** Ordinal percentile display (the S49 user convention): 0–1 fraction → "97ᵗʰ"
 *  (word=true → "97ᵗʰ percentile"). Mirrors sentiment.ordinal_percentile. */
export function ordinalPercentile(pct: number | null | undefined, word = true): string {
  if (pct == null) return '—'
  const n = Math.round(pct * 100)
  const suffix =
    n % 100 >= 11 && n % 100 <= 13 ? 'th'
    : n % 10 === 1 ? 'st' : n % 10 === 2 ? 'nd' : n % 10 === 3 ? 'rd' : 'th'
  return `${n}${SUP[suffix]}${word ? ' percentile' : ''}`
}

// pc_oi label + LEAPS tenor bounds (modules/pc_oi.py)
export const LEAPS_MIN_DTE = 180
export const LEAPS_MAX_DTE = 365

export function pcLabel(pc: number | null | undefined): string {
  if (pc == null) return 'n/a'
  return pc < 0.7 ? 'heavy call interest'
    : pc < 1.0 ? 'call-leaning'
    : pc < 1.3 ? 'put-leaning'
    : 'heavy put interest'
}
