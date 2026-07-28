"""Report generation for the FastAPI backend (S60) — ports lens_web.py's generate_payload.

One compute, two renderings (S49): gather_report produces the payload the React sections render
from, then render_payload prints the CLI-identical ANSI report from that same payload; the ANSI
is converted to HTML server-side (ansi2html — an existing dep) so the client just injects it.

CONCURRENCY: gather_report prints progress and we capture it with contextlib.redirect_stdout,
which swaps the PROCESS-GLOBAL sys.stdout — two concurrent generates would interleave their
captures. GENERATE_LOCK (asyncio) must be held by the (async) report endpoint across the
to_thread call. Never convert the endpoint to a sync `def`: FastAPI would run it in a threadpool
with no lock and the captures would race.
"""

import asyncio
import contextlib
import io
import re
from types import SimpleNamespace

from ansi2html import Ansi2HTMLConverter

import lens

DATA_DIR = "data"
GENERATE_LOCK = asyncio.Lock()
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# latest successfully generated payload per ticker — the session_state["last_payload"]
# analogue. /api/chart reads it for profile/events/GEX levels (S54: the chart renders the
# PAYLOAD's profile, never a local recompute). Single-user app; process-local is fine.
LATEST = {}

# flag → default; mirrors lens_web.py's flags dict / make_args (the argparse surface)
BOOL_FLAGS = ("vol", "call", "gex", "squeeze", "insider", "street", "movers", "geo", "live",
              "ltf", "short")
PC_OI_SCOPES = ("off", "all", "near", "leaps", "monthly")


def make_args(flags):
    """argparse-shaped namespace for lens.gather_report — candle 'none' (Plotly replaces it).
    Mirrors lens_web.make_args: `as_of` rides through; live is forced off with it (a real-time
    quote on a historical report is a contradiction)."""
    return SimpleNamespace(
        ticker=None, thesis=flags.get("thesis"), level=flags.get("level"),
        no_intraday=False, no_vix=False, geo=flags["geo"], no_color=False,
        candle="none", candle_px=128, prev=10, data_dir=DATA_DIR,
        no_refresh=False, refresh=False, as_of=flags.get("as_of"),
        pc_oi=([] if flags["pc_oi"] == "all" else [flags["pc_oi"]]) if flags["pc_oi"] != "off" else None,
        insider=flags["insider"], squeeze=flags["squeeze"],
        live=flags["live"] and not flags.get("as_of"),
        vol=flags["vol"], call=flags["call"], gex=flags["gex"],
        street=flags.get("street", False), movers=flags.get("movers", False),
        ltf=flags.get("ltf", False), short=flags.get("short", False),
    )


def flags_key(flags):
    """Hashable cache key for the exact flag combination (matches lens_web's dict-as-tuple)."""
    return tuple(sorted(flags.items()))


def strip_ansi(text):
    return _ANSI_RE.sub("", text)


def generate(ticker, flags):
    """SYNC worker (call via asyncio.to_thread under GENERATE_LOCK). Returns
    {payload, preamble, ansi_html} — payload None + preamble carrying the load-error line
    on failure, exactly like the Streamlit path."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        # as-of mode rebuilds a historical backdrop inside gather_report and discards
        # backdrop_base — skip the current-day F&G/COT/marketsent fetches entirely
        base = None if flags.get("as_of") else lens.build_backdrop(DATA_DIR)
        payload = lens.gather_report(ticker, make_args(flags), interactive=False,
                                     backdrop_base=base)
    preamble = buf.getvalue()
    ansi = ""
    if payload is not None:
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            lens.render_payload(payload, use_color=True, candle_style="none")
        ansi = buf2.getvalue()
    ansi_html = (Ansi2HTMLConverter(inline=True, dark_bg=True).convert(preamble + ansi, full=False)
                 if payload is not None else "")
    return {"payload": payload, "preamble": strip_ansi(preamble).strip(), "ansi_html": ansi_html}
