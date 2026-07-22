"""JSON-boundary sanitizer (S60).

The gather_report payload (and most loader outputs) can carry numpy scalars, NaN/inf, and
pandas Timestamps. Python's json module emits literal ``NaN`` (invalid JSON — browsers refuse
it) and raises on numpy types, so every API response passes through sanitize() at the boundary.
Plotly figures are NOT sent through this — plotly.io.json has its own numpy/NaN-aware encoder.
"""

import datetime as _dt
import math

import numpy as np
import pandas as pd


def sanitize(obj):
    """Recursively convert `obj` into JSON-safe primitives: numpy scalars → python,
    NaN/±inf → None, ndarray/Series/Index → list, Timestamp/date → ISO string, sets/tuples
    → lists. Dict keys are coerced to str (JSON object keys must be strings)."""
    if obj is None or isinstance(obj, (bool, str, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, np.generic):                      # numpy scalar (incl. np.bool_)
        return sanitize(obj.item())
    if isinstance(obj, (pd.Timestamp, _dt.datetime, _dt.date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, (np.ndarray, pd.Series, pd.Index)):
        return [sanitize(v) for v in obj.tolist()]
    return str(obj)                                      # last resort — never raise mid-response
