"""
Pre-earnings vol study (S39) — evidence layer for `lens.py --vol`.

Does the pre-earnings IV RAMP the `--vol` block assumes actually show up for a given name? For the
last ~8 earnings this measures, off on-disk data (no new API load):
  - IV ramp   = atm_iv_30d the session before the report − atm_iv_30d ~entry_td sessions earlier
  - crush     = atm_iv_30d the session after the report − the session before (the IV collapse)
  - straddle P&L for a buy-early / sell-before-the-print ATM straddle, via Black-Scholes repricing
    (captures IV gain − theta − spot drift)
plus an entry-timing sweep (5/10/15 sessions) so the ramp-vs-theta sweet spot is visible.

Descriptive CONTEXT only — never a signal (LENS ethos). HV was considered and rejected: the ramp is
an IMPLIED-vol phenomenon; realized/HV is flat-to-down pre-earnings and only spikes after the report,
so an HV-priced sim would bake in theta but miss the ramp (a systematic false-negative). So this reads
the on-disk historic IV (`atm_iv_30d`, ~2yr deep for backfilled names). When that history is too thin
it (interactively) offers to run the Massive backfill; and it degrades cleanly when Massive is
unavailable (no key / lapsed subscription). Best-effort: never raises.

Caveats (also printed): ~8 earnings (2yr Massive IV cap) is indicative, not proof; `atm_iv_30d` is a
constant-maturity 30d proxy, not the exact earnings-expiry IV; BS with r=q=0, no bid/ask or fills.
"""

import os
import sys
import math
import statistics as stats

import pandas as pd

from modules.bs_invert import black_scholes_call
from modules.features import earnings_dates

MIN_USABLE       = 3            # need at least this many earnings with usable IV to run the study
N_EARNINGS       = 8            # study the most recent N in-range earnings
POST_BUFFER_DAYS = 12           # synthetic post-earnings expiry ≈ nearest post-earnings monthly
ENTRY_SWEEP      = (5, 10, 15)  # entry-timing sweep (trading sessions before the report)


def _straddle_price(S, K, T, iv, r=0.0, q=0.0):
    """ATM-ish straddle = call + put via Black-Scholes + put-call parity. r=q=0 by default (short
    horizons, ATM → rate effect negligible). Returns the straddle price, or None on bad inputs."""
    if S <= 0 or K <= 0 or T <= 0 or iv is None or iv <= 0:
        return None
    c = black_scholes_call(S, K, r, T, iv, q)
    p = c - S * math.exp(-q * T) + K * math.exp(-r * T)      # put-call parity
    return c + max(p, 0.0)


def _sessions_for(idx, E, entry_td):
    """Index timestamps (entry, pre, post) for one earnings date E, or None if out of range.
    pre = last session strictly before E; entry = `entry_td` sessions before pre; post = first
    session strictly after E. `idx` must be a sorted DatetimeIndex."""
    pos_pre  = int(idx.searchsorted(E, side="left")) - 1     # last session < E
    pos_entry = pos_pre - entry_td
    pos_post = int(idx.searchsorted(E, side="right"))        # first session > E
    if pos_entry < 0 or pos_pre < 0 or pos_post >= len(idx):
        return None
    return idx[pos_entry], idx[pos_pre], idx[pos_post]


def _one_earnings(df, idx, E, entry_td):
    """Per-earnings IV ramp / crush / straddle P&L, or None if any input is missing/out of range."""
    s = _sessions_for(idx, E, entry_td)
    if s is None:
        return None
    entry_ts, pre_ts, post_ts = s
    iv_entry, iv_pre, iv_post = (df.at[entry_ts, "atm_iv_30d"], df.at[pre_ts, "atm_iv_30d"],
                                 df.at[post_ts, "atm_iv_30d"])
    s_entry, s_pre = df.at[entry_ts, "Close"], df.at[pre_ts, "Close"]
    if any(v is None or pd.isna(v) for v in (iv_entry, iv_pre, iv_post, s_entry, s_pre)):
        return None
    iv_entry, iv_pre, iv_post = float(iv_entry), float(iv_pre), float(iv_post)
    s_entry, s_pre = float(s_entry), float(s_pre)
    if s_entry <= 0 or s_pre <= 0:
        return None

    # synthetic post-earnings expiry ≈ the nearest post-earnings monthly; K fixed at entry spot (ATM).
    expiry = E + pd.Timedelta(days=POST_BUFFER_DAYS)
    st_e = _straddle_price(s_entry, s_entry, (expiry - entry_ts).days / 365.0, iv_entry)
    st_p = _straddle_price(s_pre,   s_entry, (expiry - pre_ts).days / 365.0, iv_pre)
    pnl = (st_p / st_e - 1.0) if (st_e and st_p and st_e > 0) else None

    return {"date": E.date().isoformat(), "iv_entry": iv_entry, "iv_pre": iv_pre, "iv_post": iv_post,
            "ramp": iv_pre - iv_entry, "crush": iv_post - iv_pre, "pnl": pnl}


def _aggregate(df, idx, past, entry_td):
    """Aggregate the per-earnings rows for one entry offset, or None if nothing usable."""
    rows = [r for r in (_one_earnings(df, idx, E, entry_td) for E in past) if r]
    if not rows:
        return None
    ramps = [r["ramp"] for r in rows]
    pnls  = [r["pnl"] for r in rows if r["pnl"] is not None]
    return {
        "entry_td": entry_td, "n": len(rows), "rows": rows,
        "ramp_median": stats.median(ramps),
        "crush_median": stats.median([r["crush"] for r in rows]),
        "pnl_median": (stats.median(pnls) if pnls else None),
        "ramp_hits": sum(1 for r in ramps if r > 0),
        "pnl_wins": sum(1 for p in pnls if p > 0), "n_pnl": len(pnls),
    }


def _summary_line(agg):
    """One-line verdict for the lens inline block."""
    r = f"IV ramped {agg['ramp_hits']}/{agg['n']}, median {agg['ramp_median'] * 100:+.0f}pt"
    if agg["pnl_median"] is not None:
        r += (f"; buy-{agg['entry_td']}d/sell-1d straddle {agg['pnl_median'] * 100:+.0f}% "
              f"(won {agg['pnl_wins']}/{agg['n_pnl']})")
    return r + f"; crush {agg['crush_median'] * 100:+.0f}pt"


def _offer_backfill(ticker, data_dir, usable, total):
    """TTY-gated: offer to run the Massive IV backfill in place. Returns True if it added IV.
    Degrades cleanly when Massive is unavailable (no key / lapsed subscription)."""
    if not os.environ.get("MASSIVE_API_KEY"):
        print(f"  {ticker}: IV history covers only {usable}/{total} earnings, and the backfill needs "
              f"a Massive key + subscription ($env:MASSIVE_API_KEY). Skipping the study.")
        return False
    try:
        ans = input(f"  {ticker}: IV history covers only {usable}/{total} earnings — run the "
                    f"~10-20 min Massive backfill now? [y/N]: ")
    except EOFError:
        return False
    if not ans.strip().lower().startswith("y"):
        print(f"  Skipped. Run `python backfill_iv.py` (ticker {ticker}) when ready.")
        return False

    from backfill_iv import backfill      # lazy import — avoids pulling yfinance/massive at load
    res = backfill(ticker, data_dir=data_dir)
    status = res.get("status")
    if status == "ok" and res.get("filled"):
        return True
    msg = {
        "no_massive_key": "no Massive API key",
        "massive_error": "Massive returned an error (auth / subscription?)",
        "no_csv": "indicators CSV not found",
        "nothing_to_do": "nothing to backfill (already populated) — earnings likely predate the 2yr cap",
    }.get(status, "Massive returned no usable IV data (plan/subscription may not cover it)")
    print(f"  Backfill did not add usable IV ({msg}); study unavailable.")
    return False


def pre_earnings_vol_study(ticker, entry_td=10, data_dir="data", earnings=None, interactive=False):
    """Historical pre-earnings IV ramp / crush / straddle-P&L study for `ticker`. Returns a dict with
    a `status` ∈ {"ok", "insufficient_iv", "no_earnings", "no_csv"}. `earnings` is injectable (list of
    dates) for offline testing. When `interactive` and IV history is thin, offers a backfill (TTY).
    Best-effort: never raises."""
    csv_path = os.path.join(data_dir, f"{ticker.lower()}_indicators.csv")
    if not os.path.exists(csv_path):
        return {"status": "no_csv", "ticker": ticker}
    try:
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True).sort_index()
    except Exception:
        return {"status": "no_csv", "ticker": ticker}
    if "atm_iv_30d" not in df.columns or "Close" not in df.columns:
        return {"status": "insufficient_iv", "ticker": ticker, "usable": 0, "total": 0}

    if earnings is None:
        earnings = earnings_dates(ticker)
    if not earnings:
        return {"status": "no_earnings", "ticker": ticker}

    idx = df.index
    today = pd.Timestamp.today().normalize()
    past_all = [pd.Timestamp(e).normalize() for e in earnings if pd.Timestamp(e).normalize() < today]
    # keep the most recent N earnings whose entry/pre/post sessions all fall inside the CSV span.
    past = sorted(e for e in past_all if _sessions_for(idx, e, entry_td) is not None)[-N_EARNINGS:]
    total = len(past)

    main_agg = _aggregate(df, idx, past, entry_td)
    usable = main_agg["n"] if main_agg else 0

    if usable < MIN_USABLE:
        if interactive and _offer_backfill(ticker, data_dir, usable, total):
            # backfill added IV — recompute once, non-interactively.
            return pre_earnings_vol_study(ticker, entry_td=entry_td, data_dir=data_dir,
                                          earnings=earnings, interactive=False)
        return {"status": "insufficient_iv", "ticker": ticker, "usable": usable, "total": total}

    sweep_tds = sorted(set(ENTRY_SWEEP) | {entry_td})
    sweep = [a for a in ((main_agg if td == entry_td else _aggregate(df, idx, past, td))
                         for td in sweep_tds) if a]
    caveats = [
        f"{usable} of {total} earnings usable (2yr Massive IV cap) — indicative, not proof",
        "IV = atm_iv_30d, a constant-maturity 30d proxy (not the exact earnings-expiry IV)",
        "straddle P&L via Black-Scholes (r=q=0), no bid/ask or fills; entry/exit keyed to the "
        "earnings date (a day early for after-close reporters)",
    ]
    return {"status": "ok", "ticker": ticker, "entry_td": entry_td, "usable": usable, "total": total,
            "agg": main_agg, "sweep": sweep, "summary": _summary_line(main_agg), "caveats": caveats}


# ─────────────────────────────────────────
# STANDALONE CLI
# ─────────────────────────────────────────
def _print_study(study):
    t, st = study["ticker"], study["status"]
    if st == "no_csv":
        print(f"  {t}: no indicators CSV — run indicators.py (then backfill_iv.py) first.")
        return
    if st == "no_earnings":
        print(f"  {t}: no earnings dates (ETF?) — pre-earnings vol study N/A.")
        return
    if st == "insufficient_iv":
        print(f"  {t}: insufficient IV history ({study.get('usable', 0)}/{study.get('total', 0)} "
              f"earnings usable). Run `python backfill_iv.py` (ticker {t}) to enable the study.")
        return

    agg = study["agg"]
    print(f"\n  PRE-EARNINGS VOL STUDY — {t}   (IV = atm_iv_30d, constant-maturity 30d proxy)")
    print(f"  buy ~{agg['entry_td']} sessions before earnings, sell the session before the report:\n")
    print(f"    {'earnings':<12}{'IVentry':>9}{'IVpre':>8}{'ramp':>8}{'crush':>8}{'straddle P&L':>15}")
    for row in agg["rows"]:
        pnl = f"{row['pnl'] * 100:+.1f}%" if row["pnl"] is not None else "n/a"
        print(f"    {row['date']:<12}{row['iv_entry'] * 100:>8.0f}%{row['iv_pre'] * 100:>7.0f}%"
              f"{row['ramp'] * 100:>+8.0f}{row['crush'] * 100:>+8.0f}{pnl:>15}")
    pnl_med = f"{agg['pnl_median'] * 100:+.1f}%" if agg["pnl_median"] is not None else "n/a"
    print(f"\n    medians ({agg['n']} usable of {study['total']}): ramp {agg['ramp_median'] * 100:+.0f}pt"
          f" · crush {agg['crush_median'] * 100:+.0f}pt · P&L {pnl_med}")
    print(f"    ramp hit {agg['ramp_hits']}/{agg['n']} · P&L win {agg['pnl_wins']}/{agg['n_pnl']}")

    print(f"\n    entry-timing sweep (median across earnings):")
    print(f"      {'entry':>6}{'ramp':>8}{'P&L':>9}{'win':>9}")
    for a in study["sweep"]:
        pnl = f"{a['pnl_median'] * 100:+.0f}%" if a["pnl_median"] is not None else "n/a"
        print(f"      {str(a['entry_td']) + 'd':>6}{a['ramp_median'] * 100:>+8.0f}{pnl:>9}"
              f"{str(a['pnl_wins']) + '/' + str(a['n_pnl']):>9}")

    print(f"\n  VERDICT: {study['summary']}")
    for c in study["caveats"]:
        print(f"    · {c}")


def main():
    try:
        ticker = input("  Ticker [XYZ]: ").strip().upper()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not ticker:
        print("  No ticker entered.")
        return
    _print_study(pre_earnings_vol_study(ticker, interactive=sys.stdin.isatty()))


if __name__ == "__main__":
    main()
