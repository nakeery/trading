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

# A harvested gauge whose last valid row lags the CSV end by more than this many sessions is
# flagged "(stale Nd)" — gather_context uses last-non-NaN per column, so a stopped Massive
# harvest would otherwise present weeks-old IV/skew/term as current (S43).
STALE_GAUGE_SESSIONS = 5

# CBOE tail-risk bands (S56; display-only — never model features). SKEW ≈100 = lognormal
# baseline, ≥150 = heavy OTM-put tail bid; VVIX long-run range roughly 80–120.
SKEW_LOW, SKEW_HIGH = 130.0, 150.0
VVIX_LOW, VVIX_HIGH = 85.0, 110.0


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


def spark_of(series, window=IV_RANK_WINDOW, points=60):
    """Trailing-`window` slice of a gauge's own series downsampled to ≤`points` floats — the
    sparkline behind the percentile (S50 web UI). Same ≥63-obs floor as percentile_of so a spark
    never appears without its percentile. Sampled from the END backwards so the latest value
    always survives. Plain list (payload stays picklable); [] when too thin."""
    s = pd.Series(series).dropna()
    if len(s) < 63:
        return []
    s = s.iloc[-window:]
    step = max(1, -(-len(s) // points))                # ceil → result never exceeds `points`
    return [float(v) for v in s.iloc[::-1][::step][::-1]]


_SUP = {"st": "ˢᵗ", "nd": "ⁿᵈ", "rd": "ʳᵈ", "th": "ᵗʰ"}


def ordinal_percentile(pct, word=True):
    """0–1 fraction → '97ᵗʰ percentile' (S49 display convention: ordinal number, Unicode
    superscript suffix — renders in terminals and in st.dataframe cells, which escape HTML —
    the word 'percentile' in full, no % sign). 11/12/13 take ᵗʰ. None → ''."""
    if pct is None:
        return ""
    n = int(round(pct * 100))
    suf = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{_SUP[suf]}" + (" percentile" if word else "")


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


def gap_gauges(df):
    """PURE (S64): overnight-gap context off the indicators CSV's gap columns (gap_pct /
    gap_ma_5d / gap_vol_5d — written by indicators.py since S1, previously unconsumed).
    Display-only, never a model feature. The percentile is of |gap_pct| — a −2% and a +2% gap
    are equally unusual; the SIGNED gap is still what's displayed. The label carries the gap
    bar's date so a pre-market run showing yesterday's open gap is unambiguous. The indicators
    today-row (NaN OHLCV, appended for the IV stamp) has a NaN gap, so dropna naturally lands
    on the last real session. Missing columns / all-NaN → []. Offline-testable."""
    out = []
    if "gap_pct" not in df.columns:
        return out
    s = df["gap_pct"].dropna()
    if not len(s):
        return out
    gap, gap_d = float(s.iloc[-1]), s.index[-1]
    abs_s = s.abs()
    lbl = f"{pd.Timestamp(gap_d):%b %d} open"
    if "gap_ma_5d" in df.columns:
        m = df["gap_ma_5d"].dropna()
        if len(m):
            lbl += f" · 5d avg {float(m.iloc[-1]):+.2%}"
    out.append({"group": "VOL", "name": "Gap at open", "value": gap, "fmt": "{:+.2%}",
                "label": lbl, "pct": percentile_of(abs_s, abs(gap)), "spark": spark_of(abs_s)})
    if "gap_vol_5d" in df.columns:
        gv_s = df["gap_vol_5d"].dropna()
        if len(gv_s):
            gv = float(gv_s.iloc[-1])
            out.append({"group": "VOL", "name": "Gap vol (5d)", "value": gv, "fmt": "{:.2%}",
                        "label": "avg |overnight gap|", "pct": percentile_of(gv_s, gv),
                        "spark": spark_of(gv_s)})
    return out


def gather_context(ticker, data_dir="data", with_vix=True, as_of=None):
    """
    Assemble the consolidated market-context gauges for `ticker`.

    Returns dict:
      {ticker, as_of, regime, gauges: [{group, name, value, fmt, label, pct}], notes: [...], net}

    group ∈ {OPTIONS, VOL, MARKET}; pct is the trailing-1y percentile (0-1) or None.
    Never raises on data gaps — missing blocks are skipped with a note.
    `as_of` (S57 — historical/backtest mode): truncate the indicators frame to that date, so
    every gauge, percentile, spark, and stale flag reads as it stood then (no lookahead). The
    VIX complex refetches for the truncated window (decades of history — fully historical);
    SKEW/VVIX only reach ~2y back (period-limited fetch) and drop out silently beyond that.
    """
    df = compute_hv_features(_load_indicators(ticker, data_dir))   # adds HV_20, IV_rank, IV_pct
    # asof_ts = the historical-mode flag; `as_of` is reused below as the display stamp, so the
    # parameter must not be tested after this point (the SKEW/VVIX cut ran on EVERY run before)
    asof_ts = pd.Timestamp(as_of).normalize() if as_of is not None else None
    if asof_ts is not None:
        df = df.loc[:asof_ts]
        if len(df) == 0:
            raise ValueError(f"no {ticker} indicator rows on/before {as_of}")
    gauges, notes = [], []
    as_of = df.index[-1].date().isoformat()

    def last_valid(col):
        """(value, index_date) of the column's last non-NaN row — (None, None) when absent/empty."""
        if col not in df.columns:
            return None, None
        s = df[col].dropna()
        return (float(s.iloc[-1]), s.index[-1]) if len(s) else (None, None)

    stale_ages = []

    def _stale(d):
        """' (stale Nd)' when a harvested gauge's last valid row lags the CSV end by more than
        STALE_GAUGE_SESSIONS sessions — a stopped Massive harvest would otherwise present a
        weeks-old IV/skew/term as current (S43). '' when fresh/unknown."""
        if d is None:
            return ""
        age = int((df.index > d).sum())
        if age <= STALE_GAUGE_SESSIONS:
            return ""
        stale_ages.append(age)
        return f" (stale {age}d)"

    atm_iv, atm_iv_d = last_valid("atm_iv_30d")
    atm_iv_l, atm_iv_l_d = last_valid("atm_iv_180d")
    skew,   skew_d   = last_valid("iv_skew_25d")
    term,   term_d   = last_valid("term_structure")
    pc_oi,  pc_oi_d  = last_valid("put_call_oi_ratio")
    hv_20,  _        = last_valid("HV_20")
    iv_rank, _       = last_valid("IV_rank")
    iv_pct,  _       = last_valid("IV_pct")

    # ── OPTIONS POSITIONING (per-ticker, harvested) ──
    if atm_iv is not None and hv_20:
        ratio = atm_iv / hv_20
        ratio_series = df["atm_iv_30d"] / df["HV_20"]
        iv_stale = _stale(atm_iv_d)
        gauges.append({"group": "OPTIONS", "name": "IV/HV ratio", "value": ratio, "fmt": "{:.2f}",
                       "label": iv_hv_label(ratio) + iv_stale,
                       "pct": percentile_of(ratio_series, ratio),
                       "spark": spark_of(ratio_series)})
        gauges.append({"group": "OPTIONS", "name": "ATM IV (30d)", "value": atm_iv, "fmt": "{:.1%}",
                       "label": iv_stale.strip(), "pct": percentile_of(df["atm_iv_30d"], atm_iv),
                       "spark": spark_of(df["atm_iv_30d"])})
    else:
        notes.append("atm_iv_30d NaN — options-IV block skipped (re-run indicators.py to "
                     "harvest; requires an active Massive subscription).")

    # ~180d ATM IV (S47) — the LEAPS-entry tenor. Label shows the ratio to the front tenor
    # (long-dated vol blends quiet weeks, so an event-bid front reads >1x its 180d). Percentile
    # accumulates forward-only (column added S47; no backfill possible at long tenors).
    if atm_iv_l is not None:
        ratio_lbl = f"{atm_iv_l / atm_iv:.2f}x front" if atm_iv else ""
        gauges.append({"group": "OPTIONS", "name": "ATM IV (180d)", "value": atm_iv_l,
                       "fmt": "{:.1%}", "label": (ratio_lbl + _stale(atm_iv_l_d)).strip(),
                       "pct": percentile_of(df["atm_iv_180d"], atm_iv_l),
                       "spark": spark_of(df["atm_iv_180d"])})

    if skew is not None:
        gauges.append({"group": "OPTIONS", "name": "25Δ skew (P-C)", "value": skew, "fmt": "{:+.3f}",
                       "label": skew_label(skew) + _stale(skew_d),
                       "pct": percentile_of(df["iv_skew_25d"], skew),
                       "spark": spark_of(df["iv_skew_25d"])})
    if term is not None:
        gauges.append({"group": "OPTIONS", "name": "Term structure", "value": term, "fmt": "{:.2f}",
                       "label": term_label(term) + _stale(term_d),
                       "pct": percentile_of(df["term_structure"], term),
                       "spark": spark_of(df["term_structure"])})
    if pc_oi is not None:
        gauges.append({"group": "OPTIONS", "name": "Put/Call OI", "value": pc_oi, "fmt": "{:.2f}",
                       "label": pc_label(pc_oi) + _stale(pc_oi_d),
                       "pct": percentile_of(df["put_call_oi_ratio"], pc_oi),
                       "spark": spark_of(df["put_call_oi_ratio"])})
    if stale_ages:
        notes.append(f"harvested options gauges lag the CSV by up to {max(stale_ages)} sessions "
                     f"(flagged 'stale') — re-run indicators.py to refresh the Massive harvest "
                     f"(requires an active Massive subscription).")

    n_hist = int(df["iv_skew_25d"].dropna().shape[0]) if "iv_skew_25d" in df.columns else 0
    if 0 < n_hist < 63:
        notes.append(f"options-gauge history thin ({n_hist} rows) — percentiles omitted; "
                     f"re-backfill IV to enable (active TODO).")

    # ── VOLATILITY (HV-derived, full history) ──
    if hv_20 is not None:
        gauges.append({"group": "VOL", "name": "HV-20 (annualized)", "value": hv_20, "fmt": "{:.1%}",
                       "label": "", "pct": percentile_of(df["HV_20"], hv_20),
                       "spark": spark_of(df["HV_20"])})
    # NOTE: IV_rank/IV_pct are the HV-20 PROXY (features.py) — realized vol's position in its own
    # 1y range, NOT the harvested ATM IV's. Named accordingly so they can't be read as real IV (S40).
    if iv_rank is not None:
        gauges.append({"group": "VOL", "name": "IV Rank (HV-proxy)", "value": iv_rank, "fmt": "{:.2f}",
                       "label": iv_regime_label(iv_rank), "pct": None})
    if iv_pct is not None:
        gauges.append({"group": "VOL", "name": "IV Pctile (HV-proxy)", "value": iv_pct, "fmt": "{:.0%}",
                       "label": "", "pct": None})

    # ── overnight gap (S64) — indicators.py's gap columns (harvested since S1, previously
    # unconsumed). Display-only context; sits after the as-of truncation so it is historically
    # valid in --as-of mode for free.
    gauges.extend(gap_gauges(df))

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
                               "label": vlab, "pct": percentile_of(dfx["VIX"], vix),
                               "spark": spark_of(dfx["VIX"])})
            if v9 is not None:
                gauges.append({"group": "MARKET", "name": "VIX9D / VIX", "value": v9, "fmt": "{:.2f}",
                               "label": ("near-term fear" if v9 >= 1.0 else "calm front"), "pct": None})
            if v3m is not None:
                gauges.append({"group": "MARKET", "name": "VIX / VIX3M", "value": v3m, "fmt": "{:.2f}",
                               "label": ("term inversion" if v3m >= REGIME_TERM_STRESS else "normal term"),
                               "pct": None})
        except Exception as e:
            notes.append(f"VIX complex unavailable ({type(e).__name__}) — market block skipped.")

        # ── CBOE tail-risk pair (S56) — SKEW (OTM-put tail pricing) + VVIX (vol-of-vol).
        # Display-only context, NEVER a model feature (S31 lesson); own try so a fetch miss
        # never costs the VIX gauges above.
        try:
            import yfinance as yf
            tail = yf.download(["^SKEW", "^VVIX"], period="2y", interval="1d",
                               progress=False, auto_adjust=True)["Close"]
            sk = tail["^SKEW"].dropna() if "^SKEW" in tail else pd.Series(dtype=float)
            vv = tail["^VVIX"].dropna() if "^VVIX" in tail else pd.Series(dtype=float)
            if asof_ts is not None:                    # 2y fetch window — empty beyond it → skipped
                def _cut(s):
                    if not len(s):
                        return s
                    c = asof_ts
                    if getattr(s.index, "tz", None) is not None:
                        c = c.tz_localize(s.index.tz)
                    return s.loc[:c]
                sk, vv = _cut(sk), _cut(vv)
            if len(sk):
                v = float(sk.iloc[-1])
                gauges.append({"group": "MARKET", "name": "SKEW (CBOE)", "value": v,
                               "fmt": "{:.0f}",
                               "label": ("tail hedging elevated (>=150)" if v >= SKEW_HIGH
                                         else "tail premium low (<130)" if v < SKEW_LOW
                                         else "typical"),
                               "pct": percentile_of(sk, v), "spark": spark_of(sk)})
            if len(vv):
                v = float(vv.iloc[-1])
                gauges.append({"group": "MARKET", "name": "VVIX (vol-of-vol)", "value": v,
                               "fmt": "{:.0f}",
                               "label": ("vol-of-vol stress (>=110)" if v >= VVIX_HIGH
                                         else "vol-of-vol becalmed (<85)" if v < VVIX_LOW
                                         else "typical"),
                               "pct": percentile_of(vv, v), "spark": spark_of(vv)})
        except Exception:
            notes.append("SKEW/VVIX unavailable — tail-risk gauges skipped.")

    net = _net_read(atm_iv, hv_20, skew, term, pc_oi, regime)
    return {"ticker": ticker.upper(), "as_of": as_of, "regime": regime,
            "gauges": gauges, "notes": notes, "net": net}
