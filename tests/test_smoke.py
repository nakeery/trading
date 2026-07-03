"""
Smoke tests for the options trading ML pipeline.

25 regression guards:
  1. Signal hierarchy (backtest CSV) — STRONG ENTRY > CAUTION > STAY OUT by avg return
  2. STRONG ENTRY baseline sanity (backtest CSV) — count/return/win-rate loose bounds
  3. Vol thresholds range (QQQ indicators CSV) — positive values in expected ranges
  4. Signal logic unit test — determine_signal() covers all 5 label cases
  5. Threshold sensitivity (S16 regression guard) — entry.train() precision changes
     when decision_threshold changes, confirming it is actually applied
  6. Econ calendar module loads — import + ECON_FEATURE_COLS shape
  7. Days_to_* bounds — all econ proximity columns in [0, 90], integer
  8. Days_to_specific_event — hardcoded FOMC date → Days_to_FOMC matches expected
  9. Regime classification thresholds — VIX/term values map to correct regime label
 10. Regime gate logic — 5 signals × 3 regimes, one-tier-down on stress
 11. Regime classification NaN handling — missing VIX → 'normal' fallback
 12. next_event_per_series shape — returned dict has all 9 series, future dates correct
 13. upcoming_events window filter — within_days arg correctly bounds the result set
 14. sentiment labelers — IV/HV, skew, term, P/C, IV-regime bands + percentile_of behavior
 15. geocontext helpers — cross-asset stress-tail detection + composite level (offline)
 16. volquote _liquid_strike — snaps a strangle wing to the NEAREST liquid-enough OTM strike
     (S40: OI ≥ SNAP_OI_FRAC × busiest candidate; tradeable filter, OTM-side + fallback)
 17. volquote _select_expiries — earnings-aware expiry choice: two post-earnings blocks when
     nearest != nearest-monthly, one when they coincide, fallback + note when earnings far/None
 18. vol_history pre_earnings_vol_study — synthetic IV ramp → status ok (ramp>0, crush<0, P&L>0),
     all-NaN IV → insufficient_iv; backfill_iv.backfill → no_massive_key when key unset (offline)
 19. volsetup vol_setup factors — real ATM-IV percentile drives cheap/rich (HV-proxy fallback
     labeled), earnings demoted to a note when IV already high, intraday squeezes don't count (S40)
 20. timeframes live-bar append — provisional Tradier session bar appended once, skipped when the
     date is already covered; apply_live_bar re-derives the forming 1W/1M (S40 --live, offline)
 21. timeframes intraday top-up merge — Tradier hourly bars replace overlapping cached hours and
     extend the frame; empty top-up no-op (S40 --live, offline)
 22. shortint parsers + squeeze scorecard — FINRA/NASDAQ fixtures parse; CRSP-like → PRESENT,
     JPM-like → ABSENT; call-flow factor gated on pc data; caveats always (S41, offline)
 23. setupcheck checklist — marks per row from fixture reads; earnings ≤7d flags not fails;
     RS n/a degrade; rel_strength math (S41, offline)
 24. fng parser — score/rating/percentile from fixture payload; missing score → None (S41, offline)
 25. insider Form 4 — XML parse (P/S only), 30d cluster-buy detection (distinct owners), net-flow
     read + sales-are-weak caveat (S42, offline)
"""


# ─── Test 1: Signal hierarchy ─────────────────────────────────────────────────

def test_signal_hierarchy_qqq(backtest_results):
    avgs = backtest_results.groupby("signal")["fwd_return"].mean()
    for label in ("STRONG ENTRY", "CAUTION", "STAY OUT"):
        assert label in avgs.index, f"{label!r} missing from backtest results"
    assert avgs["STRONG ENTRY"] > avgs["CAUTION"], (
        f"Hierarchy broken: STRONG ENTRY {avgs['STRONG ENTRY']:.4f} <= CAUTION {avgs['CAUTION']:.4f}"
    )
    assert avgs["CAUTION"] > avgs["STAY OUT"], (
        f"Hierarchy broken: CAUTION {avgs['CAUTION']:.4f} <= STAY OUT {avgs['STAY OUT']:.4f}"
    )


# ─── Test 2: STRONG ENTRY baseline sanity ─────────────────────────────────────

def test_strong_entry_baseline_qqq(backtest_results):
    se = backtest_results[backtest_results["signal"] == "STRONG ENTRY"]
    assert len(se) >= 300, (
        f"STRONG ENTRY count too low: {len(se)} "
        f"(expected >= 300; current baseline ~570)"
    )
    avg = se["fwd_return"].mean()
    assert avg >= 0.008, (
        f"STRONG ENTRY avg return too low: {avg:.4f} "
        f"(expected >= 0.8%; current baseline ~1.8%)"
    )
    win_rate = (se["fwd_return"] > 0).mean()
    assert win_rate >= 0.55, (
        f"STRONG ENTRY win rate too low: {win_rate:.3f} "
        f"(expected >= 55%; current baseline ~64%)"
    )


# ─── Test 3: Vol thresholds range ─────────────────────────────────────────────

def test_vol_thresholds_range_qqq(df_qqq):
    from modules.features import compute_vol_thresholds
    t2, t2b, t3 = compute_vol_thresholds(df_qqq, verbose=False)
    assert 0.005 < t2 < 0.10, f"WIN_THRESHOLD out of expected range: {t2:.4f}"
    assert 0.010 < t2b < 0.20, f"WIN_THRESHOLD_63 out of expected range: {t2b:.4f}"
    assert 0.010 < t3 < 0.15, f"EXPANSION_THRESHOLD out of expected range: {t3:.4f}"
    assert t2b > t2, (
        f"WIN_THRESHOLD_63 ({t2b:.4f}) should exceed WIN_THRESHOLD ({t2:.4f}) "
        f"— check P2B_VOL_MULTIPLE hasn't regressed to 0.41"
    )


# ─── Test 4: Signal logic unit test ───────────────────────────────────────────

def test_signal_logic():
    import entry
    cases = [
        # (dir_win, dir_win_63, expansion, expected_label)
        (True,  True,  True,  "STRONG ENTRY"),
        (True,  True,  False, "CAUTION"),
        (True,  False, True,  "SHORT-TERM ONLY"),
        (True,  False, False, "SHORT-TERM ONLY"),
        (False, True,  True,  "LEAPS ONLY"),
        (False, True,  False, "LEAPS ONLY"),
        (False, False, True,  "STAY OUT"),
        (False, False, False, "STAY OUT"),
    ]
    for dir_win, dir_win_63, expansion, expected in cases:
        result = entry.determine_signal(dir_win, dir_win_63, expansion)
        assert result == expected, (
            f"determine_signal({dir_win}, {dir_win_63}, {expansion}) = {result!r}, "
            f"expected {expected!r}"
        )


# ─── Test 5: Threshold sensitivity (S16 regression guard) ─────────────────────

def test_entry_train_threshold_sensitivity(df_qqq):
    """
    S16 regression: entry.train() was computing precision at threshold 0.50
    (clf.predict() default) instead of the passed decision_threshold.
    Guard: precision must differ when threshold changes from 0.50 → 0.55.
    Uses local features only (no VIX/benchmarks) to avoid network calls.
    """
    import entry
    from modules.features import (
        compute_hv_features,
        add_trend_break_features,
        normalize_features,
        compute_vol_thresholds,
        P2_FORWARD_DAYS,
    )

    # Build minimal engineered df — no network (no VIX, no benchmarks, no earnings)
    df = compute_hv_features(df_qqq.copy())
    df = add_trend_break_features(df)   # must precede normalize_features (drops MA cols)
    df = normalize_features(df)

    win_threshold, _, _ = compute_vol_thresholds(df, verbose=False)
    future_close = df["Close"].shift(-P2_FORWARD_DAYS)
    df["direction_target"] = ((future_close / df["Close"] - 1) >= win_threshold).astype(int)
    df = df.iloc[:-P2_FORWARD_DAYS]

    _, _, _, _, prec_50, _ = entry.train(df, "direction_target", decision_threshold=0.50)
    _, _, _, _, prec_55, _ = entry.train(df, "direction_target", decision_threshold=0.55)

    assert prec_55 != prec_50, (
        f"decision_threshold has no effect on precision "
        f"(prec@0.50={prec_50:.4f}, prec@0.55={prec_55:.4f}) — "
        f"S16 regression: precision is likely being computed at a hardcoded threshold"
    )
    assert prec_55 > prec_50, (
        f"prec@0.55 ({prec_55:.4f}) <= prec@0.50 ({prec_50:.4f}): "
        f"a stricter threshold on a useful model must yield equal or higher precision"
    )
    # Gross sanity check only — stripped features (no VIX/benchmarks) depress precision below
    # the production value; we're just guarding against 0.0 or 1.0 due to a code error.
    assert 0.35 < prec_55 < 0.90, (
        f"QQQ Phase 2 precision at threshold 0.55 is implausibly outside [0.35, 0.90]: "
        f"{prec_55:.4f}"
    )


# ─── Test 6: Econ calendar module loads ───────────────────────────────────────

def test_econ_calendar_loads():
    """Import the module, sanity-check ECON_FEATURE_COLS and ALL_SERIES."""
    from modules import econ_calendar
    assert hasattr(econ_calendar, "add_macro_event_proximity"), "missing add_macro_event_proximity"
    assert hasattr(econ_calendar, "ECON_FEATURE_COLS"), "missing ECON_FEATURE_COLS"
    assert hasattr(econ_calendar, "ALL_SERIES"), "missing ALL_SERIES"
    # ECON_FEATURE_COLS = per-series + aggregate
    assert len(econ_calendar.ECON_FEATURE_COLS) == len(econ_calendar.ALL_SERIES) + 1
    assert econ_calendar.ECON_FEATURE_COLS[-1] == "Days_to_macro"
    for name, _, _ in econ_calendar.ALL_SERIES:
        assert f"Days_to_{name}" in econ_calendar.ECON_FEATURE_COLS


# ─── Test 7: Days_to_* bounds ─────────────────────────────────────────────────

def test_days_to_next_bounds(tmp_path):
    """
    Build a synthetic econ_calendar.csv with all 9 series; verify Days_to_*
    columns are integer, in [0, SENTINEL_DAYS], for a row range spanning 2026.
    No network — uses tmp_path fixture.
    """
    import pandas as pd
    from modules.econ_calendar import (
        add_macro_event_proximity, ECON_FEATURE_COLS, ALL_SERIES, SENTINEL_DAYS
    )

    # Synthetic calendar: one date per series in mid-June 2026.
    rows = []
    for i, (name, release_id, display) in enumerate(ALL_SERIES):
        tier = 1 if i < 4 else 2
        rows.append({
            "series":       name,
            "date":         f"2026-06-{15 + i:02d}",
            "release_id":   release_id,
            "release_name": display,
            "tier":         tier,
        })
    cal_path = tmp_path / "econ_calendar.csv"
    pd.DataFrame(rows).to_csv(cal_path, index=False)

    # Synthetic input DataFrame: 30 daily rows spanning early-to-mid June 2026
    idx = pd.date_range("2026-06-01", periods=30, freq="D")
    df = pd.DataFrame({"dummy": range(30)}, index=idx)
    df = add_macro_event_proximity(df, data_dir=str(tmp_path))

    for col in ECON_FEATURE_COLS:
        assert col in df.columns, f"missing column {col}"
        vals = df[col]
        assert vals.min() >= 0, f"{col} has negative values: min={vals.min()}"
        assert vals.max() <= SENTINEL_DAYS, f"{col} exceeds {SENTINEL_DAYS}: max={vals.max()}"
        # All ints (numpy ints OK)
        assert pd.api.types.is_integer_dtype(vals) or (vals % 1 == 0).all(), (
            f"{col} contains non-integer values"
        )


# ─── Test 8: Days_to_specific_event ───────────────────────────────────────────

def test_days_to_specific_event(tmp_path):
    """
    Hardcoded FOMC date 2026-06-18; row at 2026-06-11 → Days_to_FOMC == 7.
    Validates the days-to-next-event arithmetic end-to-end.
    """
    import pandas as pd
    from modules.econ_calendar import add_macro_event_proximity, SENTINEL_DAYS

    rows = [{
        "series":       "FOMC",
        "date":         "2026-06-18",
        "release_id":   326,
        "release_name": "FOMC Press Release",
        "tier":         1,
    }]
    cal_path = tmp_path / "econ_calendar.csv"
    pd.DataFrame(rows).to_csv(cal_path, index=False)

    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-06-11"),   # 7d before
        pd.Timestamp("2026-06-18"),   # day-of (0d)
        pd.Timestamp("2026-06-19"),   # 1d after — no future events → sentinel
    ])
    df = pd.DataFrame({"dummy": [0, 1, 2]}, index=idx)
    df = add_macro_event_proximity(df, data_dir=str(tmp_path))

    assert int(df.loc["2026-06-11", "Days_to_FOMC"]) == 7
    assert int(df.loc["2026-06-18", "Days_to_FOMC"]) == 0
    assert int(df.loc["2026-06-19", "Days_to_FOMC"]) == SENTINEL_DAYS
    # Days_to_macro takes min across all series — only FOMC has data so == Days_to_FOMC for this row
    assert int(df.loc["2026-06-11", "Days_to_macro"]) == 7
    # Series with no data fall back to sentinel
    assert int(df.loc["2026-06-11", "Days_to_CPI"]) == SENTINEL_DAYS


# ─── Test 9: Regime classification thresholds ────────────────────────────────

def test_classify_regime_thresholds():
    """
    Synthetic VIX + term-structure rows; verify the three regime bands fire
    where the constants say they should.  No network — pure logic test.
    """
    import pandas as pd
    from modules.regime import classify_regime

    # Row 0: VIX 12, term 0.90  → calm (low VIX, low term)
    # Row 1: VIX 20, term 0.95  → normal (between bands, no stress trigger)
    # Row 2: VIX 26, term 0.95  → stress (VIX level alone fires)
    # Row 3: VIX 19, term 1.05  → stress (term inversion alone fires, even at normal VIX)
    df = pd.DataFrame({
        "VIX":             [12.0, 20.0, 26.0, 19.0],
        "VIX_VIX3M_ratio": [0.90, 0.95, 0.95, 1.05],
    })
    labels = classify_regime(df).tolist()
    assert labels == ["calm", "normal", "stress", "stress"], (
        f"classify_regime returned {labels}; expected ['calm','normal','stress','stress']"
    )


# ─── Test 10: Regime gate logic ──────────────────────────────────────────────

def test_apply_regime_gate_logic():
    """
    5 signals × 3 regimes = 15 combinations.  Stress regime: STRONG ENTRY → CAUTION,
    CAUTION → STAY OUT, others unchanged.  Non-stress regimes: no change.
    """
    from modules.regime import apply_regime_gate, REGIME_NAMES

    signals = ["STRONG ENTRY", "CAUTION", "SHORT-TERM ONLY", "LEAPS ONLY", "STAY OUT"]
    sizings = ["FULL", "REDUCED", "REDUCED", "LEAPS", "N/A"]

    expected_stress = {
        "STRONG ENTRY":    ("CAUTION",  "REDUCED"),
        "CAUTION":         ("STAY OUT", "N/A"),
        "SHORT-TERM ONLY": ("SHORT-TERM ONLY", "REDUCED"),
        "LEAPS ONLY":      ("LEAPS ONLY",      "LEAPS"),
        "STAY OUT":        ("STAY OUT",        "N/A"),
    }

    for regime in REGIME_NAMES:
        for sig, siz in zip(signals, sizings):
            new_sig, new_siz, msg = apply_regime_gate(sig, siz, regime)
            if regime == "stress":
                exp_sig, exp_siz = expected_stress[sig]
                assert new_sig == exp_sig, (
                    f"stress + {sig}: got {new_sig!r}, expected {exp_sig!r}"
                )
                assert new_siz == exp_siz, (
                    f"stress + {sig}: sizing {new_siz!r}, expected {exp_siz!r}"
                )
                if sig in ("STRONG ENTRY", "CAUTION"):
                    assert msg is not None, f"stress + {sig} should produce a gate_msg"
                else:
                    assert msg is None, f"stress + {sig} should be no-op (msg={msg!r})"
            else:
                assert new_sig == sig and new_siz == siz and msg is None, (
                    f"{regime} + {sig}: gate fired when it shouldn't have "
                    f"(got {new_sig!r}/{new_siz!r}, msg={msg!r})"
                )


# ─── Test 11: Regime classification NaN handling ─────────────────────────────

def test_classify_regime_handles_nan():
    """
    Rows missing VIX or VIX_VIX3M_ratio must NOT raise and must fall back to
    'normal' (neutral) — required for the older pre-VIX9D/VIX3M history (pre-2007).
    """
    import pandas as pd
    import numpy as np
    from modules.regime import classify_regime

    df = pd.DataFrame({
        "VIX":             [np.nan, 26.0, np.nan, 12.0],
        "VIX_VIX3M_ratio": [0.90,    np.nan, np.nan, 0.95],
    })
    labels = classify_regime(df).tolist()
    # Row 0: VIX NaN, term 0.90        → no stress trigger, no calm-eligibility (VIX missing) → normal
    # Row 1: VIX 26,  term NaN         → stress fires on VIX alone
    # Row 2: VIX NaN, term NaN         → no stress, no calm → normal (neutral fallback)
    # Row 3: VIX 12,  term 0.95        → calm (full data path)
    assert labels == ["normal", "stress", "normal", "calm"], (
        f"NaN handling broken: got {labels}; expected ['normal','stress','normal','calm']"
    )

    # Missing-columns path: pass a df with neither VIX nor VIX_VIX3M_ratio
    df_empty = pd.DataFrame({"dummy": [1, 2, 3]})
    labels_empty = classify_regime(df_empty).tolist()
    assert labels_empty == ["normal", "normal", "normal"], (
        f"Missing-columns path: got {labels_empty}; expected all 'normal'"
    )


# ─── Test 12: next_event_per_series shape ────────────────────────────────────

def test_next_event_per_series_shape(tmp_path):
    """
    Synthetic CSV with FOMC, CPI dates; assert dict has 9 keys (one per
    ALL_SERIES), FOMC/CPI return correct (date, days), other 7 series fall
    back to (None, SENTINEL_DAYS).  No network.
    """
    import pandas as pd
    from modules.econ_calendar import (
        next_event_per_series, ALL_SERIES, SENTINEL_DAYS
    )

    # Two future events at known offsets from a fixed as_of date.
    as_of = pd.Timestamp("2026-06-01")
    rows = [
        {"series": "FOMC", "date": "2026-06-08", "release_id": 101,
         "release_name": "FOMC Press Release", "tier": 1},
        {"series": "CPI",  "date": "2026-06-15", "release_id": 10,
         "release_name": "Consumer Price Index", "tier": 1},
    ]
    cal_path = tmp_path / "econ_calendar.csv"
    pd.DataFrame(rows).to_csv(cal_path, index=False)

    result = next_event_per_series(as_of=as_of, data_dir=str(tmp_path))

    # Shape: exactly one entry per series in ALL_SERIES.
    assert len(result) == len(ALL_SERIES), (
        f"expected {len(ALL_SERIES)} entries, got {len(result)}"
    )
    for name, _, _ in ALL_SERIES:
        assert name in result, f"missing series {name}"

    # Known events return correct (date, days).
    fomc_date, fomc_days = result["FOMC"]
    assert fomc_days == 7, f"FOMC expected 7d, got {fomc_days}"
    assert fomc_date == pd.Timestamp("2026-06-08")

    cpi_date, cpi_days = result["CPI"]
    assert cpi_days == 14, f"CPI expected 14d, got {cpi_days}"
    assert cpi_date == pd.Timestamp("2026-06-15")

    # Series with no rows in synthetic CSV → (None, SENTINEL_DAYS).
    for missing_name in ("NFP", "PCE", "PPI", "GDP", "Retail", "JOLTS", "Claims"):
        d, days = result[missing_name]
        assert d is None and days == SENTINEL_DAYS, (
            f"{missing_name} expected (None, {SENTINEL_DAYS}); got ({d!r}, {days})"
        )

    # Missing-CSV path: every series resolves to (None, SENTINEL_DAYS).
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    missing = next_event_per_series(as_of=as_of, data_dir=str(empty_dir))
    assert len(missing) == len(ALL_SERIES)
    for name, _, _ in ALL_SERIES:
        d, days = missing[name]
        assert d is None and days == SENTINEL_DAYS


# ─── Test 13: upcoming_events window filter ──────────────────────────────────

def test_upcoming_events_window_filter(tmp_path):
    """
    Three synthetic events at +3d, +10d, +25d.  Verify within_days correctly
    bounds the result and the DataFrame columns are populated.
    """
    import pandas as pd
    from modules.econ_calendar import upcoming_events

    as_of = pd.Timestamp("2026-06-01")
    rows = [
        {"series": "Claims", "date": "2026-06-04", "release_id": 180,
         "release_name": "Unemployment Insurance Weekly Claims Report", "tier": 2},
        {"series": "CPI",    "date": "2026-06-11", "release_id": 10,
         "release_name": "Consumer Price Index", "tier": 1},
        {"series": "FOMC",   "date": "2026-06-26", "release_id": 101,
         "release_name": "FOMC Press Release", "tier": 1},
    ]
    cal_path = tmp_path / "econ_calendar.csv"
    pd.DataFrame(rows).to_csv(cal_path, index=False)

    # 7-day window: only Claims (+3d) qualifies.
    df_7 = upcoming_events(within_days=7, as_of=as_of, data_dir=str(tmp_path))
    assert len(df_7) == 1, f"7d window expected 1 event, got {len(df_7)}"
    assert df_7.iloc[0]["series"] == "Claims"
    assert df_7.iloc[0]["days_to"] == 3

    # 14-day window: Claims + CPI, chronological order.
    df_14 = upcoming_events(within_days=14, as_of=as_of, data_dir=str(tmp_path))
    assert len(df_14) == 2
    assert df_14["series"].tolist() == ["Claims", "CPI"]
    assert df_14["days_to"].tolist() == [3, 10]

    # 30-day window: all three events.
    df_30 = upcoming_events(within_days=30, as_of=as_of, data_dir=str(tmp_path))
    assert len(df_30) == 3
    assert df_30["series"].tolist() == ["Claims", "CPI", "FOMC"]
    assert df_30["days_to"].tolist() == [3, 10, 25]

    # Required columns present + populated.
    for col in ("date", "weekday", "days_to", "tier", "series", "release_name"):
        assert col in df_30.columns, f"missing column {col}"
    assert df_30["weekday"].iloc[0] == "Thu"  # 2026-06-04 is a Thursday

    # Missing-CSV path: empty DataFrame, no exception.
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    df_missing = upcoming_events(within_days=7, as_of=as_of, data_dir=str(empty_dir))
    assert df_missing.empty


# ─── Test 14: sentiment labelers ──────────────────────────────────────────────
def test_sentiment_labels():
    """modules/sentiment.py band-labelers map values to the correct band, handle NaN, and
    percentile_of degrades to None on thin history. These labelers are the single source of
    truth shared by market_context.py and entry.py's OPTIONS-MARKET CHECK (S29)."""
    import numpy as np
    import pandas as pd
    from modules.sentiment import (
        iv_hv_label, iv_regime_label, skew_label, term_label, pc_label, percentile_of,
    )

    assert iv_hv_label(0.80) == "cheap"
    assert iv_hv_label(1.00) == "fair"
    assert iv_hv_label(1.30) == "rich"
    assert iv_hv_label(1.50) == "very rich"

    assert skew_label(-0.03) == "call-skewed"
    assert skew_label(0.00)  == "neutral"
    assert skew_label(0.03)  == "put-skewed"
    assert skew_label(0.06)  == "heavy put skew"

    assert term_label(0.94) == "contango"
    assert term_label(0.96) == "slight contango"
    assert term_label(1.00) == "noise"
    assert term_label(1.03) == "slight backwardation"
    assert term_label(1.06) == "backwardation"

    assert pc_label(0.60) == "heavy call interest"
    assert pc_label(0.90) == "call-leaning"
    assert pc_label(1.10) == "put-leaning"
    assert pc_label(1.40) == "heavy put interest"

    assert iv_regime_label(0.20) == "Low IV"
    assert iv_regime_label(0.50) == "Mid IV"
    assert iv_regime_label(0.80) == "High IV"

    # NaN → "n/a" for every labeler
    for fn in (iv_hv_label, iv_regime_label, skew_label, term_label, pc_label):
        assert fn(float("nan")) == "n/a"

    # percentile_of: enough history → fraction strictly below the value
    s = pd.Series(np.arange(100.0))                 # 0..99
    assert abs(percentile_of(s, 90.0) - 0.90) < 1e-6
    # thin history (< 63 obs) → None
    assert percentile_of(pd.Series([1.0, 2.0, 3.0]), 2.0) is None
    # NaN value → None
    assert percentile_of(s, float("nan")) is None


# ─── Test 15: geocontext composite + stress (offline) ─────────────────────────
def test_geocontext_composite_and_stress():
    """modules/geocontext.py pure helpers: stress-tail detection per direction + the composite
    level/read from how many gauges fire. No network (the fetch path is not smoke-tested)."""
    from modules.geocontext import _stressed, _composite

    # stress-tail detection (high = top tail; low = bottom tail)
    assert _stressed("high", 0.85) is True
    assert _stressed("high", 0.50) is False
    assert _stressed("low", 0.10) is True
    assert _stressed("low", 0.50) is False
    assert _stressed("high", None) is False        # missing percentile is never "stress"

    # composite level by count of firing gauges
    assert _composite([{"name": "WTI crude", "stress": False}])[0] == "LOW"

    two = [{"name": "WTI crude", "stress": True}, {"name": "Gold", "stress": True},
           {"name": "Semis (SOX)", "stress": False}]
    level2, comp2 = _composite(two)
    assert level2 == "ELEVATED"
    assert "WTI crude" in comp2 and "Gold" in comp2

    assert _composite([{"name": f"g{i}", "stress": True} for i in range(4)])[0] == "HIGH"


# ─── Test 16: volquote _liquid_strike (offline) ───────────────────────────────
def test_liquid_strike_snap():
    """modules/volquote._liquid_strike snaps a strangle wing to the NEAREST liquid-enough of the
    SNAP_K OTM strikes closest to the target (S40 rule: OI ≥ SNAP_OI_FRAC × busiest candidate,
    then closest-to-target, OI tie-break) — dead strikes are still skipped, but lumpy round-number
    OI no longer drags the wing off target (the live NVDA 190-vs-185 case). Prefers tradeable
    strikes, respects the OTM side, falls back to the plain nearest when no OTM strikes exist."""
    from modules.volquote import _liquid_strike, SNAP_K, SNAP_OI_FRAC

    def opt(strike, oi, bid, ask, typ="call"):
        return {"type": typ, "strike": strike, "bid": bid, "ask": ask, "oi": oi}

    spot = 100.0
    # Calls just OTM: 101 is closest to the target but nearly dead; 102 is the liquid neighbor.
    calls = [opt(101, 1, 0.02, 2.00), opt(102, 500, 1.00, 1.10), opt(103, 50, 0.50, 0.60)]
    picked = _liquid_strike(calls, target=101.5, spot=spot, side="call")
    assert picked["strike"] == 102, f"expected the liquid 102 strike, got {picked['strike']}"

    # A near strike with huge OI but no live market (bid/ask 0) must be skipped for a tradeable one.
    calls2 = [opt(110, 9999, 0.0, 0.0), opt(109, 200, 1.00, 1.10), opt(108, 100, 0.80, 0.95)]
    picked2 = _liquid_strike(calls2, target=110.0, spot=spot, side="call")
    assert picked2["strike"] == 109, f"untradeable 110 should be skipped, got {picked2['strike']}"

    # OTM side is respected: for a put wing, only strikes < spot are eligible (never the 101 call-side).
    puts = [opt(99, 100, 1.0, 1.1, "put"), opt(98, 200, 0.9, 1.0, "put"), opt(101, 999, 1.0, 1.1, "put")]
    picked3 = _liquid_strike(puts, target=98.5, spot=spot, side="put")
    assert picked3["strike"] == 98 and picked3["strike"] < spot

    # Fallback: no OTM strikes on that side → plain nearest (closest to target regardless of side).
    below = [opt(95, 10, 0.5, 0.6), opt(96, 10, 0.5, 0.6)]
    picked4 = _liquid_strike(below, target=105.0, spot=spot, side="call")
    assert picked4["strike"] == 96, "fallback should return the strike nearest the target"

    # S40: a nearest strike with ≥ SNAP_OI_FRAC of the busiest candidate's OI must WIN over a
    # farther, busier one (the live NVDA case: 185/OI 21k lost to 190/OI 39k under pure max-OI).
    calls3 = [opt(105, 300, 1.00, 1.05), opt(106, 500, 0.90, 0.95), opt(107, 100, 0.70, 0.80)]
    picked5 = _liquid_strike(calls3, target=105.0, spot=spot, side="call")
    assert picked5["strike"] == 105, f"liquid-enough nearest should win, got {picked5['strike']}"

    # S40: on an all-thin chain, tiny OI differences are noise — the nearest tradeable wins
    # (the live CRSP case: 45/OI 42 lost to 42.5/OI 47 under pure max-OI).
    puts2 = [opt(97, 5, 0.5, 0.7, "put"), opt(96, 7, 0.4, 0.6, "put"), opt(95, 4, 0.3, 0.5, "put")]
    picked6 = _liquid_strike(puts2, target=96.8, spot=spot, side="put")
    assert picked6["strike"] == 97, f"nearest of comparably-thin strikes should win, got {picked6['strike']}"

    assert SNAP_K >= 2            # the snap window must span more than the single closest strike
    assert 0 < SNAP_OI_FRAC <= 1  # the busiest candidate must always qualify (pick can't fail)


# ─── Test 17: volquote _select_expiries (offline) ─────────────────────────────
def test_select_expiries_earnings_aware():
    """modules/volquote._select_expiries: when earnings is near, anchor to POST-earnings expiries —
    the nearest one plus the nearest post-earnings monthly when they differ (two blocks), one when
    they coincide; and fall back to the near-monthly ~target_dte with a note when earnings is far or
    unknown. Pure logic, no network."""
    import datetime
    from modules.volquote import _select_expiries, EARN_WINDOW

    # July 2026 3rd Friday = 17th; Aug 2026 3rd Friday = 21st (both monthlies).
    future = [("2026-07-17", 16), ("2026-07-24", 23), ("2026-07-31", 30), ("2026-08-21", 51)]

    # (a) Earnings 2026-07-20 (19d out): nearest post = 07-24 (weekly), nearest post monthly = 08-21.
    selected, notes = _select_expiries(future, 30, datetime.date(2026, 7, 20), 19)
    assert notes == []
    assert len(selected) == 2, f"expected two post-earnings blocks, got {len(selected)}"
    assert selected[0][0] == "2026-07-24" and selected[0][2] == "post-earnings weekly"
    assert selected[0][3] == 4, f"days_after_earn expected 4, got {selected[0][3]}"
    assert selected[1][0] == "2026-08-21" and selected[1][2] == "post-earnings monthly"
    assert selected[1][3] == 32

    # (b) Earnings 2026-07-10 (9d out): nearest post IS the 07-17 monthly → one block, no dup.
    selected_b, notes_b = _select_expiries(future, 30, datetime.date(2026, 7, 10), 9)
    assert len(selected_b) == 1 and selected_b[0][0] == "2026-07-17"
    assert selected_b[0][2] == "post-earnings monthly"

    # (c) Earnings beyond the window → fallback near-monthly ~target_dte + an explanatory note.
    selected_c, notes_c = _select_expiries(future, 30, datetime.date(2026, 9, 1), EARN_WINDOW + 15)
    assert len(selected_c) == 1 and selected_c[0][2] == "monthly" and selected_c[0][3] is None
    assert selected_c[0][0] == "2026-07-17"  # closest monthly to target_dte=30
    assert notes_c and "beyond" in notes_c[0]

    # (d) No earnings date → fallback + note.
    selected_d, notes_d = _select_expiries(future, 30, None, None)
    assert len(selected_d) == 1 and selected_d[0][2] == "monthly"
    assert notes_d and "no earnings date" in notes_d[0]


# ─── Test 18: pre-earnings vol study + backfill graceful (offline) ────────────
def test_pre_earnings_vol_study(tmp_path, monkeypatch):
    """modules/vol_history.pre_earnings_vol_study measures the pre-earnings IV ramp / crush /
    straddle P&L off atm_iv_30d with INJECTED earnings (no network): a synthetic ramp → status
    'ok' with ramp>0, crush<0, straddle P&L>0 (flat spot, so the ramp must beat theta); all-NaN IV
    → 'insufficient_iv'. And the refactored backfill_iv.backfill degrades to 'no_massive_key'
    (no network) when the key is unset — the graceful path for an unpaid/absent Massive subscription."""
    import numpy as np
    import pandas as pd
    from modules.vol_history import pre_earnings_vol_study

    idx = pd.bdate_range("2025-01-02", periods=150)
    earn_pos = [30, 70, 110]
    earnings = [idx[p] for p in earn_pos]

    def iv_at(pos):
        nxt = min((e for e in earn_pos if e >= pos), default=None)
        if nxt is not None and nxt - pos <= 15:
            return 0.30 + 0.40 * (1 - (nxt - pos) / 15.0)    # ramp UP into the report
        prev = max((e for e in earn_pos if e < pos), default=None)
        if prev is not None and pos - prev <= 3:
            return 0.35                                       # crushed just after
        return 0.30

    df = pd.DataFrame({"Close": 100.0,
                       "atm_iv_30d": [iv_at(i) for i in range(len(idx))]}, index=idx)
    csv = tmp_path / "testx_indicators.csv"
    df.to_csv(csv)

    study = pre_earnings_vol_study("TESTX", data_dir=str(tmp_path), earnings=earnings)
    assert study["status"] == "ok", study
    agg = study["agg"]
    assert agg["n"] == 3, f"expected 3 usable earnings, got {agg['n']}"
    assert agg["ramp_median"] > 0.10, f"expected a clear IV ramp, got {agg['ramp_median']}"
    assert agg["crush_median"] < 0, f"expected a post-earnings crush, got {agg['crush_median']}"
    assert agg["pnl_median"] is not None and agg["pnl_median"] > 0, (
        f"a strong ramp with flat spot should net a positive straddle P&L, got {agg['pnl_median']}"
    )
    assert "IV ramped" in study["summary"]

    # All-NaN IV → insufficient (this is what drives the backfill offer / the lens note).
    df_na = df.copy(); df_na["atm_iv_30d"] = np.nan
    df_na.to_csv(csv)
    study_na = pre_earnings_vol_study("TESTX", data_dir=str(tmp_path), earnings=earnings)
    assert study_na["status"] == "insufficient_iv", study_na

    # backfill_iv.backfill degrades cleanly with no Massive key (no network reached).
    import backfill_iv
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    recent = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=20)
    pd.DataFrame({"Close": 100.0, "atm_iv_30d": np.nan}, index=recent).to_csv(
        tmp_path / "testy_indicators.csv")
    res = backfill_iv.backfill("TESTY", data_dir=str(tmp_path))
    assert res["status"] == "no_massive_key", res


# ─── Test 19: volsetup vol_setup factor logic (offline) ───────────────────────
def test_vol_setup_factors():
    """modules/volsetup.vol_setup (S40): the IV cheap/rich factor uses the REAL ATM-IV percentile
    (gauge pct) when harvested history exists, falling back to the HV-20 proxy with an explicit
    '(HV-proxy)' label; the earnings catalyst is demoted to a note when IV already ranks high
    (event premium priced); intraday-only squeezes no longer count as a factor (daily+ do)."""
    from modules.volsetup import vol_setup, IV_PCT_HIGH

    def ctx(iv_pct=None, hv_rank=None):
        gauges = [{"group": "OPTIONS", "name": "ATM IV (30d)", "value": 0.60,
                   "fmt": "{:.1%}", "label": "", "pct": iv_pct}]
        if hv_rank is not None:
            gauges.append({"group": "VOL", "name": "IV Rank (HV-proxy)", "value": hv_rank,
                           "fmt": "{:.2f}", "label": "", "pct": None})
        return {"gauges": gauges}

    earn = {"days": 40, "date": "2026-08-10", "hist_move": 0.076}
    sq_4h = {"4h": {"ok": True, "squeeze_on": True}}
    sq_1d = {"1D": {"ok": True, "squeeze_on": True}}

    # (a) The CRSP case: real IV at its highs + 4h-only squeeze + earnings near → NO long-vol
    # factors (squeeze off-horizon, earnings priced → note), one short-vol factor, no clear edge.
    s = vol_setup(None, sq_4h, ctx(iv_pct=0.97), earnings=earn)
    assert s["long_vol"] == [], f"expected no long-vol factors, got {s['long_vol']}"
    assert len(s["short_vol"]) == 1 and "97%ile" in s["short_vol"][0]
    assert s["notes"] and "premium likely priced" in s["notes"][0]
    assert "no clear vol edge" in s["net"]

    # (b) Cheap real IV + daily squeeze + earnings → three long-vol factors, BUY verdict,
    # S38-aligned hint (exit before the print, not "size for the crush").
    s = vol_setup(None, sq_1d, ctx(iv_pct=0.20), earnings=earn)
    assert len(s["long_vol"]) == 3 and any("20%ile" in f for f in s["long_vol"])
    assert any("squeeze ON (1D)" in f for f in s["long_vol"])
    assert s["short_vol"] == [] and s["notes"] == []
    assert "BUYING vol" in s["net"] and "exit BEFORE the print" in s["hint"]

    # (c) No real-IV percentile (thin history) → HV-proxy fallback, explicitly labeled; the
    # earnings factor stays unconditional when the real-IV read is unavailable.
    s = vol_setup(None, {}, ctx(iv_pct=None, hv_rank=IV_PCT_HIGH + 0.05), earnings=earn)
    assert len(s["short_vol"]) == 1 and "HV-proxy" in s["short_vol"][0]
    assert any("known vol catalyst" in f for f in s["long_vol"])

    # (d) Intraday-only squeeze produces no factor; the same squeeze on 1W does.
    assert not any("squeeze ON" in f for f in vol_setup(None, sq_4h, ctx())["long_vol"])
    on_1w = vol_setup(None, {"1W": {"ok": True, "squeeze_on": True}}, ctx())["long_vol"]
    assert any("squeeze ON (1W)" in f for f in on_1w)


# ─── Test 20: timeframes live-bar append (offline) ────────────────────────────
def test_append_live_bar():
    """modules/timeframes.append_live_bar (S40 --live): appends the provisional Tradier session bar
    to a daily frame only when the frame doesn't already cover that date; apply_live_bar re-derives
    1W/1M so the forming week/month absorb the live bar. Pure logic, no network."""
    import pandas as pd
    from modules.timeframes import append_live_bar, apply_live_bar, _resample

    idx = pd.bdate_range("2026-06-01", "2026-06-30")            # daily frame ends Tue 06-30
    daily = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5,
                          "Volume": 1e6}, index=idx)
    bar = {"ts": pd.Timestamp("2026-07-01"), "Open": 101.0, "High": 103.0, "Low": 100.5,
           "Close": 102.5, "Volume": 4e5, "in_progress": True, "hhmm": "12:41"}

    d2, ok = append_live_bar(daily, bar)
    assert ok and len(d2) == len(daily) + 1
    assert d2.index[-1] == bar["ts"] and float(d2["Close"].iloc[-1]) == 102.5

    # already covered (post-close stamp ran) → untouched
    d3, ok3 = append_live_bar(d2, bar)
    assert not ok3 and len(d3) == len(d2)
    assert not append_live_bar(daily, None)[1]                  # no bar → no-op

    # apply_live_bar re-derives W/M: the forming July month bar must appear with the live close.
    frames = {"1D": daily, "1W": _resample(daily, "W-FRI"), "1M": _resample(daily, "ME")}
    assert apply_live_bar(frames, bar)
    assert frames["1D"].index[-1] == bar["ts"]
    assert frames["1M"].index[-1].month == 7 and float(frames["1M"]["Close"].iloc[-1]) == 102.5
    assert float(frames["1W"]["Close"].iloc[-1]) == 102.5


# ─── Test 21: timeframes intraday top-up merge (offline) ──────────────────────
def test_merge_intraday_topup():
    """modules/timeframes.merge_intraday_topup (S40 --live): Tradier-derived hourly bars REPLACE
    overlapping cached hours (the cached tail may be a partial hour) and extend past the cached
    end; empty top-up is a no-op. Pure logic, no network."""
    import pandas as pd
    from modules.timeframes import merge_intraday_topup

    def hourly(ts_list, closes, vols):
        return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                             "Close": closes, "Volume": vols},
                            index=pd.DatetimeIndex(ts_list))

    cached = hourly(["2026-07-02 09:30", "2026-07-02 10:30", "2026-07-02 11:30"],
                    [100.0, 101.0, 101.5], [1000, 900, 50])       # 11:30 = partial hour, tiny vol
    topup = hourly(["2026-07-02 11:30", "2026-07-02 12:30"],
                   [102.0, 103.0], [800, 700])                    # complete 11:30 + new 12:30

    merged, n = merge_intraday_topup(cached, topup)
    assert n == 2 and len(merged) == 4
    assert float(merged.loc["2026-07-02 11:30", "Close"]) == 102.0    # replaced, not duplicated
    assert float(merged.loc["2026-07-02 11:30", "Volume"]) == 800
    assert merged.index[-1] == pd.Timestamp("2026-07-02 12:30")
    assert merged.index.is_monotonic_increasing and not merged.index.duplicated().any()

    same, n0 = merge_intraday_topup(cached, cached.iloc[0:0])         # empty top-up → no-op
    assert n0 == 0 and same is cached


# ─── Test 22: shortint parsers + squeeze scorecard (offline) ──────────────────
def test_shortint_squeeze():
    """modules/shortint (S41): the FINRA/NASDAQ parsers on literal fixtures, and the pure
    squeeze_read scorecard — CRSP-like inputs → SQUEEZE CONDITIONS PRESENT with the expected fuel
    factors; JPM-like inputs → ABSENT with counter factors; caveats always present."""
    from modules.shortint import parse_finra_text, parse_si_payload, squeeze_read

    finra = ("Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
             "20260701|CRSP|243764.846662|3373|426621.138652|B,Q,N\n"
             "20260701|CRSQ|10|0|20|B\n")
    row = parse_finra_text(finra, "CRSP")
    assert row is not None and abs(row[0] / row[1] - 0.5714) < 0.001
    assert parse_finra_text(finra, "ZZZZ") is None                # absent symbol → None

    payload = {"data": {"shortInterestTable": {"rows": [
        {"settlementDate": "06/15/2026", "interest": "26,572,400",
         "avgDailyShareVolume": "1,625,617", "daysToCover": 16.34604},
        {"settlementDate": "05/29/2026", "interest": "21,672,640",
         "avgDailyShareVolume": "1,858,354", "daysToCover": 11.662265},
    ]}}}
    rows = parse_si_payload(payload)
    assert len(rows) == 2 and rows[0]["settle_date"] == "2026-06-15"
    assert rows[0]["dtc"] > 16 and rows[0]["interest"] == 26572400.0

    # CRSP-like: extreme DTC + shorts adding + high SVR pctile into a rally + LVN overhead.
    r = squeeze_read(dtc=16.3, si_chg=0.226, settle_date="2026-06-15", settle_age=17,
                     svr_now=0.57, svr_pct=0.85, svr_n=90, chg_1d=0.055, chg_5d=0.08,
                     rvol=2.0, lvn_above_pct=0.013)
    assert "PRESENT" in r["net"], r["net"]
    assert any("EXTREME" in f for f in r["fuel"])
    assert any("ADDING" in f for f in r["fuel"])
    assert any("underwater" in f for f in r["fuel"])
    assert any("thin-volume air" in f for f in r["fuel"])
    assert r["counter"] == [] and len(r["caveats"]) >= 3
    assert any("bi-monthly" in c for c in r["caveats"])

    # JPM-like: low DTC, covering, subdued short volume → ABSENT with counters.
    r2 = squeeze_read(dtc=1.4, si_chg=-0.15, svr_now=0.42, svr_pct=0.15, svr_n=90,
                      chg_1d=0.002, chg_5d=0.01, rvol=0.9)
    assert "ABSENT" in r2["net"] and r2["fuel"] == [] and len(r2["counter"]) == 3

    # call-flow factor only fires when pc data is present and vol is call-heavy vs OI.
    r3 = squeeze_read(pc_oi=0.90, pc_vol=0.30)
    assert any("call-heavy" in f for f in r3["fuel"])
    assert not any("call-heavy" in f for f in squeeze_read(pc_oi=0.90, pc_vol=0.80)["fuel"])


# ─── Test 23: setupcheck checklist (offline) ──────────────────────────────────
def test_setup_check():
    """modules/setupcheck.setup_check (S41): marks per row from fixture reads/profile/ctx —
    aligned trends ✓, unconfirmed rally ✗, RS n/a degrade, earnings ≤7d flags (–) without
    failing, very-rich IV ✗. Pure, no network."""
    from modules.setupcheck import setup_check, rel_strength
    import pandas as pd

    def reads(trend="up", rsi=55, tag="up-confirmed"):
        state = "overbought" if rsi >= 70 else "oversold" if rsi <= 30 else "neutral"
        return {tf: {"trend": trend, "rsi": rsi, "rsi_state": state, "_vol": {"tag": tag}}
                for tf in ("1D", "1W", "1M")}

    profile = {"price_location": "in_value", "near_hvn_below": 55.2, "price": 58.7,
               "lvns": [59.5]}
    ctx = {"regime": "calm", "gauges": [{"name": "IV/HV ratio", "value": 1.1}]}

    s = setup_check(reads(), profile=profile, ctx=ctx,
                    earn={"days": 39, "date": "2026-08-10"}, macro_tier1_days=5,
                    rs={"bench": "IBB", "rs": {20: 0.04, 63: 0.09}})
    marks = {label: m for label, m, _ in s["rows"]}
    assert marks["HTF alignment"] == "✓" and marks["Volume confirms"] == "✓"
    assert marks["Relative strength"] == "✓" and marks["Catalyst timing"] == "✓"
    assert s["n_bad"] == 0 and "7/7" in s["net"]

    # unconfirmed rally + rich vol + imminent earnings + macro tomorrow
    s2 = setup_check(reads(tag="up-WEAK"), profile=profile,
                     ctx={"regime": "calm", "gauges": [{"name": "IV/HV ratio", "value": 1.55}]},
                     earn={"days": 3, "date": "2026-07-05"}, macro_tier1_days=1, rs=None)
    m2 = {label: m for label, m, _ in s2["rows"]}
    assert m2["Volume confirms"] == "✗" and m2["Vol regime"] == "✗"
    assert m2["Catalyst timing"] == "–"                       # flagged, NOT failed
    assert m2["Relative strength"] == "–"                     # n/a degrade
    assert s2["n_bad"] == 2

    # rel_strength math
    c = pd.Series(range(100, 200), dtype=float)               # steady climber
    b = pd.Series([100.0] * 100)                              # flat benchmark
    rs = rel_strength(c, b, horizons=(20,))
    assert rs and rs[20] > 0


# ─── Test 24: fng parser (offline) ────────────────────────────────────────────
def test_fng_parse():
    """modules/fng.parse_fng (S41): score/rating extracted, percentile computed off the payload's
    own history (needs ≥63 points), missing score → None. Pure, no network."""
    from modules.fng import parse_fng

    hist = [{"x": i, "y": float(20 + (i % 60))} for i in range(200)]   # scores 20..79
    payload = {"fear_and_greed": {"score": 75.0, "rating": "greed", "previous_close": 70.0},
               "fear_and_greed_historical": {"data": hist}}
    out = parse_fng(payload)
    assert out and out["score"] == 75.0 and out["rating"] == "greed"
    assert out["pct"] is not None and out["pct"] > 0.85                # 75 is high in 20..79

    assert parse_fng({"fear_and_greed": {}}) is None
    assert parse_fng(None) is None


# ─── Test 25: insider Form 4 parse + cluster detection (offline) ──────────────
def test_insider_form4():
    """modules/insider (S42): parse_form4 extracts open-market P/S events from Form 4 XML (other
    codes skipped); cluster_buys finds ≥2 distinct insiders inside 30d but not 60d apart;
    insider_read nets flow, surfaces the cluster and keeps the sales-are-weak caveat."""
    from modules.insider import parse_form4, cluster_buys, insider_read

    def form4(owner, date, code, shares, price, extra_tx=""):
        return f"""<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>{owner}</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>0</isOfficer></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>{date}</value></transactionDate>
      <transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>{shares}</value></transactionShares>
        <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>{extra_tx}
  </nonDerivativeTable>
</ownershipDocument>"""

    ev = parse_form4(form4("DOE JANE", "2026-06-20", "P", 12000, 51.20))
    assert len(ev) == 1 and ev[0]["code"] == "P" and ev[0]["owner"] == "DOE JANE"
    assert ev[0]["usd"] == 12000 * 51.20 and ev[0]["role"] == "Director"

    # non-open-market codes (M = option exercise, A = grant) are excluded
    assert parse_form4(form4("DOE JANE", "2026-06-20", "M", 5000, 10.0)) == []
    assert parse_form4("<not-xml") == []

    # cluster: two distinct owners within 30d fires; 60d apart doesn't; same owner twice doesn't.
    def buy(owner, date, usd=100000.0):
        return {"date": date, "code": "P", "shares": 1000, "price": usd / 1000,
                "usd": usd, "owner": owner, "role": "Director"}

    cl = cluster_buys([buy("A", "2026-05-12"), buy("B", "2026-06-02")])
    assert cl and cl["n_owners"] == 2 and cl["start"] == "2026-05-12" and cl["end"] == "2026-06-02"
    assert cluster_buys([buy("A", "2026-04-01"), buy("B", "2026-06-20")]) is None
    assert cluster_buys([buy("A", "2026-05-12"), buy("A", "2026-06-02")]) is None

    # read: cluster present → conviction NET; net flow arithmetic; caveats retained.
    sell = {"date": "2026-06-25", "code": "S", "shares": 500, "price": 60.0,
            "usd": 30000.0, "owner": "C", "role": "Officer"}
    rd = insider_read([buy("A", "2026-05-12"), buy("B", "2026-06-02"), sell])
    assert "PRESENT" in rd["net"] and rd["cluster"]["n_owners"] == 2
    assert rd["net_usd"] == 100000.0 + 100000.0 - 30000.0
    assert rd["n_buys"] == 2 and rd["n_sells"] == 1
    assert any("Lakonishok" in c for c in rd["caveats"])

    rd2 = insider_read([sell])
    assert "sales only" in rd2["net"]
    assert insider_read([])["net"].startswith("no open-market")
