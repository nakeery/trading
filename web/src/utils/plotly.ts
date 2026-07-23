// Shared Plotly layout bits for the client-composed section figures (the server-built
// candle/IV figs carry their own layout). Lifted from positioning.tsx so every section
// fig starts from the same dark surface.
export const DARK_LAYOUT = {
  template: 'plotly_dark',
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(14,17,23,1)',
  margin: { l: 10, r: 10, t: 10, b: 10 },
}

// The spot/price marker convention across every figure (api/charts.py price line,
// strike-walls/GEX spot lines, and the viz.tsx RangeStrip ▲).
export const SPOT_GOLD = '#e8c547'
