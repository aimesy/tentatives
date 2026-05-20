# tentatives

California superior court tentative rulings, archived as original court files and parsed into searchable data when a county parser is reliable enough to trust.

This repo is the multi-county generalization of [`aimesy/sfsc-tentatives`](https://github.com/aimesy/sfsc-tentatives). The important split is simple:

- Live viewer: [aimesy.github.io/tentatives](https://aimesy.github.io/tentatives/)
- Extension zip: [tentatives-extension.zip](https://github.com/aimesy/tentatives/releases/download/extension-latest/tentatives-extension.zip)

- Capture support means the extension or backfill CLI can find and archive the court's ruling files.
- Parser support means archived PDFs become normalized rows in `data/<county>/rulings.parquet`.

Do not blur those two. A county is not "done" merely because its PDFs can be fetched.

## Current Status

| County | Capture | Parser | Notes |
|---|---:|---:|---|
| El Dorado | yes | yes | Four tested PDF styles: probate, civil law and motion, probate calendar, family law. |
| Contra Costa | yes | yes | Extension handles the iframe and collapsible portal pages. |
| Placer | yes | yes | Civil law and motion PDFs with tested page and outcome extraction. |
| Amador | yes | no | Legacy 2020-2022 dropdown PDFs. Current post-02/15/2022 access moved to the Amador portal. |
| San Francisco | yes | no | Unified Family Court family-law PDFs from `webapps.sftc.org/ufctr/ufctr.dll`. Main SF civil data remains in `aimesy/sfsc-tentatives`. |
| Nevada | yes | no | Static Drupal page with Nevada City and Truckee ruling files. Current page may include `.docx`; this repo currently archives PDFs. |
| Orange | yes | no | Civil, family, and probate index pages link stable current PDFs. Use Wayback for prior contents. |
| Calaveras | yes | no | Long static lists for case-management and civil law-and-motion PDFs, with irregular filenames. |
| Fresno | yes | no | Static Law and Motion page with department PDF links. |
| Merced | yes | no | Static weekday PDF links for civil law and motion. |
| Plumas | yes | no | Static Department 2 PDF links. |
| Riverside | yes | no | Regional/department PDF links. |
| San Bernardino | yes | no | Legacy civil table on `old.sb-court.org` with direct PDF links. |
| Santa Clara | yes | no | Department pages with Tuesday/Thursday and probate/complex PDFs. |
| Shasta | yes | no | Static department PDF links, including old-to-current department labels. |
| Solano | yes | no | Static civil/probate department PDFs. |
| Tuolumne | yes | no | Static tentative-ruling PDF links, with case notes excluded. |

Other counties have been researched and triaged in [docs/county-plans.md](docs/county-plans.md). The short version: many are simple PDF-list pages; Los Angeles and Ventura need form-session handling; Kings and Mendocino are blocked by SharePoint or re:SearchCA style access.

## How It Works

1. The browser extension or `ingest.backfill` discovers court file URLs.
2. Each file is fetched and hashed.
3. The original file is stored once at `archive/<county>/<sha[:2]>/<sha>.pdf`.
4. Every fetch event is logged in `archive/<county>/captures.ndjson`.
5. `python -m ingest.orchestrate` walks the archive and runs registered parsers.
6. Parsed rows are written to `data/<county>/rulings.parquet`.
7. `site/` loads those parquet files in the browser.

The archive is content-addressed. If two URLs point to the same PDF, the repo stores one PDF and multiple capture rows.

## Repo Layout

```text
schema/                          shared Ruling and Capture dataclasses
counties/<county>/scraper.py     county discovery and, where implemented, PDF parsing
counties/<county>/tests/         pytest fixtures and parser/discovery tests
ingest/orchestrate.py            archive PDFs -> rulings.parquet
ingest/backfill.py               live and Wayback capture into archive/
archive/<county>/<sha[:2]>/      content-addressed original PDFs
archive/<county>/captures.ndjson append-only capture provenance
data/<county>/rulings.parquet    one row per parsed ruling
extension/                       Chrome/Firefox capture extension
site/                            static parquet viewer
```

## Capture With The Extension

Install the extension from the [latest release zip](https://github.com/aimesy/tentatives/releases/download/extension-latest/tentatives-extension.zip), or load `extension/` unpacked for local development.

1. Open Settings and set a GitHub token with Contents read/write access.
2. Visit a supported court page, or use the Pages list in the side panel.
3. Click Upload for the active page, Fetch for one configured landing page, or Scan all for a county.

Supported capture pages now include:

- El Dorado department pages
- Placer tentative-ruling pages
- Contra Costa current and archive portal pages
- Amador legacy dropdown page
- San Francisco UFC family-law page
- Nevada tentative-rulings page
- Orange civil, family, and probate tentative-ruling pages
- Calaveras case-management and civil law-and-motion pages
- Fresno, Merced, Plumas, Riverside, San Bernardino, Santa Clara, Shasta, Solano, and Tuolumne static PDF pages

The extension logs `dept_hint`, `division_hint`, and `source_page_url` when a content script can infer them. The parser pipeline now passes `dept_hint` through to registered parsers.

## Historical Backfill

Use the local backfill command for live pulls and Wayback pulls:

```bash
python -m ingest.backfill --county amador --live --dry-run
python -m ingest.backfill --county amador --wayback --from-year 2020 --to-year 2022
python -m ingest.backfill --county orange --live --wayback --limit 25
```

Configured counties:

```text
amador
calaveras
fresno
merced
nevada
orange
plumas
riverside
san-bernardino
san-francisco
santa-clara
shasta
solano
tuolumne
```

Amador has a county-level Wayback prefix for `www.amadorcourt.org/tentativeRulings/*`. Orange uses exact Wayback queries against the stable current PDF URLs discovered from its live index pages. Other counties can use the same pattern once their live discovery modules expose stable PDF refs.

## Parse Locally

```bash
python -m venv .venv
. .venv/Scripts/activate  # Windows PowerShell users can run: .venv\Scripts\Activate.ps1
pip install -r requirements.txt pytest

pytest counties/ -v
python -m ingest.orchestrate --dry-run
python -m ingest.orchestrate --county el-dorado --dry-run
```

`ingest.orchestrate` only parses counties in its `PARSERS` registry. Capture-only counties are archived but skipped until a parser is added and tested.

## Live Viewer

The live viewer is published at [https://aimesy.github.io/tentatives/](https://aimesy.github.io/tentatives/). The Pages workflow deploys `site/` and `data/**/rulings.parquet` from `master`.

For local development, serve from the repo root:


```bash
python -m http.server 8000
```

Then open `http://localhost:8000/site/`.

The viewer loads `data/<county>/rulings.parquet` directly in the browser through hyparquet. Counties without parquet files are skipped.

## Adding A County

1. Add `counties/<slug>/__init__.py` with `COUNTY_SLUG` and `PARSER_VERSION`.
2. Add discovery in `counties/<slug>/scraper.py`. For static pages, reuse `counties.common.PdfRef` and `extract_links`.
3. Add fixture HTML and discovery tests.
4. Add parser tests only after you have representative PDFs.
5. Implement `parse(pdf_bytes, source_url, source_sha256=None, dept_hint=None) -> list[Ruling]`.
6. Register the parser in `ingest/orchestrate.py`.
7. Add extension support only if the browser path is useful for forward capture.

Filename heuristics are allowed for discovery. Parser metadata should come from PDF content whenever possible.

## Schema

`data/<county>/rulings.parquet` columns are defined by `schema.Ruling`:

| Column | Meaning |
|---|---|
| `ruling_id` | Stable parser-owned ID. |
| `county` | County slug, such as `el-dorado`. |
| `division` | Probate, Civil, Family Law, Law and Motion, or a county-specific section. |
| `dept` | Department if known. |
| `hearing_date` | Hearing date from the PDF, not merely the filename. |
| `case_number` | Court case number as printed. |
| `case_title` | Case title as printed. |
| `motion_type` | Motion or calendar matter. |
| `outcome` | `granted`, `denied`, `continued`, `appearance_required`, `off_calendar`, or `other`. |
| `outcome_text` | Disposition text. |
| `body_text` | Parser-specific pre-disposition body text. |
| `full_text` | Per-ruling text slice. |
| `page_start`, `page_end` | Source PDF page span. |
| `source_sha256` | Hash of the archived original PDF. |
| `source_url` | Court or Wayback source URL. |
| `parser_version` | Parser version string. |

`schema.Capture` records fetch provenance, including `wayback_ts`, `dept_hint`, `division_hint`, and `source_page_url` when available.

## Known Sharp Edges

- `parser_version` does not force a reparse by itself. Existing rows are skipped by `ruling_id`.
- `captures.ndjson` can contain multiple rows for one SHA. The parser currently uses one capture row per SHA when choosing `source_url`.
- Nevada may publish Word documents. The current archive and parser path is PDF-only.
- Capture support for a county should not be represented as parser support.
