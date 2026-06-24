# Parser Output Audit - 2026-06-24

Six jurisdictional/source batches audited the archive, live surfaces, Wayback
coverage, parser output, and ruling-slice links. The current local data is the
post-audit state.

## Validation

After parser fixes, live capture, reparsing, duplicate cleanup, and slice
generation, the row-link checks pass across 18,076 parsed rows in 32 counties:

- Duplicate exact row keys after cleanup: 0 affected counties.
- Missing per-ruling slice PDFs: 0.
- Invalid PDF page ranges: 0 across 17,037 PDF-backed rows checked.
- Full test suite: `261 passed`.
- Focused ingest/backfill/discovery tests: `47 passed`.

## Current Row Counts

| County | Rows |
|---|---:|
| Amador | 203 |
| Butte | 308 |
| Calaveras | 5,509 |
| Contra Costa | 2,367 |
| El Dorado | 821 |
| Fresno | 278 |
| Los Angeles | 398 |
| Marin | 52 |
| Merced | 326 |
| Monterey | 7 |
| Napa | 48 |
| Nevada | 760 |
| Orange | 1,982 |
| Placer | 541 |
| Plumas | 178 |
| Riverside | 339 |
| San Benito | 24 |
| San Bernardino | 196 |
| San Francisco | 325 |
| San Luis Obispo | 80 |
| San Mateo | 120 |
| Santa Barbara | 403 |
| Santa Clara | 808 |
| Santa Cruz | 11 |
| Shasta | 1,305 |
| Sierra | 1 |
| Solano | 370 |
| Sonoma | 208 |
| Stanislaus | 10 |
| Tulare | 21 |
| Tuolumne | 17 |
| Ventura | 60 |

## New Parser Coverage

The audit moved the following real misses from raw archive or page snapshots to
normalized rows:

- PDF parsers: Butte, Marin, Monterey, Napa, San Benito, San Luis Obispo, San
  Mateo, Santa Cruz, Sierra, Tulare probate PDFs, and Ventura.
- HTML/page parsers: Los Angeles result pages, Santa Barbara detail pages,
  Sonoma civil/family/probate pages, Stanislaus pages, and Tulare civil page.
- Mixed source fixes: Yolo document-page/PDF probing is implemented, but the
  current live run exposed only shell pages and no broad ruling refs.

## Link And Slice QA

`ingest.slice_rulings` now creates text-backed ruling PDFs when the original
source is an HTML page or otherwise not a source PDF/DOCX. That keeps viewer
links valid for both PDF-backed and page-backed rows.

The post-slice audit found no missing slice files and no invalid PDF page spans.
`ingest.orchestrate` now also skips logical duplicate recaptures across changed
source URLs or recaptured HTML chrome by checking county, case number, hearing
date, motion text, and ruling body.

## Wayback And Reverse-Engineered URLs

The backfill lane now supports exact current URLs, prefix-style URL families,
and county-specific reverse-engineered patterns. The pattern set includes
static court-hosted PDF paths, known Google Drive download URLs, Sonoma and
Santa Cruz/Sierra Drive IDs, Santa Barbara detail pages, and other non-extension
Wayback URLs only where a county declares that shape safe.

Targeted dry runs confirmed the implementation path, but the Internet Archive
CDX service was spotty during this pass:

- Butte 2026 Wayback dry run returned 0 refs.
- San Mateo 2026 Wayback dry run hit CDX 503/504 responses.
- Sierra 2026 Drive-ID Wayback dry run hit CDX 504.
- Santa Cruz Wayback dry run timed out.

The scheduled workflow keeps a bounded weekly Wayback run so those URL families
will be retried without blocking daily live capture.

## Remaining Real Gaps

- Imperial: official public surface exists, but current postings are too sparse
  for a representative parser row. Keep daily capture and parse once real row
  PDFs appear.
- Yolo: page capture and document/PDF probing are implemented, but the latest
  live run captured only two shell pages and no ruling refs.
- San Diego: likely public ROA/document access exists, but it is not a simple
  countywide feed and needs a careful terms/cookie/session pass.
- Alameda, Kings, Mendocino, Sacramento, and broad San Joaquin remain blocked
  or case-led absent a lawful public broad-list path.

## Form-Language Follow-Up

The project still does not have SFSC-viewer-style normalized boilerplate
segregation. Current parsers strip or avoid some admin-only packets and obvious
court instructions, but repeated form language still lives inside many
`body_text` values. A future schema/viewer pass should add fields such as
`form_language`, `notice_text`, or `admin_text` if this repo wants the same
presentation split as `sfsc-tentatives`.
