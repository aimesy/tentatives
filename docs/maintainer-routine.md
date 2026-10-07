# Tentatives Maintainer Routine

This is the current maintainer shape for `aimesy/tentatives` (code) and
`aimesy/tentatives-data` (archive and parsed data). It replaces the old split
where one job captured PDFs and a later job was expected to parse them. The
workflows named here run in `aimesy/tentatives-data` and check out this code at
`master` (README, Repositories).

## Canonical Daily Loop

The primary routine is the courtproj harvest, `ops/courtproj-harvest.sh`, at
5 PM Pacific; Backfill captures (`.github/workflows/backfill.yml` in
`aimesy/tentatives-data`) runs the same loop only as its fallback
([harvest.md](harvest.md)).

Daily live run:

1. Capture all routine-enabled county sources with `ingest.backfill --live`.
2. Treat a run that archives zero refs as failed, and recheck counties whose
   discovery or fetches failed in GitHub Actions.
3. Run `ingest.ocr_missing_text` so image-only PDFs get searchable sidecars.
4. Run `ingest.orchestrate` so new sources become normalized Parquet rows.
5. Run `ingest.slice_rulings` so viewer links target the right raw PDF pages.
6. Run `update-readme.py` to refresh README/LIVE metrics and
   `site/counties.json`.
7. Commit `archive/`, `data/`, `site/counties.json`, `README.md`, and
   `LIVE.md`.
8. Rebase before pushing if `master` moved.
9. File or update a GitHub issue on failure.

Weekly Wayback run:

1. Run the same loop in bounded Wayback mode (courtproj, Sundays).
2. Keep CDX work conservative until a URL family is proven stable.
3. Preserve every captured source. Do not trim archive material to make a count
   look cleaner.

## Catch-Up Lanes

`.github/workflows/parse.yml` runs when archive/parser changes land outside the
scheduled backfill. It now follows the same derived-data loop: OCR sidecars,
parse, slice, LIVE refresh, commit.
`site/counties.json` is generated from `data/*/rulings.parquet`; do not hand
list only a subset of county databases in the viewer.

`.github/workflows/ocr.yml` is manual. Use it for bounded OCR/reparse work when
a county has image-only PDFs or a parser migration needs a deliberate reparse.

The courtproj harvest works in a temporary sparse clone and runs the full loop
itself; it does not depend on `Parse new PDFs` to finish the job. Its commits
say `[skip ci]`, so they start no workflow.

## Local Smoke Routine

Before pushing parser or maintainer changes, run focused checks from a data
checkout with this code copied in (README, Repositories):

```bash
python -m pytest counties/test_new_daily_discovery.py ingest/tests/test_backfill.py ingest/tests/test_orchestrate.py ingest/tests/test_slice_rulings.py -q
python -m ingest.orchestrate --dry-run
```

For one county:

```bash
python -m ingest.backfill --county yolo --live --continue-on-error --dry-run
python -m ingest.ocr_missing_text --county yolo --dry-run
python -m ingest.orchestrate --county yolo --dry-run
python -m ingest.slice_rulings --county yolo
```

After parsing changes, check mechanical integrity:

```bash
python - <<'PY'
from pathlib import Path
import pyarrow.parquet as pq

bad_spans = []
missing_slices = []
total = 0
for parquet in Path("data").glob("*/rulings.parquet"):
    county = parquet.parent.name
    for row in pq.read_table(parquet).to_pylist():
        total += 1
        start = row.get("page_start")
        end = row.get("page_end")
        if start and end and (start < 1 or end < start):
            bad_spans.append((county, row.get("ruling_id"), start, end))
        rid = row.get("ruling_id")
        if rid:
            path = Path("archive") / county / "rulings" / rid[:2] / f"{rid}.pdf"
            if not path.exists():
                missing_slices.append((county, rid))
print("rows", total)
print("bad_spans", len(bad_spans), bad_spans[:5])
print("missing_slices", len(missing_slices), missing_slices[:5])
PY
```

## Failure Triage

The Tests job must use a sparse checkout of source, fixtures, and archived
regression files. A complete checkout exhausted the runner during
`actions/checkout` on October 3, 2026, before Python or pytest ran. The helper
`.github/scripts/test_archive_paths.py` reads hashes from the county tests and
lists matching paths from the Git tree of `aimesy/tentatives-data`; the
workflow fetches those exact files with the `TENTATIVES_DATA_CI` token.
Do not expand this into a checkout of `archive/` or all historical blobs. Keep
the archive regression checks enabled when adding new test sources.

The extension build must likewise check out only `extension/` and its packager.
Public download links belong under `https://tentatives.amyc.us/downloads/`. The viewer
build produces those files directly from source and excludes county databases
and archived court files from its static assets.

When a maintainer issue is filed:

1. Open the workflow log and identify the first failing county or source SHA.
2. If discovery failed, inspect that county landing page and update only that
   county's `discover_live`/document probing code.
3. If parsing failed, save or reuse the exact source PDF as a fixture and add a
   focused parser test before changing parser logic.
4. If OCR failed, check whether the PDF is encrypted, password-protected, or
   merely image-only. Encrypted/password-protected files stay archived but are
   not parsed unless a lawful public password or alternate source exists.
5. If counts moved unexpectedly, separate real misses from duplicate cleanup.
   Do not re-inflate counts with duplicate rows.
6. If a repeated boilerplate/form block appears across many documents, segregate
   it only for the county/source family where it is proven. Do not generalize a
   separator across unrelated counties.

## Current Known Watch Points

- Yolo password-protected confidential probate PDFs are archived but not parsed.
- Imperial has capture support; parser support waits for representative current
  PDFs with real rows.
- San Diego needs separate ROA/path triage before broad capture.
- Alameda, Kings, Mendocino, Sacramento, and broad San Joaquin capture remain
  blocked or case-led until a lawful public access path is confirmed.
- Counties marked no-surface stay monitored negatives. Do not scrape calendars
  as if they were tentative rulings.
