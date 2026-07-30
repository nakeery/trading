"""
Smoke tests for the options trading ML pipeline.

41 regression guards:
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
 26. timeframes last_bar_partial calendar check — a Thu forming week / late-month forming month is
     partial even when the bar count clears frac; weekend month-end labels roll back; the count
     heuristic still catches stale mid-period data (S43, offline)
 27. backfill_iv _apply_result — writes only NaN cells: a date revisited for a missing
     term_structure keeps its harvested atm_iv_30d (S44, offline)
 28. massive pick_event_atm + vol_history _iv_triplet — earliest post-earnings expiry ATM chosen,
     iv=20 placeholder rejected; event IV used only when all three sessions have it (never mixes
     tenors within one ramp), 30d fallback otherwise (S44, offline)
 29. breadth read_breadth — equal-weight leading → broad-led, lagging → narrow, flat → mixed
     (±0.5% dead band); percentile off the rolling 20d-spread series; short pairs omitted
     (S45, offline)
 30. callquote pure helpers — pick_call_candidates (ATM + ~0.375Δ, no-bid strikes skipped),
     liquidity_grade bands (tight/ok/wide/dead + OI floor), curve_read cheap-tenor tag,
     _select_expiries monthly-nearest-45/90 (S46, offline)
 31. beta_corr (2x-levered clone → β≈2 corr≈1; independent → low corr; short → None),
     estimate_next_ex_div cadence estimator (quarterly → +~91d; irregular/thin → None),
     upcoming_catalysts window + ticker filter (S46, offline)
 32. massive _atm_at_tenor — the ~180d LEAPS-tenor ATM pick: nearest-to-target expiry dominates
     strike distance, iv=20 placeholder rejected, empty → None (S47, offline)
 33. lens print_report candle_style="none" — the candle panel is skipped (lens_web draws a real
     chart instead) while the header/sections still render; guards the S48 render_ticker
     extraction's print path (offline)
 34. lens render_payload — byte-equal to a direct print_report call from the same payload;
     guards the S49 compute/format split's forwarding (offline)
 35. print_report risk=/macro_events= kwargs — supplied vs unsupplied byte-equal; guards the
     S49 lifted-compute defaults (offline)
 36. gather_report payload contract — full key set, no pandas objects (the web payload is
     pickled by st.cache_data); network helpers monkeypatched off (S49, offline)
 37. pc_oi strike_profile — per-strike put/call OI aggregation, ±band spot filter, sort,
     strike-less/empty degrade; feeds the web OI-walls chart (S50, offline)
 38. sentiment spark_of — gauge sparkline series: last value always sampled, ≥63-obs floor
     mirrors percentile_of, NaNs dropped (S50, offline)
 39. econ_calendar headline_result — release-date → reference-period matching (monthly lag,
     JOLTS 2-month lag, weekly ≤8d window, quarterly, FOMC pre/post rate) + display kinds;
     future/missing obs → None (S52, offline)
 40. seasonality monthly_seasonality — per-month win counts/medians on a synthetic 20y series
     with a known monthly pattern, counts-not-percents, 10y recent window, in-progress-month
     drop is structural, <10y → insufficient (S53, offline)
 41. vol_history earnings_reactions — gap/1d/5d math, AMC/BMO larger-|move| session pick,
     d5 None at the history edge, atm_iv_event-over-30d pre_iv fallback, future dates
     ignored, no-earnings/no-csv statuses (S53, offline)
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
    import pytest
    entry = pytest.importorskip("entry")  # archived to archive/ml_pipeline/ — skips when moved
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
    import pytest
    entry = pytest.importorskip("entry")  # archived to archive/ml_pipeline/ — skips when moved
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
        ordinal_percentile,
    )

    # ordinal-superscript percentile display (S49): 1→ˢᵗ 2→ⁿᵈ 3→ʳᵈ, 11/12/13→ᵗʰ, None→''
    assert ordinal_percentile(0.97) == "97ᵗʰ percentile"
    assert ordinal_percentile(0.21) == "21ˢᵗ percentile"
    assert ordinal_percentile(0.42) == "42ⁿᵈ percentile"
    assert ordinal_percentile(0.43) == "43ʳᵈ percentile"
    assert ordinal_percentile(0.11) == "11ᵗʰ percentile"
    assert ordinal_percentile(0.13) == "13ᵗʰ percentile"
    assert ordinal_percentile(0.03, word=False) == "3ʳᵈ"
    assert ordinal_percentile(None) == ""

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
    assert len(s["short_vol"]) == 1 and "97ᵗʰ percentile" in s["short_vol"][0]
    assert s["notes"] and "premium likely priced" in s["notes"][0]
    assert "no clear vol edge" in s["net"]

    # (b) Cheap real IV + daily squeeze + earnings → three long-vol factors, BUY verdict,
    # S38-aligned hint (exit before the print, not "size for the crush").
    s = vol_setup(None, sq_1d, ctx(iv_pct=0.20), earnings=earn)
    assert len(s["long_vol"]) == 3 and any("20ᵗʰ percentile" in f for f in s["long_vol"])
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

    # (e) S43: the implied-vs-realized `em` factor was removed — em.pct/em.hv_pct reduces to the
    # same atm_iv/HV_20 ratio as the IV/HV factor, so it double-counted one input (2-factor margin).
    em_cheap = {"pct": 0.05, "hv_pct": 0.10, "dte": 30}
    with_em = vol_setup(None, {}, ctx(iv_pct=0.20), earnings=earn, em=em_cheap)
    without = vol_setup(None, {}, ctx(iv_pct=0.20), earnings=earn)
    assert with_em["long_vol"] == without["long_vol"]
    assert not any("implied move" in f for f in with_em["long_vol"] + with_em["short_vol"])


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


# ─── Test 26: timeframes last_bar_partial calendar check (offline) ────────────
def test_last_bar_partial_calendar():
    """modules/timeframes.last_bar_partial (S43): the count heuristic (frac=0.7) missed a Thu/Fri
    forming week and a late-month forming month — the calendar check (period end vs the most recent
    completed session, injectable via now_session) flags them; weekend month-end labels roll back to
    the last weekday so a complete month isn't misflagged; stale mid-period data still trips the
    count fallback. Pure logic, no network."""
    import pandas as pd
    from modules.timeframes import last_bar_partial

    def daily(end):
        idx = pd.bdate_range("2026-01-05", end)
        return pd.DataFrame({"Close": 100.0}, index=idx)

    thu = pd.Timestamp("2026-06-25")                              # Thursday
    # forming week, 4 bars: count heuristic alone said complete (4 ≥ 0.7×5) — calendar says partial
    assert last_bar_partial(daily(thu), "1W", now_session=thu) is True
    # after Friday's close the week is complete
    fri = pd.Timestamp("2026-06-26")
    assert last_bar_partial(daily(fri), "1W", now_session=fri) is False
    # late-month forming month (18 of ~22 June sessions ≥ 0.7×typical) → calendar says partial
    assert last_bar_partial(daily(thu), "1M", now_session=thu) is True
    # month-end session close → complete
    eom = pd.Timestamp("2026-06-30")                              # Tuesday, last June session
    assert last_bar_partial(daily(eom), "1M", now_session=eom) is False
    # weekend month-end label (May 2026 ends Sunday) rolls back to Friday → complete, not misflagged
    may_end = pd.Timestamp("2026-05-29")                          # Friday, last May session
    assert last_bar_partial(daily(may_end), "1M", now_session=may_end) is False
    # stale data ending mid-week long ago: calendar can't fire, the count fallback still does
    stale_end = pd.Timestamp("2026-06-10")                        # Wednesday, 3-bar final week
    assert last_bar_partial(daily(stale_end), "1W", now_session=pd.Timestamp("2026-07-06")) is True


# ─── Test 27: backfill_iv per-cell no-overwrite (offline) ─────────────────────
def test_backfill_apply_result():
    """backfill_iv._apply_result (S44): the work list selects dates missing atm_iv_30d OR
    term_structure, so a date revisited only for its missing term_structure must NOT have its
    harvested quote-based atm_iv_30d replaced by the trades-based inversion value. Only NaN
    cells are written; None values never write. Pure, no network."""
    import pandas as pd
    from backfill_iv import _apply_result

    df = pd.DataFrame(
        {"atm_iv_30d": [0.63, None], "term_structure": [None, None], "iv_skew_25d": [0.02, None]},
        index=pd.DatetimeIndex(["2026-06-20", "2026-06-21"]))
    result = {"atm_iv_30d": 0.40, "term_structure": 1.05, "iv_skew_25d": 0.09,
              "not_a_column": 9.9, "atm_strike": None}

    # term-refill date: harvested atm_iv_30d + skew survive, only the NaN term is written
    ts = pd.Timestamp("2026-06-20")
    written = _apply_result(df, ts, result)
    assert written == ["term_structure"]
    assert float(df.loc[ts, "atm_iv_30d"]) == 0.63          # harvested value UNCHANGED
    assert float(df.loc[ts, "iv_skew_25d"]) == 0.02
    assert float(df.loc[ts, "term_structure"]) == 1.05      # the gap it came for IS filled

    # all-NaN date: every present, non-None key is written
    ts2 = pd.Timestamp("2026-06-21")
    written2 = _apply_result(df, ts2, result)
    assert set(written2) == {"atm_iv_30d", "term_structure", "iv_skew_25d"}
    assert float(df.loc[ts2, "atm_iv_30d"]) == 0.40
    assert _apply_result(df, ts2, None) == []               # no result → no-op


# ─── Test 28: event-expiry IV selection + tenor guard (offline) ───────────────
def test_event_iv_selection():
    """massive.pick_event_atm (S44): earliest post-earnings expiry wins, ATM = strike nearest
    spot, the iv=20 placeholder is rejected. vol_history._iv_triplet: event-expiry IV is used
    only when ALL THREE sessions carry it (mixing tenors inside one ramp measurement would
    fabricate ramp); otherwise the 30d proxy for all three. Pure, no network."""
    import datetime
    import pandas as pd
    from modules.massive import pick_event_atm
    from modules.vol_history import _iv_triplet

    def p(typ, strike, expiry, iv):
        e = datetime.date.fromisoformat(expiry)
        return {"type": typ, "strike": strike, "expiry": e,
                "dte": (e - datetime.date(2026, 7, 6)).days, "iv": iv}

    parsed = [
        p("call", 45.0, "2026-08-21", 0.90),      # later expiry — must lose to the front one
        p("call", 47.5, "2026-08-14", 20),        # front expiry but placeholder iv → rejected
        p("call", 45.0, "2026-08-14", 0.95),      # front expiry, ATM (spot 44.8) → winner
        p("call", 50.0, "2026-08-14", 1.10),      # front expiry, farther strike
        p("put",  45.0, "2026-08-14", 0.97),      # puts ignored
    ]
    ev = pick_event_atm(parsed, underlying_price=44.8)
    assert ev and ev["event_expiry"] == "2026-08-14" and ev["atm_iv_event"] == 0.95
    assert pick_event_atm([p("call", 45.0, "2026-08-14", 20)], 44.8) is None   # placeholder-only

    idx = pd.DatetimeIndex(["2026-07-01", "2026-07-02", "2026-07-03"])
    full = pd.DataFrame({"atm_iv_30d": [0.50, 0.55, 0.40],
                         "atm_iv_event": [0.60, 0.70, 0.45]}, index=idx)
    gap = pd.DataFrame({"atm_iv_30d": [0.50, 0.55, 0.40],
                        "atm_iv_event": [None, 0.70, 0.45]}, index=idx)
    assert _iv_triplet(full, *idx) == (0.60, 0.70, 0.45, "event")   # complete → event series
    assert _iv_triplet(gap, *idx) == (0.50, 0.55, 0.40, "30d")      # gap → 30d for ALL three
    assert _iv_triplet(gap[["atm_iv_30d"]].assign(atm_iv_30d=None), *idx) == (None, None, None, None)


# ─── Test 29: equal-weight breadth read (offline) ─────────────────────────────
def test_read_breadth():
    """modules/breadth.read_breadth (S45): equal-weight outperforming over 20d → 'broad-led',
    lagging → 'narrow', inside the ±0.5% dead band → 'mixed'; percentile computed off the
    rolling 20d-spread series (an accelerating spread reads at the top of its own range);
    too-short pairs are omitted. Pure, no network."""
    import pandas as pd
    from modules.breadth import read_breadth, BREADTH_DEAD

    n = 300
    cap = pd.Series([100.0] * n)
    lead = pd.Series([100.0 * (1.002 ** i) for i in range(n)])        # steady eq outperformance
    lag = pd.Series([100.0 * (0.998 ** i) for i in range(n)])         # steady eq underperformance
    flat = cap * (1 + BREADTH_DEAD / 10)                              # inside the dead band

    out = read_breadth({"LEAD": (lead, cap), "LAG": (lag, cap), "FLAT": (flat, cap)})
    assert out["LEAD"]["tag"] == "broad-led" and out["LEAD"]["rel_20d"] > 0
    assert out["LAG"]["tag"] == "narrow" and out["LAG"]["rel_20d"] < 0
    assert out["FLAT"]["tag"] == "mixed"
    assert out["LEAD"]["rel_63d"] > out["LEAD"]["rel_20d"] > 0        # longer horizon compounds

    # accelerating outperformance (daily edge grows each session) → the latest 20d spread is the
    # strict max of its own rolling history → top-of-range percentile
    accel = 100.0 * pd.Series([1 + 0.00002 * i for i in range(n)]).cumprod()
    pct = read_breadth({"ACC": (accel, cap)})["ACC"]["pct"]
    assert pct is not None and pct >= 0.9

    # constant-spread pair reads mixed with a defined percentile; short pair is omitted
    assert read_breadth({"S": (lead.iloc[:15], cap.iloc[:15])}) is None
    both = read_breadth({"OK": (lead, cap), "S": (lead.iloc[:15], cap.iloc[:15])})
    assert "OK" in both and "S" not in both


# ─── Test 30: callquote pure helpers (offline) ────────────────────────────────
def test_callquote_helpers():
    """modules/callquote (S46): pick_call_candidates takes the tradeable ATM + the OTM call with
    delta nearest 0.375 (no-bid strikes skipped); liquidity_grade bands (tight/ok/wide/dead, OI
    floor demotion, majority-no-bid → dead); curve_read tags the cheaper tenor; select_expiries
    takes every monthly in the DTE window (S72). Pure, no network."""
    from modules.callquote import (pick_call_candidates, liquidity_grade, curve_read,
                                   select_expiries)

    def row(typ, strike, bid, ask, oi=100, delta=None, theta=None, iv=None, volume=10):
        return {"type": typ, "strike": strike, "bid": bid, "ask": ask, "oi": oi,
                "volume": volume, "delta": delta, "theta": theta, "iv": iv}

    rows = [row("call", 100.0, 5.0, 5.2, oi=500, delta=0.52),
            row("call", 105.0, 2.6, 2.8, oi=300, delta=0.38),
            row("call", 110.0, 1.2, 1.4, oi=200, delta=0.25),
            row("call", 102.5, 0.0, 3.9, oi=50, delta=0.45),      # no bid → skipped
            row("put", 100.0, 4.8, 5.0, oi=400, delta=-0.48)]
    atm, otm = pick_call_candidates(rows, spot=100.4)
    assert atm["strike"] == 100.0                                 # nearest TRADEABLE (102.5 dead)
    assert otm["strike"] == 105.0                                 # Δ0.38 nearest the 0.375 band
    assert pick_call_candidates([row("call", 100.0, 0.0, 5.0)], 100.0) == (None, None)

    def chain(spread_frac, oi, bid0=False):
        out = []
        for k in (90.0, 95.0, 100.0, 105.0, 110.0):
            for typ in ("call", "put"):
                b = 0.0 if bid0 else 5.0 * (1 - spread_frac / 2)
                out.append(row(typ, k, b, 5.0 * (1 + spread_frac / 2), oi=oi))
        return out
    assert liquidity_grade(chain(0.008, 200), 100.0)["grade"] == "tight"   # 0.8% spr, OI 2000
    assert liquidity_grade(chain(0.02, 100), 100.0)["grade"] == "ok"
    assert liquidity_grade(chain(0.05, 100), 100.0)["grade"] == "wide"
    assert liquidity_grade(chain(0.02, 5), 100.0)["grade"] == "wide"       # OI floor demotes
    assert liquidity_grade(chain(0.02, 100, bid0=True), 100.0)["grade"] == "dead"

    cr = curve_read([("Aug21", 46, 0.28), ("Sep18", 74, 0.26), ("Dec18", 165, 0.24)])
    assert cr["tag"].startswith("back cheaper") and cr["points"][0]["label"] == "Aug21"
    assert curve_read([("Aug21", 46, 0.28)]) is None
    assert curve_read([("A", 30, 0.25), ("B", 90, 0.25)])["tag"] == "flat curve"

    # S72: every MONTHLY inside the DTE window (was: nearest to each of 4 target DTEs).
    # 07-17 and 08-07 are third-Friday-shaped only for their own months — 07-17 IS July's
    # third Friday but sits below EXPIRY_MIN_DTE; 08-07 is a weekly.
    future = [("2026-07-17", 10), ("2026-08-07", 31), ("2026-08-21", 45),
              ("2026-09-18", 73), ("2026-10-16", 101)]
    assert [s[0] for s in select_expiries(future)] == ["2026-08-21", "2026-09-18", "2026-10-16"]


# ─── Test 31: beta / ex-div / catalysts helpers (offline) ─────────────────────
def test_beta_exdiv_catalysts():
    """S46 pure helpers: setupcheck.beta_corr (a 2x-levered clone reads β≈2 corr≈1; independent
    series read low corr; short series → None); features.estimate_next_ex_div (quarterly cadence
    rolls ~91d forward; thin/irregular history → None); benchmarks.upcoming_catalysts (ticker +
    window filter off a fixture CSV). No network."""
    import os
    import tempfile
    import numpy as np
    import pandas as pd
    from modules.setupcheck import beta_corr
    from modules.features import estimate_next_ex_div
    from modules.benchmarks import upcoming_catalysts

    rng = np.random.default_rng(7)
    m_ret = rng.normal(0, 0.01, 200)
    m = pd.Series(100 * np.cumprod(1 + m_ret))
    lev = pd.Series(100 * np.cumprod(1 + 2 * m_ret))              # 2x daily-return clone
    bc = beta_corr(lev, m, window=60)
    assert bc and abs(bc["beta"] - 2.0) < 0.15 and bc["corr"] > 0.99
    indep = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, 200)))
    bu = beta_corr(indep, m, window=60)
    assert bu and abs(bu["corr"]) < 0.5
    assert beta_corr(lev.iloc[:10], m.iloc[:10]) is None          # too short

    q = pd.DatetimeIndex(["2025-02-06", "2025-05-08", "2025-08-07", "2025-11-06",
                          "2026-02-05", "2026-05-07"])            # quarterly, ~91d cadence
    nxt = estimate_next_ex_div(q, today="2026-07-07")
    assert nxt is not None and abs((nxt - pd.Timestamp("2026-08-06")).days) <= 7
    assert estimate_next_ex_div(q[:3], today="2026-07-07") is None            # <4 payments
    irregular = pd.DatetimeIndex(["2020-01-01", "2021-06-01", "2023-01-01", "2024-09-01"])
    assert estimate_next_ex_div(irregular, today="2026-07-07") is None        # gaps > 400d

    d = tempfile.mkdtemp()
    with open(os.path.join(d, "catalysts.csv"), "w") as f:
        f.write("ticker,date,type,description\n"
                "CRSP,2026-07-20,pdufa,exa-cel label expansion decision\n"
                "CRSP,2026-12-01,trial_readout,too far out\n"
                "NVDA,2026-07-15,other,wrong ticker\n")
    cats = upcoming_catalysts("CRSP", within_days=45, data_dir=d, today="2026-07-07")
    assert len(cats) == 1 and cats[0][0] == "2026-07-20" and cats[0][1] == 13
    assert upcoming_catalysts("CRSP", data_dir=os.path.join(d, "missing")) == []


# ─── Test 32: long-tenor ATM IV pick (offline) ────────────────────────────────
def test_atm_at_tenor():
    """massive._atm_at_tenor (S47): the ~180d LEAPS-tenor ATM pick — expiry proximity to the
    target dominates strike distance (×10 weight), the iv=20 placeholder is rejected, puts are
    ignored, empty chains → None. Pure, no network."""
    import datetime
    from modules.massive import _atm_at_tenor

    def p(typ, strike, dte, iv):
        return {"type": typ, "strike": strike, "dte": dte, "iv": iv,
                "expiry": datetime.date(2026, 7, 7) + datetime.timedelta(days=dte)}

    parsed = [
        p("call", 60.0, 101, 0.67),      # too near the front — expiry distance dominates
        p("call", 62.5, 192, 0.64),      # ~target tenor, slightly OTM
        p("call", 60.0, 192, 20),        # ~target tenor ATM but placeholder iv → rejected
        p("call", 60.0, 374, 0.61),      # too far out
        p("put",  60.0, 192, 0.66),      # puts ignored
    ]
    atm = _atm_at_tenor(parsed, underlying_price=60.2, target_dte=180)
    assert atm and atm["dte"] == 192 and atm["strike"] == 62.5 and atm["iv"] == 0.64
    assert _atm_at_tenor([p("put", 60.0, 192, 0.66)], 60.2, 180) is None
    assert _atm_at_tenor([], 60.2, 180) is None


# ─── Test 33: candle_style="none" render path (offline) ──────────────────────
def test_print_report_candle_none():
    """lens.print_report with candle_style='none' (S48): the candle panel is skipped entirely
    (lens_web draws a real Plotly chart instead) while the header, OHLC line and sections still
    render. Also a light guard on the render path after the S48 render_ticker extraction."""
    import contextlib
    import io
    from lens import print_report

    last_bar = {"open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0, "prev_close": 100.5}
    panel = [("2026-07-06", 100.0, 103.0, 99.0, 102.0, 100.5),
             ("2026-07-07", 102.0, 104.0, 101.0, 103.0, 102.0)]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_report("TEST", reads={}, divs={}, summary={"synthesis": "mixed — fixture"},
                     profile=None, notes=[], last_bar=last_bar, as_of="2026-07-07",
                     color=False, candle_style="none", panel_bars=panel)
    out = buf.getvalue()
    assert "LENS — TEST" in out and "MULTI-TIMEFRAME" in out
    assert "███" not in out and "├─┤" not in out          # no box-candle glyphs
    assert "⠀" not in out                                  # no braille canvas
    # same fixtures with box style DO render the panel — proves the skip is the style, not the data
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        print_report("TEST", reads={}, divs={}, summary={"synthesis": "mixed — fixture"},
                     profile=None, notes=[], last_bar=last_bar, as_of="2026-07-07",
                     color=False, candle_style="box", panel_bars=panel)
    assert "│" in buf2.getvalue()


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
    assert marks["Market beta"] == "–"                    # S46 row: n/a degrade, informational
    assert s["n_bad"] == 0 and "7/8" in s["net"]

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


# ─── Test 34: render_payload == print_report on the same payload (S49, offline) ──
def test_render_payload_matches_print_report():
    """lens.render_payload must be a pure forwarding of the payload into print_report — the web
    expander's ANSI text and a direct print_report call from the same data are byte-equal."""
    import contextlib
    import io
    from lens import print_report, render_payload, rally_drawdown_risk

    last_bar = {"open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0, "prev_close": 100.5}
    panel = [("2026-07-06", 100.0, 103.0, 99.0, 102.0, 100.5),
             ("2026-07-07", 102.0, 104.0, 101.0, 103.0, 102.0)]
    risk = rally_drawdown_risk({}, profile=None, ctx=None, divergences={})
    payload = {"ticker": "TEST", "reads": {}, "divs": {}, "summary": {"synthesis": "mixed — fixture"},
               "profile": None, "notes": ["fixture note"], "last_bar": last_bar,
               "as_of": "2026-07-07", "panel_bars": panel, "ctx": None, "backdrop": "SPY: fixture",
               "geo": None, "pcoi": None, "vol": None, "live": None, "setup": None,
               "squeeze": None, "insider": None, "callq": None, "liq": None, "cats": [],
               "risk": risk, "macro_events": {}, "thesis": "bullish", "level": 100.0,
               "live_iv": None}

    buf1 = io.StringIO()
    with contextlib.redirect_stdout(buf1):
        render_payload(payload, use_color=False, candle_style="none")
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        print_report("TEST", reads={}, divs={}, summary={"synthesis": "mixed — fixture"},
                     profile=None, notes=["fixture note"], last_bar=last_bar, as_of="2026-07-07",
                     backdrop="SPY: fixture", thesis="bullish", level=100.0, color=False,
                     candle_style="none", panel_bars=panel, cats=[],
                     risk=risk, macro_events={})
    assert buf1.getvalue() == buf2.getvalue()
    assert "THESIS CHECK" in buf1.getvalue()          # thesis flowed through the payload


# ─── Test 35: risk/macro_events kwargs preserve print_report output (S49, offline) ──
def test_print_report_risk_kwarg_identity():
    """Supplying risk= and macro_events= (the two computes S49 lifted into gather_report) must
    produce byte-identical output vs the unsupplied path where print_report computes them itself
    — this is the CLI byte-identity guard for the compute/format split."""
    import contextlib
    import io
    from lens import print_report, rally_drawdown_risk
    from modules.econ_calendar import next_event_per_series

    last_bar = {"open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0, "prev_close": 100.5}
    kw = dict(reads={}, divs={}, summary={"synthesis": "mixed — fixture"}, profile=None,
              notes=[], last_bar=last_bar, as_of="2026-07-07", color=False,
              candle_style="none", thesis="bullish")

    buf1 = io.StringIO()
    with contextlib.redirect_stdout(buf1):
        print_report("TEST", **kw)                     # unsupplied → computes internally
    risk = rally_drawdown_risk({}, profile=None, ctx=None, divergences={})
    try:
        ev = next_event_per_series(data_dir="data")    # same call/params print_report uses
    except Exception:
        ev = None
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        print_report("TEST", **kw, risk=risk, macro_events=ev)
    assert buf1.getvalue() == buf2.getvalue()


# ─── Test 36: gather_report payload contract (S49, offline via monkeypatch) ──────
def test_gather_payload_keys(monkeypatch):
    """gather_report returns the full payload key set with NO pandas objects (st.cache_data
    pickles the payload — DataFrames would bloat the web cache). Network-touching best-effort
    helpers are monkeypatched off; the QQQ indicators CSV drives the frames."""
    import pandas as pd
    from types import SimpleNamespace
    import lens

    for name in ("next_earnings", "next_ex_dividend", "fetch_rs", "fetch_beta",
                 "fetch_sectors", "own_sector", "fetch_buzz", "fetch_street",   # S58 fetchers off
                 "fetch_afterhours",                                            # S64 off too
                 "fetch_breadth", "ew_comparator"):                             # S67 off too
        monkeypatch.setattr(lens, name, None, raising=False)

    args = SimpleNamespace(ticker=None, thesis=None, level=None, no_intraday=True, no_vix=True,
                           geo=False, no_color=True, candle="none", candle_px=128, prev=10,
                           data_dir="data", no_refresh=True, refresh=False, pc_oi=None,
                           insider=False, squeeze=False, live=False, vol=False, call=False,
                           street=False)
    payload = lens.gather_report("QQQ", args, interactive=False, backdrop_base=None)
    assert payload is not None

    expected = {"ticker", "reads", "divs", "summary", "profile", "notes", "last_bar", "as_of",
                "panel_bars", "ctx", "backdrop", "geo", "pcoi", "gex", "vol", "live", "setup",
                "squeeze", "insider", "callq", "liq", "cats", "risk", "macro_events",
                "thesis", "level", "live_iv", "earn", "exd", "as_of_mode",
                "sectors", "buzz", "street",                                     # S58 keys
                "ah",                                                            # S64 key
                "ladder", "short",                                               # S65 keys
                "breadth"}                                                       # S67 key
    assert set(payload.keys()) == expected
    assert not any(isinstance(v, (pd.DataFrame, pd.Series)) for v in payload.values())
    assert payload["reads"] and payload["risk"] is not None      # frames were read + risk lifted


# ─── Test 37: pc_oi strike_profile (S50, offline) ────────────────────────────────
def test_strike_profile():
    """Per-strike OI aggregation: put/call split by strike, ±band filter around spot, sorted;
    strike-less/empty chains → []. Feeds the web UI's OI-walls chart."""
    import pandas as pd
    from modules.pc_oi import strike_profile

    chain = pd.DataFrame({
        "strike":        [90, 90, 100, 100, 110, 130],
        "option_type":   ["call", "put", "call", "put", "call", "call"],
        "open_interest": [10, 20, 30, 40, 0, 99],
    })
    prof = strike_profile(chain, spot=100, band=0.20)
    assert prof == [[90.0, 10.0, 20.0], [100.0, 30.0, 40.0], [110.0, 0.0, 0.0]]  # 130 > +20% cut

    assert strike_profile(chain, spot=None)[-1][0] == 130.0      # no spot → uncapped
    assert strike_profile(chain.drop(columns=["strike"]), spot=100) == []
    assert strike_profile(chain.iloc[0:0], spot=100) == []


# ─── Test 38: sentiment spark_of (S50, offline) ──────────────────────────────────
def test_spark_of():
    """Gauge sparkline series: ≤points+1 floats sampled so the LAST value always survives;
    same ≥63-obs floor as percentile_of; NaNs dropped."""
    import numpy as np
    import pandas as pd
    from modules.sentiment import spark_of

    s = pd.Series(np.linspace(0.0, 1.0, 300))
    sp = spark_of(s, window=252, points=60)
    assert 0 < len(sp) <= 60 and sp[-1] == 1.0
    assert all(isinstance(v, float) for v in sp)

    assert spark_of(pd.Series([1.0] * 10)) == []                 # thin history → no spark
    noisy = pd.Series([1.0, np.nan] * 100)
    assert spark_of(noisy) and all(v == 1.0 for v in spark_of(noisy))


# ─── Test 39: econ_calendar headline_result (S52, offline) ───────────────────────
def test_headline_result():
    """Release-date → reference-period matching + headline display per kind: monthly m/m %
    (lag 1), monthly change-in-thousands, JOLTS 2-month lag, weekly claims ≤8d window,
    quarterly GDP value, FOMC rate hold/cut; future/missing obs → None."""
    from modules.econ_calendar import headline_result

    # CPI: July 14 release publishes JUNE data; +0.5% m/m off the index
    cpi = [("2026-05-01", 320.0), ("2026-06-01", 321.6)]
    assert headline_result("CPI", "2026-07-14", cpi) == "+0.5% m/m"
    assert headline_result("CPI", "2026-08-12", cpi) is None     # July data not in obs yet

    # NFP: PAYEMS in thousands → change printed as k jobs
    nfp = [("2026-05-01", 159000.0), ("2026-06-01", 159140.0)]
    assert headline_result("NFP", "2026-07-02", nfp) == "+140k jobs"

    # JOLTS: Aug 4 release publishes JUNE data (2-month lag), level in thousands → M
    jolts = [("2026-06-01", 7600.0)]
    assert headline_result("JOLTS", "2026-08-04", jolts) == "7.6M open"

    # Claims: Thursday release covers the week ending the prior Saturday (≤8d); stale obs → None
    claims = [("2026-07-04", 228000.0)]
    assert headline_result("Claims", "2026-07-09", claims) == "228k claims"
    assert headline_result("Claims", "2026-07-30", claims) is None

    # GDP: Q3 release publishes Q2 (obs dated at quarter start); value IS the headline %
    gdp = [("2026-04-01", 2.8)]
    assert headline_result("GDP", "2026-07-30", gdp) == "+2.8% q/q ann."

    # FOMC: post-meeting level vs pre-meeting — hold and cut; future meeting → None
    hold = [("2026-07-28", 4.50), ("2026-07-30", 4.50)]
    cut = [("2026-07-28", 4.50), ("2026-07-30", 4.25)]
    assert headline_result("FOMC", "2026-07-29", hold) == "4.50% (hold)"
    assert headline_result("FOMC", "2026-07-29", cut) == "4.25% (-0.25)"
    assert headline_result("FOMC", "2026-09-16", hold) is None

    assert headline_result("NOPE", "2026-07-14", cpi) is None    # unmapped series
    assert headline_result("CPI", "2026-07-14", []) is None      # empty obs


# ─── Test 40: seasonality monthly base rates (S53, offline) ──────────────────────
def test_monthly_seasonality():
    """Synthetic 20y series: Jan–Jun always up (+2%/mo), Jul–Dec always down (−1%/mo) —
    win counts must be n/n and 0/n respectively; recent window ~10 obs; short series →
    insufficient; counts (not just rates) are preserved."""
    import pandas as pd
    from modules.seasonality import monthly_seasonality

    idx = pd.bdate_range("2000-01-03", "2019-12-31")
    daily_up, daily_dn = 1.02 ** (1 / 21), 0.99 ** (1 / 21)
    vals, price = [], 100.0
    for d in idx:
        price *= daily_up if d.month <= 6 else daily_dn
        vals.append(price)
    close = pd.Series(vals, index=idx)

    out = monthly_seasonality(close)
    assert out["status"] == "ok" and out["years"] > 19
    assert len(out["months"]) == 12 and len(out["recent"]) == 12
    jan, aug = out["months"][0], out["months"][7]
    assert jan["n"] >= 18 and jan["up"] == jan["n"] and jan["win"] == 1.0
    assert aug["up"] == 0 and aug["win"] == 0.0
    assert jan["median"] is not None and jan["median"] > 0 > aug["median"]
    r_jan = out["recent"][0]
    assert 9 <= r_jan["n"] <= 11 and r_jan["up"] == r_jan["n"]   # trailing-10y window

    thin = monthly_seasonality(close.tail(252 * 5))              # ~5y < 10y floor
    assert thin["status"] == "insufficient" and thin["months"] == []
    assert monthly_seasonality(None)["status"] == "insufficient"


# ─── Test 41: earnings reaction history (S53, offline) ───────────────────────────
def test_earnings_reactions():
    """Synthetic frame with three prints: BMO (moves same session), AMC (moves the NEXT
    session — larger-|move| pick), and one at the history edge (d5 None). pre_iv prefers
    atm_iv_event over atm_iv_30d on the pre-print session; future dates are ignored."""
    import pandas as pd
    from modules.vol_history import earnings_reactions

    idx = pd.bdate_range("2026-01-05", periods=40)
    c = [100.0] * 10 + [110.0] * 4 + [112.0] * 12 + [100.8] * 12 + [106.848] * 2
    df = pd.DataFrame({"Close": c}, index=idx)
    df["Open"] = df["Close"].shift(1).fillna(100.0)              # gap 0 by default
    df.loc[idx[10], "Open"] = 108.0                              # E1 gaps +8%
    df.loc[idx[26], "Open"] = 103.0
    df["atm_iv_30d"] = 0.5
    df["atm_iv_event"] = float("nan")
    df.loc[idx[9], "atm_iv_event"] = 0.8                         # pre-print session of E1

    earnings = [idx[10],                                         # BMO: +10% ON the date
                idx[25],                                         # AMC: −10% the NEXT session
                idx[38],                                         # +6%, too close to the edge for d5
                idx[-1] + pd.Timedelta(days=5)]                  # future → ignored
    out = earnings_reactions(df, earnings)
    assert out["status"] == "ok" and len(out["rows"]) == 3
    e3, e2, e1 = out["rows"]                                     # newest first

    assert e1["date"] == idx[10].date().isoformat()
    assert abs(e1["d1"] - 0.10) < 1e-9 and abs(e1["gap"] - 0.08) < 1e-9
    assert abs(e1["d5"] - 0.12) < 1e-9                           # Close[14]=112 vs 100
    assert e1["pre_iv"] == 0.8                                   # event IV preferred

    assert e2["date"] == idx[26].date().isoformat()              # AMC → next session picked
    assert e2["d1"] < -0.09 and e2["pre_iv"] == 0.5              # 30d fallback

    assert e3["d5"] is None and e3["d1"] > 0.05                  # history edge
    assert out["up"] == 2 and out["dn"] == 1
    assert abs(out["med_abs_d1"] - 0.10) < 1e-9

    assert earnings_reactions(df, [])["status"] == "no_earnings"
    assert earnings_reactions(None, earnings)["status"] == "no_csv"


# ─── Test 42: GEX pure math (S56, offline) ───────────────────────────────────────
def test_gex_math():
    """Dealer-GEX aggregation, walls, max pain, unusual activity, expiry selection and the
    zero-gamma crossing — all on fixture rows (no network)."""
    import datetime
    from modules.gex import (gex_by_strike, key_levels, max_pain, unusual_activity,
                             select_gex_expiries, zero_gamma, _unit_gex)
    from modules.bs_invert import bs_gamma

    spot = 100.0
    rows = [
        {"type": "call", "strike": 105.0, "oi": 100, "volume": 50, "gamma": 0.04,
         "iv": 0.30, "dte": 20, "expiry": "2026-07-31"},
        {"type": "call", "strike": 110.0, "oi": 300, "volume": 2000, "gamma": 0.02,
         "iv": 0.30, "dte": 20, "expiry": "2026-07-31"},
        {"type": "put", "strike": 95.0, "oi": 600, "volume": 900, "gamma": 0.03,
         "iv": 0.35, "dte": 20, "expiry": "2026-07-31"},
        {"type": "put", "strike": 90.0, "oi": 50, "volume": 600, "gamma": 0.01,
         "iv": 0.35, "dte": 20, "expiry": "2026-07-31"},
    ]

    strikes, net = gex_by_strike(rows, spot)
    assert [s["strike"] for s in strikes] == [90.0, 95.0, 105.0, 110.0]     # ascending
    # calls positive, puts negative; unit formula = Γ·OI·100·S²·0.01
    assert abs(strikes[2]["call"] - _unit_gex(0.04, 100, spot)) < 1e-9
    assert strikes[1]["put"] < 0
    assert abs(net - sum(s["net"] for s in strikes)) < 1e-6

    lvl = key_levels(strikes)
    assert lvl["call_wall"] == 110.0          # 0.02×300 > 0.04×100
    assert lvl["put_wall"] == 95.0            # biggest |put| gamma-OI
    assert key_levels([]) == {"call_wall": None, "call_wall_gex": None,
                              "put_wall": None, "put_wall_gex": None}

    # max pain: with heavy call OI above and put OI below, the minimum sits between the wings
    mp = max_pain(rows)
    assert 90.0 <= mp <= 110.0
    assert max_pain([r for r in rows if r["type"] == "call"]) is None       # one-sided → None

    # unusual activity: floor(vol≥500) and ratio(≥2×OI) both bind; NEW (zero-OI) ranks first
    rows_ua = rows + [{"type": "call", "strike": 120.0, "oi": 0, "volume": 800,
                       "gamma": 0.0, "iv": None, "dte": 20, "expiry": "2026-07-31"}]
    ua = unusual_activity(rows_ua, min_vol=500, min_ratio=2.0)
    assert ua[0]["oi"] == 0 and ua[0]["ratio"] is None                      # NEW first
    assert {u["strike"] for u in ua} == {120.0, 90.0, 110.0}                # 95p: 900/600 < 2×
    assert all(u["volume"] >= 500 for u in ua)

    # expiry selection: nearest N + monthlies inside the window, deduped, dte-sorted
    fut = [("2026-07-14", 2), ("2026-07-15", 3), ("2026-07-16", 4), ("2026-07-21", 9),
           ("2026-08-21", 40),   # 3rd Friday → monthly, must survive beyond nearest-5
           ("2026-09-04", 54), ("2026-10-16", 96)]
    sel = select_gex_expiries(fut, max_dte=60, near=3, cap=8)
    assert ("2026-08-21", 40) in sel and ("2026-10-16", 96) not in sel
    assert [d for _, d in sel] == sorted(d for _, d in sel)
    assert datetime.date(2026, 8, 21).weekday() == 4                        # fixture sanity

    # bs_gamma: peaks near ATM, 0 on degenerate inputs
    g_atm = bs_gamma(100, 100, 0.04, 30 / 365, 0.3)
    assert g_atm > bs_gamma(100, 80, 0.04, 30 / 365, 0.3)
    assert g_atm > bs_gamma(100, 120, 0.04, 30 / 365, 0.3)
    assert bs_gamma(100, 100, 0.04, 0, 0.3) == 0.0

    # zero-gamma: call-heavy above / put-heavy below → a crossing between the wings,
    # found near spot; rows without iv/dte → None
    zg = zero_gamma(rows, spot, band=0.15)
    assert zg is None or 85.0 <= zg <= 115.0
    assert zero_gamma([{**r, "iv": None} for r in rows], spot) is None


# ─── Test 43: signal-ledger scorer (S56, offline via tmp_path) ───────────────────
def test_score_ledger(tmp_path):
    """score() joins ledger rows to realized 15d/63d returns and WIN-tags vs each row's OWN
    stamped threshold; rows younger than a horizon are pending; missing files degrade to a
    status, never an exception."""
    import pandas as pd
    from score_ledger import score

    idx = pd.bdate_range("2026-01-05", periods=80)
    close = pd.Series(100.0, index=idx)
    close.iloc[20:] = 105.0          # +5% from session 5 → session 20 window
    pd.DataFrame({"Close": close}).to_csv(tmp_path / "xyz_indicators.csv")

    ledger = pd.DataFrame([
        # session 5 → fwd15 = 105/100−1 = +5% ≥ 2% threshold → WIN; fwd63 lands in-data too
        {"date": idx[5].date().isoformat(), "ticker": "XYZ", "signal": "STRONG ENTRY",
         "win_threshold": 0.02, "win_threshold_63": 0.20},
        # session 70 → 15d/63d windows both extend past the data → pending
        {"date": idx[70].date().isoformat(), "ticker": "XYZ", "signal": "STAY OUT",
         "win_threshold": 0.02, "win_threshold_63": 0.20},
    ])
    ledger.to_csv(tmp_path / "xyz_signal_ledger.csv", index=False)

    res = score("XYZ", data_dir=str(tmp_path))
    assert res["status"] == "ok" and res["n_rows"] == 2
    newest, oldest = res["rows"]                                # newest first
    assert newest["fwd15"] is None and newest["win15"] is None  # pending
    assert abs(oldest["fwd15"] - 0.05) < 1e-9 and oldest["win15"] is True
    assert oldest["win63"] is False                             # +5% < 20% bar
    assert res["pending15"] == 1 and res["baseline"]["scored15"] == 1
    assert res["summary"]["STRONG ENTRY"]["win15"] == 1.0

    assert score("NOPE", data_dir=str(tmp_path))["status"] == "no_ledger"
    (tmp_path / "ghost_signal_ledger.csv").write_text(
        "date,ticker,signal,win_threshold,win_threshold_63\n", encoding="utf-8")
    assert score("GHOST", data_dir=str(tmp_path))["status"] == "empty"


# ─── Test 44: Phase B source parsers (S56, offline) ──────────────────────────────
def test_cot_buzz_finra_parsers():
    """CFTC COT parse + labels, ApeWisdom buzz_read, FINRA consolidated-SI parse — all pure,
    on fixture payloads mirroring the live shapes probed 2026-07-12."""
    from modules.cot import parse_cot, label_cot
    from modules.buzz import buzz_read
    from modules.shortint import parse_finra_si

    # COT: 30 weekly rows so the percentile (≥26 floor) engages; net trends up
    rows = [{"report_date_as_yyyy_mm_dd": f"2026-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}T00:00:00.000",
             "lev_money_positions_long": str(1000 + 40 * i),
             "lev_money_positions_short": "1000",
             "open_interest_all": "10000"} for i in range(30)]
    rows[-1]["report_date_as_yyyy_mm_dd"] = "2026-12-30T00:00:00.000"   # unambiguous newest
    read = parse_cot(rows)
    assert read["date"] == "2026-12-30" and read["n_weeks"] == 30
    assert abs(read["net_pct_oi"] - (40 * 29) / 10000) < 1e-9
    assert read["pct"] is not None and read["pct"] >= 0.9               # newest = most long
    assert "net long" in label_cot(read) and "crowded long" in label_cot(read)
    inv = {"net_pct_oi": -0.3, "pct": 0.05, "net": -3000}
    assert label_cot(inv, invert=True) == "net short · crowded vol-short"
    assert parse_cot([]) is None
    assert parse_cot([{"open_interest_all": "0"}]) is None

    # buzz: found (with 24h change), zero-prior (chg None), unranked → None
    res = [{"rank": 3, "ticker": "CRSP", "name": "CRISPR", "mentions": 120, "upvotes": 400,
            "rank_24h_ago": 9, "mentions_24h_ago": 60},
           {"rank": 4, "ticker": "NEWB", "name": "New", "mentions": 50, "upvotes": 10,
            "rank_24h_ago": None, "mentions_24h_ago": 0}]
    b = buzz_read(res, "crsp")
    assert b["rank"] == 3 and abs(b["chg"] - 1.0) < 1e-9 and b["rank_prev"] == 9
    assert buzz_read(res, "NEWB")["chg"] is None
    assert buzz_read(res, "GHOST") is None and buzz_read(None, "X") is None

    # FINRA consolidated SI: oldest-first input → newest-first output, same shape as NASDAQ
    fin = [{"settlementDate": "2026-05-15", "currentShortPositionQuantity": 100e6,
            "averageDailyVolumeQuantity": 50e6, "daysToCoverQuantity": 2.0},
           {"settlementDate": "2026-05-29", "currentShortPositionQuantity": 120e6,
            "averageDailyVolumeQuantity": 60e6, "daysToCoverQuantity": 2.5},
           {"settlementDate": "bad", "currentShortPositionQuantity": None,
            "averageDailyVolumeQuantity": 1, "daysToCoverQuantity": 1}]
    out = parse_finra_si(fin)
    assert [r["settle_date"] for r in out] == ["2026-05-29", "2026-05-15"]   # bad row dropped
    assert out[0]["dtc"] == 2.5 and out[0]["interest"] == 120e6
    assert parse_finra_si(None) == []


# ─── Test 45: lens_web snapshot/diff + section slugs (S56, offline) ──────────────
def test_web_snapshot_diff_and_slugs():
    """Day-over-day snapshot extraction + diff (pure) and the stable section-anchor slugs the
    sidebar quick-nav links against. Importing lens_web executes the page script in bare mode
    — doubles as a does-the-module-even-run smoke."""
    import pytest
    lens_web = pytest.importorskip("lens_web")  # archived to archive/streamlit/ — skips when moved
    _slug = pytest.importorskip("lens_web_sections")._slug

    pay = {"as_of": "2026-07-10", "last_bar": {"close": 100.0, "prev_close": 99.0},
           "setup": {"rows": [("HTF alignment", "✓", ""), ("Momentum room", "✗", "")]},
           "risk": {"drawdown": ["1M overbought"], "rally": ["HVN support below"]},
           "ctx": {"gauges": [{"name": "ATM IV (30d)", "value": 0.3, "pct": 0.20},
                              {"name": "VIX", "value": 17.0, "pct": None}]}}
    snap = lens_web.snap_from_payload(pay)
    assert snap["setup"] == {"HTF alignment": "✓", "Momentum room": "✗"}
    assert snap["gauges"]["ATM IV (30d)"] == [0.3, 0.20] and snap["close"] == 100.0

    pay2 = {**pay, "as_of": "2026-07-11",
            "setup": {"rows": [("HTF alignment", "✗", ""), ("Momentum room", "✗", "")]},
            "risk": {"drawdown": ["1M overbought", "extended above MA20"], "rally": []},
            "ctx": {"gauges": [{"name": "ATM IV (30d)", "value": 0.4, "pct": 0.55}]}}
    d = lens_web.diff_snapshots(snap, lens_web.snap_from_payload(pay2))
    assert d["flips"] == [("HTF alignment", "✓", "✗")]
    assert d["dd_added"] == ["extended above MA20"] and d["rally_removed"] == ["HVN support below"]
    assert d["gauge_moves"][0][0] == "ATM IV (30d)"            # 20ᵗʰ → 55ᵗʰ ≥ 10-pt move
    assert lens_web.diff_snapshots(snap, snap) is None         # no change → None

    # slugs: qualifier text after —/( never leaks into the anchor
    assert _slug("MULTI-TIMEFRAME  (longest → shortest)") == "multi-timeframe"
    assert _slug("GAMMA EXPOSURE — dealer positioning, Tradier chain  (≤40d)") == "gamma-exposure"
    assert _slug("OPTIONS & VOL CONTEXT  (regime: calm)") == "options-vol-context"
    assert _slug("SHORT POSITIONING / SQUEEZE  (context, not a prediction)") \
        == "short-positioning-squeeze"


# ─── Test 46: as-of historical truncation (S57 backtest mode, offline) ───────────
def test_as_of_truncation():
    """The S57 date-range/backtest mode: build_timeframes truncates the SOURCE frames (the
    forming week/month as of that date survives — truncating resampled labels would drop it),
    gather_context reads every gauge/percentile off the truncated frame, last_bar_partial
    honors the historical session via now_session, and an as-of before the data raises."""
    import pandas as pd
    import pytest
    from modules.timeframes import build_timeframes, last_bar_partial
    from modules.sentiment import gather_context

    asof = "2024-06-27"                                     # a Thursday trading day
    frames, _ = build_timeframes("QQQ", data_dir="data", include_intraday=False, as_of=asof)
    cut = pd.Timestamp(asof)
    assert frames["1D"].index.max() <= cut
    # the forming week/month resample only from bars ≤ as-of → their close == the 1D close
    d_last = float(frames["1D"]["Close"].iloc[-1])
    for tf in ("1W", "1M"):
        assert abs(float(frames[tf]["Close"].iloc[-1]) - d_last) < 1e-9
    # Thursday as-of → 4-bar forming week clears the count heuristic (4 ≥ 0.7×5), so ONLY the
    # calendar check can mark it partial — and that needs the HISTORICAL session, not the wall
    # clock (against today the 2024 week-end label is long past). The override is load-bearing.
    assert last_bar_partial(frames["1D"], "1W", now_session=frames["1D"].index[-1])
    assert not last_bar_partial(frames["1D"], "1W")

    ctx = gather_context("QQQ", data_dir="data", with_vix=False, as_of=asof)
    assert ctx["as_of"] == "2024-06-27"                     # gauges read as of that session
    assert all(g.get("value") is not None for g in ctx["gauges"])

    with pytest.raises(FileNotFoundError):                  # as-of predating all data
        build_timeframes("QQQ", data_dir="data", include_intraday=False, as_of="1970-01-02")


# ─── Test 47: trend-regime read (S57 — "inside a rally" detection, offline) ──────
def test_trend_regime():
    """The overbought-can-stay-overbought fix: during an established trend the risk scorecard's
    stretch factors fire continuously (accurately — but they read like a top call, the AMD
    Mar–Apr 2026 run being the motivating case). trend_regime labels the trend from reads the
    lens already computes; the factor tallies stay untouched (S43)."""
    import numpy as np
    import pandas as pd
    from modules.structure import (trend_regime, read_timeframe, rally_drawdown_risk,
                                   REGIME_MIN_RUN)

    reads = {"1D": {"ok": True, "trend": "up", "ma20_run": 14,
                    "_vol": {"ok": True, "tag": "up-confirmed", "price_chg_10": 0.31}},
             "1W": {"ok": True, "trend": "up"}, "1M": {"ok": True, "trend": "up"}}
    r = trend_regime(reads)
    assert r and r["state"] == "up" and r["label"] == "ESTABLISHED UPTREND"
    assert r["why"][0] == "1D+1W+1M trends aligned up"
    assert "14 consecutive sessions above" in r["why"][1]
    assert "PULLBACK" in r["note"] and "not a top call" in r["note"]

    # a short MA20 run is a poke, not a regime; 1W disagreement kills it; empty reads → None
    assert trend_regime({**reads, "1D": {**reads["1D"],
                                         "ma20_run": REGIME_MIN_RUN - 1}}) is None
    assert trend_regime({**reads, "1W": {"ok": True, "trend": "mixed"}}) is None
    assert trend_regime({}) is None

    # symmetric downtrend (the oversold-stays-oversold mirror); 1M disagrees → not listed
    dn = {"1D": {"ok": True, "trend": "down", "ma20_run": -9, "_vol": {}},
          "1W": {"ok": True, "trend": "down"}, "1M": {"ok": True, "trend": "up"}}
    rd = trend_regime(dn)
    assert rd["state"] == "down" and rd["why"][0] == "1D+1W trends aligned down"
    assert "BOUNCE" in rd["note"]

    # ma20_run wiring end-to-end: a steady ramp closes above a rising MA20 every bar → long
    # positive run, and the regime rides rally_drawdown_risk's return (tallies untouched)
    idx = pd.date_range("2025-01-01", periods=120, freq="B")
    c = pd.Series(np.linspace(100, 200, 120), index=idx)
    df = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c,
                       "Volume": 1e6}, index=idx)
    rt = read_timeframe(df)
    assert rt["ok"] and rt["trend"] == "up" and rt["ma20_run"] >= 90
    risk = rally_drawdown_risk({"1D": rt, "1W": rt}, profile=None, ctx=None, divergences={})
    assert risk["regime"] and risk["regime"]["state"] == "up"
    assert rally_drawdown_risk({}, profile=None, ctx=None, divergences={})["regime"] is None


# ─── Test 48: S58 sector rotation (offline) ─────────────────────────────────────
def test_sector_rotation(monkeypatch, tmp_path):
    """rotation_read: RS math vs SPY, quadrant tags, 63d-descending rank; own_sector maps via
    TICKER_BENCHMARK without network (AMD → XLK though its FIRST benchmark is ^SOX; a sector
    ETF maps to itself); QQQ (only benchmark ^GSPC, not a sector) falls through to the .info
    fallback, which is patched to fail here — proving the last-resort branch degrades to None
    instead of raising, without touching the network."""
    import numpy as np
    import pandas as pd
    from modules.sectors import rotation_read, own_sector, _quadrant, ROT_DEAD

    n = 80
    spy = pd.Series(np.linspace(100, 102, n))
    strong = pd.Series(np.linspace(100, 112, n))          # ahead on both horizons
    weak = pd.Series(np.linspace(100, 92, n))             # behind on both
    rows = rotation_read({"SPY": spy, "XLK": strong, "XLE": weak})
    assert [r["sym"] for r in rows] == ["XLK", "XLE"]     # ranked by 63d RS, descending
    assert rows[0]["tag"] == "leading" and rows[0]["rank"] == 1
    assert rows[1]["tag"] == "lagging" and rows[1]["rel_20d"] < 0
    assert rotation_read({"XLK": strong}) is None          # no benchmark → no read
    # quadrant corners + the flat band
    assert _quadrant(0.02, 0.05) == "leading"
    assert _quadrant(0.02, -0.05) == "improving"
    assert _quadrant(-0.02, 0.05) == "weakening"
    assert _quadrant(-0.02, -0.05) == "lagging"
    assert _quadrant(ROT_DEAD / 2, ROT_DEAD / 2) == "in line"
    monkeypatch.setattr("yfinance.Ticker",
                         lambda t: (_ for _ in ()).throw(RuntimeError("no network in tests")))
    assert own_sector("AMD", data_dir=str(tmp_path)) == "XLK"
    assert own_sector("QQQ", data_dir=str(tmp_path)) is None
    assert own_sector("XLF", data_dir=str(tmp_path)) == "XLF"


# ─── Test 48a: own_sector .info primary lookup (offline) ───────────────────────
def test_own_sector_info_fallback(monkeypatch, tmp_path):
    """own_sector's live yfinance .info lookup: a ticker absent from SECTORS resolves via
    .info['sector'] -> benchmarks.SECTOR_BENCHMARK, the result is cached to disk (a second
    call makes no further yf.Ticker call), an unmapped/empty sector (e.g. an ETF, and not a
    TICKER_BENCHMARK member) degrades to None, and a raising .info (401, etc.) never
    propagates (and, absent a TICKER_BENCHMARK/stale-cache match, also degrades to None)."""
    from modules.sectors import own_sector, LOOKUP_CACHE_FILE

    calls = []

    class FakeTicker:
        def __init__(self, sym):
            calls.append(sym)
            self.info = {"sector": "Technology"}

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)
    assert own_sector("MSFT", data_dir=str(tmp_path)) == "XLK"
    assert calls == ["MSFT"]
    assert (tmp_path / LOOKUP_CACHE_FILE).exists()

    assert own_sector("MSFT", data_dir=str(tmp_path)) == "XLK"   # served from cache
    assert calls == ["MSFT"]                                     # no second network call

    class EmptyTicker:
        def __init__(self, sym):
            self.info = {}
    monkeypatch.setattr("yfinance.Ticker", EmptyTicker)
    assert own_sector("SPY", data_dir=str(tmp_path)) is None      # unmapped, not in TICKER_BENCHMARK

    monkeypatch.setattr("yfinance.Ticker",
                         lambda t: (_ for _ in ()).throw(RuntimeError("401")))
    assert own_sector("ZZZZ", data_dir=str(tmp_path)) is None     # raises, not in TICKER_BENCHMARK


# ─── Test 48a-ii: own_sector — network takes priority over TICKER_BENCHMARK ────
def test_own_sector_network_priority(monkeypatch, tmp_path):
    """A live .info resolution now WINS over TICKER_BENCHMARK, even for a ticker
    TICKER_BENCHMARK already covers: AMD's TICKER_BENCHMARK entry implies XLK, but a
    successful live .info read of "Communication Services" resolves it to XLC instead,
    proving the network call fires and takes priority rather than TICKER_BENCHMARK
    short-circuiting it. calls confirms yf.Ticker really was invoked for AMD."""
    from modules.sectors import own_sector

    calls = []

    class FakeTicker:
        def __init__(self, sym):
            calls.append(sym)
            self.info = {"sector": "Communication Services"}

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)
    assert own_sector("AMD", data_dir=str(tmp_path)) == "XLC"
    assert calls == ["AMD"]


# ─── Test 48a-iii: own_sector — TICKER_BENCHMARK fallback, then stale cache ────
def test_own_sector_ticker_benchmark_and_stale_fallback(monkeypatch, tmp_path):
    """When the live lookup fails, own_sector falls back to TICKER_BENCHMARK (AMD -> XLK,
    matching test_sector_rotation). Once a ticker has EVER resolved, that resolution
    survives as a last-resort fallback past its cache TTL even if BOTH the live lookup and
    TICKER_BENCHMARK subsequently fail for it (a stale answer beats none)."""
    import json
    import time
    from modules.sectors import own_sector, LOOKUP_CACHE_FILE

    monkeypatch.setattr("yfinance.Ticker",
                         lambda t: (_ for _ in ()).throw(RuntimeError("no network")))
    assert own_sector("AMD", data_dir=str(tmp_path)) == "XLK"     # TICKER_BENCHMARK fallback

    # Ticker not in TICKER_BENCHMARK at all, seeded with an expired-but-resolved cache entry.
    cache_path = tmp_path / LOOKUP_CACHE_FILE
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache["MSFT"] = {"sym": "XLK", "ts": time.time() - 999 * 24 * 3600}   # far past the 30d TTL
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    assert own_sector("MSFT", data_dir=str(tmp_path)) == "XLK"    # stale-cache last resort


# ─── Test 48b: S59 sector top performers (offline) ─────────────────────────────
def test_sector_top_performers():
    """top_performers_read: 63d-descending rank within each sector, TOP_N cap, 20d fallback
    when a series is too short for 63d, <REL_SHORT+1-session names omitted, empty → {};
    YF_SECTOR_KEYS covers all 11 SPDR sectors."""
    import numpy as np
    import pandas as pd
    from modules.sectors import (top_performers_read, SECTORS, YF_SECTOR_KEYS,
                                 TOP_N, REL_SHORT)

    assert set(YF_SECTOR_KEYS) == set(SECTORS)             # every sector reachable
    n = 70
    closes = {
        "AAA": pd.Series(np.linspace(100, 130, n)),        # r63 ≈ +27% — best
        "BBB": pd.Series(np.linspace(100, 115, n)),        # r63 ≈ +13%
        "CCC": pd.Series(np.linspace(100, 105, n)),        # r63 ≈ +5% — cut by TOP_N
        "DDD": pd.Series(np.linspace(100, 101, n)),        # r63 ≈ +1% — cut by TOP_N
        "SHORT63": pd.Series(np.linspace(100, 120, 40)),   # <64 sessions → r63 None; its r20
        "TOOSHORT": pd.Series(np.linspace(100, 150, 10)),  # (≈+9%) ranks it above CCC's 63d
    }
    cons = {"XLK": [(s, s.title()) for s in
                    ("AAA", "BBB", "CCC", "DDD", "SHORT63", "TOOSHORT")],
            "XLE": [("TOOSHORT", "Tooshort")]}             # no usable name → sector omitted
    out = top_performers_read(cons, closes)
    assert "XLE" not in out and set(out) == {"XLK"}
    tk = out["XLK"]
    assert len(tk) == TOP_N                                # capped
    # SHORT63's 20d return (~+9%) outranks CCC's 63d (~+5%) under the shared sort key
    assert [m["sym"] for m in tk] == ["AAA", "BBB", "SHORT63"]
    assert tk[0]["r63"] is not None and tk[2]["r63"] is None and tk[2]["r20"] > 0
    assert len(pd.Series(closes["TOOSHORT"])) <= REL_SHORT # the omission premise holds
    assert top_performers_read({}, {}) == {}
    assert top_performers_read(None, None) == {}


# ─── Test 49: S58 buzz history / unranked sentinel (offline via canned cache) ──
def test_buzz_history(tmp_path):
    """fetch_buzz off a fresh canned cache (no network): ranked ticker → read + history row
    recorded (deduped on date+ticker); absent ticker → {"unranked": True}; mentions_pct floors
    at HIST_MIN_OBS prior days and excludes today's own row."""
    import json
    from modules.buzz import fetch_buzz, mentions_pct, record_history, ticker_history, HIST_MIN_OBS

    d = str(tmp_path)
    results = [{"ticker": "NVDA", "rank": 3, "mentions": 120, "upvotes": 10,
                "rank_24h_ago": 5, "mentions_24h_ago": 60}]
    (tmp_path / "buzz_cache.json").write_text(json.dumps(results), encoding="utf-8")

    r = fetch_buzz("NVDA", data_dir=d)
    assert r["rank"] == 3 and r["chg"] == 1.0
    assert r["history"] and r["history"][-1]["mentions"] == 120
    assert fetch_buzz("ZZZZZ", data_dir=d) == {"unranked": True}

    record_history(results, d)                             # same day again → deduped, not doubled
    assert len(ticker_history("NVDA", d)) == 1

    hist = [{"date": f"2026-06-{i:02d}", "mentions": 10} for i in range(1, HIST_MIN_OBS + 1)]
    assert mentions_pct(hist, 50, today="2026-07-01") == 1.0
    assert mentions_pct(hist[: HIST_MIN_OBS - 1], 50, today="2026-07-01") is None
    assert mentions_pct(hist + [{"date": "2026-07-01", "mentions": 999}], 50,
                        today="2026-07-01") == 1.0        # today's own row excluded


# ─── Test 50: S58 street_read (offline) ─────────────────────────────────────────
def test_street_read():
    """street_read: PT upside vs spot, 30d EPS-revision tags + net, trailing-90d rating counts;
    empty inputs (ETF/uncovered) → {} so the section degrades to headlines-only."""
    from modules.street import street_read, REV_DEAD

    pt = {"current": 100.0, "mean": 110.0, "median": 108.0, "high": 130.0, "low": 90.0}
    eps = {"0q": {"current": 1.05, "30daysAgo": 1.00},      # +5% → up
           "+1y": {"current": 0.99, "30daysAgo": 1.00}}     # −1% → down
    ud = [{"date": "2026-07-10", "firm": "A", "action": "up", "pt_action": "Raises"},
          {"date": "2026-07-01", "firm": "B", "action": "main", "pt_action": "Raises"},
          {"date": "2026-06-20", "firm": "C", "action": "down", "pt_action": "Lowers"},
          {"date": "2025-01-01", "firm": "D", "action": "up", "pt_action": "Raises"}]  # stale
    r = street_read(pt, ud, eps, now="2026-07-14")
    assert abs(r["pt"]["upside_mean"] - 0.10) < 1e-9
    tags = {x["period"]: x["tag"] for x in r["revisions"]}
    assert tags == {"0q": "up", "+1y": "down"} and r["rev_net"] == "estimates flat"
    assert r["ud"]["n"] == 3 and r["ud"]["n_up"] == 1 and r["ud"]["n_down"] == 1
    assert r["ud"]["pt_raises"] == 2 and r["ud"]["pt_lowers"] == 1
    assert street_read({}, [], {}, now="2026-07-14") == {}
    assert abs(REV_DEAD - 0.005) < 1e-12


# ─── Test 51: S58 marketsent parsers/reads (offline) ────────────────────────────
def test_marketsent_reads():
    """parse_cboe on the escaped Next.js blob shape; equity-P/C bands; aaii_read full-history
    percentile + contrarian tag; naaim_read bands + accumulated-history percentile floor;
    liq_read FRED-native units (WALCL/WTREGEN $mn, RRP $bn) + 13w tag."""
    from modules.marketsent import (parse_cboe, label_equity_pc, aaii_read, naaim_read,
                                    liq_read, HIST_MIN_WEEKLY)

    blob = ('x{\\"name\\":\\"TOTAL PUT/CALL RATIO\\",\\"value\\":\\"0.96\\"},'
            '{\\"name\\":\\"INDEX PUT/CALL RATIO\\",\\"value\\":\\"1.10\\"},'
            '{\\"name\\":\\"EQUITY PUT/CALL RATIO\\",\\"value\\":\\"0.67\\"}y')
    r = parse_cboe(blob)
    assert r == {"total": 0.96, "index": 1.10, "equity": 0.67}
    assert parse_cboe("<html>no ratios</html>") is None
    assert label_equity_pc(0.40).startswith("complacent")
    assert label_equity_pc(0.67) == "normal" and label_equity_pc(1.0).startswith("fearful")

    rows = [{"date": f"2025-{m:02d}-01", "bull": 0.30, "bear": 0.40} for m in range(1, 13)]
    rows += [{"date": f"2026-{m:02d}-01", "bull": 0.30, "bear": 0.40} for m in range(1, 13)]
    rows += [{"date": "2026-07-03", "bull": 0.30, "bear": 0.40},
             {"date": "2026-07-10", "bull": 0.60, "bear": 0.10}]      # most bullish ever
    a = aaii_read(rows)
    assert a["pct"] == 1.0 and a["tag"].startswith("crowded bullish")
    assert abs(a["spread"] - 0.50) < 1e-9
    assert aaii_read(rows[:5]) is None                    # under the weekly floor

    hist = {f"2026-01-{i:02d}": 50.0 for i in range(1, HIST_MIN_WEEKLY + 1)}
    n = naaim_read([("2026-07-08", 95.0), ("2026-07-01", 85.0)], hist=hist)
    assert n["tag"] == "leveraged/max long" and n["pct"] == 1.0
    assert naaim_read([("2026-07-08", 20.0)], hist={})["tag"] == "defensive"

    import pandas as pd
    dates = pd.date_range("2025-01-01", periods=30, freq="W-WED")
    walcl = {d.date().isoformat(): 6_600_000 + i * 10_000 for i, d in enumerate(dates)}  # $mn, rising
    tga = {d.date().isoformat(): 800_000 for d in dates}                                 # $mn
    rrp = {d.date().isoformat(): 100.0 for d in dates}                                   # $bn
    lq = liq_read(walcl, tga, rrp)
    assert lq["tag"] == "rising" and abs(lq["chg_13w_bn"] - 130.0) < 1e-6
    assert abs(lq["level_bn"] - (6_890.0 - 800.0 - 100.0)) < 1e-6


def test_s61_live_bar_prefers_official_close():
    """fetch_live_bar (S40) post-bell: the quote's `close` is the OFFICIAL close — `last`
    keeps updating on after-hours prints and would contaminate a bar presented as the
    completed session (in_progress False)."""
    import pandas as pd

    import modules.tradier as tradier
    from modules.timeframes import fetch_live_bar

    now_ms = int(pd.Timestamp.now(tz="UTC").value // 10**6)
    base = {"trade_date": now_ms, "open": 420.0, "high": 431.0, "low": 419.0,
            "volume": 1_000_000}
    orig = tradier.get_daily_quote
    try:
        # session open: close is null → provisional bar rides `last`
        tradier.get_daily_quote = lambda t: {**base, "last": 425.5, "close": None}
        bar = fetch_live_bar("QQQ")
        assert bar["in_progress"] is True and bar["Close"] == 425.5
        # after the bell: official close present, `last` is an AH print — close wins
        tradier.get_daily_quote = lambda t: {**base, "last": 421.5, "close": 430.0}
        bar = fetch_live_bar("QQQ")
        assert bar["in_progress"] is False and bar["Close"] == 430.0
    finally:
        tradier.get_daily_quote = orig


def test_s61_buzz_percentile_uses_full_history(tmp_path):
    """The mentions percentile must see the full retained history (~400d), not the 60-row
    sparkline tail — a name quiet for 60 days otherwise reads '100th percentile' on any
    modest uptick. Also guards the sparkline payload staying capped at 60 rows."""
    import json as _json
    import time as _time

    import pandas as pd

    from modules.buzz import CACHE_FILE, HISTORY_FILE, fetch_buzz

    days = pd.bdate_range(end=pd.Timestamp.today() - pd.Timedelta(days=1), periods=100)
    n = len(days)   # pandas 3.x returns periods-1 when `end` lands on a non-business day
                    # (e.g. run on a Monday → end is a Sunday); size the values off the index
    hist = pd.DataFrame({"date": [d.date().isoformat() for d in days],
                         "ticker": "TST", "rank": 10,
                         "mentions": list(range(1, n + 1))})     # 1..n, oldest→newest
    hist.to_csv(tmp_path / HISTORY_FILE, index=False)
    results = [{"ticker": "TST", "rank": 5, "mentions": 50, "upvotes": 1,
                "rank_24h_ago": 6, "mentions_24h_ago": 40}]
    (tmp_path / CACHE_FILE).write_text(_json.dumps(results), encoding="utf-8")

    read = fetch_buzz("TST", data_dir=str(tmp_path))
    assert read is not None and read.get("rank") == 5
    # 49 of the n prior days (mentions 1..49) sit below 50 → 49/n; the old 60-row window
    # capped the denominator at ~59 prior days and read ~0.15
    assert abs(read["pct"] - 49 / n) < 1e-9
    assert len(read["history"]) <= 60                    # sparkline rows stay capped
    _time.sleep(0)  # (no-op; keeps the import grouped)


def test_s61_buzz_cache_read_stamps_fetch_date(tmp_path):
    """A post-midnight read of yesterday-evening's cache must stamp history under the
    FETCH date (file mtime), not the read date — keep='first' would otherwise block the
    day's real snapshot."""
    import json as _json
    import os as _os
    import time as _time

    import pandas as pd

    from modules.buzz import CACHE_FILE, HISTORY_FILE, fetch_buzz

    results = [{"ticker": "TST", "rank": 3, "mentions": 77}]
    path = tmp_path / CACHE_FILE
    path.write_text(_json.dumps(results), encoding="utf-8")
    yesterday_2300 = _time.time() - 4 * 3600             # a 23:00-yesterday-style mtime
    _os.utime(path, (yesterday_2300, yesterday_2300))

    fetch_buzz("TST", data_dir=str(tmp_path), ttl_hours=6)
    hist = pd.read_csv(tmp_path / HISTORY_FILE, dtype={"date": str})
    stamped = _time.strftime("%Y-%m-%d", _time.localtime(yesterday_2300))
    assert list(hist["date"]) == [stamped]               # mtime date, never the read date


def test_s61_marketsent_allfail_never_rewrites(tmp_path, monkeypatch):
    """All four sources failing must serve the stale cache WITHOUT rewriting it — a
    rewrite restamps stale gauges with a fresh as_of/mtime and suppresses the retry
    (cot.py's documented guard, previously missing here)."""
    import json as _json
    import os as _os

    import modules.marketsent as ms

    old = {"gauges": {"cboe": {"equity": 0.7, "date": "2026-07-20"}},
           "hist": {"eq_pc": {}, "naaim": {}}, "as_of_str": "OLD-STAMP"}
    path = tmp_path / ms.CACHE_FILE
    path.write_text(_json.dumps(old), encoding="utf-8")
    stale = _os.path.getmtime(path) - 2 * 86400
    _os.utime(path, (stale, stale))

    def boom(*a, **k):
        raise RuntimeError("network down")
    for name in ("_fetch_cboe", "_fetch_aaii", "_fetch_naaim", "_fetch_liq"):
        monkeypatch.setattr(ms, name, boom)

    out = ms.fetch_marketsent(data_dir=str(tmp_path), ttl_hours=6)
    assert out["as_of_str"] == "OLD-STAMP"               # stale served…
    on_disk = _json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["as_of_str"] == "OLD-STAMP"           # …and never restamped
    # shape-corrupt cache (valid JSON, wrong type) must not escape "never raises"
    path.write_text(_json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert ms.fetch_marketsent(data_dir=str(tmp_path), ttl_hours=6) is None


def test_s61_cot_percentile_prior_weeks_strict():
    """parse_cot's percentile: PRIOR weeks only, strict < — self-inclusion with <= put a
    1/n floor under record extremes (a record low could never read 0th percentile)."""
    from modules.cot import parse_cot

    def rows(npos):
        return [{"report_date_as_yyyy_mm_dd": f"2026-{(i // 4) + 1:02d}-{(i % 4) * 7 + 1:02d}",
                 "lev_money_positions_long": str(1000 + n), "lev_money_positions_short": "1000",
                 "open_interest_all": "10000"} for i, n in enumerate(npos)]

    up = parse_cot(rows(list(range(30))))                # latest = record high
    assert up["pct"] == 1.0
    dn = parse_cot(rows(list(range(29, -1, -1))))        # latest = record low
    assert dn["pct"] == 0.0


def test_s61_sectors_close_frame_single_symbol():
    """yfinance returns FLAT columns when exactly one symbol survives a list download —
    the old raw[['Close']] fallback kept the literal column name 'Close' and silently
    discarded the data in hand."""
    import pandas as pd

    from modules.sectors import _close_frame

    idx = pd.bdate_range("2026-01-02", periods=5)
    flat = pd.DataFrame({"Open": 1.0, "Close": [10, 11, 12, 13, 14]}, index=idx)
    out = _close_frame(flat, ["XLK"])
    assert "XLK" in out.columns and list(out["XLK"]) == [10, 11, 12, 13, 14]

    multi = pd.DataFrame({("Close", "XLK"): [1.0] * 5, ("Close", "SPY"): [2.0] * 5}, index=idx)
    multi.columns = pd.MultiIndex.from_tuples(multi.columns)
    out2 = _close_frame(multi, ["XLK", "SPY"])
    assert set(out2.columns) == {"XLK", "SPY"}


def test_s61_street_nan_price_targets():
    """NaN is truthy — a NaN mean/median from yfinance previously passed the guards and
    printed 'median $nan' (and landed as an invalid NaN token in the cache JSON)."""
    from modules.street import street_read

    assert "pt" not in street_read({"current": 100.0, "mean": float("nan")}, [], {})
    r = street_read({"current": 100.0, "mean": 120.0, "median": float("nan"),
                     "high": 150.0, "low": float("nan")}, [], {})
    assert r["pt"]["median"] is None and r["pt"]["low"] is None
    assert r["pt"]["high"] == 150.0 and abs(r["pt"]["upside_mean"] - 0.20) < 1e-9


# ─── S62: squeeze-shell fix + Massive auth-aware failure message ─────────────────
def test_s62_failed_squeeze_leaves_buzz_standalone(monkeypatch):
    """gather_squeeze returning None (both SI sources down) with a RANKED buzz must leave
    payload['squeeze'] None — the old code built {'buzz': ...}, rendering an all-n/a
    SHORT POSITIONING shell that also suppressed the RETAIL ATTENTION section."""
    from types import SimpleNamespace

    import lens

    for name in ("next_earnings", "next_ex_dividend", "fetch_rs", "fetch_beta",
                 "fetch_sectors", "own_sector", "fetch_street",
                 "fetch_breadth", "ew_comparator"):                             # S67 off too
        monkeypatch.setattr(lens, name, None, raising=False)
    ranked = {"rank": 42, "mentions": 100, "rank_prev": 50, "chg": 0.1}
    monkeypatch.setattr(lens, "fetch_buzz", lambda ticker, data_dir="data": dict(ranked))
    monkeypatch.setattr(lens, "gather_squeeze", lambda *a, **k: None)

    args = SimpleNamespace(ticker=None, thesis=None, level=None, no_intraday=True, no_vix=True,
                           geo=False, no_color=True, candle="none", candle_px=128, prev=10,
                           data_dir="data", no_refresh=True, refresh=False, pc_oi=None,
                           insider=False, squeeze=True, live=False, vol=False, call=False,
                           street=False)
    payload = lens.gather_report("QQQ", args, interactive=False, backdrop_base=None)
    assert payload is not None
    assert payload["squeeze"] is None                      # no empty shell
    assert payload["buzz"] and payload["buzz"]["rank"] == 42   # buzz survives standalone
    assert any("short-positioning data unavailable" in n for n in payload["notes"])

    # and when the squeeze fetch SUCCEEDS, ranked buzz still rides the block
    monkeypatch.setattr(lens, "gather_squeeze", lambda *a, **k: {"si": None, "read": {}})
    payload2 = lens.gather_report("QQQ", args, interactive=False, backdrop_base=None)
    assert payload2["squeeze"] and payload2["squeeze"]["buzz"]["rank"] == 42


def test_s62_massive_auth_failure_message():
    """A paused/inactive Massive subscription surfaces as HTTP 401/403 — the failure line
    must say so (re-running the harvest cannot help until the subscription is restored)."""
    from types import SimpleNamespace

    from modules.massive import _fetch_fail_msg

    auth = SimpleNamespace(response=SimpleNamespace(status_code=403))
    msg = _fetch_fail_msg(auth)
    assert "403" in msg and "subscription" in msg and "price pipeline unaffected" in msg
    assert "subscription" not in _fetch_fail_msg(RuntimeError("boom"))
    assert "boom" in _fetch_fail_msg(RuntimeError("boom"))


# ─── S63: day-trader timeframes (2h trend row + 5m/15m/30m entry timing) ─────────
def test_s63_session_open_boundaries():
    """The entry-timing frames exist only inside RTH — the gate must be exact at both ends
    and shut on weekends (holidays are approximated as weekdays, same as
    _last_completed_session)."""
    import pandas as pd

    from modules.timeframes import session_open

    mon = "2026-07-27"                                  # a Monday
    assert not session_open(pd.Timestamp(f"{mon} 09:29"))
    assert session_open(pd.Timestamp(f"{mon} 09:30"))    # bell — inclusive
    assert session_open(pd.Timestamp(f"{mon} 15:59"))
    assert not session_open(pd.Timestamp(f"{mon} 16:00"))   # close — exclusive
    assert not session_open(pd.Timestamp(f"{mon} 20:00"))
    assert not session_open(pd.Timestamp("2026-07-25 12:00"))   # Saturday
    # tz-aware input is converted, not rejected: 17:00 UTC = 13:00 ET → open
    assert session_open(pd.Timestamp(f"{mon} 17:00", tz="UTC"))


def test_s63_ltf_resampling():
    """One 5m fetch feeds three rows: 15m/30m resample off it (the :30 session grid divides
    evenly, so no offset), and 2h rides the cached 1h frame with a 90min offset so its bins
    are session-anchored (09:30/11:30/13:30/15:30) rather than wall-clock. 90 and not 30:
    pandas anchors bins at midnight+offset, and 09:30 sits 90min past a 2h boundary."""
    import pandas as pd

    from modules.timeframes import _resample

    idx = pd.date_range("2026-07-27 09:30", periods=78, freq="5min")   # one RTH session
    m5 = pd.DataFrame({"Open": range(78), "High": range(1, 79), "Low": range(-1, 77),
                       "Close": range(78), "Volume": [10.0] * 78}, index=idx)
    m15 = _resample(m5, "15min")
    assert len(m15) == 26 and str(m15.index[0].time()) == "09:30:00"
    assert m15["Volume"].iloc[0] == 30.0                 # 3 five-minute bars summed
    assert m15["Open"].iloc[0] == 0 and m15["Close"].iloc[0] == 2
    assert m15["High"].iloc[0] == 3 and m15["Low"].iloc[0] == -1
    m30 = _resample(m5, "30min")
    assert len(m30) == 13 and m30["Volume"].iloc[0] == 60.0

    h1 = pd.DataFrame({"Open": range(7), "High": range(1, 8), "Low": range(-1, 6),
                       "Close": range(7), "Volume": [100.0] * 7},
                      index=pd.date_range("2026-07-27 09:30", periods=7, freq="60min"))
    h2 = _resample(h1, "2h", offset="90min")
    assert [str(t.time()) for t in h2.index] == ["09:30:00", "11:30:00", "13:30:00", "15:30:00"]
    assert h2["Volume"].iloc[0] == 200.0                 # two hourly bars per 2h bin
    # without the offset the bins land on the wall clock instead — the reason it is passed
    assert str(_resample(h1, "2h").index[0].time()) == "08:00:00"


def test_s63_entry_frames_excluded_from_analysis():
    """The whole contract of the entry-timing block: it is DISPLAY-ONLY. A sub-hourly read
    must not enter the confluence synthesis, must not raise an RSI-split warning, and its
    divergences must not become risk-scorecard factors."""
    from modules.structure import multi_timeframe_summary, rally_drawdown_risk

    trend = {"1M": {"ok": True, "trend": "up", "rsi_state": "neutral"},
             "1W": {"ok": True, "trend": "up", "rsi_state": "neutral"},
             "1D": {"ok": True, "trend": "up", "rsi_state": "neutral"},
             "1h": {"ok": True, "trend": "up", "rsi_state": "neutral"}}
    base = multi_timeframe_summary(trend)
    assert base["synthesis"] == "full bullish confluence across timeframes."
    assert base["rsi_conflict"] is None

    # a 5m gone oversold + a 15m gone down: the synthesis and the RSI-split line must not move
    noisy = {**trend,
             "30m": {"ok": True, "trend": "down", "rsi_state": "neutral"},
             "15m": {"ok": True, "trend": "down", "rsi_state": "overbought"},
             "5m": {"ok": True, "trend": "down", "rsi_state": "oversold"}}
    out = multi_timeframe_summary(noisy)
    assert out["synthesis"] == base["synthesis"]
    assert out["rsi_conflict"] is None                   # would fire on OB+OS without the filter
    assert set(out["trend_row"]) == set(trend)           # sub-hourly absent from the rows too

    # 2h DOES count — it is an hourly-grade trend frame, only sub-hour is excluded
    assert "2h" in multi_timeframe_summary(
        {**trend, "2h": {"ok": True, "trend": "up", "rsi_state": "neutral"}})["trend_row"]

    # divergences: lens._trend_divs strips the sub-hourly ones before the scorecard sees them
    import lens

    divs = {"1W": ("bearish", "why"), "5m": ("bullish", "why"), "30m": ("bullish", "why")}
    assert set(lens._trend_divs(divs)) == {"1W"}
    r_clean = rally_drawdown_risk(trend, divergences=lens._trend_divs(divs))
    r_raw = rally_drawdown_risk(trend, divergences=divs)
    assert len(r_clean["rally"]) == 0                    # …and 2 bogus rally factors without it
    assert len(r_raw["rally"]) == 2


# ─── Test 62 (S67): market-breadth section reads (offline) ─────────────────────
def test_breadth_section_reads(monkeypatch, tmp_path):
    """S67 read_breadth extensions (spark / cap_off_high / divergence fields), the pure
    divergence_read matrix, and the fetch_breadth cache shape gate (a TTL-fresh pre-S67 cache
    refetches; the stale-FALLBACK path still serves the old shape, so consumers must .get())."""
    import json
    import pandas as pd
    from modules.breadth import (read_breadth, divergence_read, fetch_breadth,
                                 BREADTH_DEAD, CACHE_FILE)

    n = 300
    cap = pd.Series([100.0] * n)
    lead = pd.Series([100.0 * (1.002 ** i) for i in range(n)])
    out = read_breadth({"LEAD": (lead, cap)})["LEAD"]
    assert isinstance(out["spark"], list) and 2 <= len(out["spark"]) <= 60
    assert all(isinstance(v, float) for v in out["spark"])
    assert abs(out["spark"][-1] - out["rel_20d"]) < 1e-12     # latest spread survives sampling
    assert out["cap_off_high"] <= 0                           # distance from 252d high is ≤ 0
    assert out["div_state"] in ("narrowing", "broad", "repair", "neutral")

    # divergence matrix — two-sided per S43
    assert divergence_read(-0.02, 0.10, -0.01)[0] == "narrowing"
    assert divergence_read(0.0, 0.10, -0.01)[0] == "narrowing"   # low-percentile trigger alone
    assert divergence_read(0.02, 0.80, -0.01)[0] == "broad"
    assert divergence_read(0.02, 0.80, -0.10)[0] == "repair"
    assert divergence_read(0.0, 0.50, -0.03) == ("neutral", "")
    assert divergence_read(None, None, None) == ("neutral", "")
    assert divergence_read(-0.02, 0.10, -0.10)[0] == "neutral"   # off the highs + lagging ≠ narrowing

    # cache shape gate: a TTL-fresh pre-S67 cache (no "participation") must NOT satisfy the
    # fresh-path read…
    old = {"pairs": {"RSP−SPY": {"rel_20d": 0.01, "rel_63d": 0.02, "pct": 0.5, "tag": "broad-led"}}}
    (tmp_path / CACHE_FILE).write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr("yfinance.download",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network")))
    got = fetch_breadth(data_dir=str(tmp_path))
    assert got == old                          # …but the stale FALLBACK still serves it
    # …and with a working download the refetch produces the new shape
    idx = pd.bdate_range("2025-01-01", periods=n)
    syms = ["IWM", "QQQ", "QQQE", "RSP", "SPY"]
    frame = pd.DataFrame({("Close", s): [100.0 * (1.001 ** i) for i in range(n)] for s in syms},
                         index=idx)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    monkeypatch.setattr("yfinance.download", lambda *a, **k: frame)
    got2 = fetch_breadth(data_dir=str(tmp_path))
    assert "participation" in got2 and "IWM−SPY" in got2["participation"]
    assert set(got2["pairs"]) == {"RSP−SPY", "QQQE−QQQ"}
    assert "spark" in got2["pairs"]["RSP−SPY"]


# ─── Test 63 (S67): sector equal-weight twin read (offline) ────────────────────
def test_sector_ew_twin(monkeypatch, tmp_path):
    """rotation_read's ew_20d/ew_tag: EW twin lagging its SPDR beyond ±ROT_DEAD → 'narrow',
    leading → 'broad', twin absent from closes → None/None; ranking untouched. Plus the new
    fetch_sectors shape gate: a TTL-fresh pre-S67 cache (rows without 'ew_tag') refetches."""
    import json
    import numpy as np
    import pandas as pd
    from modules.sectors import rotation_read, fetch_sectors, CACHE_FILE

    n = 80
    spy = pd.Series(np.linspace(100, 102, n))
    xlk = pd.Series(np.linspace(100, 112, n))
    xle = pd.Series(np.linspace(100, 92, n))
    rspt_lag = pd.Series(np.linspace(100, 104, n))       # well behind XLK → narrow
    rows = rotation_read({"SPY": spy, "XLK": xlk, "XLE": xle, "RSPT": rspt_lag})
    xlk_row = next(r for r in rows if r["sym"] == "XLK")
    assert xlk_row["ew_tag"] == "narrow" and xlk_row["ew_20d"] < 0
    xle_row = next(r for r in rows if r["sym"] == "XLE")
    assert xle_row["ew_20d"] is None and xle_row["ew_tag"] is None   # no RSPG series supplied
    assert [r["sym"] for r in rows] == ["XLK", "XLE"]                # ranking untouched
    assert xlk_row["rank"] == 1

    rspt_lead = pd.Series(np.linspace(100, 125, n))      # well ahead of XLK → broad
    rows2 = rotation_read({"SPY": spy, "XLK": xlk, "RSPT": rspt_lead})
    assert rows2[0]["ew_tag"] == "broad" and rows2[0]["ew_20d"] > 0

    # shape gate: fresh old-shape cache must refetch instead of serving rows missing ew_tag
    old = {"rows": [{"sym": "XLK", "name": "Technology", "rel_20d": 0.01, "rel_63d": 0.02,
                     "tag": "leading", "rank": 1}]}
    (tmp_path / CACHE_FILE).write_text(json.dumps(old), encoding="utf-8")
    idx = pd.bdate_range("2025-01-01", periods=n)
    frame = pd.DataFrame({("Close", "SPY"): spy.values, ("Close", "XLK"): xlk.values,
                          ("Close", "RSPT"): rspt_lag.values}, index=idx)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    monkeypatch.setattr("yfinance.download", lambda *a, **k: frame)
    got = fetch_sectors(data_dir=str(tmp_path))
    assert got["rows"] and "ew_tag" in got["rows"][0]    # refetched, new shape


# ─── Test 64 (S67): equal-weight comparator mapping (offline, pure) ────────────
def test_ew_comparator():
    """sectors.ew_comparator: QQQ→QQQE, SPY→RSP, a SPDR→its RSP* twin, a resolved own-sector
    →its twin, unknown+no-sector→RSP fallback, an equal-weight vehicle itself→None."""
    from modules.sectors import ew_comparator

    assert ew_comparator("QQQ") == ("QQQE", "average NDX-100 stock")
    assert ew_comparator("SPY") == ("RSP", "average S&P 500 stock")
    assert ew_comparator("XLK") == ("RSPT", "average Technology stock")
    assert ew_comparator("CRSP", own_sector_sym="XLV") == ("RSPH", "average Health Care stock")
    assert ew_comparator("FAKE") == ("RSP", "average S&P 500 stock")
    assert ew_comparator("FAKE", own_sector_sym=None) == ("RSP", "average S&P 500 stock")
    for ew in ("RSP", "QQQE", "RSPT"):
        assert ew_comparator(ew) is None


# ─── Test 65 (S67): fetch_rs extra rider (offline) ─────────────────────────────
def test_fetch_rs_extra_rider(monkeypatch, tmp_path):
    """fetch_rs(extra=): comparators ride the SAME single download as a symbol list; extra=None
    returns the exact pre-S67 shape and numbers (no 'extra' key); setup_check row 4 is
    byte-identical with or without the rider (row semantics frozen, S65); the flat-columns
    single-survivor download shape still resolves (S61 lesson). S70: each call gets its own
    empty data_dir so the rs_cache stays cold — the batching assertion keeps its meaning."""
    import pandas as pd
    from modules.setupcheck import fetch_rs, setup_check

    n = 100
    idx = pd.bdate_range("2025-01-01", periods=n)
    daily = pd.DataFrame({"Close": [100.0 * (1.002 ** i) for i in range(n)]}, index=idx)
    calls = []

    def fake_download(syms, **k):
        calls.append(list(syms) if isinstance(syms, (list, tuple)) else [syms])
        cols = {("Close", s): [100.0 * (1.001 ** i) * (1 + j * 0.001)
                               for i in range(n)]
                for j, s in enumerate(calls[-1])}
        f = pd.DataFrame(cols, index=idx)
        f.columns = pd.MultiIndex.from_tuples(f.columns)
        return f

    monkeypatch.setattr("yfinance.download", fake_download)
    base = fetch_rs("FAKE", daily, data_dir=str(tmp_path / "a"))   # FAKE → SPY fallback bench
    assert set(base) == {"bench", "rs"} and base["bench"] == "SPY"
    assert set(base["rs"]) == {20, 63}

    withx = fetch_rs("FAKE", daily, data_dir=str(tmp_path / "b"),
                     extra=[("RSP", "average S&P 500 stock")])
    assert calls[-1] == ["SPY", "RSP"]                         # ONE download, symbol list
    assert withx["bench"] == "SPY" and withx["rs"] == base["rs"]   # bench math untouched
    assert withx["extra"]["RSP"]["label"] == "average S&P 500 stock"
    assert set(withx["extra"]["RSP"]["rs"]) == {20, 63}

    # setup_check row 4 byte-identical with/without the rider
    row4 = lambda rs: next(r for r in setup_check({}, rs=rs)["rows"]
                           if r[0] == "Relative strength")
    assert row4(base) == row4(withx)

    # flat single-survivor shape (yfinance drops the MultiIndex when one symbol survives)
    def flat_download(syms, **k):
        return pd.DataFrame({"Close": [100.0 * (1.001 ** i) for i in range(n)]}, index=idx)

    monkeypatch.setattr("yfinance.download", flat_download)
    flat = fetch_rs("FAKE", daily, data_dir=str(tmp_path / "c"))
    assert flat and set(flat["rs"]) == {20, 63}


# ─── Test 66 (S68): level projections — travel + repricing (offline, pure) ─────
def test_levelproj_travel_and_reprice():
    """travel_sessions is linear sigma-days off HV-20 (None/degenerate → None, 252 cap);
    reprice_contract is exact BS repricing at the target — instant leg T unchanged, paced
    leg T reduced by the trading→calendar conversion (huge travel → intrinsic), at-ask P&L
    below at-mid, downside targets price to an honest loss, iv-less candidates → None."""
    import math
    from modules.bs_invert import black_scholes_call
    from modules.levelproj import (travel_sessions, reprice_contract,
                                   MAX_TRAVEL_SESSIONS, RISK_FREE)

    daily = 0.16 / math.sqrt(252)                       # hv20 16% → σ/day ≈ 1.008%
    assert abs(travel_sessions(0.03, 0.16) - 0.03 / daily) < 1e-12
    assert travel_sessions(0.03, None) is None
    assert travel_sessions(0.03, 0.0) is None
    assert travel_sessions(9.0, 0.16) == MAX_TRAVEL_SESSIONS

    cand = {"strike": 100.0, "mid": 5.0, "iv": 0.25, "ask": 5.6}
    c = reprice_contract(110.0, cand, 45, expiry="2026-09-18", travel_td=3.0)
    assert c["instant"]["value"] == black_scholes_call(110.0, 100.0, RISK_FREE, 45 / 365.0, 0.25)
    assert c["paced"]["value"] < c["instant"]["value"]          # shorter T, same upside target
    assert c["instant"]["pnl_ask_pct"] < c["instant"]["pnl_mid_pct"]
    assert c["expiry"] == "2026-09-18" and c["entry_ask"] == 5.6

    slow = reprice_contract(110.0, cand, 45, travel_td=1000.0)  # travel exceeds dte → intrinsic
    assert slow["paced"]["t_rem_days"] == 0.0
    assert abs(slow["paced"]["value"] - 10.0) < 1e-9            # max(110-100, 0)

    down = reprice_contract(92.0, cand, 45, travel_td=3.0)
    assert down["instant"]["pnl_mid_pct"] < 0 and down["paced"]["pnl_mid_pct"] < 0

    assert reprice_contract(110.0, {"strike": 100.0, "mid": 5.0}, 45) is None   # no iv
    assert reprice_contract(110.0, cand, 45)["paced"] is None                   # no pace


# ─── Test 67 (S68): synthetic modeled call + IV-source fallback (offline, pure) ─
def test_levelproj_synthetic_call():
    """synthetic_call: premium is the exact BS ATM price; P&L is vs that premium; no ask
    legs (a model has no spread); invalid inputs → None."""
    from modules.bs_invert import black_scholes_call
    from modules.levelproj import synthetic_call, RISK_FREE

    s = synthetic_call(100.0, 106.0, 0.22, 30, travel_td=4.0)
    assert s["premium"] == black_scholes_call(100.0, 100.0, RISK_FREE, 30 / 365.0, 0.22)
    assert s["strike"] == 100.0 and s["iv_src"] == "ATM IV (30d)"
    assert s["instant"]["pnl_mid_pct"] > 0 and s["instant"]["pnl_ask_pct"] is None
    assert s["paced"]["value"] < s["instant"]["value"]
    assert synthetic_call(100.0, 106.0, None, 30) is None
    assert synthetic_call(None, 106.0, 0.22, 30) is None
    assert synthetic_call(100.0, 106.0, 0.22, 30, iv_src="HV-20 proxy")["iv_src"] == "HV-20 proxy"


# ─── Test 68 (S68): project_targets orchestration (offline, pure) ───────────────
def test_project_targets():
    """Target selection off a real build_ladder output (user level dedups with its S/R
    cluster and keeps kind 'your level'; zone cap 2), quoted path populates contracts +
    quote_meta (dte refreshed from expiry vs the injected today), synthetic fallback
    covers callq=None (30d + 180d tenors when iv180 given), downside targets go negative."""
    from datetime import date
    from modules.levels import build_ladder
    from modules.levelproj import project_targets, MAX_ZONE_TARGETS

    # 704.4 user level sits within 0.5% of two other tags → one cluster, user_level set
    levels = [(704.40, "YOUR LEVEL"), (704.20, "value-area high"), (705.10, "prior-day high"),
              (688.20, "POC"), (688.90, "MA50 1D"),          # below-spot confluence zone
              (660.00, "LVN"), (650.00, "MA200 1D"), (651.10, "HVN"),
              (735.00, "52w high")]
    ladder = build_ladder(692.0, levels)
    assert ladder["user_level"] is not None

    callq = {"as_of_str": "14:32", "age_str": "today", "stale": False,
             "quotes": [{"expiry": "2026-09-18", "dte": 999,   # bogus cached dte — must refresh
                         # mid ≈ fair BS value at spot 692 (a too-cheap fixture mid would make
                         # even the DOWNSIDE reprice profitable and invert the loss assertion)
                         "atm": {"strike": 690.0, "mid": 27.5, "iv": 0.24, "ask": 28.5},
                         "otm": {"strike": 715.0, "mid": 9.0, "iv": 0.23}}]}
    proj = project_targets(ladder, hv20=0.20, callq=callq, iv30=0.22, iv180=0.25,
                           today=date(2026, 7, 29))
    kinds = [t["kind"] for t in proj["targets"]]
    assert kinds[0] == "your level"
    assert "support" in kinds and "resistance" not in kinds   # user's cluster IS the nearest res
    assert kinds.count("confluence") <= MAX_ZONE_TARGETS
    prices = [round(t["price"], 2) for t in proj["targets"]]
    assert len(prices) == len(set(prices))                    # deduped

    yl = proj["targets"][0]
    assert yl["contracts"] and not yl["synthetic"]            # quoted path wins
    assert {c["kind"] for c in yl["contracts"]} == {"atm", "otm"}
    assert yl["contracts"][0]["dte"] == (date(2026, 9, 18) - date(2026, 7, 29)).days  # refreshed
    assert proj["quote_meta"]["as_of_str"] == "14:32"
    sup = next(t for t in proj["targets"] if t["kind"] == "support")
    atm_at_sup = next(c for c in sup["contracts"] if c["kind"] == "atm")
    assert atm_at_sup["instant"]["pnl_mid_pct"] < 0           # long call loses on the way down

    # STALE cache: mids were struck at another spot — entry is re-modeled at CURRENT spot
    # (same strike/IV, refreshed dte), the dead ask leg is dropped, and the row is flagged
    from modules.bs_invert import black_scholes_call
    from modules.levelproj import RISK_FREE
    stale_q = dict(callq, stale=True)
    sproj = project_targets(ladder, hv20=0.20, callq=stale_q, iv30=0.22,
                            today=date(2026, 7, 29))
    satm = next(c for c in sproj["targets"][0]["contracts"] if c["kind"] == "atm")
    dte_live = (date(2026, 9, 18) - date(2026, 7, 29)).days
    assert satm["entry_modeled"] is True
    assert satm["entry_mid"] == black_scholes_call(692.0, 690.0, RISK_FREE,
                                                   dte_live / 365.0, 0.24)
    assert satm["entry_ask"] is None and satm["instant"]["pnl_ask_pct"] is None
    fresh_atm = next(c for c in yl["contracts"] if c["kind"] == "atm")
    assert fresh_atm["entry_modeled"] is False and fresh_atm["entry_mid"] == 27.5

    # synthetic fallback: three tenors (S69 — 30/180/365, the last two being what this project
    # trades). Per tenor the IV preference is harvested gauge → --call curve → HV-20 proxy.
    synth = project_targets(ladder, hv20=0.20, callq=None, iv30=0.22, iv180=0.25)
    yl2 = synth["targets"][0]
    assert not yl2["contracts"] and [s["dte"] for s in yl2["synthetic"]] == [30, 180, 365]
    assert [s["iv_src"] for s in yl2["synthetic"]] == [
        "ATM IV (30d)", "ATM IV (180d)", "HV-20 proxy"]   # no 365d gauge exists → proxy
    assert synth["quote_meta"] is None
    # iv180 absent → the 180d leg falls to the HV-20 proxy rather than vanishing (pre-S69 it
    # was dropped entirely, which is why the long row never rendered: atm_iv_180d is empty in
    # every indicators CSV on disk)
    only30 = project_targets(ladder, hv20=0.20, callq=None, iv30=0.22)
    assert [s["dte"] for s in only30["targets"][0]["synthetic"]] == [30, 180, 365]
    assert only30["targets"][0]["synthetic"][1]["iv_src"] == "HV-20 proxy"
    proxy = project_targets(ladder, hv20=0.20, callq=None)    # no IV at all → HV proxy
    assert proxy["targets"][0]["synthetic"][0]["iv_src"] == "HV-20 proxy"
    assert project_targets(None) is None


# ─── Test 69 (S68): cached_call_quote zero-network read (offline, tmp dir) ──────
def test_cached_call_quote(tmp_path):
    """The level-projection sibling of cached_liquidity: reads the call2 session cache with
    zero network — wrapped quote (+ as_of_str/stale/cached) when usable, None when the file
    is absent or holds no quote blocks."""
    import json
    import os
    import time
    from modules.callquote import cached_call_quote, SCOPEKEY
    from modules.pc_oi import _cache_path

    assert cached_call_quote("QQQ", data_dir=str(tmp_path)) is None      # no file

    path = _cache_path("QQQ", SCOPEKEY, str(tmp_path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    quote = {"spot": 692.0, "quotes": [{"expiry": "2026-09-18", "dte": 51,
                                        "atm": {"strike": 690.0, "mid": 20.0, "iv": 0.24}}]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"as_of": time.time(), "quote": quote}, f)
    got = cached_call_quote("QQQ", data_dir=str(tmp_path))
    assert got and got["quotes"][0]["atm"]["iv"] == 0.24
    assert got["cached"] is True and "as_of_str" in got and "stale" in got

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"as_of": time.time(), "quote": {"spot": 1.0, "quotes": []}}, f)
    assert cached_call_quote("QQQ", data_dir=str(tmp_path)) is None      # empty quotes


# ─── Test 70 (S68): projections render regression (offline) ─────────────────────
def test_projections_render():
    """print_report with a ladder carrying projections prints the block + the unconditional
    caveat (paced=None → '—'); the SAME payload with projections stripped renders the ladder
    byte-identically to the pre-S68 path (the block only adds output, never changes it)."""
    import contextlib
    import copy
    import io
    from lens import print_report

    last_bar = {"open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0, "prev_close": 100.5}
    ladder = {"spot": 102.0,
              "levels": [{"price": 106.0, "dist_pct": 0.0392, "tags": ["HVN"], "side": "above",
                          "zone": None},
                         {"price": 98.0, "dist_pct": -0.0392, "tags": ["POC"], "side": "below",
                          "zone": None}],
              "zones": [], "nearest_support": None, "nearest_resistance": None,
              "user_level": None,
              "projections": {
                  "targets": [
                      {"price": 106.0, "dist_pct": 0.0392, "kind": "resistance", "label": "HVN",
                       "travel_sessions": 3.2,
                       "contracts": [{"strike": 100.0, "dte": 45.0, "expiry": "2026-09-18",
                                      "iv": 0.25, "entry_mid": 5.0, "entry_ask": 5.6,
                                      "kind": "atm", "src": "quoted",
                                      "instant": {"value": 7.5, "pnl_mid_pct": 0.5,
                                                  "pnl_ask_pct": 0.339},
                                      "paced": {"value": 6.9, "pnl_mid_pct": 0.38,
                                                "pnl_ask_pct": 0.232, "t_rem_days": 40.6}}],
                       "synthetic": []},
                      {"price": 98.0, "dist_pct": -0.0392, "kind": "support", "label": "POC",
                       "travel_sessions": None,                       # no hv20 → paced '—'
                       "contracts": [],
                       "synthetic": [{"strike": 102.0, "dte": 30, "iv": 0.22,
                                      "iv_src": "ATM IV (30d)", "premium": 2.6, "src": "modeled",
                                      "instant": {"value": 0.9, "pnl_mid_pct": -0.654,
                                                  "pnl_ask_pct": None},
                                      "paced": None}]}],
                  "quote_meta": {"as_of_str": "14:32", "age_str": "today", "stale": True},
                  "params": {"hv20": None, "r": 0.04},
                  "pace_note": "…"}}
    kw = dict(reads={}, divs={}, summary={"synthesis": "fixture"}, profile=None, notes=[],
              last_bar=last_bar, as_of="2026-07-29", color=False, candle_style="none")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_report("TEST", **kw, ladder=ladder)
    out = buf.getvalue()
    assert "level projections (quoted contracts as of 14:32 — STALE" in out
    assert "→ resistance 106.00 (+3.9% · HVN) · ~3 sessions at recent pace" in out
    assert "mid 5.00 → 7.50 instant / 6.90 paced   +50% / +38%  (at ask +34%/+23%)" in out
    assert "~30d ATM call (modeled, IV 22.0% ATM IV (30d), prem ≈ 2.60 — not a quote)" in out
    assert "→ 0.90 / —   -65% / —" in out                       # paced None prints —
    assert "straight-line heuristic, not advice" in out          # unconditional caveat

    bare = copy.deepcopy(ladder)
    del bare["projections"]
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        print_report("TEST", **kw, ladder=bare)
    out2 = buf2.getvalue()
    assert "level projections" not in out2
    # the block is purely additive — stripping it reproduces the pre-S68 ladder byte-for-byte
    assert out2 == out.replace(out[out.index("\n    ── level projections"):
                                   out.index("not advice") + len("not advice\n")], "")


# ─── S72: monthly-window expiry selection, holiday-aware (offline) ──────────────
def test_s72_monthly_window_selection():
    """S72 replaced "nearest expiry to each of 4 target DTEs" with "every MONTHLY in a DTE
    window". The S69 rule quoted 4 expiries and silently hid the rest — SOFI lists monthlies at
    113/141/232 DTE that never appeared as pills.

    The load-bearing subtlety is HOLIDAY SHIFT: when a third Friday is a market holiday the
    monthly moves to the Thursday before, and pc_oi.is_monthly_expiry (Friday, day 15-21) then
    calls it non-monthly. Probed live 2026-07-30 — SOFI/QQQ/AMD all list 2027-06-17 (Thu) and
    NOT 2027-06-18, because Juneteenth 2027 is a Saturday, observed that Friday. A naive
    monthlies-only filter would DROP that LEAP."""
    from modules.callquote import monthly_expiries, nearest_to_targets, select_expiries

    # SOFI's real grid (probed 2026-07-30), weeklies included
    sofi = [("2026-07-31", 1), ("2026-08-07", 8), ("2026-08-14", 15), ("2026-08-21", 22),
            ("2026-08-28", 29), ("2026-09-04", 36), ("2026-09-11", 43), ("2026-09-18", 50),
            ("2026-10-16", 78), ("2026-11-20", 113), ("2026-12-18", 141), ("2027-01-15", 169),
            ("2027-03-19", 232), ("2027-06-17", 322), ("2027-12-17", 505), ("2028-01-21", 540),
            ("2028-06-16", 687), ("2028-12-15", 869)]
    mon = [d for _, d in monthly_expiries(sofi)]
    assert 322 in mon                                  # the holiday-shifted June-2027 monthly
    assert mon == [22, 50, 78, 113, 141, 169, 232, 322, 505, 540, 687, 869]
    assert all(w not in mon for w in (1, 8, 15, 29, 36, 43))     # weeklies excluded

    # the window keeps everything tradeable and drops only the 687/869 tail (EXPIRY_MAX_DTE)
    sel = [d for _, d in select_expiries(sofi)]
    assert sel == [22, 50, 78, 113, 141, 169, 232, 322, 505, 540]
    assert all(20 <= d <= 550 for d in sel)
    # …and the previously-hidden monthlies are now present
    assert {113, 141, 232} <= set(sel)

    # month-end quarterlies are NOT monthlies (QQQ lists 26-12-31 Thu and 27-03-31 Wed), and
    # a Thursday weekly in the 15-21 window must not be mistaken for a holiday shift
    qqq = [("2026-08-13", 14), ("2026-08-20", 21), ("2026-08-21", 22), ("2026-12-31", 154),
           ("2027-03-31", 244), ("2027-09-17", 414)]
    qmon = [e for e, _ in monthly_expiries(qqq)]
    assert qmon == ["2026-08-21", "2027-09-17"]        # 08-20 Thu ignored: 08-21 Fri is listed

    # cap is nearest-first
    assert [d for _, d in select_expiries(sofi, max_n=3)] == [22, 50, 78]

    # CLI curation picks one per canonical tenor out of the full set
    assert [d for _, d in nearest_to_targets([(e, d) for e, d in select_expiries(sofi)])] == [
        50, 78, 169, 322]
    assert nearest_to_targets([]) == []


def test_s69_strike_ladder():
    """The per-expiry ladder rides the SAME parsed chain rows as the ATM pick (zero extra
    network) and is what the web strike selector offers: tradeable only, bounded by ±pct of
    spot, capped, tagged atm/otm/other with moneyness."""
    from modules.callquote import strike_ladder

    def row(strike, bid=1.0, delta=0.5, typ="call"):
        return {"type": typ, "strike": strike, "bid": bid, "ask": bid * 1.05,
                "oi": 100, "volume": 10, "delta": delta, "theta": -0.01, "iv": 0.5}

    rows = [row(s, delta=max(0.05, 1.0 - (s - 80) / 50)) for s in range(80, 126, 5)]
    rows.append(row(100.0, bid=0.0))            # no-bid duplicate must be ignored
    rows.append(row(100.0, typ="put"))          # puts are not call candidates
    lad = strike_ladder(rows, spot=100.0, max_n=5, pct=0.25)

    assert [c["strike"] for c in lad] == sorted(c["strike"] for c in lad)   # sorted by strike
    assert len(lad) <= 6                        # max_n, +1 only if the OTM pick sits outside
    assert all(abs(c["moneyness"] - (c["strike"] / 100.0 - 1)) < 1e-12 for c in lad)
    kinds = [c["kind"] for c in lad]
    assert kinds.count("atm") == 1 and lad[[c["kind"] for c in lad].index("atm")]["strike"] == 100.0
    assert all(k in ("atm", "otm", "other") for k in kinds)
    # ±pct bound: a far strike is excluded
    assert all(abs(c["strike"] - 100.0) / 100.0 <= 0.25 for c in lad if c["kind"] != "otm")
    assert strike_ladder([], 100.0) == [] and strike_ladder(rows, 0) == []


def test_s69_ladder_repricing():
    """project_targets reprices the WHOLE ladder (the web selectors filter rows that already
    exist — no BS in TypeScript), carrying kind/moneyness/delta for the selector labels, and
    still handles a pre-S69 cache that only has atm/otm."""
    from modules.levelproj import project_targets, curve_iv

    ladder = {"spot": 100.0, "levels": [], "nearest_support": None, "nearest_resistance": None,
              "user_level": {"price": 110.0, "dist_pct": 0.10, "confluence": []}}
    blk = {"expiry": "2027-06-17", "dte": 322, "ladder": [
        {"strike": 95.0, "mid": 12.0, "iv": 0.5, "delta": 0.62, "kind": "other", "moneyness": -0.05},
        {"strike": 100.0, "mid": 9.5, "iv": 0.5, "delta": 0.55, "kind": "atm", "moneyness": 0.0},
        {"strike": 115.0, "mid": 4.5, "iv": 0.52, "delta": 0.375, "kind": "otm", "moneyness": 0.15}]}
    curve = {"points": [{"label": "27-01-15", "dte": 169, "iv": 0.6}]}
    p = project_targets(ladder, hv20=0.45, callq={"quotes": [blk], "curve": curve})
    rows = p["targets"][0]["contracts"]
    assert len(rows) == 3                                    # every ladder strike repriced
    assert {c["kind"] for c in rows} == {"atm", "otm", "other"}
    assert all(c["moneyness"] is not None and c["delta"] is not None for c in rows)
    assert all(c["dte"] == 322 and c["expiry"] == "2027-06-17" for c in rows)
    # further OTM = more leverage into an up-move
    by_k = {c["strike"]: c["instant"]["pnl_mid_pct"] for c in rows}
    assert by_k[115.0] > by_k[100.0] > by_k[95.0]

    # curve IV is the working long-tenor source; a 22d front point may not stand in for 365d
    assert curve_iv({"curve": curve}, 180) == (0.6, 169)
    assert curve_iv({"curve": curve}, 365) is None
    assert curve_iv({"curve": {"points": []}}, 180) is None

    # pre-S69 cached block (atm/otm, no ladder) still reprices — old caches must not break
    old = {"expiry": "2026-09-18", "dte": 50,
           "atm": {"strike": 100.0, "mid": 4.0, "iv": 0.5},
           "otm": {"strike": 110.0, "mid": 1.2, "iv": 0.52}}
    p2 = project_targets(ladder, hv20=0.45, callq={"quotes": [old]})
    assert [(c["strike"], c["kind"]) for c in p2["targets"][0]["contracts"]] == [
        (100.0, "atm"), (110.0, "otm")]


def test_s70_project_price():
    """The custom-price stepper (S70) must go through the SAME pricing path as the fixed
    targets — one Black-Scholes implementation, server-side — so the two can never disagree."""
    from modules.levelproj import project_price, project_targets

    blk = {"expiry": "2027-06-17", "dte": 322, "ladder": [
        {"strike": 100.0, "mid": 9.5, "iv": 0.5, "delta": 0.55, "kind": "atm", "moneyness": 0.0},
        {"strike": 115.0, "mid": 4.5, "iv": 0.52, "delta": 0.375, "kind": "otm", "moneyness": 0.15}]}
    callq = {"quotes": [blk]}

    out = project_price(110.0, 100.0, hv20=0.45, callq=callq)
    t = out["target"]
    assert t["kind"] == "custom price"
    assert abs(t["dist_pct"] - 0.10) < 1e-12 and t["price"] == 110.0
    assert len(t["contracts"]) == 2 and {c["kind"] for c in t["contracts"]} == {"atm", "otm"}

    # identical to the ladder path at the same price — the anti-drift guarantee. dist_pct uses
    # the SAME expression project_price does: 110/100 - 1 is 0.10000000000000009, not 0.10, and
    # that 1e-17 feeds travel_sessions, so a hardcoded 0.10 makes this a near-miss not a match.
    lad = {"spot": 100.0, "levels": [], "nearest_support": None, "nearest_resistance": None,
           "user_level": {"price": 110.0, "dist_pct": 110.0 / 100.0 - 1.0, "confluence": []}}
    ref = project_targets(lad, hv20=0.45, callq=callq)["targets"][0]
    assert ([c["instant"]["value"] for c in t["contracts"]]
            == [c["instant"]["value"] for c in ref["contracts"]])
    assert t["travel_sessions"] == ref["travel_sessions"]

    # stepping the price down is monotonically worth less (a call is increasing in spot) — the
    # invariant that matters for a stepper, and independent of the fixture's entry mids
    down = project_price(90.0, 100.0, hv20=0.45, callq=callq)["target"]
    flat = project_price(100.0, 100.0, hv20=0.45, callq=callq)["target"]
    assert down["dist_pct"] < 0 and flat["dist_pct"] == 0
    for i in range(len(t["contracts"])):
        assert (down["contracts"][i]["instant"]["value"]
                < flat["contracts"][i]["instant"]["value"]
                < t["contracts"][i]["instant"]["value"])
    # travel is distance-symmetric, and zero distance costs zero sessions
    assert abs(down["travel_sessions"] - t["travel_sessions"]) < 1e-9
    assert flat["travel_sessions"] == 0

    # S70 SPOT-DRIFT re-model. The S68 fix only re-modeled a session-STALE cache, but a cache
    # taken earlier the SAME session is "fresh" and can still be struck at a far-away spot —
    # probed live: SOFI's call3 cache held spot 16.13 against a 15.25 report spot, so EVERY
    # contract read ≈ −19% at a zero-percent move. Projecting at spot must be ≈ break-even.
    drifted = {"quotes": [blk], "spot": 110.0, "stale": False}      # quoted 10% above spot
    at_spot = project_price(100.0, 100.0, hv20=0.45, callq=drifted)
    assert at_spot["quote_meta"]["remodeled"] is True
    assert abs(at_spot["quote_meta"]["spot_drift"] - 0.10) < 1e-9
    for c in at_spot["target"]["contracts"]:
        assert c["entry_modeled"] is True
        assert abs(c["instant"]["pnl_mid_pct"]) < 1e-9      # no move → no P&L
        assert c["entry_ask"] is None                       # the stale spread is dead too

    # inside the tolerance nothing is re-modeled (a 0.5% drift is just noise)
    near = project_price(100.0, 100.0, hv20=0.45,
                         callq={"quotes": [blk], "spot": 100.5, "stale": False})
    assert near["quote_meta"]["remodeled"] is False
    assert all(c["entry_modeled"] is False for c in near["target"]["contracts"])
    # a cache with no spot at all can't drift-check — unchanged pre-S70 behaviour
    assert project_price(100.0, 100.0, hv20=0.45,
                         callq={"quotes": [blk]})["quote_meta"]["remodeled"] is False

    # guards — never raises, never invents a projection
    assert project_price(None, 100.0) is None
    assert project_price(110.0, 100.0, callq=callq, on_date="not-a-date") is None
    assert project_price(110.0, None) is None
    assert project_price(0, 100.0) is None and project_price(-5, 100.0) is None
    assert project_price("abc", 100.0) is None


def test_s71_dated_leg():
    """The date picker (S71): a third leg holding until a chosen DATE. Same repricing as
    instant/paced, just an explicit hold instead of the HV-20 travel estimate — so it must
    decay monotonically with time and collapse to intrinsic past the contract's expiry."""
    from datetime import date, timedelta

    from modules.levelproj import project_price

    today = date(2026, 7, 30)
    blk = {"expiry": "2027-06-17", "dte": 322, "ladder": [
        {"strike": 100.0, "mid": 9.5, "iv": 0.5, "delta": 0.55, "kind": "atm", "moneyness": 0.0}]}
    callq = {"quotes": [blk]}

    def leg(days, price=110.0):
        out = project_price(price, 100.0, hv20=0.45, callq=callq, today=today,
                            on_date=(today + timedelta(days=days)).isoformat())
        return out["target"]["contracts"][0]

    # no date → no dated leg at all (the column must not appear on the fixed targets)
    plain = project_price(110.0, 100.0, hv20=0.45, callq=callq, today=today)
    assert plain["target"]["contracts"][0]["dated"] is None
    assert plain["on_date"] is None and plain["hold_days"] is None

    # date == today → zero hold → identical to the instant leg
    d0 = leg(0)
    assert d0["dated"]["value"] == d0["instant"]["value"]
    assert d0["dated"]["t_rem_days"] == d0["dte"] and d0["dated"]["expired"] is False

    # holding longer is worth strictly less (theta), and time left shrinks day for day
    vals = [leg(d)["dated"] for d in (0, 30, 120, 300)]
    assert all(a["value"] > b["value"] for a, b in zip(vals, vals[1:]))
    assert [v["t_rem_days"] for v in vals] == [322, 292, 202, 22]

    # past the contract's own expiry: dead, floored to intrinsic, and flagged
    gone = leg(400)["dated"]
    assert gone["expired"] is True and gone["t_rem_days"] == 0
    assert abs(gone["value"] - 10.0) < 1e-9          # max(110 − 100, 0)
    # …and below the strike it expires worthless, not at a negative value
    worthless = leg(400, price=90.0)["dated"]
    assert worthless["value"] == 0.0 and worthless["pnl_mid_pct"] == -1.0

    # echoed metadata drives the column header + "N days out" caption
    out = project_price(110.0, 100.0, hv20=0.45, callq=callq, today=today,
                        on_date=(today + timedelta(days=45)).isoformat())
    assert out["on_date"] == "2026-09-13" and out["hold_days"] == 45
    # the past is not a projection
    assert project_price(110.0, 100.0, callq=callq, today=today,
                         on_date=(today - timedelta(days=1)).isoformat()) is None


def test_s63_tf_order_and_ltf_gate(monkeypatch):
    """TF_ORDER is the single source of row order for the whole stack (CLI + React iterate
    insertion order), and build_timeframes drops any key absent from it. The sub-hourly
    frames are gated on the session, not just the flag."""
    import modules.timeframes as tfm

    assert tfm.TF_ORDER == ["1M", "1W", "1D", "4h", "2h", "1h", "30m", "15m", "5m"]
    assert list(tfm.INTRADAY_TFS) == ["30m", "15m", "5m"]
    assert all(tf in tfm.TF_ORDER for tf in tfm.INTRADAY_TFS)
    # every intraday key that can be marked partial has a bar length
    assert set(tfm.TF_MINUTES) >= set(tfm.INTRADAY_TFS) | {"1h", "2h", "4h"}

    frames, notes = tfm.build_timeframes("QQQ", data_dir="data", include_intraday=False, ltf=False)
    assert list(frames) == [tf for tf in tfm.TF_ORDER if tf in frames]     # ordered by TF_ORDER
    assert not any(tf in frames for tf in tfm.INTRADAY_TFS)

    # --ltf outside RTH: skipped with a note, and NOTHING is fetched
    def boom(*a, **k):
        raise AssertionError("_load_ltf must not run while the market is closed")
    monkeypatch.setattr(tfm, "_load_ltf", boom)
    monkeypatch.setattr(tfm, "session_open", lambda *a, **k: False)
    _, notes = tfm.build_timeframes("QQQ", data_dir="data", include_intraday=False, ltf=True)
    assert any("market closed" in n for n in notes)

    # as-of mode never loads them either (no historical sub-hourly source)
    monkeypatch.setattr(tfm, "session_open", lambda *a, **k: True)
    f3, n3 = tfm.build_timeframes("QQQ", data_dir="data", include_intraday=False,
                                  ltf=True, as_of="2026-06-10")
    assert not any(tf in f3 for tf in tfm.INTRADAY_TFS)
    assert not any("market closed" in n for n in n3)      # the as-of note covers it instead


# ─── Test 55 (S64): overnight futures + after-hours reads (offline) ────────────
def test_s64_overnight_reads():
    """modules/overnight (S64): read_futures on synthetic settle series ("vs prior settle" =
    last daily row vs the one before it); afterhours_read on REAL-SHAPED Tradier quotes (`last`
    == `close` post-bell) with an injectable clock — no extended-hours print → None, a tape
    print → tape price/pct + print-time stamp, pre-open pre-mkt via prevclose, out-of-window
    drop, malformed never raises; and the print_report AH line renders. All offline."""
    import contextlib
    import io

    import pandas as pd
    from lens import print_report
    from modules.overnight import afterhours_read, read_futures

    idx = pd.date_range("2026-07-20", periods=5, freq="D")
    es = pd.Series([100.0, 101.0, 102.0, 103.0, 104.06], index=idx)
    out = read_futures({"ES": es, "NQ": pd.Series([50.0], index=idx[:1])})
    assert set(out) == {"ES"}                                  # 1-row NQ omitted
    assert abs(out["ES"]["chg"] - (104.06 / 103.0 - 1.0)) < 1e-12
    assert out["ES"]["settle"] == 103.0 and out["ES"]["bar_date"] == "2026-07-24"
    assert read_futures({}) is None and read_futures(None) is None

    from modules.overnight import _ext_window_start

    def ts(s):                                                 # ET wall time → ms epoch
        return int(pd.Timestamp(s, tz="America/New_York").tz_convert("UTC").value // 10**6)

    def et(s):
        return pd.Timestamp(s, tz="America/New_York")

    # THE REGRESSION GUARD. A REAL post-bell Tradier quote: `last` latches to the official close
    # at the bell and trade_date freezes at 16:00 (probed live 2026-07-27 on SOFI — last 16.88 ==
    # close 16.88, trade_date 16:00:00.153, 34 minutes after the close with AH volume trading).
    # The original S64 read derived the AH price from `last`, so it could only ever say +0.00%;
    # its test passed only because the fixture invented a quote with last != close. With no
    # extended-hours print the read MUST be None so nothing renders.
    now_ah = et("2026-07-24 18:00")
    q = {"last": 512.53, "close": 512.53, "prevclose": 510.0,
         "trade_date": ts("2026-07-24 16:00")}
    assert afterhours_read(q, ext=None, now=now_ah) is None
    assert afterhours_read(q, now=now_ah) is None                 # ext omitted entirely

    # with a real print off the timesales tape: price + % come from the TAPE, ref from the quote,
    # and hhmm is the PRINT's time (17:59), never the wall clock (18:00)
    r = afterhours_read(q, ext={"price": 514.32, "ts": et("2026-07-24 17:59")}, now=now_ah)
    assert r["label"] == "AH" and r["ref"] == 512.53 and r["last"] == 514.32
    assert abs(r["chg_pct"] - (514.32 / 512.53 - 1.0) * 100.0) < 1e-9
    assert r["hhmm"] == "17:59"

    # pre-open Friday: close null → prevclose reference, pre-mkt label. The window opened at
    # THURSDAY's close, so Friday 07:55 is inside it.
    now_pm = et("2026-07-24 08:00")
    q2 = {"last": 510.0, "close": None, "prevclose": 510.0}
    r2 = afterhours_read(q2, ext={"price": 511.0, "ts": et("2026-07-24 07:55")}, now=now_pm)
    assert r2["label"] == "pre-mkt" and r2["ref"] == 510.0 and r2["hhmm"] == "07:55"

    # window guard: one rule spans the evening AND the next pre-market
    assert _ext_window_start(et("2026-07-24 18:00")) == et("2026-07-24 16:00")   # Fri evening
    assert _ext_window_start(et("2026-07-24 08:00")) == et("2026-07-23 16:00")   # Fri pre-mkt
    assert _ext_window_start(et("2026-07-27 06:00")) == et("2026-07-24 16:00")   # Mon pre-mkt

    # a print from BEFORE the window (prior session's AH, read the next evening) → dropped
    assert afterhours_read(q, ext={"price": 514.32, "ts": et("2026-07-23 17:00")},
                           now=now_ah) is None
    # malformed → None, never raises
    good_ext = {"price": 514.32, "ts": et("2026-07-24 17:59")}
    assert afterhours_read({"close": 1.0}, ext={"price": None, "ts": et("2026-07-24 17:59")},
                           now=now_ah) is None
    assert afterhours_read({"close": 0.0}, ext=good_ext, now=now_ah) is None
    assert afterhours_read(None, ext=good_ext, now=now_ah) is None
    assert afterhours_read({"close": "y"}, ext={"price": "x", "ts": "nope"}, now=now_ah) is None

    # fetch_live_bar accepts a pre-fetched quote (S64); fully offline with the quote injected
    from modules.timeframes import fetch_live_bar
    now_ms = int(pd.Timestamp.now(tz="UTC").value // 10**6)
    bar = fetch_live_bar("QQQ", quote={"open": 100.0, "high": 103.0, "low": 99.0,
                                       "last": 102.0, "close": 101.5, "volume": 1000,
                                       "trade_date": now_ms})
    assert bar and bar["Close"] == 101.5 and bar["in_progress"] is False
    assert fetch_live_bar("QQQ", quote={"trade_date": None}) is None

    # render path: the AH line prints under the OHLC line
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_report("TEST", reads={}, divs={}, summary={"synthesis": "mixed — fixture"},
                     profile=None, notes=[],
                     last_bar={"open": 100.0, "high": 103.0, "low": 99.0,
                               "close": 102.0, "prev_close": 100.5},
                     as_of="2026-07-24", color=False, candle_style="none",
                     ah={"last": 514.32, "ref": 512.53, "chg_pct": 0.35,
                         "label": "AH", "hhmm": "18:00"})
    out_txt = buf.getvalue()
    assert "AH: $514.32" in out_txt and "+0.35% vs close" in out_txt


# ─── Test 56 (S64): overnight-gap gauges (offline) ─────────────────────────────
def test_s64_gap_gauges():
    """sentiment.gap_gauges (S64): two VOL gauges off the previously-orphaned gap columns.
    The displayed value is SIGNED but the percentile is of |gap| — a large negative gap must
    read high-percentile (unusual magnitude), which the signed series would call ~0th.
    Missing columns → []."""
    import numpy as np
    import pandas as pd
    from modules.sentiment import gap_gauges

    n = 120
    idx = pd.date_range("2026-01-02", periods=n, freq="B")
    gp = np.full(n, -0.002)
    gp[-1] = -0.004                       # large NEGATIVE gap: signed pct ~0, |gap| pct ~1
    df = pd.DataFrame({"gap_pct": gp,
                       "gap_ma_5d": np.full(n, -0.001),
                       "gap_vol_5d": np.full(n, 0.002)}, index=idx)
    g = gap_gauges(df)
    assert [x["name"] for x in g] == ["Gap at open", "Gap vol (5d)"]
    assert all(x["group"] == "VOL" for x in g)
    gap = g[0]
    assert abs(gap["value"] - (-0.004)) < 1e-12               # signed value displayed
    assert gap["pct"] is not None and gap["pct"] > 0.9        # |gap| percentile, not signed
    assert "open" in gap["label"] and "5d avg" in gap["label"]
    assert g[1]["value"] == 0.002 and g[1]["spark"]

    # NaN tail (the indicators today-row) lands on the last REAL session
    df2 = df.copy()
    df2.loc[df2.index[-1], ["gap_pct", "gap_ma_5d", "gap_vol_5d"]] = np.nan
    g2 = gap_gauges(df2)
    assert abs(g2[0]["value"] - (-0.002)) < 1e-12

    assert gap_gauges(pd.DataFrame({"Close": [1.0]})) == []


# ─── Test 57 (S65): price ladder (offline) ─────────────────────────────────────
def test_build_ladder():
    """modules/levels (S65): collect_levels merges every optional source; build_ladder sorts by
    |distance|, clusters confluence (≥2 distinct tags within ±0.5%), picks nearest S/R, and
    annotates the user level. All-None inputs degrade to None, never raise."""
    from modules.levels import build_ladder, collect_levels

    spot = 100.0
    profile = {"poc": 98.0, "va_low": 95.0, "va_high": 102.0,
               "hvns": [90.0, 98.0], "lvns": [93.0]}
    gex = {"call_wall": 105.0, "put_wall": 95.02, "zero_gamma": 99.0,
           "max_pain": {"strike": 100.0}}
    reads = {"1D": {"ok": True, "ma20": 97.9, "ma50": 96.0, "ma200": None},
             "1W": {"ok": False, "ma20": 50.0}}                 # not-ok frame skipped
    levels = collect_levels(spot, profile=profile, gex=gex, reads=reads,
                            range52={"hi": 110.0, "lo": 80.0},
                            prior_day={"high": 101.0, "low": 99.5, "close": 100.4},
                            user_level=95.1)
    tags = {t for _, t in levels}
    assert "MA20 1D" in tags and "MA20 1W" not in tags          # ok-gate on reads
    assert "YOUR LEVEL" in tags and "52w high" in tags

    lad = build_ladder(spot, levels)
    assert lad["levels"] == sorted(lad["levels"], key=lambda r: abs(r["dist_pct"]))
    # confluence: POC 98.0 + MA20 97.9 within 0.5% → one row, both tags, zone set
    poc_row = next(r for r in lad["levels"] if "POC" in r["tags"])
    assert "MA20 1D" in poc_row["tags"] and poc_row["zone"] is not None
    # nearest S/R are strictly below/above spot
    assert lad["nearest_support"]["price"] < spot < lad["nearest_resistance"]["price"]
    # user level 95.1 clusters with va_low 95.0 + put wall 95.02 → confluence reported
    ul = lad["user_level"]
    assert ul and ul["side"] == "below" and "value-area low" in ul["confluence"]
    assert "GEX put wall" in ul["confluence"]

    # degradation: no inputs → no ladder; junk spot → None; never raises
    assert build_ladder(spot, []) is None
    assert build_ladder(None, levels) is None
    assert build_ladder("x", levels) is None
    assert collect_levels(spot) == []
    assert collect_levels(spot, gex={"call_wall": "bad"}) == []


def test_nearest_lvn_below():
    """levels.nearest_lvn_below (S65): the below-spot mirror of shortint's LVN-air factor —
    nearest LVN strictly below spot within −8%, as a signed pct."""
    from modules.levels import nearest_lvn_below

    prof = {"lvns": [80.0, 95.0, 97.0, 103.0]}
    r = nearest_lvn_below(prof, 100.0)
    assert abs(r - (97.0 / 100.0 - 1.0)) < 1e-12               # nearest below, signed negative
    assert nearest_lvn_below({"lvns": [80.0]}, 100.0) is None  # outside −8%
    assert nearest_lvn_below({"lvns": [103.0]}, 100.0) is None # above spot doesn't count
    assert nearest_lvn_below(None, 100.0) is None
    assert nearest_lvn_below(prof, None) is None
    assert nearest_lvn_below(prof, "x") is None


# ─── Test 58 (S65): short-opportunity lens (offline) ───────────────────────────
def test_is_s21_contrarian():
    """The S21 prefix matcher must track the EXACT factor strings rally_drawdown_risk builds
    (structure.py) — if those strings drift, this test must fail so the thesis-bearish
    annotation doesn't silently stop matching."""
    from modules.shortside import is_s21_contrarian

    # the two live factor formats from structure.rally_drawdown_risk
    assert is_s21_contrarian("VIX stress regime (elevated market risk)")
    assert is_s21_contrarian("term backwardation — near-term stress priced")
    assert not is_s21_contrarian("daily near top of 1y range")
    assert not is_s21_contrarian(None)

    # drift guard: build the real factors from a synthetic ctx and assert they match
    from modules.structure import rally_drawdown_risk
    ctx = {"regime": "stress",
           "gauges": [{"name": "Term structure", "value": 1.10}]}
    risk = rally_drawdown_risk({}, ctx=ctx)
    s21 = [f for f in risk["drawdown"] if is_s21_contrarian(f)]
    assert len(s21) == 2, f"expected both S21 factors matched, got {s21}"


def test_short_setup_factors():
    """shortside.short_setup (S65): downtrend evidence lands on 'for', bounce/S21 evidence on
    'against', the checklist inverts the long setup rows, and the S28 caveats always print."""
    from modules.shortside import short_setup

    dn = {"ok": True, "trend": "down", "rsi": 45.0, "rsi_state": "neutral",
          "dist_ma20_pct": -0.02, "range_pos": 0.4,
          "_vol": {"ok": True, "tag": "dn-distrib", "distribution": True, "unconfirmed": False}}
    reads = {"1D": dn, "1W": {**dn, "_vol": None}, "1M": {**dn, "_vol": None}}
    s = short_setup(
        reads, profile={"price_location": "below_value"},
        divergences={"1D": ("bearish", "price HH, RSI LH")},
        rs={"bench": "SOX", "rs": {20: -0.03, 63: -0.08}},
        sectors={"own": "XLK", "rows": [{"sym": "XLK", "tag": "lagging", "rank": 11}]},
        gex={"net_gex": -1e9, "zero_gamma": 105.0, "spot": 100.0},
        street={"ud": {"n_up": 1, "n_down": 4, "window_days": 90},
                "rev_net": "estimates drifting DOWN"},
        lvn_below_pct=-0.05,
        regime={"state": "down", "label": "ESTABLISHED DOWNTREND", "why": ["1D+1W aligned"]})
    joined = " | ".join(s["for"])
    for token in ("ESTABLISHED DOWNTREND", "distribution", "bearish divergence",
                  "BELOW value", "thin-volume air", "lagging SOX", "XLK lagging",
                  "short gamma", "zero-gamma", "downgrades", "drifting DOWN"):
        assert token in joined, f"missing '{token}' in for-factors: {joined}"
    marks = {label: mark for label, mark, _ in s["checklist"]}
    assert marks["HTF alignment"] == "✓" and marks["Volume confirms"] == "✓"
    assert marks["Relative strength"] == "✓"
    assert len(s["caveats"]) == 3 and "S28" in s["caveats"][0]

    # uptrend + oversold + S21 conditions → against side; checklist flips
    up = {"ok": True, "trend": "up", "rsi": 25.0, "rsi_state": "oversold",
          "dist_ma20_pct": -0.10, "range_pos": 0.05,
          "_vol": {"ok": True, "tag": "up-confirmed", "distribution": False}}
    reads2 = {"1D": up, "1W": {**up, "_vol": None}, "1M": {**up, "_vol": None}}
    s2 = short_setup(reads2, ctx={"regime": "stress",
                                  "gauges": [{"name": "Term structure", "value": 1.10}]},
                     rs={"bench": "SOX", "rs": {20: 0.02, 63: 0.05}},
                     regime={"state": "up", "label": "ESTABLISHED UPTREND", "why": []})
    j2 = " | ".join(s2["against"])
    for token in ("ESTABLISHED UPTREND", "S28", "oversold", "snap-back", "bottom of 1y range",
                  "VIX stress", "contrarian-BUY", "backwardation"):
        assert token in j2, f"missing '{token}' in against: {j2}"
    m2 = {label: mark for label, mark, _ in s2["checklist"]}
    assert m2["Momentum room"] == "✗" and m2["Volume confirms"] == "✗"
    assert m2["Relative strength"] == "✗"
    assert short_setup({})["net"]                        # empty inputs never raise


def test_short_setup_crowding():
    """Crowding verdict off the squeeze read: ≥2 fuel → crowded (+ an against factor),
    counters → uncrowded, None → unknown with the --squeeze hint."""
    from modules.shortside import short_setup

    crowded = short_setup({}, sqz_read={"fuel": ["DTC 16 — extreme", "shorts underwater"],
                                        "counter": []})
    assert crowded["crowding"]["state"] == "crowded"
    assert any("CROWDED" in f for f in crowded["against"])
    uncrowded = short_setup({}, sqz_read={"fuel": [], "counter": ["DTC 1.2 — low"]})
    assert uncrowded["crowding"]["state"] == "uncrowded"
    unknown = short_setup({})
    assert unknown["crowding"]["state"] == "unknown"
    assert any("--squeeze" in l for l in unknown["crowding"]["lines"])


def test_thesis_bearish_s21_annotation():
    """print_report (S65): under --thesis bearish, S21 contrarian factors in the confirmations
    list carry the ⚠ annotation + a summary count; under bullish they don't."""
    import contextlib
    import io
    from lens import print_report

    risk = {"net": "x", "regime": None,
            "drawdown": ["VIX stress regime (elevated market risk)", "daily near top of 1y range"],
            "rally": []}
    def render(thesis):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_report("TEST", reads={}, divs={}, summary={"synthesis": "s"}, profile=None,
                         notes=[], color=False, candle_style="none", thesis=thesis, risk=risk)
        return buf.getvalue()
    bear = render("bearish")
    assert "⚠ S21: historically contrarian-BUY" in bear
    assert "1 of 2 confirmations are S21" in bear
    bull = render("bullish")
    assert "S21" not in bull


def test_bottom_performers_read():
    """sectors.bottom_performers_read (S65): worst-first tail of the same ranking that
    top_performers_read heads; short series omitted identically."""
    import numpy as np
    import pandas as pd
    from modules.sectors import bottom_performers_read, top_performers_read

    idx = pd.date_range("2026-01-01", periods=80, freq="B")
    def series(total_ret):
        return pd.Series(np.linspace(100, 100 * (1 + total_ret), 80), index=idx)
    closes = {"AAA": series(0.30), "BBB": series(0.10), "CCC": series(-0.20),
              "DDD": pd.Series([100.0], index=idx[:1])}          # too short — omitted
    cons = {"XLK": [("AAA", "A"), ("BBB", "B"), ("CCC", "C"), ("DDD", "D")]}
    top = top_performers_read(cons, closes, top_n=2)
    bot = bottom_performers_read(cons, closes, bottom_n=2)
    assert [m["sym"] for m in top["XLK"]] == ["AAA", "BBB"]
    assert [m["sym"] for m in bot["XLK"]] == ["CCC", "BBB"]      # worst first
    assert bottom_performers_read({}, {}) == {}


# ─── Test 59 (S65): enriched watchlist tile ────────────────────────────────────
def test_load_tile_enrichment():
    """api.loaders.load_tile (S65): the tile carries 52w position (0–1), a staleness count,
    and (when a snapshot exists) risk lean + regime — all zero-network off disk."""
    fastapi = __import__("pytest").importorskip("fastapi")  # noqa: F841 — api dep
    from api.loaders import load_tile

    t = load_tile("QQQ")
    assert t is not None and t["ticker"] == "QQQ"
    assert 0.0 <= t["pos52"] <= 1.0
    assert t["stale_days"] is None or t["stale_days"] >= 1
    assert "risk" in t and "regime" in t                       # keys present (values may be None)
    if t["risk"] is not None:
        assert set(t["risk"]) == {"dd", "rally"}


# ─── Test 60 (S65): lens self-score (offline, tmp dir) ─────────────────────────
def test_lens_score():
    """lens_score (S65): snapshot rows join to forward returns at the score_ledger
    convention; band edges land at 6/4/3; young rows pend; aggregates carry avg+median only;
    empty history → no_snapshots. All offline via a tmp payload_history + synthetic closes."""
    import json
    import os
    import tempfile

    import numpy as np
    import pandas as pd
    from lens_score import (SCORE_BANDS, _band, aggregate, score, score_snapshots,
                            snapshot_row)

    assert _band(6) == SCORE_BANDS[0][2] and _band(8) == SCORE_BANDS[0][2]
    assert _band(5) == "4–5 ✓" and _band(4) == "4–5 ✓"
    assert _band(3) == "≤3 ✓" and _band(0) == "≤3 ✓"

    snap = {"as_of": "2026-03-02", "close": 100.0,
            "setup": {"a": "✓", "b": "✓", "c": "–", "d": "✗"},
            "dd": ["x", "y"], "rally": ["z"], "regime": "ESTABLISHED UPTREND"}
    row = snapshot_row(snap)
    assert row == {"as_of": "2026-03-02", "ok": 2, "total": 4,
                   "n_dd": 2, "n_rally": 1, "regime": "ESTABLISHED UPTREND"}

    idx = pd.date_range("2026-03-02", periods=80, freq="B")
    close = pd.Series(np.linspace(100.0, 110.0, 80), index=idx)   # +10% over 79 steps
    scored = score_snapshots([row, {**row, "as_of": idx[-2].date().isoformat()}], close)
    assert scored[0]["fwd15"] is not None and scored[0]["fwd15"] > 0
    exp15 = float(close.iloc[15]) / float(close.iloc[0]) - 1
    assert abs(scored[0]["fwd15"] - exp15) < 1e-12
    assert scored[1]["fwd15"] is None                             # young row pends

    agg = aggregate(scored)
    cell = agg["bands"]["≤3 ✓"]                                   # ok=2 → ≤3 band
    assert cell["n"] == 2 and cell["scored15"] == 1
    assert set(cell) == {"n", "scored15", "avg15", "med15", "scored63", "avg63", "med63"}
    assert "4–5 ✓" not in agg["bands"]                            # empty cells absent
    assert agg["regimes"]["UPTREND"]["n"] == 2
    assert agg["leans"]["dd>rally"]["n"] == 2

    # end-to-end via a tmp dir: no history → no_snapshots; with history → ok
    with tempfile.TemporaryDirectory() as td:
        assert score("QQQ", td)["status"] == "no_snapshots"
        d = os.path.join(td, "payload_history", "qqq")
        os.makedirs(d)
        with open(os.path.join(d, "2026-03-02.json"), "w", encoding="utf-8") as f:
            json.dump(snap, f)
        pd.DataFrame({"Close": close}, index=idx).to_csv(os.path.join(td, "qqq_indicators.csv"))
        res = score("QQQ", td)
        assert res["status"] == "ok" and res["n"] == 1
        assert "NO significance" in res["note"]


# ─── Test 61 (S66): chart timeframes (offline — daily-CSV paths only) ──────────
def test_chart_tf_frame():
    """api.charts.tf_frame (S66): constants cover every TF; 1D delegates to chart_frame;
    1W/1M resample the daily CSV (W-FRI labels are Fridays); hour-bounds exist for exactly
    the intraday TFs (4h reopens at 08:00 — its midnight-anchored bins sit before 09:30)."""
    __import__("pytest").importorskip("fastapi")
    from api import charts

    assert set(charts.TF_VIEW) == set(charts.CHART_TFS)
    assert set(charts.TF_HOUR_BOUNDS) == {t for t in charts.CHART_TFS
                                          if t not in ("1D", "1W", "1M")}
    assert charts.TF_HOUR_BOUNDS["4h"][1] < 9.5 <= charts.TF_HOUR_BOUNDS["1h"][1]

    d1, nv1 = charts.tf_frame("QQQ", "1D")
    assert nv1 == charts.CHART_BARS and len(d1) > nv1
    dw, nvw = charts.tf_frame("QQQ", "1W")
    assert nvw == charts.TF_VIEW["1W"]
    assert all(d.weekday() == 4 for d in dw.index)          # W-FRI period-end labels
    dm, _ = charts.tf_frame("QQQ", "1M")
    assert len(dm) > 12
    # as-of truncation on the resampled path
    dw2, _ = charts.tf_frame("QQQ", "1W", as_of="2026-03-10")
    assert dw2.index.max() <= __import__("pandas").Timestamp("2026-03-14")


# ─── Test 71 (S70): netcache conventions (offline, pure) ────────────────────────
def test_s70_netcache_conventions(tmp_path):
    """most_recent_close mirrors pc_oi._most_recent_close (drift guard — the 10-line duplicate
    keeps pc_oi/tradier out of features.py's import chain); session_fresh flips exactly at the
    close boundary; fresh_hours is a plain wall-clock TTL; JSON helpers never raise."""
    import time
    from modules import netcache
    from modules import pc_oi

    close = netcache.most_recent_close()
    assert close == pc_oi._most_recent_close()               # drift guard
    assert close.weekday() < 5 and close.hour == 16

    ts = close.timestamp()
    assert netcache.session_fresh(ts + 1)                    # just after the boundary
    assert not netcache.session_fresh(ts - 1)                # just before → a close intervened
    assert not netcache.session_fresh(None)                  # unusable → stale, never raises
    assert not netcache.session_fresh("garbage")

    assert netcache.fresh_hours(time.time() - 3600, 24)
    assert not netcache.fresh_hours(time.time() - 25 * 3600, 24)
    assert not netcache.fresh_hours(None, 24)

    p = str(tmp_path / "sub" / "c.json")
    assert netcache.load_json(p) is None                     # missing → None
    netcache.save_json(p, {"a": 1})                          # makedirs
    assert netcache.load_json(p) == {"a": 1}
    with open(p, "w") as f:
        f.write("{not json")
    assert netcache.load_json(p) is None                     # corrupt → None, never raises


# ─── Test 72 (S70): VIX-complex close cache (offline) ───────────────────────────
def test_s70_vix_cache(tmp_path, monkeypatch):
    """add_vix behind the session-stale close cache: 3 downloads cold, 0 warm with identical
    values; an as-of sub-window is served from containment; an earlier start widens the fetch;
    an aged as_of refetches; a failed download serves the stale covering cache."""
    import json
    import time as _t
    import pandas as pd
    from modules import features

    n = 300
    idx = pd.bdate_range("2024-01-02", periods=n)
    df = pd.DataFrame({"Close": [100.0 + i * 0.1 for i in range(n)]}, index=idx)
    start = idx.min().strftime("%Y-%m-%d")
    end = (idx.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    calls = []

    def fake_download(sym, start=None, end=None, **k):
        calls.append((sym, start))
        vals = pd.date_range(start, end, freq="B")
        return pd.DataFrame({"Close": [20.0 + i * 0.01 for i in range(len(vals))]}, index=vals)

    monkeypatch.setattr(features.yf, "download", fake_download)
    d = str(tmp_path)

    a = features.add_vix(df.copy(), start, end, data_dir=d)
    assert len(calls) == 3                                    # cold: one per symbol
    b = features.add_vix(df.copy(), start, end, data_dir=d)
    assert len(calls) == 3                                    # warm: zero network
    pd.testing.assert_frame_equal(a, b)                       # cache round-trips exact values

    # as-of sub-window (narrower) — containment serves it with zero network
    sub_end = (idx[150] + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    features.add_vix(df.iloc[:151].copy(), start, sub_end, data_dir=d)
    assert len(calls) == 3

    # earlier start — the fetch WIDENS (min rule) and goes to network once per symbol
    features.add_vix(df.copy(), "2023-06-01", end, data_dir=d)
    assert len(calls) == 6 and all(s == "2023-06-01" for _, s in calls[3:])
    features.add_vix(df.copy(), start, end, data_dir=d)       # narrower again → contained
    assert len(calls) == 6

    # aged as_of → refetch
    p = tmp_path / "vix_cache" / "vix.json"
    c = json.loads(p.read_text())
    c["as_of"] = _t.time() - 14 * 24 * 3600
    p.write_text(json.dumps(c))
    features.add_vix(df.copy(), start, end, data_dir=d)
    assert len(calls) == 7                                    # only ^VIX was aged

    # failed download with a covering (stale) cache → served, never raises
    for f in (tmp_path / "vix_cache").iterdir():
        c = json.loads(f.read_text())
        c["as_of"] = 0.0
        f.write_text(json.dumps(c))

    def boom(*a, **k):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(features.yf, "download", boom)
    out = features.add_vix(df.copy(), start, end, data_dir=d)
    assert "VIX" in out.columns and out["VIX"].notna().any()


# ─── Test 73 (S70): SKEW/VVIX tail cache (offline) ──────────────────────────────
def test_s70_tail_cache(tmp_path, monkeypatch):
    """_fetch_tail: one batched download cold, zero warm; stale cache served on failure;
    empty Series (never a raise) on total failure with no cache."""
    import pandas as pd
    from modules import sentiment

    idx = pd.bdate_range("2025-01-02", periods=50)
    calls = []

    def fake_download(syms, **k):
        calls.append(syms)
        f = pd.DataFrame({("Close", "^SKEW"): [130.0 + i for i in range(len(idx))],
                          ("Close", "^VVIX"): [90.0 + i * 0.1 for i in range(len(idx))]},
                         index=idx)
        f.columns = pd.MultiIndex.from_tuples(f.columns)
        return f

    monkeypatch.setattr("yfinance.download", fake_download)
    d = str(tmp_path)
    sk, vv = sentiment._fetch_tail(d)
    assert len(calls) == 1 and len(sk) == 50 and len(vv) == 50
    sk2, vv2 = sentiment._fetch_tail(d)
    assert len(calls) == 1                                    # warm: zero network
    pd.testing.assert_series_equal(sk, sk2, check_names=False, check_freq=False)

    def boom(*a, **k):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr("yfinance.download", boom)
    sk3, vv3 = sentiment._fetch_tail(d)                       # stale fallback
    assert len(sk3) == 50 and float(sk3.iloc[-1]) == float(sk.iloc[-1])
    sk4, vv4 = sentiment._fetch_tail(str(tmp_path / "empty")) # no cache + failure → empty
    assert len(sk4) == 0 and len(vv4) == 0


# ─── Test 74 (S70): rs_cache — fetch_rs/fetch_beta shared closes (offline) ──────
def test_s70_rs_beta_cache(tmp_path, monkeypatch):
    """fetch_rs twice = ONE download total; fetch_beta after a SPY-bench fetch_rs = ZERO
    downloads (shared per-symbol cache); warm values equal the cold run; mixed fresh/stale
    symbols batch only the stale ones."""
    import pandas as pd
    from modules import setupcheck

    n = 100
    idx = pd.bdate_range("2025-01-01", periods=n)
    daily = pd.DataFrame({"Close": [100.0 * (1.002 ** i) for i in range(n)]}, index=idx)
    calls = []

    def fake_download(syms, **k):
        got = list(syms) if isinstance(syms, (list, tuple)) else [syms]
        calls.append(got)
        cols = {("Close", s): [100.0 * (1.001 ** i) * (1 + j * 0.001) for i in range(n)]
                for j, s in enumerate(got)}
        f = pd.DataFrame(cols, index=idx)
        f.columns = pd.MultiIndex.from_tuples(f.columns)
        return f

    monkeypatch.setattr("yfinance.download", fake_download)
    d = str(tmp_path)

    cold = setupcheck.fetch_rs("FAKE", daily, data_dir=d)     # FAKE → SPY fallback bench
    assert len(calls) == 1 and calls[0] == ["SPY"]
    warm = setupcheck.fetch_rs("FAKE", daily, data_dir=d)
    assert len(calls) == 1                                    # zero network on the repeat
    assert warm["rs"] == cold["rs"]                           # cache round-trips the math

    beta = setupcheck.fetch_beta("FAKE", daily, data_dir=d)   # SPY already cached
    assert len(calls) == 1 and beta and beta["n"] > 20

    # mixed fresh/stale: RSP is new → ONE batched download of just the stale symbol
    withx = setupcheck.fetch_rs("FAKE", daily, data_dir=d, extra=[("RSP", "ew twin")])
    assert len(calls) == 2 and calls[1] == ["RSP"]
    assert withx["rs"] == cold["rs"] and "RSP" in withx["extra"]


# ─── Test 75 (S70): earnings + ex-div result caches (offline) ───────────────────
def test_s70_earnings_exdiv_cache(tmp_path, monkeypatch):
    """earnings_dates: 24h cache incl. the EMPTY list (ETFs), stale fallback on failure.
    next_ex_dividend: result cached (null too), days recomputed on hit, past date refetches."""
    import json
    import time as _t
    import pandas as pd
    from modules import features

    d = str(tmp_path)
    future = (pd.Timestamp.today().normalize() + pd.Timedelta(days=30))
    calls = []

    class FakeT:
        def __init__(self, t):
            calls.append(t)

        def get_earnings_dates(self, limit=16):
            return pd.DataFrame({"EPS": [1.0]}, index=pd.DatetimeIndex([future]))

    monkeypatch.setattr(features.yf, "Ticker", FakeT)
    a = features.earnings_dates("FAKE", data_dir=d)
    assert len(calls) == 1 and a == [future]
    b = features.earnings_dates("FAKE", data_dir=d)
    assert len(calls) == 1 and b == a                         # cache hit, Timestamps restored

    class EmptyT:
        def __init__(self, t):
            calls.append(t)

        def get_earnings_dates(self, limit=16):
            return None

    monkeypatch.setattr(features.yf, "Ticker", EmptyT)
    assert features.earnings_dates("QETF", data_dir=d) == []
    assert features.earnings_dates("QETF", data_dir=d) == []
    assert calls.count("QETF") == 1                           # the EMPTY list is cached too

    # TTL expiry → refetch; fetch failure → stale fallback
    p = tmp_path / "earnings_cache" / "FAKE.json"
    c = json.loads(p.read_text())
    c["as_of"] = _t.time() - 25 * 3600
    p.write_text(json.dumps(c))

    class BoomT:
        def __init__(self, t):
            calls.append(t)

        def get_earnings_dates(self, limit=16):
            raise RuntimeError("yahoo down")

    monkeypatch.setattr(features.yf, "Ticker", BoomT)
    assert features.earnings_dates("FAKE", data_dir=d) == [future]   # stale beats nothing

    # ── ex-div: result cached, days recomputed from the cached DATE on every hit
    exd_date = (pd.Timestamp.today().normalize() + pd.Timedelta(days=10))
    ex_calls = []

    class DivT:
        def __init__(self, t):
            ex_calls.append(t)

        def get_calendar(self):
            return {"Ex-Dividend Date": exd_date}

        @property
        def dividends(self):
            return pd.Series(dtype=float)

    monkeypatch.setattr(features.yf, "Ticker", DivT)
    v1 = features.next_ex_dividend("PAYER", data_dir=d)
    assert len(ex_calls) == 1 and v1["days"] == 10 and v1["est"] is False
    v2 = features.next_ex_dividend("PAYER", data_dir=d)
    assert len(ex_calls) == 1 and v2 == v1                    # hit, zero network

    class NoDivT:
        def __init__(self, t):
            ex_calls.append(t)

        def get_calendar(self):
            return {}

        @property
        def dividends(self):
            return pd.Series(dtype=float)

    monkeypatch.setattr(features.yf, "Ticker", NoDivT)
    assert features.next_ex_dividend("GROWTH", data_dir=d) is None
    assert features.next_ex_dividend("GROWTH", data_dir=d) is None
    assert ex_calls.count("GROWTH") == 1                      # null cached (non-payers)

    # past cached date → treated stale → refetch
    p = tmp_path / "exdiv_cache" / "PAYER.json"
    c = json.loads(p.read_text())
    c["val"]["date"] = "2020-01-02"
    p.write_text(json.dumps(c))
    monkeypatch.setattr(features.yf, "Ticker", DivT)
    v3 = features.next_ex_dividend("PAYER", data_dir=d)
    assert ex_calls.count("PAYER") == 2 and v3["days"] == 10


# ─── Test 76 (S70): session-stale report cache (offline) ────────────────────────
def test_s70_report_session_cache(monkeypatch):
    """put_report/get_report: hit while session-fresh; a market close having passed →
    miss + prune; maxsize eviction drops the oldest."""
    __import__("pytest").importorskip("fastapi")
    import pandas as pd
    from api import cache as api_cache
    from modules import netcache

    api_cache.report_cache.clear()
    try:
        key = ("QQQ", (("vol", False),))
        bundle = {"payload": {"ticker": "QQQ"}, "preamble": "", "ansi_html": ""}
        api_cache.put_report(key, bundle)
        assert api_cache.get_report(key) is bundle             # same-session hit

        # a close has occurred since the entry was stored → miss AND pruned
        future_close = netcache.most_recent_close() + pd.Timedelta(days=5)
        monkeypatch.setattr(netcache, "most_recent_close", lambda: future_close)
        assert api_cache.get_report(key) is None
        assert key not in api_cache.report_cache
        monkeypatch.undo()

        # maxsize eviction — oldest entry goes first
        api_cache.report_cache.clear()
        old_max = api_cache._REPORT_MAX
        api_cache._REPORT_MAX = 3
        try:
            for i in range(4):
                api_cache.put_report((f"T{i}", ()), {"payload": {"i": i}})
            assert len(api_cache.report_cache) == 3
            assert ("T0", ()) not in api_cache.report_cache
            assert api_cache.get_report(("T3", ()))["payload"]["i"] == 3
        finally:
            api_cache._REPORT_MAX = old_max
    finally:
        api_cache.report_cache.clear()
