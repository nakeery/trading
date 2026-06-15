"""
GARCH conditional-volatility forecasting (S33 — Stage 1, Gate B).

The framework's most genuinely-real signal is volatility (Phase 3). It currently predicts HV
"expansion" with a LogReg classifier on price features. GARCH (ML4T Ch9) is the textbook-correct
model for the exact phenomenon Phase 3 exploits — volatility clustering. This module forecasts
H-day-ahead annualized vol via GARCH(1,1), to test (Gate B) whether it beats naive persistence
(HV stays the same), which is the standard bar a vol model must clear.

Uses the `arch` package. Returns are scaled ×100 (percent) for the optimizer's numerical stability.
"""

import numpy as np
import pandas as pd
from arch import arch_model

TRADING_DAYS = 252


def _ann_vol_from_daily_var_pct(daily_var_pct):
    """Convert mean daily variance (in pct^2, from ×100 returns) to annualized vol (decimal)."""
    return np.sqrt(daily_var_pct) / 100.0 * np.sqrt(TRADING_DAYS)


def garch_forecast_vol(log_returns, horizon, lookback=1500, vol_model="GARCH"):
    """Fit a GARCH-family model on the trailing `lookback` log-returns and forecast the average
    annualized vol over the next `horizon` days. `vol_model`: "GARCH" (symmetric) or "EGARCH"
    (asymmetric — captures the equity leverage effect). Returns decimal annualized vol or NaN."""
    r = log_returns.dropna()
    if len(r) < 250:
        return np.nan
    r = r.iloc[-lookback:] * 100.0   # percent scale
    try:
        kw = dict(mean="Constant", vol=vol_model, p=1, q=1, dist="normal")
        if vol_model == "EGARCH":
            kw["o"] = 1   # asymmetry term (leverage effect)
        res = arch_model(r, **kw).fit(disp="off")
        fc = res.forecast(horizon=horizon, reindex=False)
        daily_var = fc.variance.values[-1]          # H daily variance forecasts (pct^2)
        return _ann_vol_from_daily_var_pct(daily_var.mean())
    except Exception:
        return np.nan


def realized_vol(log_returns, window):
    """Annualized realized vol over a trailing/forward window of log-returns (decimal)."""
    return log_returns.std(ddof=0) * np.sqrt(TRADING_DAYS) if len(log_returns) > 1 else np.nan
