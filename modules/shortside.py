"""
Short-opportunity lens (S65) — the tape read through a short-seller's eyes. CONTEXT, not a signal.

Why this exists: the report's bearish evidence was scattered (drawdown factors, squeeze
counters, sector laggards) and the --thesis bearish overlay simply relabeled the drawdown list
as short "confirmations" — including VIX stress and term backwardation, the two conditions S21
documents as historically contrarian-BUY for this framework. This module assembles a coherent
two-sided short read with those guardrails built in.

HARD GUARDRAILS (encoded, not just documented — the caveats print unconditionally):
  - S28: the put-side backtest was a cross-ticker NO-GO — bearish signals on secular-uptrend
    names catch dips that mean-revert UP. There is NO backtested short edge here; this section
    characterizes the tape so the user can time THEIR OWN short/hedge, nothing more.
  - S21: VIX stress / backwardation appear on the AGAINST side, explicitly labeled
    contrarian-BUY conditions (bounce fuel), never as short confirmations.
  - S43: nothing here feeds the risk-scorecard tallies; setupcheck.py stays untouched (its
    long-framed rows keep a stable meaning for snapshots/diff/self-score) — the short-side
    checklist inversion lives HERE.

Crowding: a short is a very different trade on a crowded name (squeeze fuel) than an uncrowded
one — when --squeeze data is present its fuel/counter read is folded into a crowding verdict;
without it the state is explicitly "unknown" (this module never fetches — network stays opt-in).

PURE + display-only: no network, offline-testable, never a model feature (S20/S31).
"""

# must match the factor strings built in structure.rally_drawdown_risk (guarded by test)
S21_CONTRA_PREFIXES = ("VIX stress regime", "term backwardation")

CROWDED_FUEL_MIN = 2          # ≥2 squeeze-fuel factors → crowded (squeeze danger)
RS_LAG_TFS = ("1D", "1W", "1M")

CAVEATS = [
    "S28 GUARDRAIL: this project has NO backtested short edge — the put-side backtest failed "
    "cross-ticker (secular-uptrend names mean-revert UP and crush shorts at 6mo). This section "
    "characterizes the tape; it is NOT a signal.",
    "S21: VIX stress / term backwardation / washout conditions are historically contrarian-BUY "
    "in this framework — they appear above as counter-evidence (bounce fuel), never as short "
    "confirmations.",
    "squeeze fuel ≠ ignition, and uncrowded ≠ safe — sizing and a hard stop are yours; borrow "
    "cost and dividend liability are not modeled here.",
]


def is_s21_contrarian(factor):
    """True when a risk/thesis factor string names an S21 contrarian-buy condition."""
    return isinstance(factor, str) and factor.startswith(S21_CONTRA_PREFIXES)


def _crowding(sqz_read):
    """Squeeze fuel/counter → the short-crowding verdict. Pure."""
    if not sqz_read:
        return {"state": "unknown",
                "lines": ["run --squeeze for the crowding read (days-to-cover, short-volume "
                          "percentile, shorts-underwater) — a crowded short is a squeeze "
                          "waiting for ignition"]}
    fuel = sqz_read.get("fuel") or []
    counter = sqz_read.get("counter") or []
    if len(fuel) >= CROWDED_FUEL_MIN:
        return {"state": "crowded",
                "lines": [f"CROWDED short — {len(fuel)} squeeze-fuel factors: entry timing "
                          f"matters more than thesis"] + [f"fuel: {f}" for f in fuel]}
    if counter:
        return {"state": "uncrowded",
                "lines": ["uncrowded short — little forced-covering fuel against you"]
                         + [f"counter: {c}" for c in counter]}
    return {"state": "neutral", "lines": ["no strong crowding read either way"]}


def short_setup(reads, profile=None, ctx=None, divergences=None, rs=None,
                sectors=None, sqz_read=None, gex=None, street=None,
                lvn_below_pct=None, regime=None):
    """PURE: the lens' existing reads → a two-sided short-side view.

    → {'for': [...], 'against': [...], 'crowding': {state, lines}, 'checklist':
       [(label, mark, detail)], 'net': str, 'caveats': [...]}. Every input optional;
    `regime` = risk['regime'] (trend_regime result); `sqz_read` = squeeze['read'];
    `lvn_below_pct` = levels.nearest_lvn_below. Offline-testable, never raises."""
    reads = reads or {}
    sfor, against = [], []
    d = reads.get("1D") or {}
    w = reads.get("1W") or {}
    m = reads.get("1M") or {}
    trends = [t.get("trend") for t in (d, w, m) if t.get("ok")]

    # ── FOR (the tape favors downside) ──
    if regime and regime.get("state") == "down":
        sfor.append(f"{regime.get('label', 'ESTABLISHED DOWNTREND')} — "
                    + " · ".join(regime.get("why") or []))
    elif len(trends) == 3 and all(t == "down" for t in trends):
        sfor.append("1M+1W+1D trends aligned down")
    for tf in ("1D", "1W"):
        v = (reads.get(tf) or {}).get("_vol") or {}
        if v.get("distribution"):
            sfor.append(f"{tf} distribution — price down on rising volume")
    for tf, (kind, why) in (divergences or {}).items():
        if kind == "bearish":
            sfor.append(f"{tf} bearish divergence ({why})")
    if profile and profile.get("price_location") == "below_value":
        sfor.append("price BELOW value area — prior acceptance overhead acts as resistance")
    if lvn_below_pct is not None:
        sfor.append(f"thin-volume air {lvn_below_pct:.0%} below (LVN) — little support memory "
                    f"on a breakdown")
    r = (rs or {}).get("rs") or {}
    if r and all(v < 0 for v in r.values()):
        sfor.append(f"lagging {rs.get('bench', 'benchmark')} on "
                    + " and ".join(f"{h}d" for h in sorted(r)))
    own = (sectors or {}).get("own")
    if own:
        row = next((x for x in (sectors.get("rows") or []) if x.get("sym") == own), None)
        if row and row.get("tag") == "lagging":
            sfor.append(f"own sector {own} lagging SPY (rank {row.get('rank', '?')}"
                        f"/{len(sectors.get('rows') or [])})")
    if gex:
        if (gex.get("net_gex") or 0) < 0:
            sfor.append("dealers short gamma — hedging AMPLIFIES moves (both ways)")
        zg, spot = gex.get("zero_gamma"), gex.get("spot")
        if zg is not None and spot is not None and spot < zg:
            sfor.append(f"spot below the zero-gamma flip (~{zg:.0f}) — amplification regime")
    ud = (street or {}).get("ud") or {}
    if ud and ud.get("n_down", 0) > ud.get("n_up", 0):
        sfor.append(f"street: {ud['n_down']} downgrades vs {ud['n_up']} upgrades "
                    f"({ud.get('window_days', 90)}d)")
    if (street or {}).get("rev_net") == "estimates drifting DOWN":
        sfor.append("EPS estimates drifting DOWN (30d revisions)")

    # ── AGAINST (bounce / squeeze / fighting-the-framework risk) ──
    if regime and regime.get("state") == "up":
        against.append(f"{regime.get('label', 'ESTABLISHED UPTREND')} — shorting against the "
                       f"documented mean-reversion edge (S28)")
    elif len(trends) == 3 and all(t == "up" for t in trends):
        against.append("1M+1W+1D trends aligned up — fighting the tape")
    for tf in ("1W", "1M"):
        t = reads.get(tf) or {}
        if t.get("ok") and t.get("rsi_state") == "oversold":
            against.append(f"{tf} oversold (RSI {t.get('rsi', 0):.0f}) — bounce risk")
    dist = d.get("dist_ma20_pct")
    if d.get("ok") and dist is not None and dist < -0.08:
        against.append(f"daily {dist:+.0%} below MA20 — snap-back zone, chasing weakness")
    if d.get("ok") and d.get("range_pos", 0.5) < 0.1:
        against.append("near bottom of 1y range — the washout is behind, not ahead")
    if profile and profile.get("near_hvn_below"):
        against.append(f"volume HVN support ~{profile['near_hvn_below']:.2f} just below")
    if ctx:
        if ctx.get("regime") == "stress":
            against.append("VIX stress regime — S21: historically contrarian-BUY here; "
                           "bounce fuel, not short confirmation")
        for g in ctx.get("gauges") or []:
            if g.get("name") == "Term structure" and (g.get("value") or 0) >= 1.05:
                against.append("term backwardation — S21: stress already priced; historically "
                               "a contrarian-BUY condition, weak short evidence")

    crowding = _crowding(sqz_read)
    if crowding["state"] == "crowded":
        against.append("short side is CROWDED (squeeze fuel present) — see crowding read")

    # ── checklist — the short-side inversion of the long setup rows (lives here, not in
    # setupcheck.py: the main SETUP CHECK's meaning stays stable for snapshots/diff/scoring) ──
    checklist = []
    if len(trends) == 3 and all(t == "down" for t in trends):
        checklist.append(("HTF alignment", "✓", "1M+1W+1D aligned DOWN — short-side tape"))
    elif len(trends) == 3 and all(t == "up" for t in trends):
        checklist.append(("HTF alignment", "✗", "aligned UP — fighting every timeframe"))
    elif trends:
        checklist.append(("HTF alignment", "–", "mixed timeframes"))
    rsi_st = d.get("rsi_state")
    if rsi_st == "overbought":
        checklist.append(("Momentum room", "✓",
                          f"daily overbought (RSI {d.get('rsi', 0):.0f}) — room to fall"))
    elif rsi_st == "oversold":
        checklist.append(("Momentum room", "✗",
                          f"daily oversold (RSI {d.get('rsi', 0):.0f}) — chasing weakness"))
    elif rsi_st:
        checklist.append(("Momentum room", "–", f"daily RSI {d.get('rsi', 0):.0f} neutral"))
    tag = ((d.get("_vol") or {}).get("tag"))
    if tag == "dn-distrib":
        checklist.append(("Volume confirms", "✓", "distribution — selling pressure confirmed"))
    elif tag == "up-confirmed":
        checklist.append(("Volume confirms", "✗", "healthy accumulation — no seller in charge"))
    elif tag == "dn-exhaust":
        checklist.append(("Volume confirms", "–", "down on fading volume — exhaustion, "
                                                  "late to press"))
    elif tag:
        checklist.append(("Volume confirms", "–", tag))
    if r:
        if all(v < 0 for v in r.values()):
            checklist.append(("Relative strength", "✓",
                              f"lagging {rs.get('bench', 'benchmark')} — weak name"))
        elif all(v > 0 for v in r.values()):
            checklist.append(("Relative strength", "✗", "leading the benchmark — strong name"))
        else:
            checklist.append(("Relative strength", "–", "mixed vs benchmark"))

    lean = ("short-favorable" if len(sfor) > len(against)
            else "counter-evidence dominates" if len(against) > len(sfor)
            else "balanced")
    return {"for": sfor, "against": against, "crowding": crowding, "checklist": checklist,
            "net": f"{lean}  ({len(sfor)} for vs {len(against)} against)",
            "caveats": list(CAVEATS)}
