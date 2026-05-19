"""
VIX regime classifier — gate-only layer for SIGNAL post-hoc modification.

Three regimes derived from VIX level + VIX term-structure (VIX_VIX3M_ratio):
  calm    — VIX < REGIME_VIX_NORMAL,  no stress triggers
  normal  — REGIME_VIX_NORMAL <= VIX < REGIME_VIX_STRESS,  no stress triggers
  stress  — VIX >= REGIME_VIX_STRESS  OR  VIX_VIX3M_ratio >= REGIME_TERM_STRESS

In stress regime the gate downgrades SIGNAL one tier:
  STRONG ENTRY → CAUTION
  CAUTION      → STAY OUT
  SHORT-TERM ONLY / LEAPS ONLY / STAY OUT → unchanged

Required input columns (already produced by modules.features.compute_vix_features):
  VIX, VIX_VIX3M_ratio.  Missing values fall back to label 'normal' (neutral).

Import pattern:
    from modules.regime import (
        REGIME_VIX_NORMAL, REGIME_VIX_STRESS, REGIME_TERM_STRESS, REGIME_NAMES,
        classify_regime, is_stress_regime, apply_regime_gate,
    )
"""

import pandas as pd

# ─── Tunable thresholds ──────────────────────────────────────────────────────
REGIME_VIX_NORMAL  = 18.0   # VIX < 18 → calm
REGIME_VIX_STRESS  = 25.0   # VIX >= 25 → stress
REGIME_TERM_STRESS = 1.05   # VIX/VIX3M >= 1.05 (real backwardation) → stress (independent trigger)
                            # Matches framework's existing "term > 1.05 = stress" convention
                            # (entry.py 5-band display).  1.00 is too loose: (a) compute_vix_features
                            # fills NaN with 1.0 sentinel pre-Dec-2007 (no VIX3M history) — would
                            # falsely flag 25% of the backtest window as stress; (b) front ~ back
                            # is normal fear-noise, not real inversion.

REGIME_NAMES = ["calm", "normal", "stress"]


def classify_regime(df: pd.DataFrame) -> pd.Series:
    """Per-row regime label as a string Series aligned to df.index.

    stress  if VIX >= REGIME_VIX_STRESS  OR  VIX_VIX3M_ratio >= REGIME_TERM_STRESS
    calm    if VIX < REGIME_VIX_NORMAL  AND  not stress-triggered
    normal  otherwise

    Rows with NaN in either input column resolve to 'normal' (neutral fallback;
    avoids spurious stress triggers from missing data, never raises).
    """
    vix  = df.get("VIX")
    term = df.get("VIX_VIX3M_ratio")
    if vix is None or term is None:
        return pd.Series("normal", index=df.index)

    vix_filled  = vix.fillna(-1.0)           # sentinel below all real VIX values
    term_filled = term.fillna(0.0)            # sentinel below all real ratios

    stress = (vix_filled >= REGIME_VIX_STRESS) | (term_filled >= REGIME_TERM_STRESS)
    calm   = (vix_filled < REGIME_VIX_NORMAL) & (vix_filled >= 0.0) & ~stress

    out = pd.Series("normal", index=df.index)
    out[calm]   = "calm"
    out[stress] = "stress"
    return out


def is_stress_regime(row) -> bool:
    """Scalar helper: True iff the given row (Series with VIX + VIX_VIX3M_ratio)
    classifies as stress.  Used by entry.py for the display-only stress tells
    when the gate is OFF."""
    vix  = row.get("VIX")
    term = row.get("VIX_VIX3M_ratio")
    if pd.isna(vix) and pd.isna(term):
        return False
    if pd.notna(vix) and vix >= REGIME_VIX_STRESS:
        return True
    if pd.notna(term) and term >= REGIME_TERM_STRESS:
        return True
    return False


def apply_regime_gate(signal: str, sizing: str, regime: str):
    """One-tier-down downgrade in stress regime; mirror of IV/HV and P4 gates.

    Returns (new_signal, new_sizing, gate_msg | None).
      stress + STRONG ENTRY → ('CAUTION',  'REDUCED', msg)
      stress + CAUTION      → ('STAY OUT', 'N/A',     msg)
      anything else          → (signal, sizing, None)  unchanged
    """
    if regime != "stress":
        return signal, sizing, None

    if signal == "STRONG ENTRY":
        return "CAUTION", "REDUCED", "Regime gate: VIX stress → STRONG ENTRY downgraded"
    if signal == "CAUTION":
        return "STAY OUT", "N/A", "Regime gate: VIX stress → CAUTION downgraded"

    return signal, sizing, None
