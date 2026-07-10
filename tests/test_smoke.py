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
    floor demotion, majority-no-bid → dead); curve_read tags the cheaper tenor; _select_expiries
    picks the monthlies nearest 45/90 DTE. Pure, no network."""
    from modules.callquote import (pick_call_candidates, liquidity_grade, curve_read,
                                   _select_expiries)

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

    future = [("2026-07-17", 10), ("2026-08-07", 31), ("2026-08-21", 45),
              ("2026-09-18", 73), ("2026-10-16", 101)]
    assert [s[0] for s in _select_expiries(future)] == ["2026-08-21", "2026-10-16"]


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

    for name in ("next_earnings", "next_ex_dividend", "fetch_rs", "fetch_beta"):
        monkeypatch.setattr(lens, name, None, raising=False)

    args = SimpleNamespace(ticker=None, thesis=None, level=None, no_intraday=True, no_vix=True,
                           geo=False, no_color=True, candle="none", candle_px=128, prev=10,
                           data_dir="data", no_refresh=True, refresh=False, pc_oi=None,
                           insider=False, squeeze=False, live=False, vol=False, call=False)
    payload = lens.gather_report("QQQ", args, interactive=False, backdrop_base=None)
    assert payload is not None

    expected = {"ticker", "reads", "divs", "summary", "profile", "notes", "last_bar", "as_of",
                "panel_bars", "ctx", "backdrop", "geo", "pcoi", "vol", "live", "setup",
                "squeeze", "insider", "callq", "liq", "cats", "risk", "macro_events",
                "thesis", "level", "live_iv", "earn", "exd"}
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
