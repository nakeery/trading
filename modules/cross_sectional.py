"""
Cross-sectional factor + Information Coefficient engine (S33 — Stage 1, Gate A).

Time-series timing (the old framework) asks "will THIS name go up?" → ~40 independent bets.
Cross-sectional asks "which names beat their PEERS?" → one ranking problem per period across the
whole universe. This module computes standard factors, ranks them within each date's cross-section,
and measures predictive skill via the Information Coefficient (IC) — the per-period rank-correlation
between a factor and forward RELATIVE return.

Rigor note: IC is evaluated on NON-OVERLAPPING monthly rebalances so the forward windows don't
overlap and the t-stat is honest — directly applying the overlapping-window lesson from the
single-name red-team (where 570 'signals' were really ~40 independent bets).
"""

import numpy as np
import pandas as pd


def compute_factors(prices):
    """Return {factor_name: (dates × tickers) DataFrame}. Each factor is oriented so that a
    HIGHER value is the hypothesised OUTPERFORMER (positive expected IC)."""
    ret = lambda n: prices / prices.shift(n) - 1
    factors = {
        # 12-1 momentum: return from 12mo ago to 1mo ago (skip last month to avoid reversal).
        "mom_12_1":   prices.shift(21) / prices.shift(252) - 1,
        # short-term reversal: recent losers tend to bounce → negate the 5d return.
        "reversal_5": -(ret(5)),
        # low-volatility anomaly: lower realized vol → better risk-adj return → negate vol.
        "low_vol_20": -(np.log(prices / prices.shift(1)).rolling(20).std()),
        # short cross-sectional momentum (20d relative strength).
        "mom_20":     ret(20),
    }
    return factors


def forward_relative_return(prices, horizon):
    """Forward `horizon`-day return MINUS the cross-sectional mean that day (relative/peer-demeaned)."""
    fwd = prices.shift(-horizon) / prices - 1
    return fwd.sub(fwd.mean(axis=1), axis=0)


def rebalance_dates(index, step):
    """Non-overlapping rebalance dates: every `step` trading days."""
    return index[::step]


def information_coefficient(factor, fwd_rel, rebal):
    """Per-rebalance Spearman rank-corr between factor and forward relative return (across names).
    Returns a Series indexed by rebalance date (NaN dates with <5 names dropped)."""
    ics = {}
    for d in rebal:
        if d not in factor.index or d not in fwd_rel.index:
            continue
        f = factor.loc[d]
        y = fwd_rel.loc[d]
        pair = pd.concat([f, y], axis=1).dropna()
        if len(pair) < 5:
            continue
        ics[d] = pair.iloc[:, 0].corr(pair.iloc[:, 1], method="spearman")
    return pd.Series(ics).dropna()


def summarize_ic(ic):
    """Mean IC, IC information ratio (mean/std), and t-stat (IR × √n) over non-overlapping periods."""
    n = len(ic)
    if n < 3:
        return {"n": n, "mean_ic": np.nan, "ir": np.nan, "tstat": np.nan, "hit": np.nan}
    mean, std = ic.mean(), ic.std(ddof=1)
    ir = mean / std if std > 0 else np.nan
    return {
        "n": n,
        "mean_ic": mean,
        "ir": ir,
        "tstat": ir * np.sqrt(n) if np.isfinite(ir) else np.nan,
        "hit": (ic > 0).mean(),   # fraction of periods with positive IC
    }
