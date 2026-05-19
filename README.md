# tentatives

Open-source archive of California superior court **tentative rulings**, expanded across multiple counties. Originals are stored content-addressable in the repo, parsed into per-county parquet, and searchable in the browser.

This repo is a generalisation of [`aimesy/sfsc-tentatives`](https://github.com/aimesy/sfsc-tentatives) (San Francisco, ~190K rulings) to other counties. First non-SF target: **El Dorado** (Probate, Dept. 9 fixture included).

## How it works

```
       ┌──────────────────┐     extension visits a court page,
       │ browser extension│ ──▶ scrapes PDF links, hashes,
       └──────────────────┘     PUTs to GitHub Contents API
                │
                ▼
       ┌──────────────────┐     content-addressable:
       │  archive/<county>│     archive/<county>/<sha[:2]>/<sha>.pdf
       │   *.pdf + .ndjson│     captures.ndjson logs source URLs
       └──────────────────┘
                │
                ▼  (GitHub Action: .github/workflows/parse.yml)
       ┌──────────────────┐     ingest/orchestrate.py walks archive,
       │ data/<county>/   │     parses any new PDFs, appends to
       │ rulings.parquet  │     rulings.parquet
       └──────────────────┘
                │
                ▼
       ┌──────────────────┐     static site, DuckDB-WASM,
       │ site/  (TODO)    │     links every ruling back to its PDF
       └──────────────────┘
```

The court's live site purges old URLs (~2 months of retention for EDC), so the same content can have multiple capture sources over time — the same sha256 is one file, many `captures.ndjson` rows.

## Repo layout

```
schema/                          Ruling/Capture dataclasses, cross-county
counties/<county>/scraper.py     discover_live, fetch, parse
counties/<county>/fixtures/      sample PDFs + HTML for tests
counties/<county>/tests/         pytest, runs against fixtures
ingest/orchestrate.py            CLI: parse archive → rulings.parquet
archive/<county>/<sha[:2]>/      content-addressable PDF store
archive/<county>/captures.ndjson append-only log of fetch events
data/<county>/rulings.parquet    one row per (case × motion)
extension/                       Chrome MV3 capture extension
.github/workflows/parse.yml      auto-runs orchestrator on new PDFs
.github/workflows/test.yml       runs parser tests on PRs
```

## Adding a new county

1. Create `counties/<slug>/`.
2. Implement `discover_live(html)` and `parse(pdf_bytes, source_url, source_sha256)` in `scraper.py`. Return `list[Ruling]`. Take metadata from PDF content, not filenames — filenames are often inconsistent.
3. Drop a sample PDF and HTML index page into `fixtures/`.
4. Write tests asserting ruling count, case-number formats, outcome classification, page spans.
5. Add the parser to `PARSERS` in `ingest/orchestrate.py`.
6. Add a content script to `extension/sites/<slug>.js` and a host pattern to `extension/manifest.json`.

The El Dorado implementation is the reference. Filename heuristics live entirely inside that scraper — every county will have its own — but the output `Ruling` schema is shared.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest

# Run parser tests
pytest counties/

# Parse anything new in archive/
python -m ingest.orchestrate
python -m ingest.orchestrate --county el-dorado --dry-run

# Query the parquet
python -c "import duckdb; print(duckdb.sql(\"SELECT outcome, COUNT(*) FROM 'data/el-dorado/rulings.parquet' GROUP BY 1\"))"
```

## Loading the extension

**[⬇ Download the latest extension zip](https://github.com/aimesy/tentatives/releases/download/extension-latest/tentatives-extension.zip)** — rebuilt automatically on every push to `master` that touches `extension/`.

1. Download `tentatives-extension.zip`, unzip somewhere stable (the folder must stay where Chrome can read it).
2. `chrome://extensions` → **Developer mode** on → **Load unpacked** → pick the unzipped folder.
3. Click the extension's icon → **Settings**.
4. Paste a GitHub PAT (`repo` scope, or fine-grained with `contents:write` on this repo). Set owner = `aimesy`, repo = `tentatives`, branch = the branch you want commits to land on.
5. Visit a supported court page (e.g. `https://www.eldorado.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-dept-9`).
6. Click the extension icon → **Upload**. The popup shows progress per PDF; the badge shows how many PDFs are on the current page.

Alternatively, clone the repo and load `extension/` directly as the unpacked extension folder (useful for development).

Each upload is one commit (Contents API). Switching to batched commits (Git Data API) is a planned upgrade for bulk Wayback backfills.

## Schema

`data/<county>/rulings.parquet` columns (full definitions in `schema/ruling.py`):

| column | type | notes |
|---|---|---|
| `ruling_id` | str | `sha256(source_sha256 + ruling_index)[:32]`. Stable across re-parses. |
| `county` | str | slug, e.g. `el-dorado` |
| `division` | str | `Probate`, `Civil`, `Family Law`, … |
| `dept` | str | court department number |
| `hearing_date` | date | from PDF page header, **not** filename |
| `ruling_index` | int | 1-based position in source PDF |
| `case_number` | str | e.g. `25PR0206`, `PP20200121` |
| `case_title` | str | e.g. `MATTER OF ANDRESEN TRUST` |
| `motion_type` | str | as printed |
| `outcome` | str | `granted` \| `denied` \| `continued` \| `appearance_required` \| `off_calendar` \| `other` |
| `outcome_text` | str | raw disposition text (remote-appearance boilerplate stripped) |
| `conditional` | bool | True for "ABSENT OBJECTION … GRANTED" |
| `continued_to` | date \| null | next hearing date if `outcome == continued` |
| `body_text` | str | narrative between header and TENTATIVE RULING marker |
| `full_text` | str | per-ruling slice of the PDF, page headers stripped |
| `page_start`, `page_end` | int | for `?page=N` deep links |
| `source_sha256` | str | FK into the archive |
| `source_url` | str | canonical court URL |
| `parser_version` | str | e.g. `el-dorado-v1` — bump to force re-parse |
| `ingest_ts` | str | ISO 8601 |

## Status

- [x] Schema (`Ruling`, `Capture`)
- [x] El Dorado discover + parse against the live fixture (15 rulings, 4 outcome classes, two case-number formats incl. legacy)
- [x] Tests against the fixture (11 passing)
- [x] Ingest orchestrator with idempotent append
- [x] Browser extension (MV3, EDC adapter, GitHub Contents API)
- [x] GitHub Action to auto-parse on push
- [ ] Site / viewer (DuckDB-WASM + PDF.js)
- [ ] Wayback backfill mode (`discover_wayback`, batched Git Data API commits)
- [ ] More counties (Contra Costa, Marin, Placer, Sonoma; forward-only OC/SC/San Mateo)
- [ ] Unified cross-county `data/index.parquet`
