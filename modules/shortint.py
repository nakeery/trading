"""
Short positioning / squeeze context (S41) — backs lens.py `--squeeze`.

CONTEXT ONLY, never a prediction or a model feature (LENS ethos): a transparent two-sided
fuel-vs-counter scorecard in the style of structure.rally_drawdown_risk / volsetup.vol_setup.
Squeeze FUEL (crowded shorts, forced-covering mechanics) is a necessary but not sufficient
condition — it still needs a spark, and crowded shorts are sometimes right.

Sources (both free; probed live 2026-07-02):
  - NASDAQ short-interest API (unofficial, browser-UA-gated): the bi-monthly FINRA-settled short
    interest, avg daily share volume, and days-to-cover. Settles twice a month with a ~2-week
    dissemination lag — the caveat is printed with the settle date.
  - FINRA Reg SHO daily short-volume files (official CDN, no auth): per-symbol daily short volume /
    total volume — the DAILY pulse between settlements. NB short VOLUME includes market-making
    shorting (~50% of volume is a normal baseline), so the trailing percentile is the read,
    not the raw level.

Caching: NASDAQ payload per ticker, session-stale (reuses pc_oi.cache_stale). FINRA history per
ticker as an incremental date→(short,total) map — first run fetches ~SVR_SESSIONS small CDN files,
after that one file per new session. Best-effort throughout: never raises.
"""

import datetime
import json
import os
import time

import pandas as pd
import requests

from modules.pc_oi import cache_stale
from modules.sentiment import percentile_of

CACHE_SUBDIR = "shortint_cache"
NASDAQ_URL = "https://api.nasdaq.com/api/quote/{sym}/short-interest?assetClass=stocks"
FINRA_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{d}.txt"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
           "Accept": "application/json, text/plain, */*"}

SVR_SESSIONS = 90       # trailing sessions of short-volume history (percentile needs ≥63 real obs)
FINRA_GRACE_BD = 3      # a missing file this recent may simply not be published yet — don't tombstone

# scorecard bands
DTC_HIGH, DTC_EXTREME, DTC_LOW = 8.0, 15.0, 3.0   # days-to-cover: elevated / extreme / low
SI_CHG_BAND = 0.10                                 # ±10% settlement-over-settlement SI change
SVR_HIGH_PCT, SVR_LOW_PCT = 0.80, 0.20             # short-volume-ratio trailing percentile bands
UNDERWATER_PCT, UNDERWATER_CHG = 0.60, 0.05        # elevated shorting INTO a ≥5% 5-session rally
THRUST_CHG, THRUST_RVOL = 0.03, 1.5                # covering-style thrust: +3% day on 1.5x volume
CALL_FLOW_FRAC = 0.5                               # session P/C vol ≤ half of P/C OI = upside chase
LVN_NEAR_PCT = 0.08                                # thin-volume air within +8% overhead


def _cache_path(ticker, kind, data_dir):
    return os.path.join(data_dir, CACHE_SUBDIR, f"{ticker.lower()}_{kind}.json")


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_json(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Parsers (pure — unit-testable offline)
# ─────────────────────────────────────────────────────────────────────────────
def parse_si_payload(payload):
    """NASDAQ short-interest JSON → [{settle_date(iso), interest, adv, dtc}, …] newest-first.
    Numbers arrive comma-grouped; dates as MM/DD/YYYY. Bad rows are skipped."""
    rows = ((((payload or {}).get("data") or {}).get("shortInterestTable") or {}).get("rows")) or []
    out = []
    for r in rows:
        try:
            d = datetime.datetime.strptime(str(r.get("settlementDate")), "%m/%d/%Y").date()
            out.append({"settle_date": d.isoformat(),
                        "interest": float(str(r.get("interest")).replace(",", "")),
                        "adv": float(str(r.get("avgDailyShareVolume")).replace(",", "")),
                        "dtc": float(r.get("daysToCover"))})
        except Exception:
            continue
    return out


def parse_finra_text(text, ticker):
    """One FINRA Reg SHO daily file → (short_volume, total_volume) for `ticker`, or None.
    Format: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market"""
    needle = f"|{ticker.upper()}|"
    for line in text.splitlines():
        if needle not in line:
            continue
        parts = line.split("|")
        if len(parts) >= 5 and parts[1] == ticker.upper():
            try:
                return float(parts[2]), float(parts[4])
            except ValueError:
                return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Fetchers (network, cached, best-effort)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_short_interest(ticker, data_dir="data"):
    """Bi-monthly short-interest rows (newest-first) from the NASDAQ API, cached session-stale.
    On any failure serves the cached rows regardless of age; None only when nothing is available."""
    path = _cache_path(ticker, "si", data_dir)
    cache = _load_json(path)
    if cache and not cache_stale(cache):
        return cache.get("rows") or None
    try:
        r = requests.get(NASDAQ_URL.format(sym=ticker.upper()), headers=HEADERS, timeout=15)
        r.raise_for_status()
        rows = parse_si_payload(r.json())
        if rows:
            _save_json(path, {"as_of": time.time(), "rows": rows})
            return rows
    except Exception:
        pass
    return (cache or {}).get("rows") or None


def fetch_short_volume(ticker, data_dir="data", sessions=SVR_SESSIONS):
    """Daily short-volume-ratio history from FINRA Reg SHO files, incrementally cached per ticker.
    Returns a date-indexed pd.Series of short/total (0..1), or None. A date can be cached as:
    [short, total] (data), "absent" (holiday / symbol missing — never refetched), or simply not
    present (recent 404 inside the grace window — retried next run: the file may publish later)."""
    path = _cache_path(ticker, "svr", data_dir)
    cache = _load_json(path) or {}
    days = cache.get("days") or {}

    today = pd.Timestamp.today().normalize()
    wanted = pd.bdate_range(end=today, periods=sessions)
    grace_floor = wanted[-min(FINRA_GRACE_BD, len(wanted))]
    fetched = 0
    for ts in wanted:
        key = ts.strftime("%Y%m%d")
        if key in days:
            continue
        try:
            r = requests.get(FINRA_URL.format(d=key), headers=HEADERS, timeout=15)
            if r.status_code == 404:
                if ts < grace_floor:
                    days[key] = "absent"           # holiday — tombstone so we never re-ask
                continue                           # recent: may not be published yet
            r.raise_for_status()
            row = parse_finra_text(r.text, ticker)
            days[key] = list(row) if row else "absent"
            fetched += 1
        except Exception:
            continue                               # transient — retry next run
    if fetched:
        _save_json(path, {"days": days})

    vals = {}
    for key, v in days.items():
        if isinstance(v, list) and len(v) == 2 and v[1]:
            ts = pd.Timestamp(key)
            if ts in wanted:
                vals[ts] = v[0] / v[1]
    if not vals:
        return None
    return pd.Series(vals).sort_index()


# ─────────────────────────────────────────────────────────────────────────────
# Scorecard (pure — unit-testable offline)
# ─────────────────────────────────────────────────────────────────────────────
def squeeze_read(dtc=None, si_chg=None, settle_date=None, settle_age=None,
                 svr_now=None, svr_pct=None, svr_n=None, chg_1d=None, chg_5d=None, rvol=None,
                 pc_oi=None, pc_vol=None, lvn_above_pct=None):
    """Two-sided squeeze-fuel scorecard. Every firing factor is listed; NET is a count, not a
    probability. All inputs optional — absent data simply doesn't produce a factor."""
    fuel, counter = [], []

    if dtc is not None:
        if dtc >= DTC_EXTREME:
            fuel.append(f"days-to-cover {dtc:.1f} — EXTREME (≥{DTC_EXTREME:.0f}): shorts need "
                        f"~{dtc:.0f} sessions of avg volume to exit")
        elif dtc >= DTC_HIGH:
            fuel.append(f"days-to-cover {dtc:.1f} — elevated (≥{DTC_HIGH:.0f})")
        elif dtc <= DTC_LOW:
            counter.append(f"days-to-cover {dtc:.1f} — low; little forced-covering fuel")

    if si_chg is not None:
        if si_chg >= SI_CHG_BAND:
            fuel.append(f"short interest {si_chg:+.0%} vs prior settlement — shorts ADDING")
        elif si_chg <= -SI_CHG_BAND:
            counter.append(f"short interest {si_chg:+.0%} vs prior settlement — covering underway")

    if svr_pct is not None and svr_now is not None:
        n = f" of {svr_n} sessions" if svr_n else ""
        if svr_pct >= SVR_HIGH_PCT:
            fuel.append(f"short-volume ratio {svr_now:.0%} at {svr_pct:.0%}ile{n} — heavy recent shorting")
        elif svr_pct <= SVR_LOW_PCT:
            counter.append(f"short-volume ratio {svr_now:.0%} at {svr_pct:.0%}ile{n} — pressure subdued")
        if svr_pct >= UNDERWATER_PCT and chg_5d is not None and chg_5d >= UNDERWATER_CHG:
            fuel.append(f"elevated short volume INTO a {chg_5d:+.0%} 5-session rally — fresh shorts underwater")

    if chg_1d is not None and rvol is not None and chg_1d >= THRUST_CHG and rvol >= THRUST_RVOL:
        fuel.append(f"today {chg_1d:+.1%} on {rvol:.1f}x volume — covering-style thrust")

    if pc_vol is not None and pc_oi is not None and pc_oi > 0 and pc_vol <= CALL_FLOW_FRAC * pc_oi:
        fuel.append(f"session option flow call-heavy vs positioning (P/C vol {pc_vol:.2f} "
                    f"vs OI {pc_oi:.2f}) — upside chase")

    if lvn_above_pct is not None and 0 <= lvn_above_pct <= LVN_NEAR_PCT:
        fuel.append(f"thin-volume air {lvn_above_pct:+.1%} overhead (LVN) — little resistance memory above")

    nf, nc = len(fuel), len(counter)
    if nf >= 3 and nf - nc >= 3:
        net = f"SQUEEZE CONDITIONS PRESENT ({nf} fuel vs {nc} counter)"
    elif nf - nc >= 1:
        net = f"partial squeeze conditions ({nf} fuel vs {nc} counter)"
    else:
        net = f"squeeze conditions ABSENT ({nf} fuel vs {nc} counter)"

    caveats = []
    if settle_date:
        age = f", {settle_age}d ago" if settle_age is not None else ""
        caveats.append(f"short interest settles bi-monthly (as of {settle_date}{age}) — "
                       f"positioning may have moved since")
    caveats.append("short VOLUME includes market-making (~50% of volume is a normal baseline) — "
                   "the percentile is the tell, not the level")
    caveats.append("fuel ≠ ignition: a squeeze still needs a spark (catalyst/breakout), and "
                   "crowded shorts are sometimes right")
    return {"fuel": fuel, "counter": counter, "net": net, "caveats": caveats}


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator for the lens
# ─────────────────────────────────────────────────────────────────────────────
def gather_squeeze(ticker, daily=None, rvol=None, pc=None, profile=None, data_dir="data"):
    """Assemble the SHORT POSITIONING / SQUEEZE block for `ticker`: fetch SI + short-volume history
    and run the scorecard against the lens-computed price/flow/profile context. Returns
    {si, svr, read} or None when neither source yields data. Best-effort: never raises."""
    try:
        si_rows = fetch_short_interest(ticker, data_dir=data_dir)
        svr = fetch_short_volume(ticker, data_dir=data_dir)
        if not si_rows and (svr is None or not len(svr)):
            return None

        si = None
        dtc = si_chg = settle_date = settle_age = None
        if si_rows:
            latest = si_rows[0]
            dtc, settle_date = latest.get("dtc"), latest.get("settle_date")
            if settle_date:
                settle_age = (datetime.date.today() - datetime.date.fromisoformat(settle_date)).days
            if len(si_rows) > 1 and si_rows[1].get("interest"):
                si_chg = latest["interest"] / si_rows[1]["interest"] - 1.0
            si = {"interest": latest.get("interest"), "adv": latest.get("adv"), "dtc": dtc,
                  "settle_date": settle_date, "settle_age": settle_age, "chg": si_chg}

        svr_now = svr_pct = svr_5d = svr_20d = svr_n = None
        if svr is not None and len(svr):
            svr_now = float(svr.iloc[-1])
            svr_pct = percentile_of(svr, svr_now)
            svr_5d = float(svr.iloc[-5:].mean())
            svr_20d = float(svr.iloc[-20:].mean())
            svr_n = int(len(svr))

        chg_1d = chg_5d = None
        if daily is not None and len(daily) > 6:
            c = daily["Close"].dropna()
            chg_1d = float(c.iloc[-1] / c.iloc[-2] - 1)
            chg_5d = float(c.iloc[-1] / c.iloc[-6] - 1)

        pc_oi_v = pc_vol_v = None
        if pc and pc.get("total"):
            pc_oi_v, pc_vol_v = pc["total"].get("pc"), pc["total"].get("pc_vol")

        lvn_above = None
        if profile and profile.get("lvns") and profile.get("price"):
            p = profile["price"]
            lvn_above = min(((l / p - 1) for l in profile["lvns"] if l > p), default=None)

        read = squeeze_read(dtc=dtc, si_chg=si_chg, settle_date=settle_date, settle_age=settle_age,
                            svr_now=svr_now, svr_pct=svr_pct, svr_n=svr_n,
                            chg_1d=chg_1d, chg_5d=chg_5d, rvol=rvol,
                            pc_oi=pc_oi_v, pc_vol=pc_vol_v, lvn_above_pct=lvn_above)
        return {"si": si,
                "svr": {"now": svr_now, "pct": svr_pct, "avg5": svr_5d, "avg20": svr_20d, "n": svr_n},
                "read": read}
    except Exception:
        return None
