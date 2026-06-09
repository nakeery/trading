"""
Market-context / sentiment helpers — shared band-labelers + context assembly (S29).

Centralizes the fear/positioning gauge labels that were previously inline in entry.py's
OPTIONS-MARKET CHECK (and pc_oi.py's pc_label), and assembles a consolidated per-ticker
"market context" read used by market_context.py — and, later, the backlog-#5 contrarian
sizing amplifier, which imports gather_context() directly.

Read-only: gather_context() reads the indicators CSV + (optionally) downloads the VIX complex
via modules.features.add_vix. No model training, no signal logic.

Band thresholds are kept local (mirroring entry.py's IV/HV gate + display bands) so this module
has no dependency on entry.py; entry.py/pc_oi.py can later import these labelers to DRY-unify.
"""

import os

import numpy as np
import pandas as pd

from modules.features import IV_RANK_WINDOW, compute_hv_features, add_vix
from modules.regime import (
    classify_regime, REGIME_VIX_NORMAL, REGIME_VIX_STRESS, REGIME_TERM_STRESS,
)

# IV/HV bands (mirror entry.py:74-76)
IV_HV_FAIR_LOW  = 0.85
IV_HV_FAIR_HIGH = 1.20
IV_HV_RICH      = 1.40


# ─────────────────────────────────────────────────────────────────────────────
# Band labelers (single source of truth; mirror entry.py OPTIONS-MARKET CHECK)
# ─────────────────────────────────────────────────────────────────────────────
def iv_hv_label(ratio):
    if ratio is None or pd.isna(ratio):
        return "n/a"
    if ratio < IV_HV_FAIR_LOW:  return "cheap"
    if ratio < IV_HV_FAIR_HIGH: return "fair"
    if ratio < IV_HV_RICH:      return "rich"
    return "very rich"


def iv_regime_label(iv_rank):
    if iv_rank is None or pd.isna(iv_rank):
        return "n/a"
    return "Low IV" if iv_rank < 0.33 else "High IV" if iv_rank > 0.67 else "Mid IV"


def skew_label(skew):
    if skew is None or pd.isna(skew):
        return "n/a"
    if skew < -0.02: return "call-skewed"
    if skew <  0.02: return "neutral"
    if skew <  0.05: return "put-skewed"
    return "heavy put skew"


def term_label(term):
    if term is None or pd.isna(term):
        return "n/a"
    if term >= 1.05: return "backwardation"
    if term >= 1.02: return "slight backwardation"
    if term >  0.98: return "noise"
    if term >= 0.95: return "slight contango"
    return "contango"


def pc_label(pc):
    if pc is None or pd.isna(pc):
        return "n/a"
    if pc < 0.70: return "heavy call interest"
    if pc < 1.00: return "call-leaning"
    if pc < 1.30: return "put-leaning"
    return "heavy put interest"


def percentile_of(series, value, window=IV_RANK_WINDOW):
    """Trailing-window percentile: fraction of the last `window` observations below `value`.
    Mirrors the IV_pct construction (features.py:48). Returns None if < 63 real observations
    (so thin/wiped options-gauge history degrades gracefully to 'no percentile')."""
    if value is None or pd.isna(value):
        return None
    s = pd.Series(series).dropna()
    if len(s) < 63:
        return None
    prior = s.iloc[-window:]
    return float((prior < value).mean())


# ─────────────────────────────────────────────────────────────────────────────
# Context assembly
# ─────────────────────────────────────────────────────────────────────────────
def _load_indicators(ticker, data_dir):
    path = os.path.join(data_dir, f"{ticker.lower()}_indicators.csv")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if "Ticker" in df.columns:
        df = df.drop(columns=["Ticker"])
    return df


def _net_read(atm_iv, hv_20, skew, term, pc_oi, regime):
    """One-line qualitative summary + the S21 contrarian-buy note (bridge to backlog #5)."""
    tells = []
    if atm_iv and hv_20:
        r = atm_iv / hv_20
        if r >= IV_HV_RICH:        tells.append("very rich IV")
        elif r < IV_HV_FAIR_LOW:   tells.append("cheap IV")
    if skew is not None and skew >= 0.05:  tells.append("heavy put skew")
    if term is not None and term >= 1.05:  tells.append("backwardation")
    if pc_oi is not None and pc_oi >= 1.30: tells.append("put-heavy OI")
    if regime == "stress":                  tells.append("VIX stress")
    if not tells:
        return "calm / balanced positioning — no elevated fear tells."
    return ("elevated fear / hedging: " + ", ".join(tells)
            + ".  (Framework note: in this lens stress = contrarian BUY for STRONG ENTRY — "
            "size up, don't fade; see S21.)")


def gather_context(ticker, data_dir="data", with_vix=True):
    """
    Assemble the consolidated market-context gauges for `ticker`.

    Returns dict:
      {ticker, as_of, regime, gauges: [{group, name, value, fmt, label, pct}], notes: [...], net}

    group ∈ {OPTIONS, VOL, MARKET}; pct is the trailing-1y percentile (0-1) or None.
    Never raises on data gaps — missing blocks are skipped with a note.
    """
    df = compute_hv_features(_load_indicators(ticker, data_dir))   # adds HV_20, IV_rank, IV_pct
    gauges, notes = [], []
    as_of = df.index[-1].date().isoformat()

    def last_valid(col):
        if col not in df.columns:
            return None
        s = df[col].dropna()
        return float(s.iloc[-1]) if len(s) else None

    atm_iv  = last_valid("atm_iv_30d")
    skew    = last_valid("iv_skew_25d")
    term    = last_valid("term_structure")
    pc_oi   = last_valid("put_call_oi_ratio")
    hv_20   = last_valid("HV_20")
    iv_rank = last_valid("IV_rank")
    iv_pct  = last_valid("IV_pct")

    # ── OPTIONS POSITIONING (per-ticker, harvested) ──
    if atm_iv is not None and hv_20:
        ratio = atm_iv / hv_20
        ratio_series = df["atm_iv_30d"] / df["HV_20"]
        gauges.append({"group": "OPTIONS", "name": "IV/HV ratio", "value": ratio, "fmt": "{:.2f}",
                       "label": iv_hv_label(ratio), "pct": percentile_of(ratio_series, ratio)})
        gauges.append({"group": "OPTIONS", "name": "ATM IV (30d)", "value": atm_iv, "fmt": "{:.1%}",
                       "label": "", "pct": percentile_of(df["atm_iv_30d"], atm_iv)})
    else:
        notes.append("atm_iv_30d NaN — options-IV block skipped (re-run indicators.py to harvest).")

    if skew is not None:
        gauges.append({"group": "OPTIONS", "name": "25Δ skew (P-C)", "value": skew, "fmt": "{:+.3f}",
                       "label": skew_label(skew), "pct": percentile_of(df["iv_skew_25d"], skew)})
    if term is not None:
        gauges.append({"group": "OPTIONS", "name": "Term structure", "value": term, "fmt": "{:.2f}",
                       "label": term_label(term), "pct": percentile_of(df["term_structure"], term)})
    if pc_oi is not None:
        gauges.append({"group": "OPTIONS", "name": "Put/Call OI", "value": pc_oi, "fmt": "{:.2f}",
                       "label": pc_label(pc_oi), "pct": percentile_of(df["put_call_oi_ratio"], pc_oi)})

    n_hist = int(df["iv_skew_25d"].dropna().shape[0]) if "iv_skew_25d" in df.columns else 0
    if 0 < n_hist < 63:
        notes.append(f"options-gauge history thin ({n_hist} rows) — percentiles omitted; "
                     f"re-backfill IV to enable (active TODO).")

    # ── VOLATILITY (HV-derived, full history) ──
    if hv_20 is not None:
        gauges.append({"group": "VOL", "name": "HV-20 (annualized)", "value": hv_20, "fmt": "{:.1%}",
                       "label": "", "pct": percentile_of(df["HV_20"], hv_20)})
    if iv_rank is not None:
        gauges.append({"group": "VOL", "name": "IV Rank (1y)", "value": iv_rank, "fmt": "{:.2f}",
                       "label": iv_regime_label(iv_rank), "pct": None})
    if iv_pct is not None:
        gauges.append({"group": "VOL", "name": "IV Percentile (1y)", "value": iv_pct, "fmt": "{:.0%}",
                       "label": "", "pct": None})

    # ── MARKET (VIX complex, live) ──
    regime = "n/a"
    if with_vix:
        try:
            start = df.index.min().strftime("%Y-%m-%d")
            end   = (df.index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            dfx   = add_vix(df.copy(), start, end)
            rrow  = dfx.iloc[-1]
            regime = str(classify_regime(dfx).iloc[-1])
            vix = float(rrow["VIX"]) if pd.notna(rrow.get("VIX")) else None
            v9  = float(rrow["VIX9D_VIX_ratio"]) if pd.notna(rrow.get("VIX9D_VIX_ratio")) else None
            v3m = float(rrow["VIX_VIX3M_ratio"]) if pd.notna(rrow.get("VIX_VIX3M_ratio")) else None
            if vix is not None:
                vlab = ("stress (>=25)" if vix >= REGIME_VIX_STRESS
                        else "calm (<18)" if vix < REGIME_VIX_NORMAL else "normal")
                gauges.append({"group": "MARKET", "name": "VIX", "value": vix, "fmt": "{:.1f}",
                               "label": vlab, "pct": percentile_of(dfx["VIX"], vix)})
            if v9 is not None:
                gauges.append({"group": "MARKET", "name": "VIX9D / VIX", "value": v9, "fmt": "{:.2f}",
                               "label": ("near-term fear" if v9 >= 1.0 else "calm front"), "pct": None})
            if v3m is not None:
                gauges.append({"group": "MARKET", "name": "VIX / VIX3M", "value": v3m, "fmt": "{:.2f}",
                               "label": ("term inversion" if v3m >= REGIME_TERM_STRESS else "normal term"),
                               "pct": None})
        except Exception as e:
            notes.append(f"VIX complex unavailable ({type(e).__name__}) — market block skipped.")

    net = _net_read(atm_iv, hv_20, skew, term, pc_oi, regime)
    return {"ticker": ticker.upper(), "as_of": as_of, "regime": regime,
            "gauges": gauges, "notes": notes, "net": net}
