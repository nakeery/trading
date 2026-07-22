"""Offline tests for the FastAPI backend (S60/M1) — sanitizer, endpoints with a
monkeypatched gather_report (no network), generate-lock serialization, cache eviction.

Chart/IV tests use data/QQQ_indicators.csv (offline — same prerequisite as test_smoke.py).
"""

import asyncio
import datetime as dt
import json
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import reportgen
from api.cache import evict_ticker, frame_cache, report_cache, tile_cache
from api.main import app
from api.sanitize import sanitize

client = TestClient(app)


# ── sanitize ─────────────────────────────────────────────────────────────────
def test_sanitize_numpy_scalars():
    assert sanitize(np.float64(1.5)) == 1.5
    assert sanitize(np.int32(7)) == 7
    assert sanitize(np.bool_(True)) is True


def test_sanitize_nan_inf():
    assert sanitize(float("nan")) is None
    assert sanitize(np.float64("nan")) is None
    assert sanitize(float("inf")) is None
    assert sanitize(-float("inf")) is None


def test_sanitize_nested_and_containers():
    out = sanitize({"a": [np.float64("nan"), (1, np.int64(2))],
                    "b": {"c": np.array([1.0, float("nan")])},
                    3: "int key"})
    assert out == {"a": [None, [1, 2]], "b": {"c": [1.0, None]}, "3": "int key"}
    # the result must be strictly JSON-serializable (allow_nan=False is the real test)
    json.dumps(out, allow_nan=False)


def test_sanitize_timestamps():
    assert sanitize(pd.Timestamp("2026-07-21")) == "2026-07-21T00:00:00"
    assert sanitize(dt.date(2026, 7, 21)) == "2026-07-21"


# ── report endpoint (monkeypatched generate — no network, no lens) ───────────
def fake_payload(**over):
    p = {"ticker": "FAKE", "as_of": "2026-07-20", "as_of_mode": None,
         "last_bar": {"close": np.float64(100.0), "prev_close": float("nan"),
                      "open": 99.0, "high": 101.0, "low": 98.5},
         "setup": {"rows": [("HTF alignment", "✓", "detail")]},
         "risk": {"drawdown": ["factor a"], "rally": [], "regime": None},
         "ctx": {"gauges": [{"name": "ATM IV (30d)", "value": np.float64(0.21),
                             "pct": np.float64(0.97)}]},
         "gex": None, "earn": None, "exd": None, "cats": [], "macro_events": {}}
    p.update(over)
    return p


def fake_generate(payload):
    def _gen(ticker, flags):
        return {"payload": payload, "preamble": "fake preamble",
                "ansi_html": "<pre>fake</pre>" if payload is not None else ""}
    return _gen


@pytest.fixture(autouse=True)
def clean_state(monkeypatch, tmp_path):
    """Isolate every test: empty caches/LATEST, snapshots under tmp_path (never the real
    data/payload_history)."""
    report_cache.clear()
    reportgen.LATEST.clear()
    from api import loaders
    monkeypatch.setattr(loaders, "HISTORY_DIR", str(tmp_path / "payload_history"))
    yield
    report_cache.clear()
    reportgen.LATEST.clear()


def test_report_endpoint_sanitizes_fake_payload(monkeypatch):
    monkeypatch.setattr(reportgen, "generate", fake_generate(fake_payload()))
    r = client.get("/api/report/FAKE?vol=1")
    assert r.status_code == 200
    d = r.json()
    assert d["payload"]["last_bar"]["close"] == 100.0
    assert d["payload"]["last_bar"]["prev_close"] is None          # NaN → null
    assert d["payload"]["ctx"]["gauges"][0]["pct"] == 0.97
    assert d["preamble"] == "fake preamble"
    json.dumps(d, allow_nan=False)                                 # strictly valid JSON
    # success stored the payload as the ticker's LATEST (the chart's source)
    assert reportgen.LATEST["FAKE"]["ticker"] == "FAKE"


def test_report_endpoint_failure_returns_null_payload(monkeypatch):
    monkeypatch.setattr(reportgen, "generate", fake_generate(None))
    r = client.get("/api/report/NOPE")
    assert r.status_code == 200
    d = r.json()
    assert d["payload"] is None and d["diff"] is None
    assert "NOPE" not in reportgen.LATEST                           # failures never stored


def test_report_endpoint_caches_and_force_refetches(monkeypatch):
    calls = []

    def counting_gen(ticker, flags):
        calls.append(ticker)
        return {"payload": fake_payload(), "preamble": "", "ansi_html": ""}

    monkeypatch.setattr(reportgen, "generate", counting_gen)
    client.get("/api/report/FAKE")
    client.get("/api/report/FAKE")                                 # cache hit
    assert len(calls) == 1
    client.get("/api/report/FAKE?force=1")                         # Run button
    assert len(calls) == 2
    client.get("/api/report/FAKE?vol=1")                           # different flags = new key
    assert len(calls) == 3


def test_report_asof_skips_snapshot(monkeypatch, tmp_path):
    from api import loaders
    monkeypatch.setattr(reportgen, "generate",
                        fake_generate(fake_payload(as_of_mode="2026-06-30")))
    r = client.get("/api/report/FAKE?as_of=2026-06-30")
    assert r.json()["diff"] is None
    assert not (tmp_path / "payload_history").exists()             # nothing written


def test_generate_lock_serializes(monkeypatch):
    """Concurrent /api/report requests must never run generate() concurrently — the stdout
    redirect inside is process-global. Concurrency is driven inside ONE event loop via
    httpx.ASGITransport (the sync TestClient spins a fresh loop per request, and an
    asyncio.Lock waiter created in one loop can never be woken from another — deadlock)."""
    import httpx

    active = {"n": 0, "max": 0}

    def slow_gen(ticker, flags):
        active["n"] += 1
        active["max"] = max(active["max"], active["n"])
        time.sleep(0.2)
        active["n"] -= 1
        return {"payload": fake_payload(), "preamble": "", "ansi_html": ""}

    monkeypatch.setattr(reportgen, "generate", slow_gen)

    async def _run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            rs = await asyncio.gather(*(ac.get(f"/api/report/T{i}") for i in range(3)))
        assert all(r.status_code == 200 for r in rs)

    asyncio.run(_run())
    assert active["max"] == 1


# ── snapshot/diff (pure fns, tmp dir via fixture) ────────────────────────────
def test_snapshot_and_diff_roundtrip(monkeypatch):
    from api import loaders
    p1 = fake_payload(as_of="2026-07-18")
    assert loaders.snapshot_and_diff("FAKE", p1) is None           # first run: no history
    p2 = fake_payload(as_of="2026-07-20",
                      setup={"rows": [("HTF alignment", "✗", "detail")]},
                      risk={"drawdown": ["factor a", "factor b"], "rally": [],
                            "regime": {"label": "ESTABLISHED UPTREND"}})
    d = loaders.snapshot_and_diff("FAKE", p2)
    assert d["prev_as_of"] == "2026-07-18"
    ch = d["changes"]
    assert ("HTF alignment", "✓", "✗") in [tuple(f) for f in ch["flips"]]
    assert "factor b" in ch["dd_added"]


# ── chart endpoints (real QQQ CSV, offline) ──────────────────────────────────
def test_chart_endpoint_valid_json():
    frame_cache.clear()
    r = client.get("/api/chart/QQQ?overlays=ma20,ma50,ma200,bb,volume,rsi,macd,pline")
    assert r.status_code == 200
    d = r.json()
    assert d["fig"] is not None
    types = {t["type"] for t in d["fig"]["data"]}
    assert "candlestick" in types and "bar" in types
    assert d["range52"] and 0 <= d["range52"]["pos"] <= 1
    json.dumps(d, allow_nan=False)


def test_chart_asof_truncates():
    r = client.get("/api/chart/QQQ?as_of=2026-03-10")
    assert r.json()["as_of"] == "2026-03-10" or r.json()["as_of"] <= "2026-03-10"


def test_iv_history_endpoint():
    r = client.get("/api/iv_history/QQQ")
    assert r.status_code == 200
    d = r.json()
    if d["fig"] is not None:                                       # QQQ has harvested IV
        json.dumps(d, allow_nan=False)
        assert len(d["fig"]["data"]) >= 2


# ── cache eviction ───────────────────────────────────────────────────────────
def test_evict_ticker():
    frame_cache["QQQ"] = "frame"
    frame_cache["AMD"] = "other"
    tile_cache["QQQ"] = "tile"
    evict_ticker("qqq")
    assert "QQQ" not in frame_cache and "QQQ" not in tile_cache
    assert "AMD" in frame_cache
