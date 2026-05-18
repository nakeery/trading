"""
Economic-release calendar — proximity features for forward-looking macro awareness.

Mirrors the catalyst-proximity pattern at modules/benchmarks.py:124 at the macro
level. Adds Days_to_FOMC, Days_to_CPI, Days_to_NFP, ... columns so models can
position around scheduled releases that pure price/volume features can't see.

Auth: free FRED API key from fred.stlouisfed.org. Reads FRED_API_KEY env var;
calls fail clearly if unset. Normal pipeline reads need only the cached CSV.

Refresh weekly:  python -m modules.econ_calendar --refresh
List releases:   python -m modules.econ_calendar --list-releases
"""

import argparse
import datetime
import os
import sys

import pandas as pd
import requests

FRED_API_KEY   = os.environ.get("FRED_API_KEY", "")
FRED_URL       = "https://api.stlouisfed.org/fred"
CACHE_FILENAME = "econ_calendar.csv"
SENTINEL_DAYS  = 90    # matches modules/benchmarks.py:153 catalyst sentinel

# Tier 1 — highest market-impact releases. Tracked on every ticker by default.
# Format: (canonical_short_name, fred_release_id, display_name)
# Release IDs verified via `python -m modules.econ_calendar --list-releases` (2026-05-18).
TIER1_SERIES = [
    ("FOMC",   101, "FOMC Press Release"),
    ("CPI",    10,  "Consumer Price Index"),
    ("NFP",    50,  "Employment Situation"),
    ("PCE",    54,  "Personal Income and Outlays"),
]

# Tier 2 — high impact, secondary tier.
TIER2_SERIES = [
    ("PPI",    46,  "Producer Price Index"),
    ("GDP",    53,  "Gross Domestic Product"),
    ("Retail", 436, "Monthly Retail Trade and Food Services"),
    ("JOLTS",  192, "Job Openings and Labor Turnover Survey"),
    ("Claims", 180, "Unemployment Insurance Weekly Claims Report"),
]

ALL_SERIES = TIER1_SERIES + TIER2_SERIES

# Public export — column names that downstream code may need to reference
# programmatically (e.g., to exclude from feature_cols if NaN).
ECON_FEATURE_COLS = [f"Days_to_{name}" for name, _, _ in ALL_SERIES] + ["Days_to_macro"]

# FOMC meeting dates — manually curated from federalreserve.gov/monetarypolicy/fomccalendars.htm.
# FRED release_id=101 ("FOMC Press Release") publishes every weekday and can't be used as a
# meeting-date proxy. Maintenance: update annually when the Fed publishes next year's calendar
# (typically released ~14 months ahead). Each entry is the meeting's END date — the day the
# statement and rate decision are published. Two-day meetings list the day-2 date only.
FOMC_MEETING_DATES = [
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    # 2027
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
    "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08",
]


def _get(path, params=None):
    """FRED GET wrapper. Raises RuntimeError if FRED_API_KEY unset."""
    if not FRED_API_KEY:
        raise RuntimeError("FRED_API_KEY env var not set — cannot call FRED API")
    p = {"api_key": FRED_API_KEY, "file_type": "json"}
    if params:
        p.update(params)
    resp = requests.get(f"{FRED_URL}/{path}", params=p, timeout=15)
    resp.raise_for_status()
    return resp.json()


def list_releases():
    """Enumerate all FRED releases — used once to verify release_ids in TIER1/TIER2."""
    data = _get("releases", {"limit": 1000})
    releases = data.get("releases", [])
    for r in releases:
        print(f"  {r['id']:5d}  {r['name']}")
    print(f"\n  Total: {len(releases)} releases")


def refresh(data_dir="modules"):
    """
    Fetch forward release dates for every series in ALL_SERIES from FRED and
    write atomic CSV (tmp → rename on success).
    Keeps 5y of history + all forward dates returned by the API.
    """
    rows  = []
    today = datetime.date.today()
    cutoff_past = today - datetime.timedelta(days=365 * 5)

    for series_name, release_id, release_display in ALL_SERIES:
        tier = 1 if (series_name, release_id, release_display) in TIER1_SERIES else 2

        # FOMC: hardcoded dates (FRED release_id=101 returns every weekday, not meeting dates).
        if series_name == "FOMC":
            n_added = 0
            for date_str in FOMC_MEETING_DATES:
                try:
                    d = datetime.date.fromisoformat(date_str)
                except ValueError:
                    continue
                if d < cutoff_past:
                    continue
                rows.append({
                    "series":       series_name,
                    "date":         date_str,
                    "release_id":   release_id,
                    "release_name": release_display,
                    "tier":         tier,
                })
                n_added += 1
            print(f"  ✓ {series_name}: {n_added} dates (manual — {len(FOMC_MEETING_DATES)} total)")
            continue

        try:
            data = _get(
                "release/dates",
                {"release_id":                         release_id,
                 "include_release_dates_with_no_data": "true",
                 "sort_order":                         "desc",
                 "limit":                              1000},
            )
        except Exception as e:
            print(f"  ✗ {series_name} (release_id={release_id}): {e}")
            continue

        n_added = 0
        for rd in data.get("release_dates", []):
            date_str = rd.get("date")
            if not date_str:
                continue
            try:
                d = datetime.date.fromisoformat(date_str)
            except ValueError:
                continue
            if d < cutoff_past:
                continue
            rows.append({
                "series":       series_name,
                "date":         date_str,
                "release_id":   release_id,
                "release_name": release_display,
                "tier":         tier,
            })
            n_added += 1
        print(f"  ✓ {series_name}: {n_added} dates (release_id={release_id})")

    if not rows:
        print("\n  ✗ no rows fetched — leaving any existing CSV in place")
        return

    df = pd.DataFrame(rows).sort_values(["series", "date"]).reset_index(drop=True)
    out_path = os.path.join(data_dir, CACHE_FILENAME)
    tmp_path = out_path + ".tmp"
    df.to_csv(tmp_path, index=False)
    os.replace(tmp_path, out_path)
    print(f"\n  Wrote {len(df)} rows -> {out_path}")


def _load_cache(data_dir):
    """Return cached DataFrame with parsed date column, or None if file missing."""
    path = os.path.join(data_dir, CACHE_FILENAME)
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _check_staleness(cal, today):
    """Print one-line warning for any series with < 30 forward days."""
    cutoff = today + pd.Timedelta(days=30)
    for series_name, _, _ in ALL_SERIES:
        future = cal[(cal["series"] == series_name) & (cal["date"] >= today)]
        if len(future) == 0:
            print(f"  ⚠ econ_calendar.csv: no forward dates for {series_name} — run --refresh")
        elif future["date"].max() < cutoff:
            days_left = (future["date"].max() - today).days
            print(f"  ⚠ econ_calendar.csv: only {days_left}d forward for {series_name}")


def add_macro_event_proximity(df, data_dir="modules", for_direction=False):
    """
    Add Days_to_FOMC, Days_to_CPI, ..., Days_to_macro columns to df.

    Macro events are universal — no ticker arg required.

    The for_direction kwarg is reserved for future use (signature symmetry with
    modules.benchmarks.add_catalyst_proximity); in v1 macro proximity is treated
    as a real signal for all models including direction.

    Sentinel SENTINEL_DAYS (90) fills:
      - missing CSV entirely
      - series with no future dates
      - cap on values larger than SENTINEL_DAYS

    All columns are integer-valued and bounded [0, SENTINEL_DAYS].
    """
    cal = _load_cache(data_dir)
    if cal is None:
        for col in ECON_FEATURE_COLS:
            df[col] = SENTINEL_DAYS
        print(f"  ⚠ econ_calendar.csv not found — Days_to_* filled with {SENTINEL_DAYS}")
        return df

    today = pd.Timestamp.today().normalize()
    _check_staleness(cal, today)

    for series_name, _, _ in ALL_SERIES:
        col = f"Days_to_{series_name}"
        series_dates = sorted(
            cal[cal["series"] == series_name]["date"].dt.normalize().unique()
        )
        if not series_dates:
            df[col] = SENTINEL_DAYS
            continue

        def _days_to_next(idx_date, _dates=series_dates):
            future = [d for d in _dates if d >= idx_date]
            if not future:
                return SENTINEL_DAYS
            return min(int((future[0] - idx_date).days), SENTINEL_DAYS)

        df[col] = [_days_to_next(d) for d in df.index]

    feature_cols = [f"Days_to_{name}" for name, _, _ in ALL_SERIES]
    df["Days_to_macro"] = df[feature_cols].min(axis=1).astype(int)

    print(f"  ✓ {', '.join(ECON_FEATURE_COLS)}")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Economic release calendar — refresh / list releases."
    )
    parser.add_argument("--refresh", action="store_true",
                        help="Fetch fresh release dates from FRED and update the cache CSV.")
    parser.add_argument("--list-releases", action="store_true",
                        help="List all FRED releases (use to verify release_ids in constants).")
    parser.add_argument("--data-dir", default="modules",
                        help="Cache directory (default: modules).")
    args = parser.parse_args()

    if args.list_releases:
        list_releases()
    elif args.refresh:
        refresh(data_dir=args.data_dir)
    else:
        parser.print_help()
        sys.exit(1)
