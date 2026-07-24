# archive/ - retired from the active app (generated 2026-07-24)

Nothing in here is imported or invoked by the current React + FastAPI app
(api.main -> lens -> modules, served with web/). These files were moved out of the
repo root to declutter it. History is preserved (git mv); restore any file with a
plain `git mv` back to the root.

## research/       one-off research & diagnostic scripts (nothing imported them)
## ml_pipeline/    legacy ML options-swing pipeline (indicators->entry->sizing + diagnostics)
## streamlit/      legacy Streamlit UI, superseded by the React app

### Kept at the repo root ON PURPOSE (do NOT move - the app needs them):
- lens.py          the shared engine (imported by api/reportgen.py)
- indicators.py    invoked by lens.py as a SUBPROCESS on auto-refresh (not an import)
- backfill_iv.py   lazy-imported by modules/vol_history.py (`from backfill_iv import backfill`)
- score_ledger.py  imported by api/loaders.py for the scored signal ledger
- api/, modules/, web/, tests/   all left intact

### Known side effects of this move (see the delivered plan for fixes):
- tests/test_smoke.py has 3 FUNCTION-LOCAL tests that `import entry` / `import lens_web`
  / `from lens_web_sections import _slug` (around lines 135, 164, 1700-1701). Those tests
  exercise now-retired code and will raise ModuleNotFoundError; delete or mark them
  xfail/skip. The rest of test_smoke.py and ALL of test_api.py are unaffected.
- .claude/launch.json (gitignored) has lens-web / lens-web-dev configs pointing at
  lens_web.py; update the path to archive/streamlit/lens_web.py or remove them.
- A resurrected archive script that imports project code must run from the repo root
  (e.g. `python -m archive.research.xs_research`) since it is no longer at the root.
