"""
Stage 1 / GATE A — is there ANY cross-sectional signal worth the rebuild? (S33)

Loads the universe, computes standard factors, and reports the Information Coefficient (IC) of each
on NON-OVERLAPPING monthly rebalances. Includes a RANDOM factor as a sanity anchor (should print
IC≈0, t-stat≈0).

GATE A passes if at least one real factor (or the equal-weight combo) shows mean |IC| >= ~0.02 with
|t-stat| > 2 out-of-sample. If nothing clears it → STOP; no cross-sectional signal worth the build.

Run:  python xs_research.py            (default 21d horizon, monthly rebalance)
"""

import sys
import numpy as np
import pandas as pd

from modules.universe import load_universe_prices
from modules.cross_sectional import (
    compute_factors, forward_relative_return, rebalance_dates,
    information_coefficient, summarize_ic,
)

HORIZON = 21   # forward trading days (≈ 1 month) — matches the monthly rebalance (non-overlapping)
STEP    = 21   # rebalance every 21 trading days → forward windows do not overlap


def main():
    prices = load_universe_prices()
    print(f"Universe: {prices.shape[1]} names, {prices.index.min().date()} -> {prices.index.max().date()} "
          f"({prices.shape[0]} dates)\n")

    factors = compute_factors(prices)
    # cross-sectional rank-normalize each factor (pct rank within each date); IC is rank-based so
    # this doesn't change single-factor IC, but it makes the equal-weight COMBO well-posed.
    ranked = {k: v.rank(axis=1, pct=True) for k, v in factors.items()}
    ranked["COMBO_eqw"] = pd.concat(ranked.values()).groupby(level=0).mean()  # avg of factor ranks
    rng = np.random.default_rng(42)
    ranked["random_ANCHOR"] = pd.DataFrame(
        rng.random(prices.shape), index=prices.index, columns=prices.columns
    )

    fwd_rel = forward_relative_return(prices, HORIZON)
    rebal = rebalance_dates(prices.index, STEP)

    print(f"Forward horizon {HORIZON}d | {len(rebal)} non-overlapping rebalances | "
          f"GATE A: |mean IC| >= 0.02 AND |t| > 2\n")
    print(f"  {'factor':<16} {'n':>4} {'mean IC':>9} {'IC-IR':>7} {'t-stat':>7} {'IC>0':>6}  verdict")
    print("  " + "-" * 70)

    results = {}
    for name, fac in ranked.items():
        ic = information_coefficient(fac, fwd_rel, rebal)
        s = summarize_ic(ic)
        results[name] = s
        passed = (abs(s["mean_ic"]) >= 0.02 and abs(s["tstat"]) > 2) if np.isfinite(s["tstat"]) else False
        tag = "  <-- signal" if (passed and "ANCHOR" not in name) else ""
        print(f"  {name:<16} {s['n']:>4} {s['mean_ic']:>+9.4f} {s['ir']:>+7.3f} "
              f"{s['tstat']:>+7.2f} {s['hit']:>5.0%}{tag}")

    real = {k: v for k, v in results.items() if "ANCHOR" not in k}
    best = max(real, key=lambda k: abs(real[k]["tstat"]) if np.isfinite(real[k]["tstat"]) else 0)
    bs = real[best]
    print("  " + "-" * 70)
    print(f"\n  Sanity: random anchor t-stat = {results['random_ANCHOR']['tstat']:+.2f} "
          f"(should be ~0 / |t|<2).")
    gate = np.isfinite(bs["tstat"]) and abs(bs["mean_ic"]) >= 0.02 and abs(bs["tstat"]) > 2
    if gate:
        print(f"  GATE A: PASS — best factor '{best}' mean IC {bs['mean_ic']:+.4f}, t {bs['tstat']:+.2f}. "
              f"Cross-sectional signal exists → proceed to Stage 2.")
    else:
        print(f"  GATE A: FAIL — best factor '{best}' only t {bs['tstat']:+.2f}. "
              f"No cross-sectional signal worth the rebuild on this universe/horizon.")
    print()


if __name__ == "__main__":
    main()
