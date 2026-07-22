// Plotly React component from the FINANCE partial bundle (~1.2 MB vs ~4.5 MB full) —
// includes candlestick, bar, scatter: every trace type the LENS figures use.
// Figures arrive fully built from the API; this component renders them unchanged.
import createPlotlyComponent from 'react-plotly.js/factory'
// @ts-expect-error — the dist bundle ships no type declarations
import Plotly from 'plotly.js-finance-dist-min'
import type { PlotlyFig } from '../api/types'

const PlotlyComponent = createPlotlyComponent(Plotly)

export default function Plot({ fig }: { fig: PlotlyFig }) {
  return (
    <PlotlyComponent
      data={fig.data as never}
      layout={fig.layout as never}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%' }}
      useResizeHandler
    />
  )
}
