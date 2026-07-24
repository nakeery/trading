"""
Stage 1 / GATE B — does GARCH forecast vol better than naive persistence? (S33)

Walk-forward (refit every `STEP` days): at each rebalance, fit GARCH(1,1) on history and forecast
the average annualized vol over the next H days. Compare to (a) NAIVE persistence (trailing H-day
HV carried forward) and (b) the ACTUAL realized vol over the next H days.

GATE B passes if GARCH beats naive persistence out-of-sample (lower RMSE AND higher correlation
with realized vol). Independent of Gate A — the vol upgrade can ship even if cross-sectional fails.

Run:  python garch_research.py            (defaults QQQ JPM AAPL)
      python garch_research.py QQQ
"""

import os
import sys
import numpy as np
import pandas as pd

from modules.garch_vol import garch_forecast_vol, TRADING_DAYS

H = 21      # forecast horizon (trading days)
STEP = 21   # refit / evaluate every 21 days (non-overlapping forward windows)


def evaluate(prices_ticker, label):
    px = prices_ticker.dropna()
    logret = np.log(px / px.shift(1)).dropna()
    n = len(logret)
    rows = []
    # walk forward: need history before t and H days after t. (EGARCH deferred — its multi-step
    # forecast needs simulation in `arch`; plain GARCH already characterizes the vol upgrade.)
    for i in range(1500, n - H, STEP):
        hist = logret.iloc[:i]
        g = garch_forecast_vol(hist, H, vol_model="GARCH")
        naive = hist.iloc[-H:].std(ddof=0) * np.sqrt(TRADING_DAYS)          # trailing HV
        actual = logret.iloc[i:i + H].std(ddof=0) * np.sqrt(TRADING_DAYS)   # forward realized
        if all(np.isfinite(x) for x in (g, naive, actual)):
            rows.append((g, naive, actual))
    if len(rows) < 20:
        print(f"  {label}: too few windows ({len(rows)})")
        return
    g, naive, actual = (np.array(x) for x in zip(*rows))
    rmse = lambda a, b: np.sqrt(np.mean((a - b) ** 2))
    corr = lambda a, b: np.corrcoef(a, b)[0, 1]
    g_rmse, n_rmse = rmse(g, actual), rmse(naive, actual)
    g_corr, n_corr = corr(g, actual), corr(naive, actual)
    win = (g_rmse < n_rmse) and (g_corr > n_corr)
    print(f"\n  {label}  (n={len(rows)} non-overlapping {H}d windows)")
    print(f"    forecast vs realized vol     RMSE        corr")
    print(f"    GARCH(1,1)                  {g_rmse:>6.3f}     {g_corr:>+5.2f}")
    print(f"    naive persistence (HV)      {n_rmse:>6.3f}     {n_corr:>+5.2f}")
    print(f"    -> GARCH {'BEATS' if win else 'does NOT beat'} naive "
          f"(RMSE {(n_rmse - g_rmse) / n_rmse:+.0%}, corr {g_corr - n_corr:+.2f})")
    return win


if __name__ == "__main__":
    tickers = [t.upper() for t in sys.argv[1:]] or ["QQQ", "JPM", "NVDA"]
    print("GATE B — GARCH vs naive persistence (out-of-sample vol forecasting)")
    wins = []
    for t in tickers:
        path = os.path.join("data", f"{t.lower()}_indicators.csv")
        if not os.path.exists(path):
            print(f"\n  {t}: no indicators CSV — skipping")
            continue
        close = pd.read_csv(path, index_col=0, parse_dates=True)["Close"]
        wins.append(evaluate(close, t))
    done = [w for w in wins if w is not None]
    print(f"\n  GATE B: GARCH beat naive on {sum(1 for w in done if w)}/{len(done)} tickers.")
