"""Gate-A robustness: factor IC across horizons (non-overlapping). Disciplined check —
momentum's natural horizon is longer than 21d, so a single-horizon fail could be misleading."""
import numpy as np
from modules.universe import load_universe_prices
from modules.cross_sectional import (
    compute_factors, forward_relative_return, rebalance_dates,
    information_coefficient, summarize_ic,
)

px = load_universe_prices()
facs = {k: v.rank(axis=1, pct=True) for k, v in compute_factors(px).items()}
print(f"Universe {px.shape[1]} names | IC = mean(t-stat) on non-overlapping rebalances\n")
print(f"  {'horizon':>8}  " + "  ".join(f"{k:>16}" for k in facs))
for h in [21, 63, 126, 252]:
    fwd = forward_relative_return(px, h)
    rebal = rebalance_dates(px.index, h)
    cells = []
    for k, v in facs.items():
        s = summarize_ic(information_coefficient(v, fwd, rebal))
        cells.append(f"{s['mean_ic']:+.3f}/t{s['tstat']:+.1f}(n{s['n']})")
    print(f"  {h:>6}d   " + "  ".join(f"{c:>16}" for c in cells))
print("\n  GATE A bar: |mean IC| >= 0.02 AND |t| > 2  (and correct sign for the anomaly).")
