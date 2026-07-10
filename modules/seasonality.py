"""
Monthly seasonality — descriptive calendar base rates (S53). DISPLAY-ONLY, permanently:
seasonality is literally a calendar-time feature, the exact class the S31 leak audit banned
from models (calendar-ramp features manufactured edge on secular-uptrend names in
walk-forward). As human context it's an honest prior — "you're entering in the historically
weakest month" — as a model feature it would be poison.

Pure computation, offline-testable; the web renderer lives in lens_web.py.
"""

import pandas as pd

RECENT_YEARS = 10


def monthly_seasonality(close, min_years=10):
    """Per-calendar-month base rates from a daily Close series.

    Returns {"status": "ok"|"insufficient", "years", "months", "recent"} where `months` has
    one dict per calendar month 1..12 — {"month", "n", "up", "win", "median", "mean"} — over
    monthly close-to-close returns of the FULL history, and `recent` is the same over the
    trailing RECENT_YEARS (stability check: a month strong in both windows is a real prior;
    one that flips between windows is noise). Counts are kept alongside rates (18/25, not
    just 72%) — ~25 obs per month means wide error bars, and the display shows that. The
    in-progress calendar month is dropped (a partial month isn't a base rate).
    """
    empty = {"status": "insufficient", "years": 0.0, "months": [], "recent": []}
    if close is None or len(close) == 0:
        return empty
    s = pd.Series(close).dropna()
    if len(s) == 0:
        return empty
    s.index = pd.DatetimeIndex(s.index)
    s = s.sort_index()
    monthly = s.resample("ME").last().pct_change().dropna()
    now = pd.Timestamp.today()
    monthly = monthly[~((monthly.index.year == now.year)
                        & (monthly.index.month == now.month))]
    years = (s.index[-1] - s.index[0]).days / 365.25
    if years < min_years or len(monthly) < min_years * 10:
        return {"status": "insufficient", "years": round(years, 1),
                "months": [], "recent": []}

    def stats(rets):
        out = []
        for m in range(1, 13):
            r = rets[rets.index.month == m]
            n = int(len(r))
            up = int((r > 0).sum())
            out.append({"month": m, "n": n, "up": up,
                        "win": round(up / n, 3) if n else None,
                        "median": round(float(r.median()), 4) if n else None,
                        "mean": round(float(r.mean()), 4) if n else None})
        return out

    cutoff = monthly.index.max() - pd.DateOffset(years=RECENT_YEARS)
    return {"status": "ok", "years": round(years, 1),
            "months": stats(monthly), "recent": stats(monthly[monthly.index >= cutoff])}
