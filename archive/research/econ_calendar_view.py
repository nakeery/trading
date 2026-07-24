"""
Economic Calendar — graphical month view
=========================================
Pops a calendar window (matplotlib) showing the scheduled macro releases tracked by
modules/econ_calendar.py — FOMC, CPI, NFP, PCE (Tier 1) and PPI, GDP, Retail, JOLTS,
Claims (Tier 2) — on a month grid, color-coded by tier, with today highlighted.

Reads the cached calendar from data/econ_calendar.csv. On launch it does a TTL
"refresh if stale" (refresh when the cache is older than 7 days) with graceful fallback
— no FRED key or network needed to view the cached data; only an actual refresh needs a
key. It always writes a PNG (data/econ_calendar.png) and also opens a popup window unless
--save-only is given.

Usage:
    python econ_calendar_view.py                 # current + next 2 months (popup + PNG)
    python econ_calendar_view.py --months 6      # six months (wraps to a grid)
    python econ_calendar_view.py --tier1-only    # only FOMC / CPI / NFP / PCE
    python econ_calendar_view.py --no-refresh    # never touch the network
    python econ_calendar_view.py --save-only     # write the PNG, no window (headless)

Refresh the underlying cache (weekly; needs FRED_API_KEY):
    python -m modules.econ_calendar --refresh

Requirements: matplotlib, numpy, pandas (all core deps).
"""

import argparse
import calendar as calmod
import datetime
import os
import sys

import numpy as np

import matplotlib
if "--save-only" in sys.argv:        # headless / verification — force non-GUI backend
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Patch

from modules.econ_calendar import (
    events_in_range, refresh_if_stale, coverage_end_per_series,
    ALL_SERIES, TIER1_SERIES,
)

DATA_DIR = "data"

TIER1_NAMES = {name for name, _, _ in TIER1_SERIES}
TIER1_COLOR = "#c0392b"   # red — the market movers
TIER2_COLOR = "#5d8aa8"   # steel blue
EMPTY_COLOR = "#f7f7f7"
TODAY_EDGE  = "#f39c12"   # gold outline
GRID_EDGE   = "#dddddd"
WEEKDAYS    = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _month_iter(year, month, n):
    """Yield (year, month) for n consecutive months starting at (year, month)."""
    y, m = year, month
    for _ in range(n):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def build_events_by_day(events_df, year, month, tier1_only):
    """{day_of_month: [(series, tier), ...]} for one month from an events DataFrame."""
    out = {}
    if events_df.empty:
        return out
    mask = (events_df["date"].dt.year == year) & (events_df["date"].dt.month == month)
    for _, r in events_df[mask].iterrows():
        if tier1_only and r["series"] not in TIER1_NAMES:
            continue
        out.setdefault(int(r["date"].day), []).append((r["series"], int(r["tier"])))
    return out


def draw_month(ax, year, month, events_by_day, today):
    weeks   = calmod.Calendar(firstweekday=0).monthdayscalendar(year, month)
    n_weeks = len(weeks)
    ax.set_xlim(0, 7)
    ax.set_ylim(0, n_weeks + 1)
    ax.axis("off")
    ax.set_title(f"{calmod.month_name[month]} {year}", fontsize=12, fontweight="bold", pad=6)

    for i, wd in enumerate(WEEKDAYS):
        ax.text(i + 0.5, n_weeks + 0.45, wd, ha="center", va="center", fontsize=9,
                fontweight="bold", color="#999999" if i >= 5 else "#333333")

    for w, week in enumerate(weeks):
        y = n_weeks - 1 - w
        for i, day in enumerate(week):
            if day == 0:
                continue
            evs = events_by_day.get(day, [])
            if evs:
                facecolor = TIER1_COLOR if any(t == 1 for _, t in evs) else TIER2_COLOR
                daycolor  = "white"
            else:
                facecolor, daycolor = EMPTY_COLOR, "#333333"
            ax.add_patch(Rectangle((i, y), 1, 1, facecolor=facecolor,
                                   edgecolor=GRID_EDGE, linewidth=0.8))
            if (year, month, day) == (today.year, today.month, today.day):
                ax.add_patch(Rectangle((i + 0.02, y + 0.02), 0.96, 0.96, fill=False,
                                       edgecolor=TODAY_EDGE, linewidth=2.5))
            ax.text(i + 0.07, y + 0.9, str(day), ha="left", va="top",
                    fontsize=8, fontweight="bold", color=daycolor)
            for j, (series, _) in enumerate(evs[:3]):
                ax.text(i + 0.5, y + 0.55 - j * 0.24, series, ha="center", va="center",
                        fontsize=7.5, fontweight="bold", color="white")
            if len(evs) > 3:
                ax.text(i + 0.5, y + 0.08, f"+{len(evs) - 3}", ha="center", va="bottom",
                        fontsize=6.5, color="white")


def main():
    parser = argparse.ArgumentParser(description="Graphical economic-release calendar.")
    parser.add_argument("--months", type=int, default=3, help="Months to show from current (default 3).")
    parser.add_argument("--tier1-only", action="store_true", help="Show only Tier-1 series (FOMC/CPI/NFP/PCE).")
    parser.add_argument("--no-refresh", action="store_true", help="Skip the TTL refresh-if-stale check.")
    parser.add_argument("--save-only", action="store_true", help="Write the PNG, don't open a window.")
    parser.add_argument("--data-dir", default=DATA_DIR, help="Cache directory (default: data).")
    parser.add_argument("--out", default=os.path.join("data", "econ_calendar.png"), help="PNG output path.")
    args = parser.parse_args()

    # 1. Freshness — graceful, never fatal.
    if args.no_refresh:
        status, status_msg = "skipped", "refresh skipped (--no-refresh)"
    else:
        status, status_msg = refresh_if_stale(data_dir=args.data_dir)
    print(f"  Calendar cache: {status} — {status_msg}")

    # 2. Date range = first of this month .. last day of the final shown month.
    today  = datetime.date.today()
    months = max(1, args.months)
    month_list = list(_month_iter(today.year, today.month, months))
    last_y, last_m = month_list[-1]
    start = datetime.date(today.year, today.month, 1)
    end   = datetime.date(last_y, last_m, calmod.monthrange(last_y, last_m)[1])
    events_df = events_in_range(start, end, data_dir=args.data_dir)

    # 3. Draw — wrap to a grid (max 3 columns) for larger --months.
    ncols = min(months, 3)
    nrows = (months + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.4 * ncols, 6.0 * nrows))
    axes = np.atleast_1d(axes).flatten()
    for idx, ax in enumerate(axes):
        if idx < len(month_list):
            y, m = month_list[idx]
            draw_month(ax, y, m, build_events_by_day(events_df, y, m, args.tier1_only), today)
        else:
            ax.axis("off")

    banner_color = ("#27ae60" if status in ("fresh", "refreshed")
                    else "#7f8c8d" if status == "skipped" else "#c0392b")
    fig.suptitle(f"Economic Calendar    ·    {status_msg}", fontsize=13,
                 fontweight="bold", color=banner_color, y=0.99)

    handles = [Patch(facecolor=TIER1_COLOR, label="Tier 1  (FOMC · CPI · NFP · PCE)"),
               Patch(facecolor=TIER2_COLOR, label="Tier 2  (PPI · GDP · Retail · JOLTS · Claims)")]
    fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False,
               fontsize=9, bbox_to_anchor=(0.5, 0.012))

    # Coverage footnote — series whose cache runs out before the last shown month.
    cov = coverage_end_per_series(data_dir=args.data_dir)
    ran_out = []
    for name, _, _ in ALL_SERIES:
        if args.tier1_only and name not in TIER1_NAMES:
            continue
        last = cov.get(name)
        if last is None:
            ran_out.append(f"{name}: none")
        elif last.date() < end:
            ran_out.append(f"{name}: ends {last.strftime('%Y-%m')}")
    if ran_out:
        fig.text(0.5, 0.05, "Coverage note — " + " · ".join(ran_out)
                 + "   (refresh: python -m modules.econ_calendar --refresh)",
                 ha="center", va="bottom", fontsize=7.5, color="#c0392b")

    fig.tight_layout(rect=[0, 0.09, 1, 0.96])

    # 4. Always save the PNG; open the window unless --save-only.
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    fig.savefig(args.out, dpi=120, bbox_inches="tight")
    print(f"  Saved {args.out}")
    if not args.save_only:
        plt.show()


if __name__ == "__main__":
    main()
