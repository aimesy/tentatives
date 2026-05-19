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
site/                            Static viewer (hyparquet, no backend)
.github/workflows/parse.yml      auto-runs orchestrator on new PDFs
.github/workflows/site.yml       deploys site/ + data/*.parquet to Pages
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
2. **Chrome**: `chrome://extensions` → **Developer mode** on → **Load unpacked** → pick the unzipped folder.
   **Firefox**: `about:debugging` → **This Firefox** → **Load Temporary Add-on** → pick the unzipped folder's `manifest.json`.
3. Click the extension's icon → **Settings**.
4. Paste a GitHub PAT — fine-grained with **Contents: Read and write** on this repo ([create one](https://github.com/settings/tokens?type=beta)), or classic with `repo`. Set owner = `aimesy`, repo = `tentatives`. Click **Test connection** to verify the PAT before uploading.
5. Visit a supported court page:
   - El Dorado: `https://www.eldorado.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-dept-<N>`
   - Placer: any page under `https://www.placer.courts.ca.gov/` that links to PDFs.
   - Contra Costa: `https://contracosta.courts.ca.gov/online-services/tentative-rulings` (the page is mostly an iframe loading `cc-courts.org` with many collapsibles — the extension expands them and harvests PDFs from every dept).
6. Click the extension icon → **Upload**. The popup shows live progress per PDF; the badge on the icon shows how many PDFs are on the current page.

The extension dedups by source URL — if a PDF was uploaded before, the next visit skips the download entirely. PDFs are stored content-addressable (`archive/<county>/<sha[:2]>/<sha>.pdf`), so re-captures of the same content from different URLs only write one file.

Each upload is one commit via the Contents API. Switching to batched commits (Git Data API) is a planned upgrade for bulk Wayback backfills.

## Site viewer

`site/` is a static, single-page viewer that loads `data/<county>/rulings.parquet` straight from the browser using [hyparquet](https://github.com/hyparam/hyparquet). No backend, no SQL engine bundled — just one fetch per county plus client-side filter/sort/page.

To run locally:

```bash
# Serve from the repo root so site/index.html and data/<county>/ are siblings.
python -m http.server 8000
# → http://localhost:8000/site/
```

The page detects whether it's served at the repo root (dev) or alongside `data/` (the Pages build) and adjusts the parquet URL accordingly. Filters round-trip through query parameters, so the **Copy link** button gives you a shareable URL of any view.

The Pages deploy is wired up in `.github/workflows/site.yml` and ships at `https://<owner>.github.io/<repo>/` on every push to `main`/`master` that touches `site/` or `data/`.

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
- [x] El Dorado parser — 4 styles (probate dept-9, law&motion dept-4, probate dept-4, family-law dept-12); 27 tests
- [x] Contra Costa parser — 5 depts (09, 10, 14, 16, 18); 8 tests
- [x] Placer parser — 3 fixtures across depts 3, 33, 42; 7 tests
- [x] Ingest orchestrator with idempotent append, idempotent re-parse
- [x] Browser extension (MV3) — Chrome + Firefox compatible; EDC + Placer + Contra Costa site adapters; cross-origin iframe + collapsible expansion; URL-based dedup; streaming progress
- [x] Auto-zip workflow publishing `tentatives-extension.zip` at stable release URL
- [x] GitHub Action to auto-parse on push (`.github/workflows/parse.yml`)
- [x] Static site viewer (`site/`) — hyparquet, filter / sort / paginate, deep-link to PDF page
- [x] GitHub Pages deploy workflow (`.github/workflows/site.yml`)
- [ ] Wayback backfill mode (`discover_wayback`, batched Git Data API commits)
- [ ] More counties (Marin, Sonoma; forward-only OC/SC/San Mateo)
- [ ] Unified cross-county `data/index.parquet`
