"""
Options Trading — Put/Call OI + Volume Viewer
==============================================
Ad-hoc lookup of put/call OPEN-INTEREST and VOLUME by expiration date, read off the live
Tradier options chain. Run as needed — NOT part of the daily pipeline and NOT a model
feature.

  P/C OI    (per expiry) = sum(put open interest) / sum(call open interest)  (positioning)
  P/C Vol   (per expiry) = sum(put volume)        / sum(call volume)         (latest session)
  Call Vol / Put Vol     = raw latest-session volume (contracts traded each side)

Reading the ratios:
  < 1.0  -> more calls than puts  -> call-leaning / bullish positioning
  > 1.0  -> more puts than calls   -> put-leaning  / hedging or bearish positioning

OI is a STOCK (cumulative positioning; updates once/day at the prior close). Volume is a
FLOW (latest-session activity; resets each session; outside market hours it shows the last
completed session). Seeing both shows whether an OI reading is being actively traded or is
stale. Both are point-in-time snapshots of the CURRENT chain — future expiries are fully
visible because those contracts already trade today. (Arbitrary PAST dates are not
available — vendors don't serve historical OI.)

Usage (interactive, matches sizing.py):
    python -X utf8 pc_oi.py
      Ticker: QQQ
      Expiry filter (YYYY-MM-DD, blank = all): 2026-12-18

  - Blank expiry filter -> full term structure across every future expiry (+ TOTAL).
  - A date              -> just that expiry.

Piped (Windows — see CLAUDE.md):
    cmd /c "(echo QQQ && echo.) | python -X utf8 pc_oi.py"             # all expiries
    cmd /c "(echo QQQ && echo 2026-12-18) | python -X utf8 pc_oi.py"   # one expiry

Requirements: pandas, requests; a Tradier brokerage token (TRADIER_TOKEN env var or the
fallback in modules/tradier.py).
"""

import sys
import datetime

import pandas as pd

from modules.tradier import (
    TRADIER_TOKEN,
    get_current_price,
    get_expirations,
    get_chain,
)

# LEAPS tenor the framework actually trades (6-12 months). Rows in this window are
# flagged so positioning at the real holding horizon stands out from near-term weeklies.
LEAPS_MIN_DTE = 180
LEAPS_MAX_DTE = 365


# ─────────────────────────────────────────
# LABEL — same bands as entry.py OPTIONS-MARKET CHECK
# ─────────────────────────────────────────
def pc_label(pc):
    if pc is None:
        return "n/a"
    return ("heavy call interest" if pc < 0.70
            else "call-leaning"    if pc < 1.00
            else "put-leaning"     if pc < 1.30
            else "heavy put interest")


# ─────────────────────────────────────────
# FETCH — sum put/call OI and volume per future expiry off the live chain
# ─────────────────────────────────────────
def pc_by_expiry(ticker, date_filter=None):
    """
    Returns a list of dicts sorted by DTE:
      {expiry, dte, call_oi, put_oi, pc, call_vol, put_vol, pc_vol}
    One Tradier chain call per expiry — pass date_filter to limit to a single call.
    """
    today = datetime.date.today()

    expirations = get_expirations(ticker)
    if isinstance(expirations, str):       # Tradier returns a bare string for 1 expiry
        expirations = [expirations]

    future = sorted(
        (e, (datetime.date.fromisoformat(e) - today).days) for e in expirations
    )
    future = [(e, d) for e, d in future if d > 0]          # future expiries only

    if date_filter:
        match = [(e, d) for e, d in future if e == date_filter]
        if not match:
            print(f"  No future expiry on {date_filter}. Available future expiries:")
            print("    " + ", ".join(e for e, _ in future))
            return []
        future = match

    rows = []
    for exp, dte in future:
        print(f"  Fetching {exp} ({dte} DTE)...")
        try:
            chain = get_chain(ticker, exp)
        except Exception as e:
            print(f"  Skipping {exp}: {e}")
            continue
        if chain.empty or "open_interest" not in chain.columns or "option_type" not in chain.columns:
            continue

        is_call = chain["option_type"] == "call"
        is_put  = chain["option_type"] == "put"

        oi  = pd.to_numeric(chain["open_interest"], errors="coerce").fillna(0)
        vol = (pd.to_numeric(chain["volume"], errors="coerce").fillna(0)
               if "volume" in chain.columns else pd.Series(0, index=chain.index))

        call_oi  = float(oi[is_call].sum())
        put_oi   = float(oi[is_put].sum())
        call_vol = float(vol[is_call].sum())
        put_vol  = float(vol[is_put].sum())

        # Ratio guards: only the DENOMINATOR (call side) can break the division.
        # call_vol == 0 is a real state (illiquid / far-dated / untraded this session),
        # so emit None -> "n/a" rather than 0.0 (which would falsely read as call-heavy).
        # A zero NUMERATOR with calls > 0 is fine: ratio 0.0 = genuinely all-call activity.
        # The raw Call Vol / Put Vol columns still show the counts when the ratio is n/a.
        pc     = (put_oi  / call_oi)  if call_oi  > 0 else None
        pc_vol = (put_vol / call_vol) if call_vol > 0 else None

        rows.append({"expiry": exp, "dte": dte,
                     "call_oi": call_oi, "put_oi": put_oi, "pc": pc,
                     "call_vol": call_vol, "put_vol": put_vol, "pc_vol": pc_vol})
    return rows


# ─────────────────────────────────────────
# PRINT
# ─────────────────────────────────────────
def print_table(rows, ticker, current_price):
    w   = 114
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'═'*w}")
    print(f"  PUT/CALL — {ticker}  |  Price: ${current_price:.2f}  |  as of {now}")
    print(f"  P/C OI = put OI / call OI (positioning)   P/C Vol = put vol / call vol (latest session)")
    print(f"{'─'*w}")
    print(f"  {'Expiry':>10}  {'DTE':>4}  {'Call OI':>12}  {'Put OI':>12}  {'P/C OI':>6}  "
          f"{'Call Vol':>12}  {'Put Vol':>12}  {'P/C Vol':>7}  Positioning")
    print(f"  {'─'*110}")

    tot_call = tot_put = tot_call_vol = tot_put_vol = 0.0
    for r in rows:
        tot_call     += r["call_oi"]
        tot_put      += r["put_oi"]
        tot_call_vol += r["call_vol"]
        tot_put_vol  += r["put_vol"]
        pc_str  = f"{r['pc']:.2f}"     if r["pc"]     is not None else "n/a"
        pcv_str = f"{r['pc_vol']:.2f}" if r["pc_vol"] is not None else "n/a"
        leaps   = " *" if LEAPS_MIN_DTE <= r["dte"] <= LEAPS_MAX_DTE else ""
        print(f"  {r['expiry']:>10}  {r['dte']:>4}  {int(r['call_oi']):>12,}  "
              f"{int(r['put_oi']):>12,}  {pc_str:>6}  {int(r['call_vol']):>12,}  "
              f"{int(r['put_vol']):>12,}  {pcv_str:>7}  {pc_label(r['pc'])}{leaps}")

    if len(rows) > 1:
        tot_pc      = (tot_put / tot_call) if tot_call > 0 else None
        tot_pcv     = (tot_put_vol / tot_call_vol) if tot_call_vol > 0 else None
        tot_pc_str  = f"{tot_pc:.2f}"  if tot_pc  is not None else "n/a"
        tot_pcv_str = f"{tot_pcv:.2f}" if tot_pcv is not None else "n/a"
        print(f"  {'─'*110}")
        print(f"  {'TOTAL':>10}  {'':>4}  {int(tot_call):>12,}  {int(tot_put):>12,}  "
              f"{tot_pc_str:>6}  {int(tot_call_vol):>12,}  {int(tot_put_vol):>12,}  "
              f"{tot_pcv_str:>7}  {pc_label(tot_pc)}")

    print(f"\n  {'─'*110}")
    print(f"  Bands (Positioning uses P/C OI):  < 0.70 heavy call | < 1.00 call-leaning | "
          f"< 1.30 put-leaning | >= 1.30 heavy put")
    print(f"  * = LEAPS tenor ({LEAPS_MIN_DTE}-{LEAPS_MAX_DTE} DTE) — the framework's target horizon")
    print(f"  Call Vol / Put Vol = raw latest-session volume (contracts traded).  P/C Vol 'n/a' = zero call volume.")
    print(f"  OI = cumulative positioning; Volume = latest-session flow (resets each session, partial intraday).")
    print(f"{'═'*w}\n")


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    if TRADIER_TOKEN == "YOUR_TOKEN_HERE":
        print("  Set TRADIER_TOKEN (env var or modules/tradier.py) before running.")
        sys.exit(1)

    try:
        ticker = input("  Ticker [XYZ]: ").strip().upper()
    except KeyboardInterrupt:
        print()
        sys.exit(0)
    if not ticker:
        print("  No ticker entered.")
        sys.exit(1)

    date_filter = input("  Expiry filter (YYYY-MM-DD, blank = all): ").strip()
    if date_filter:
        try:
            datetime.date.fromisoformat(date_filter)
        except ValueError:
            print(f"  Invalid date '{date_filter}' — use YYYY-MM-DD.")
            sys.exit(1)

    print(f"\n  Fetching {ticker} from Tradier...")
    try:
        current_price = get_current_price(ticker)
        print(f"  Current price: ${current_price:.2f}")
    except Exception as e:
        print(f"  Error fetching price: {e}")
        sys.exit(1)

    rows = pc_by_expiry(ticker, date_filter or None)
    if not rows:
        print("  No open-interest data found.")
        sys.exit(0)

    print_table(rows, ticker, current_price)
