"""
SEC EDGAR insider activity (S42) — backs lens.py `--insider`.

CONTEXT ONLY, never a prediction or a model feature. Reads open-market insider transactions from
SEC Form 4 filings via the OFFICIAL free EDGAR APIs and surfaces the one pattern with real research
support — CLUSTER BUYING (≥2 distinct insiders buying open-market within a 30-day window;
Lakonishok & Lee 2001: cluster purchases predict abnormal returns, while insider SALES mostly
don't — they're diversification/compensation noise. That asymmetry is printed as a caveat).

Data path (all free, official):
  1. ticker → CIK:  https://www.sec.gov/files/company_tickers.json          (cached ~7 days)
  2. filings list:  https://data.sec.gov/submissions/CIK{cik:010}.json      (recent Form 4s)
  3. per filing:    https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}  (Form 4 XML)

SEC fair-access policy: a descriptive User-Agent WITH a contact email is REQUIRED (set
$env:SEC_CONTACT to override the default), and ≤10 requests/second — a small sleep is enforced
between filing fetches. Parsed summary is cached per ticker (session-stale, like pc-oi), so the
filing fetches happen at most once per session. Best-effort: never raises.

Scoring scope: NON-DERIVATIVE open-market transactions only — code P (purchase) and S (sale).
Option exercises (M), grants (A), gifts (G), tax withholding (F) are ignored: they aren't
conviction trades.
"""

import datetime
import json
import os
import time
import xml.etree.ElementTree as ET

import requests

from modules.pc_oi import cache_stale

CACHE_SUBDIR = "insider_cache"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
SEC_HEADERS = {"User-Agent": f"trading-lens/1.0 ({os.environ.get('SEC_CONTACT', 'ericdrichmond@gmail.com')})",
               "Accept-Encoding": "gzip, deflate"}

LOOKBACK_DAYS = 90         # trailing window for the read
MAX_FILINGS = 25           # newest Form 4s parsed per run (rate-limit friendly)
REQ_SLEEP = 0.12           # ≥10 req/s ceiling per SEC policy
CLUSTER_WINDOW_D = 30      # distinct insiders buying within this window = a cluster
CLUSTER_MIN_OWNERS = 2
TICKERS_TTL_DAYS = 7


def _cache_path(name, data_dir):
    return os.path.join(data_dir, CACHE_SUBDIR, name)


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
# Pure parsing / analysis (unit-testable offline)
# ─────────────────────────────────────────────────────────────────────────────
def parse_form4(xml_text):
    """One Form 4 XML → list of open-market events:
    [{date, code ('P'|'S'), shares, price, usd, owner, role}, …]. Non-derivative table only;
    other transaction codes are skipped. Returns [] on any parse problem."""
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    def txt(node, path):
        el = node.find(path)
        return el.text.strip() if (el is not None and el.text) else None

    owner = txt(root, ".//reportingOwner/reportingOwnerId/rptOwnerName") or "unknown"
    is_dir = (txt(root, ".//reportingOwnerRelationship/isDirector") or "0").lower() in ("1", "true")
    is_off = (txt(root, ".//reportingOwnerRelationship/isOfficer") or "0").lower() in ("1", "true")
    title = txt(root, ".//reportingOwnerRelationship/officerTitle")
    role = title or ("Director" if is_dir else "Officer" if is_off else "10% owner/other")

    events = []
    for tr in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        code = txt(tr, "transactionCoding/transactionCode")
        if code not in ("P", "S"):
            continue
        date = txt(tr, "transactionDate/value")
        shares = txt(tr, "transactionAmounts/transactionShares/value")
        price = txt(tr, "transactionAmounts/transactionPricePerShare/value")
        try:
            shares = float(shares) if shares else None
            price = float(price) if price else None
        except ValueError:
            continue
        if not date or not shares:
            continue
        usd = shares * price if price else None
        events.append({"date": date, "code": code, "shares": shares, "price": price,
                       "usd": usd, "owner": owner, "role": role})
    return events


def cluster_buys(events, window_days=CLUSTER_WINDOW_D, min_owners=CLUSTER_MIN_OWNERS):
    """Detect the research-backed pattern: ≥`min_owners` DISTINCT insiders with open-market BUYS
    inside any `window_days` window. Returns the best window found
    {owners, n_owners, usd, start, end} or None. Pure."""
    buys = sorted((e for e in events if e["code"] == "P" and e.get("date")),
                  key=lambda e: e["date"])
    if not buys:
        return None
    best = None
    for i, anchor in enumerate(buys):
        try:
            d0 = datetime.date.fromisoformat(anchor["date"])
        except ValueError:
            continue
        in_win = []
        for e in buys[i:]:
            try:
                d = datetime.date.fromisoformat(e["date"])
            except ValueError:
                continue
            if (d - d0).days <= window_days:
                in_win.append(e)
        owners = sorted({e["owner"] for e in in_win})
        if len(owners) >= min_owners:
            cand = {"owners": owners, "n_owners": len(owners),
                    "usd": sum(e["usd"] for e in in_win if e.get("usd")),
                    "start": in_win[0]["date"], "end": in_win[-1]["date"]}
            if best is None or cand["n_owners"] > best["n_owners"] or (
                    cand["n_owners"] == best["n_owners"] and cand["usd"] > best["usd"]):
                best = cand
    return best


def insider_read(events, window_days=CLUSTER_WINDOW_D):
    """Two-sided read over trailing open-market events (house style: factors listed, count ≠
    probability). Returns {net_usd, n_buys, n_sells, n_owners, cluster, latest_buy, positive,
    flags, net, caveats}. Pure."""
    buys = [e for e in events if e["code"] == "P"]
    sells = [e for e in events if e["code"] == "S"]
    net_usd = (sum(e["usd"] for e in buys if e.get("usd"))
               - sum(e["usd"] for e in sells if e.get("usd")))
    owners = {e["owner"] for e in events}
    cluster = cluster_buys(events, window_days=window_days)
    latest_buy = max(buys, key=lambda e: e["date"]) if buys else None

    positive, flags = [], []
    if cluster:
        positive.append(f"CLUSTER BUY — {cluster['n_owners']} distinct insiders bought within "
                        f"{window_days}d ({cluster['start']} → {cluster['end']}"
                        + (f", ${cluster['usd']:,.0f} total" if cluster.get("usd") else "") + ")")
    elif buys:
        positive.append(f"{len(buys)} open-market buy{'s' if len(buys) != 1 else ''} "
                        f"(single-insider — weaker than a cluster)")
    if sells and net_usd < 0 and len({e['owner'] for e in sells}) >= 3:
        flags.append(f"broad selling — {len({e['owner'] for e in sells})} insiders sold "
                     f"(weak signal individually, breadth is worth noting)")

    if cluster:
        net = "insider conviction signal PRESENT (cluster buying)"
    elif buys and net_usd > 0:
        net = "net insider buying (no cluster — modest signal)"
    elif sells and not buys:
        net = "sales only — common and weakly informative"
    elif not events:
        net = "no open-market insider transactions in the window"
    else:
        net = "mixed / net selling — weakly informative"

    caveats = [
        "cluster BUYS carry the research edge (Lakonishok-Lee); SALES are mostly "
        "diversification/comp noise — don't short a stock because insiders sold",
        "Form 4 files within 2 business days of the trade; 10b5-1 pre-planned sales are "
        "not separated out here",
        "open-market P/S only — option exercises, grants, gifts and tax withholding are excluded",
    ]
    return {"net_usd": net_usd, "n_buys": len(buys), "n_sells": len(sells),
            "n_owners": len(owners), "cluster": cluster, "latest_buy": latest_buy,
            "positive": positive, "flags": flags, "net": net, "caveats": caveats}


# ─────────────────────────────────────────────────────────────────────────────
# EDGAR fetchers (network, cached, best-effort)
# ─────────────────────────────────────────────────────────────────────────────
def _get(url):
    time.sleep(REQ_SLEEP)                       # SEC fair-access ceiling (≤10 req/s)
    r = requests.get(url, headers=SEC_HEADERS, timeout=15)
    r.raise_for_status()
    return r


def cik_for(ticker, data_dir="data"):
    """Ticker → integer CIK via the SEC company_tickers map (cached ~7 days). None if unknown."""
    path = _cache_path("company_tickers.json", data_dir)
    data = None
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < TICKERS_TTL_DAYS * 86400:
        data = _load_json(path)
    if data is None:
        try:
            data = _get(TICKERS_URL).json()
            _save_json(path, data)
        except Exception:
            data = _load_json(path)             # stale beats nothing
    if not data:
        return None
    t = ticker.upper()
    for row in data.values():
        if str(row.get("ticker", "")).upper() == t:
            return int(row["cik_str"])
    return None


def fetch_form4_events(ticker, data_dir="data", lookback_days=LOOKBACK_DAYS,
                       max_filings=MAX_FILINGS):
    """Open-market insider events for `ticker` from its recent Form 4 filings. Network path:
    CIK map → submissions JSON → per-filing XML (rate-limited). Returns a list of event dicts
    (see parse_form4) or None when EDGAR is unreachable / ticker unknown."""
    cik = cik_for(ticker, data_dir=data_dir)
    if cik is None:
        return None
    try:
        sub = _get(SUBMISSIONS_URL.format(cik=cik)).json()
        recent = (sub.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        accs = recent.get("accessionNumber") or []
        docs = recent.get("primaryDocument") or []
        dates = recent.get("filingDate") or []
    except Exception:
        return None

    floor = (datetime.date.today() - datetime.timedelta(days=lookback_days)).isoformat()
    events, parsed = [], 0
    for form, acc, doc, fdate in zip(forms, accs, docs, dates):
        if form != "4" or not acc or not doc:
            continue
        if fdate and fdate < floor:
            break                                # recent lists are newest-first
        if parsed >= max_filings:
            break
        # primaryDocument may carry an xsl-stylesheet prefix — the raw XML is the bare filename.
        url = FILING_URL.format(cik=cik, acc=acc.replace("-", ""), doc=doc.split("/")[-1])
        try:
            events.extend(parse_form4(_get(url).text))
            parsed += 1
        except Exception:
            continue                             # one bad filing shouldn't kill the block
    # keep only events inside the lookback (filing date ≥ floor doesn't guarantee trade date is)
    return [e for e in events if e.get("date") and e["date"] >= floor]


def gather_insider(ticker, data_dir="data"):
    """Assemble the INSIDER ACTIVITY block: events + read, cached per ticker session-stale
    (a new market close → refetch; Form 4s trickle in daily). Best-effort: never raises;
    a fetch failure serves any cached summary."""
    path = _cache_path(f"{ticker.lower()}.json", data_dir)
    cache = _load_json(path)
    if cache and not cache_stale(cache):
        return cache.get("summary")
    try:
        events = fetch_form4_events(ticker, data_dir=data_dir)
    except Exception:
        events = None
    if events is None:
        return (cache or {}).get("summary")
    summary = {"ticker": ticker.upper(), "lookback_days": LOOKBACK_DAYS,
               "events": events, "read": insider_read(events)}
    _save_json(path, {"as_of": time.time(), "summary": summary})
    return summary
