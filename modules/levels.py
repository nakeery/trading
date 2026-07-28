"""
Price-level ladder (S65) — one distance-from-spot sorted view of every level the lens knows.

The report computes levels in four unrelated sections (volume profile POC/value-area/HVN/LVN,
GEX walls/zero-gamma/max-pain, the expected-move band, the 52-week range) and silently drops
others (numeric MA20/50/200 values — read_timeframe exposed only booleans before S65; prior-day
H/L/C; the user's --level, which was never compared to anything). Entry timing is exactly the
question "what is price about to run into" — this module merges everything into ONE ladder:

  - each level tagged by source, sorted by |distance from spot|
  - levels within ±CONFLUENCE_PCT of each other cluster into a confluence ZONE (a POC sitting
    on the weekly MA50 on a GEX call wall is a materially stronger level than any one alone)
  - nearest support / nearest resistance called out
  - the user's --level annotated with distance, side, and zone membership

PURE + display-only: no network, no model features (S20/S31), not a risk-scorecard factor
(S43). Every input is optional — the ladder renders from whatever the report actually computed
(gex/em absent unless --gex/--vol ran; historical inputs make it as-of-valid for free).

`nearest_lvn_below` is the below-spot mirror of shortint's LVN-air-overhead squeeze factor
(the only path-of-least-resistance read in the stack was overhead-only) — consumed by the
S65 short lens.
"""

CONFLUENCE_PCT = 0.005    # levels within ±0.5% of each other merge into one zone
MAX_SIDE = 6              # display cap per side (full list still returned)


def collect_levels(spot, profile=None, gex=None, em=None, reads=None,
                   range52=None, prior_day=None, user_level=None):
    """→ [(price, tag)] — every known level, deduped by (rounded price, tag). All inputs
    optional/None-tolerant; bad values are skipped, never raised on. Offline-testable."""
    out = []

    def add(price, tag):
        try:
            p = float(price)
        except (TypeError, ValueError):
            return
        if p > 0:
            out.append((p, tag))

    if profile:
        add(profile.get("poc"), "POC")
        add(profile.get("va_low"), "value-area low")
        add(profile.get("va_high"), "value-area high")
        for h in profile.get("hvns") or []:
            add(h, "HVN")
        for l in profile.get("lvns") or []:
            add(l, "LVN")
    if gex:
        add(gex.get("call_wall"), "GEX call wall")
        add(gex.get("put_wall"), "GEX put wall")
        add(gex.get("zero_gamma"), "zero-gamma flip")
        add((gex.get("max_pain") or {}).get("strike"), "max pain")
    if em:
        add(em.get("lo"), "expected-move low")
        add(em.get("hi"), "expected-move high")
    for tf in ("1D", "1W"):
        r = (reads or {}).get(tf) or {}
        if r.get("ok"):
            for key, name in (("ma20", "MA20"), ("ma50", "MA50"), ("ma200", "MA200")):
                add(r.get(key), f"{name} {tf}")
    if range52:
        add(range52.get("hi"), "52w high")
        add(range52.get("lo"), "52w low")
    if prior_day:
        add(prior_day.get("high"), "prior-day high")
        add(prior_day.get("low"), "prior-day low")
        add(prior_day.get("close"), "prior close")
    if user_level is not None:
        add(user_level, "YOUR LEVEL")

    seen, dedup = set(), []
    for p, tag in out:
        key = (round(p, 4), tag)
        if key not in seen:
            seen.add(key)
            dedup.append((p, tag))
    return dedup


def build_ladder(spot, levels, confluence_pct=CONFLUENCE_PCT):
    """PURE: spot + [(price, tag)] → the ladder dict, or None when there's nothing to build.

    {'spot', 'levels': [{price, dist_pct, tags, side, zone}] sorted by |dist_pct|,
     'zones': [{lo, hi, mid, tags, n}]  (clusters of ≥2 distinct-tag levels within confluence_pct),
     'nearest_support', 'nearest_resistance',    # nearest level-dict strictly below / above spot
     'user_level': {price, dist_pct, side, zone} | None}

    Levels within confluence_pct of each other are merged into ONE row carrying every tag
    (mid-price of the cluster) — the row IS the zone when it holds ≥2 tags."""
    if spot is None or not levels:
        return None
    try:
        spot = float(spot)
    except (TypeError, ValueError):
        return None
    if spot <= 0:
        return None

    # greedy cluster on sorted prices: extend while the next price stays within
    # confluence_pct of the cluster's LOW anchor (stable, order-independent)
    ordered = sorted(levels, key=lambda t: t[0])
    clusters, cur = [], [ordered[0]]
    for p, tag in ordered[1:]:
        if p / cur[0][0] - 1 <= confluence_pct:
            cur.append((p, tag))
        else:
            clusters.append(cur)
            cur = [(p, tag)]
    clusters.append(cur)

    rows, zones, user = [], [], None
    for ci, cluster in enumerate(clusters):
        prices = [p for p, _ in cluster]
        tags = []
        for _, tag in cluster:                      # preserve order, dedupe
            if tag not in tags:
                tags.append(tag)
        mid = sum(prices) / len(prices)
        zone = None
        if len(tags) >= 2:
            zone = len(zones)
            zones.append({"lo": min(prices), "hi": max(prices), "mid": mid,
                          "tags": tags, "n": len(tags)})
        row = {"price": mid, "dist_pct": mid / spot - 1.0, "tags": tags,
               "side": "above" if mid >= spot else "below", "zone": zone}
        rows.append(row)
        if "YOUR LEVEL" in tags:
            user_price = next(p for p, t in cluster if t == "YOUR LEVEL")
            others = [t for t in tags if t != "YOUR LEVEL"]
            user = {"price": user_price, "dist_pct": user_price / spot - 1.0,
                    "side": "above" if user_price >= spot else "below",
                    "zone": zone, "confluence": others}

    rows.sort(key=lambda r: abs(r["dist_pct"]))
    sup = next((r for r in rows if r["side"] == "below"), None)
    res = next((r for r in rows if r["side"] == "above"), None)
    return {"spot": spot, "levels": rows, "zones": zones,
            "nearest_support": sup, "nearest_resistance": res, "user_level": user}


def nearest_lvn_below(profile, spot, near_pct=0.08):
    """PURE: nearest LVN strictly below spot within −near_pct → signed pct (negative), else
    None. The below-spot mirror of shortint's LVN-air-overhead factor: thin volume UNDER price
    = little support memory — the path of least resistance for a breakdown."""
    if not profile or spot is None:
        return None
    try:
        spot = float(spot)
    except (TypeError, ValueError):
        return None
    if spot <= 0:
        return None
    cands = [l for l in (profile.get("lvns") or [])
             if spot * (1 - near_pct) <= l < spot]
    if not cands:
        return None
    return max(cands) / spot - 1.0
