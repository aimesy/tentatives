# tentatives

California superior court tentative rulings, court calendar notes, and other perishable ruling-adjacent material.

The point is preservation first, parsing second. The archive keeps the court source material. The data pipeline normalizes counties only after the parser has fixtures and tests.

- Viewer: [aimesy.github.io/tentatives](https://aimesy.github.io/tentatives/)
- Chrome extension: [tentatives-extension.zip](https://github.com/aimesy/tentatives/releases/download/extension-latest/tentatives-extension.zip)
- Firefox extension: [tentatives-extension-firefox.zip](https://github.com/aimesy/tentatives/releases/download/extension-latest/tentatives-extension-firefox.zip)
- Contact: amy@chattopadhyay.org

## Status

Capture support means this repo can find and archive court source material.

Parser support means archived material is converted into normalized rows in `data/<county>/rulings.parquet`.

| County | Capture | Parser | Notes |
|---|---:|---:|---|
| Contra Costa | yes | yes | PDFs, archive pages, and changed HTML page captures for ruling pages and probate calendar notes. |
| El Dorado | yes | yes | Probate, civil law and motion, probate calendar, and family law PDF styles. |
| Placer | yes | yes | Civil law and motion PDFs. |
| Amador | yes | yes | Legacy dropdown PDFs from public archive/Wayback sources. Current post-02/15/2022 access appears portal-based. |
| Calaveras | yes | no | Case-management and civil law-and-motion PDFs. |
| Fresno | yes | no | Law and Motion department PDFs. |
| Merced | yes | no | Weekday civil law-and-motion PDFs. |
| Nevada | yes | yes | Static ruling page. Word documents are not yet archived. |
| Orange | yes | yes | Stable current PDF URLs; changed hashes matter. |
| Plumas | yes | no | Department 2 PDFs. |
| Riverside | yes | no | Regional and department PDF links. |
| San Bernardino | yes | no | Legacy civil table. |
| San Francisco | yes | yes | UFC family-law PDFs. Main SF civil work remains in `aimesy/sfsc-tentatives`. |
| Santa Clara | yes | yes | Department PDF pages; changed hashes matter. |
| Shasta | yes | yes | Department PDFs; changed hashes matter. |
| Solano | yes | yes | Civil and probate department PDFs. |
| Tuolumne | yes | no | Tentative rulings and Case Notes. |

See [docs/county-plans.md](docs/county-plans.md) for the broader county triage.

## Parsed Date Coverage

This section reflects normalized rows in `data/<county>/rulings.parquet`.
Capture-only counties can have archived PDFs without appearing here.

<details>
<summary>Amador - 11 rulings across 2 PDFs</summary>

| Division | Department | First hearing date | Last hearing date | Rows |
|---|---:|---:|---:|---:|
| Civil Case Management Conference | 3 | 2015-09-21 | 2015-09-21 | 8 |
| Civil Law and Motion | 1 | 2022-04-11 | 2022-04-11 | 3 |

</details>

<details>
<summary>Nevada - 589 rulings across 60 PDFs</summary>

| Division | Department | First hearing date | Last hearing date | Rows |
|---|---:|---:|---:|---:|
| Case Management | 6 | 2026-03-02 | 2026-05-18 | 165 |
| Case Management | A | 2026-02-20 | 2026-04-17 | 32 |
| Case Management | Unspecified | 2026-03-09 | 2026-05-18 | 59 |
| Guardianship | 3 | 2026-05-07 | 2026-05-07 | 15 |
| Guardianship | A | 2026-01-26 | 2026-01-26 | 3 |
| Law and Motion | 4 | 2026-03-13 | 2026-03-13 | 1 |
| Law and Motion | 5 | 2026-04-03 | 2026-04-03 | 1 |
| Law and Motion | 6 | 2026-04-24 | 2026-05-22 | 7 |
| Law and Motion | A | 2026-01-12 | 2026-05-11 | 3 |
| Law and Motion | Unspecified | 2026-01-12 | 2026-05-22 | 154 |
| Probate | 6 | 2026-03-06 | 2026-05-22 | 107 |
| Probate | A | 2026-05-11 | 2026-05-11 | 1 |
| Probate | Unspecified | 2026-01-12 | 2026-05-15 | 41 |

</details>

<details>
<summary>Orange - 296 rulings across 36 PDFs</summary>

| Division | Department | First hearing date | Last hearing date | Rows |
|---|---:|---:|---:|---:|
| Civil | C11 | 2026-05-18 | 2026-05-18 | 11 |
| Civil | C12 | 2026-05-15 | 2026-05-15 | 12 |
| Civil | C13 | 2026-05-15 | 2026-05-15 | 8 |
| Civil | C15 | 2026-05-18 | 2026-05-18 | 15 |
| Civil | C23 | 2026-05-14 | 2026-05-21 | 29 |
| Civil | C25 | 2026-05-19 | 2026-05-19 | 11 |
| Civil | C26 | 2026-01-30 | 2026-01-30 | 1 |
| Civil | C27 | 2026-05-18 | 2026-05-18 | 2 |
| Civil | C28 | 2026-05-18 | 2026-05-18 | 11 |
| Civil | C32 | 2026-05-19 | 2026-05-19 | 13 |
| Civil | C33 | 2026-05-14 | 2026-05-21 | 22 |
| Civil | C34 | 2026-05-21 | 2026-05-21 | 9 |
| Civil | C44 | 2026-05-07 | 2026-05-07 | 8 |
| Civil | CM2 | 2026-05-21 | 2026-05-21 | 14 |
| Civil | CX101 | 2026-05-22 | 2026-05-22 | 8 |
| Civil | CX103 | 2026-05-18 | 2026-05-18 | 17 |
| Civil | CX105 | 2026-05-14 | 2026-05-21 | 26 |
| Civil | N14 | 2026-05-18 | 2026-05-18 | 9 |
| Civil | N15 | 2026-05-18 | 2026-05-18 | 18 |
| Civil | N17 | 2026-05-18 | 2026-05-18 | 2 |
| Civil | Unspecified | 2025-10-24 | 2026-05-20 | 9 |
| Civil | W15 | 2026-05-21 | 2026-05-21 | 11 |
| Family Law | C22 | 2025-12-05 | 2025-12-05 | 3 |
| Probate | C10 | 2026-05-21 | 2026-05-21 | 1 |
| Probate | C21 | 2026-05-15 | 2026-05-15 | 9 |
| Probate | CM04 | 2026-01-16 | 2026-01-16 | 1 |
| Probate | CM05 | 2026-05-20 | 2026-05-20 | 2 |
| Probate | CM06 | 2026-05-14 | 2026-05-14 | 2 |
| Probate | CM08 | 2026-05-20 | 2026-05-20 | 8 |
| Probate | CM3 | 2026-05-06 | 2026-05-06 | 1 |
| Probate | Unspecified | 2026-05-20 | 2026-05-20 | 3 |

</details>

<details>
<summary>San Francisco - 175 rulings across 23 PDFs</summary>

| Division | Department | First hearing date | Last hearing date | Rows |
|---|---:|---:|---:|---:|
| Family Law | 403 | 2026-04-21 | 2026-05-21 | 90 |
| Family Law | 404 | 2026-04-21 | 2026-05-21 | 82 |
| Family Law | 414 | 2026-03-26 | 2026-05-07 | 3 |

</details>

<details>
<summary>Santa Clara - 73 rulings across 12 PDFs</summary>

| Division | Department | First hearing date | Last hearing date | Rows |
|---|---:|---:|---:|---:|
| Civil Law and Motion | 10 | 2026-05-19 | 2026-05-21 | 11 |
| Civil Law and Motion | 12 | 2026-05-15 | 2026-05-20 | 11 |
| Civil Law and Motion | 13 | 2026-05-08 | 2026-05-20 | 17 |
| Civil Law and Motion | 6 | 2026-05-19 | 2026-05-21 | 13 |
| Law and Motion | 1 | 2026-05-19 | 2026-05-21 | 17 |
| Probate Law and Motion | 2 | 2026-05-07 | 2026-05-18 | 4 |

</details>

<details>
<summary>Shasta - 133 rulings across 9 PDFs</summary>

| Division | Department | First hearing date | Last hearing date | Rows |
|---|---:|---:|---:|---:|
| Civil / Probate / Family Law | 24 | 2024-06-10 | 2024-06-10 | 1 |
| Civil / Probate / Family Law | 42 | 2026-05-04 | 2026-05-18 | 19 |
| Civil / Probate / Family Law | 6 | 2023-05-22 | 2023-05-22 | 1 |
| Conservatorships | 44 | 2026-05-18 | 2026-05-18 | 46 |
| Law and Motion | 53 | 2022-06-06 | 2022-06-06 | 9 |
| Law and Motion | 63 | 2026-05-18 | 2026-05-18 | 26 |
| Law and Motion | 64 | 2026-05-18 | 2026-05-18 | 22 |
| Law and Motion | Unspecified | 2026-05-01 | 2026-05-01 | 3 |
| Trusts | 44 | 2026-05-18 | 2026-05-18 | 6 |

</details>

<details>
<summary>Solano - 37 rulings across 7 PDFs</summary>

| Division | Department | First hearing date | Last hearing date | Rows |
|---|---:|---:|---:|---:|
| Civil | 3 | 2026-05-19 | 2026-05-22 | 5 |
| Civil | 7 | 2026-05-19 | 2026-05-22 | 12 |
| Civil | 8 | 2026-05-21 | 2026-05-21 | 5 |
| Probate / Civil | 22 | 2026-05-21 | 2026-05-21 | 14 |
| Probate / Civil | 5 | 2025-12-23 | 2025-12-23 | 1 |

</details>

## How It Works

1. The extension or `ingest.backfill` discovers public court material.
2. PDFs are fetched, hashed, and stored once at `archive/<county>/<sha[:2]>/<sha>.pdf`.
3. PDF fetches are logged in `archive/<county>/captures.ndjson`.
4. Contra Costa HTML page captures are stored at `archive/contra-costa/pages/<sha[:2]>/<sha>.html`.
5. HTML page captures are logged in `archive/contra-costa/page-captures.ndjson`.
6. Page-layout fingerprints are stored at `archive/<county>/layouts/<sha[:2]>/<sha>.json`.
7. Layout captures are logged in `archive/<county>/layout-captures.ndjson`.
8. `python -m ingest.orchestrate` parses archived material into Parquet.
9. `site/` loads Parquet files. It does not download archived PDFs on startup.

Re-capture is cheap. For ordinary PDF URLs, the extension skips URLs already logged. For Orange, Santa Clara, Shasta, and Tuolumne, it fetches and hashes first because courts reuse the same filenames while changing the contents. For Contra Costa HTML pages and layout fingerprints, only changed hashes are logged.

## Extension

Install the release zip for your browser. For Firefox development, load `extension/` unpacked. For Chrome side-panel development, use the Chrome release zip generated by the extension workflow.

Open Settings and set a GitHub token with Contents read/write access. Owner, repo, and branch default to `aimesy/tentatives@master`.

The side panel can:

- upload PDFs from the active supported court tab;
- fetch one listed court page;
- scan every page for one county;
- scan selected counties, with all configured counties selected by default;
- shell-scan selected counties in parallel browser tabs, pausing if a page needs manual attention;
- pause, resume, or stop a long scan;
- retry a failed landing page three times before moving on.
- document page layout fingerprints the first time a page is scanned, then again only when the structure changes.

Contra Costa should be opened through the public court pages, not the internal iframe URLs. The extension keeps `cc-courts.org` permission because the official Contra Costa pages load that host in an iframe, and the content script must read the frame.

## Backfill

Run live or Wayback capture from the command line:

```bash
python -m ingest.backfill --county all --live --continue-on-error
python -m ingest.backfill --county all --wayback --continue-on-error --limit 25 --dry-run
python -m ingest.backfill --county amador --wayback --url-from-year 2020 --url-to-year 2022
python -m ingest.backfill --county orange --live --wayback --limit 25
```

`--county all` means the CLI-backed counties. It does not include browser-only flows that need an iframe or active page execution.

The GitHub workflow runs live capture daily. It also runs a bounded Wayback check weekly because current URLs may acquire archived versions later.

Wayback has not been broadly backfilled yet. The local archive currently shows one Wayback row, for Amador. Start bounded, then widen.

## Parse

Install dependencies and run tests:

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt pytest
pytest
python -m ingest.orchestrate --dry-run
```

Run one county:

```bash
python -m ingest.orchestrate --county contra-costa --dry-run
python -m ingest.orchestrate --county contra-costa --reparse-existing --dry-run
python -m ingest.orchestrate --max-sources-per-county 50
```

By default, `ingest.orchestrate` skips source hashes already represented in Parquet. Use `--reparse-existing` for parser migrations. The Actions workflow parses at most 50 new sources per county per run so archive bursts do not turn into long failing jobs. The parser registry is intentionally narrow. Capture-only counties stay in the archive until a parser has fixtures and tests.

## Layout

```text
schema/                          shared Capture and Ruling records
counties/<county>/scraper.py     discovery and parser code
counties/<county>/tests/         fixtures and parser/discovery tests
ingest/backfill.py               live and Wayback capture into archive/
ingest/orchestrate.py            archive -> data/<county>/rulings.parquet
archive/<county>/captures.ndjson PDF capture provenance
archive/<county>/pages/          changed HTML page captures, currently Contra Costa
archive/<county>/layouts/        changed page-layout fingerprints
data/<county>/rulings.parquet    normalized rows for the viewer
extension/                       browser capture extension
site/                            static viewer
```

## Adding A County

1. Add `counties/<slug>/__init__.py` with `COUNTY_SLUG` and `PARSER_VERSION`.
2. Add discovery in `counties/<slug>/scraper.py`.
3. Add fixture HTML and discovery tests.
4. Add parser tests only after you have representative source files.
5. Implement `parse(...) -> list[Ruling]`.
6. Register the parser in `ingest/orchestrate.py`.
7. Add extension support only when the browser path is needed or useful.

Filename and link-text hints are allowed for capture. Parser facts should come from the source document or page text whenever possible.

## Sharp Edges

- Capture support is not parser support.
- Existing rows are keyed by `ruling_id`; changing `parser_version` alone does not force a reparse.
- `captures.ndjson` may contain several rows for one SHA.
- Nevada can publish `.docx`; this repo is still PDF-first.
- Contra Costa page captures are normalized as page rows, not as PDF rulings.
- Login-backed or authenticated systems are out of scope unless there is a public lawful access path.
