"""
Market Context — consolidated fear / positioning surface (backlog #4, S29)
==========================================================================
A quick, standalone read of where a ticker's options/vol sentiment sits RIGHT NOW, relative to
its own trailing-year history — without running the full entry.py model pipeline. Consolidates
indicators the framework already produces:

  OPTIONS POSITIONING (per-ticker, harvested in indicators CSV):
    IV/HV ratio, ATM IV (30d), 25Δ skew, term structure, Put/Call OI
  VOLATILITY (HV-derived, full history):
    HV-20, IV Rank, IV Percentile
  MARKET (live VIX complex):
    VIX, VIX9D/VIX, VIX/VIX3M  + regime (calm / normal / stress)

Each gauge shows its value, band label, and trailing-1y percentile (where history allows), plus
a one-line NET read. This is human-decision CONTEXT (the S22 principle) — not a model feature and
not a signal. The S21 reminder is baked into the net read: in this framework's lens, stress is a
contrarian BUY for STRONG ENTRY, not a sell.

Usage:
    python -X utf8 market_context.py                 # console table (prompts for ticker)
    python -X utf8 market_context.py --graphical      # + matplotlib panel popup + PNG
    python -X utf8 market_context.py --save-only ...   # PNG only (headless), no popup
    python -X utf8 market_context.py --no-vix          # skip the live VIX download (offline)

Piped (Windows — see CLAUDE.md):
    cmd /c "(echo AMD) | python -X utf8 market_context.py"

Notes:
  - Options-gauge percentiles need IV history (AMD/NVDA ~1y); QQQ/SOFI/LYFT were wiped pre-S23 →
    snapshot only (no percentile) until re-backfilled. HV-rank + VIX percentiles work everywhere.
  - Requires data/{ticker}_indicators.csv (run indicators.py first). matplotlib, numpy, pandas.
"""

import argparse
import os
import sys

import matplotlib
if "--save-only" in sys.argv:        # headless / verification — force non-GUI backend
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm

from modules.sentiment import gather_context

DATA_DIR = "data"
GROUP_NAMES = {
    "OPTIONS": "OPTIONS POSITIONING",
    "VOL":     "VOLATILITY (HV-derived)",
    "MARKET":  "MARKET (VIX complex)",
}


# ─────────────────────────────────────────
# CONSOLE
# ─────────────────────────────────────────
def print_console(ctx):
    w = 74
    print(f"\n{'═'*w}")
    print(f"  MARKET CONTEXT — {ctx['ticker']}  |  as of {ctx['as_of']}  |  regime: {ctx['regime'].upper()}")
    print(f"{'─'*w}")
    print(f"  {'Gauge':<22}{'Value':>9}  {'Label':<22}{'%ile(1y)':>9}")
    print(f"  {'─'*66}")
    last_group = None
    for g in ctx["gauges"]:
        if g["group"] != last_group:
            print(f"  {GROUP_NAMES.get(g['group'], g['group'])}")
            last_group = g["group"]
        val = g["fmt"].format(g["value"])
        pct = f"{int(round(g['pct']*100))}" if g["pct"] is not None else "—"
        print(f"    {g['name']:<20}{val:>9}  {g['label']:<22}{pct:>9}")
    print(f"  {'─'*66}")
    print(f"  NET: {ctx['net']}")
    for n in ctx["notes"]:
        print(f"  note: {n}")
    print(f"{'═'*w}\n")


# ─────────────────────────────────────────
# GRAPHICAL  (horizontal trailing-1y percentile bars; high = more fear/vol = red)
# ─────────────────────────────────────────
def render_graphical(ctx, out_path, show):
    bars = [g for g in ctx["gauges"] if g.get("pct") is not None]
    if not bars:
        print("  (no gauges with percentile history — skipping graphical panel)")
        return
    fig, ax = plt.subplots(figsize=(10, max(3.0, 0.55 * len(bars) + 2.0)))
    pcts   = [g["pct"] * 100 for g in bars]
    colors = [cm.RdYlGn_r(g["pct"]) for g in bars]   # high percentile -> red (more fear/vol)
    y = list(range(len(bars)))
    ax.barh(y, pcts, color=colors, edgecolor="#888888", height=0.62)
    ax.set_xlim(0, 100)
    ax.set_yticks(y)
    ax.set_yticklabels([g["name"] for g in bars])
    ax.invert_yaxis()
    ax.set_xlabel("trailing 1-year percentile (high = elevated vs own history)")
    ax.axvline(50, color="#bbbbbb", ls="--", lw=0.8)
    for i, g in enumerate(bars):
        txt = f"{g['fmt'].format(g['value'])}  {g['label']}".strip()
        if g["pct"] < 0.78:
            ax.text(g["pct"] * 100 + 1.5, i, txt, va="center", ha="left", fontsize=8)
        else:
            ax.text(g["pct"] * 100 - 1.5, i, txt, va="center", ha="right", fontsize=8, color="white")

    ax.set_title(f"Market Context — {ctx['ticker']}   ·   {ctx['as_of']}   ·   "
                 f"regime: {ctx['regime'].upper()}", fontweight="bold")
    net_color = "#c0392b" if ctx["net"].startswith("elevated") else "#27ae60"
    fig.text(0.5, 0.01, "NET: " + ctx["net"], ha="center", va="bottom", fontsize=8,
             color=net_color, wrap=True)
    fig.tight_layout(rect=[0, 0.08, 1, 1])

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    print(f"  Saved {out_path}")
    if show:
        plt.show()


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Consolidated market-context (fear/positioning) surface.")
    parser.add_argument("--graphical", action="store_true", help="Also render a matplotlib panel + PNG.")
    parser.add_argument("--save-only", action="store_true", help="With --graphical: save the PNG, no popup.")
    parser.add_argument("--no-vix", action="store_true", help="Skip the live VIX-complex download (offline).")
    parser.add_argument("--data-dir", default=DATA_DIR, help="Indicators CSV directory (default: data).")
    parser.add_argument("--out", default=None, help="PNG output path (default: data/{ticker}_market_context.png).")
    args = parser.parse_args()

    try:
        ticker = input("  Ticker [XYZ]: ").strip().upper()
    except KeyboardInterrupt:
        print()
        sys.exit(0)
    if not ticker:
        print("  No ticker entered.")
        sys.exit(1)

    try:
        ctx = gather_context(ticker, data_dir=args.data_dir, with_vix=not args.no_vix)
    except FileNotFoundError:
        print(f"  No indicators CSV for {ticker} in {args.data_dir}/ — run indicators.py first.")
        sys.exit(1)

    # CNN Fear & Greed (S41) — market-level sentiment gauge, cached ~6h; best-effort.
    try:
        from modules.fng import fetch_fng
        fng = fetch_fng(data_dir=args.data_dir)
        if fng and fng.get("score") is not None:
            ctx["gauges"].append({"group": "MARKET", "name": "Fear & Greed (CNN)",
                                  "value": fng["score"], "fmt": "{:.0f}",
                                  "label": fng.get("rating", ""), "pct": fng.get("pct")})
            if "fear" in (fng.get("rating") or ""):
                ctx["notes"].append("F&G in fear territory — S21: for this framework's signals, "
                                    "stress/fear has historically been a contrarian BUY, not a sell.")
    except Exception:
        pass

    # Equal-weight breadth (S45) — RSP−SPY / QQQE−QQQ 20d spread, cached ~6h; best-effort.
    # Context only (never a feature, not a risk factor) — narrow = fragility tell, not a sell.
    try:
        from modules.breadth import fetch_breadth
        br = fetch_breadth(data_dir=args.data_dir)
        narrow = []
        for lbl, d in ((br or {}).get("pairs") or {}).items():
            ctx["gauges"].append({"group": "MARKET", "name": f"Breadth {lbl} 20d",  # ≤20 chars (S40 convention)
                                  "value": d["rel_20d"], "fmt": "{:+.1%}",
                                  "label": d["tag"], "pct": d.get("pct")})
            if d["tag"] == "narrow" and (d.get("pct") is None or d["pct"] <= 0.25):
                narrow.append(lbl)
        if narrow:
            ctx["notes"].append(f"narrow breadth ({', '.join(narrow)}) — mega-cap-led tape; "
                                "average-stock entries face a weaker tape than the headline "
                                "index implies.")
    except Exception:
        pass

    print_console(ctx)

    if args.graphical:
        out = args.out or os.path.join(args.data_dir, f"{ticker.lower()}_market_context.png")
        render_graphical(ctx, out, show=not args.save_only)
