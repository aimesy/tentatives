---
title: Parser output audit, 2026-06-08
visibility: public
classification: project-audit
period: 2026-06-08
sources: data/*/rulings.parquet; archive/*; schema/ruling.py; README.md; LIVE.md; county parser tests and scraper modules
---

# Parser output audit, 2026-06-08

Audit scope: every `data/<county>/rulings.parquet` output present locally, with county and department/source subdivisions checked for schema completeness, counts, date ranges, required fields, IDs, source URLs, source/archive consistency, short text bodies, text artifacts, and outcome distributions. This was an audit only; no parser code or data output files were changed.

## Executive findings

1. The normalized schema is present for all 17 counties, and all rows use valid outcome enum values. No row has a future hearing date after 2026-06-08.
2. There are two duplicate `ruling_id` problems:
   - El Dorado has one duplicated ID for two different probate matters in the same source/ruling index: `06f69fa47ed3391d61cf0843fb979476`, 2026-05-01, source `eef240...af1c5`, index 1, cases `22PR0258` and `25PR0007`.
   - Placer has one exact duplicate row: `fdbfe52a4680c1776d68db35783c0e89`, 2026-05-29, source `d5aff0...e10c`, index 1, case `S-CV-0050336`.
3. Calaveras has 12 impossible-looking pre-2010 hearing dates. The source URLs are 2024/2025 PDFs, but the parsed dates are `2000-10-12` or `2004-06-28`. Example: source `1-24-25-lm-tentative-rulings.pdf` parsed as 2000-10-12 for case `24CV47497`.
4. Several counties have `source_url` fallback values of `archive://...` rather than court HTTP URLs: Orange 29 rows, San Bernardino 52 rows, Solano 18 rows. That is expected from `ingest.orchestrate` when capture metadata is absent, but it means those rows lack court URL provenance in the normalized output.
5. Local archive provenance is uneven. Counties with committed `captures.ndjson` and source files line up cleanly: Calaveras, Fresno, Merced, Nevada, Plumas, Riverside, San Bernardino, Tuolumne. Counties without local capture logs/source files currently cannot be fully source-audited from this checkout: Amador, Contra Costa, El Dorado, Orange, Placer, San Francisco, Santa Clara, Shasta, Solano.
6. Per-ruling PDF slices are missing for the same no-source/no-capture group, plus San Francisco/Santa Clara/Shasta/Solano, but present for Calaveras, Fresno, Merced, Nevada, Plumas, Riverside, San Bernardino, and Tuolumne.
7. `body_text` is not a reliable narrative field across counties. Many parsers intentionally set it blank or use it for judge/time metadata. `full_text` is the meaningful text field for most counties. True short `full_text` issues are concentrated in Merced, Orange, Santa Clara, and isolated Calaveras/Nevada rows.
8. The top LIVE totals match the current data (`17,615` rows, 17 counties, range `2000-10-12` to `2026-06-08`), but detailed county sections in `README.md` are stale for multiple counties. I did not refresh README because this audit was restricted to one report file.

## Aggregate county checks

`short_body` means `body_text` length under 20 after trimming. It is a useful consistency signal but not always a parser defect because several parser modules explicitly set `body_text=""`.

| County | Rows | Sources | Date range | Pre-2010 | Blank division | Blank dept | Blank motion | Blank outcome text | Blank body | Short body | Blank title | Text artifacts | Duplicate IDs | Duplicate source/index | Bad source URL shape | Missing slices |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| amador | 206 | 31 | 2015-09-21 to 2022-05-11 | 0 | 32 | 48 | 206 | 0 | 15 | 30 | 0 | 0 | 0 | 2 | 0 | 206 |
| calaveras | 9,200 | 577 | 2000-10-12 to 2026-06-05 | 12 | 0 | 9,200 | 181 | 9 | 9,200 | 9,200 | 185 | 49 | 0 | 0 | 0 | 0 |
| contra-costa | 2,188 | 151 | 2025-11-20 to 2026-06-08 | 0 | 230 | 0 | 316 | 10 | 582 | 1,553 | 0 | 44 | 0 | 10 | 0 | 2,188 |
| el-dorado | 656 | 71 | 2017-06-16 to 2026-06-08 | 0 | 184 | 43 | 274 | 1 | 45 | 45 | 0 | 2 | 1 | 1 | 0 | 656 |
| fresno | 162 | 37 | 2026-05-07 to 2026-06-04 | 0 | 0 | 0 | 6 | 0 | 162 | 162 | 0 | 2 | 0 | 0 | 0 | 0 |
| merced | 237 | 18 | 2023-03-17 to 2026-06-08 | 0 | 0 | 28 | 48 | 26 | 237 | 237 | 0 | 0 | 0 | 0 | 0 | 0 |
| nevada | 689 | 70 | 2026-01-12 to 2026-06-08 | 0 | 0 | 266 | 549 | 1 | 689 | 689 | 0 | 1 | 0 | 0 | 0 | 0 |
| orange | 1,480 | 168 | 2023-09-15 to 2026-06-08 | 0 | 1 | 75 | 1,332 | 19 | 500 | 1,190 | 95 | 57 | 0 | 0 | 29 | 1,480 |
| placer | 374 | 33 | 2026-02-27 to 2026-06-08 | 0 | 67 | 0 | 0 | 160 | 374 | 374 | 0 | 1 | 1 | 1 | 0 | 374 |
| plumas | 113 | 6 | 2025-12-22 to 2026-06-08 | 0 | 0 | 0 | 31 | 0 | 113 | 113 | 0 | 0 | 0 | 0 | 0 | 0 |
| riverside | 83 | 26 | 2026-06-05 to 2026-06-08 | 0 | 0 | 0 | 0 | 0 | 83 | 83 | 0 | 3 | 0 | 0 | 0 | 0 |
| san-bernardino | 104 | 82 | 2022-12-10 to 2026-06-04 | 0 | 0 | 0 | 40 | 0 | 104 | 104 | 2 | 4 | 0 | 0 | 52 | 0 |
| san-francisco | 250 | 34 | 2026-03-26 to 2026-06-04 | 0 | 0 | 0 | 9 | 0 | 0 | 232 | 0 | 1 | 0 | 0 | 0 | 250 |
| santa-clara | 543 | 79 | 2024-06-24 to 2026-06-05 | 0 | 0 | 0 | 465 | 124 | 6 | 413 | 19 | 21 | 0 | 18 | 0 | 543 |
| shasta | 1,101 | 58 | 2022-06-06 to 2026-06-08 | 0 | 0 | 161 | 170 | 170 | 219 | 1,101 | 0 | 3 | 0 | 0 | 0 | 1,101 |
| solano | 212 | 47 | 2023-12-28 to 2026-06-08 | 0 | 0 | 0 | 11 | 1 | 3 | 212 | 0 | 20 | 0 | 0 | 18 | 212 |
| tuolumne | 17 | 1 | 2026-06-03 to 2026-06-03 | 0 | 0 | 0 | 1 | 1 | 17 | 17 | 0 | 2 | 0 | 0 | 0 | 0 |

## County and department notes

### Amador

206 rows across 31 source hashes, date range 2015-09-21 to 2022-05-11. Departments/divisions are plausible for legacy Amador output: Child Support, Civil Case Management Conference, Family Law Case Management, Law and Motion, Civil Law and Motion, plus 32 rows with blank division and 48 rows with blank department. All 206 rows have blank `motion_type`, which appears consistent with parser style rather than a sporadic extraction failure. There are two duplicate `(county, source_sha256, ruling_index)` combinations but no duplicate `ruling_id`; these should be inspected if Amador gets cleaned up.

Local source provenance is incomplete in this checkout: no `archive/amador/captures.ndjson`, no matching source files by SHA, and no per-ruling slices.

### Calaveras

9,200 rows across 577 source hashes. Department is blank for all rows; division/source subdivisions are nevertheless visible as Case Management, Civil Case Management, Family Law Case Management, and Civil Law and Motion. The dominant department-level issue is that there is no department dimension at all, which may be acceptable if Calaveras does not publish department-level tentative files.

High-priority defects:
- 12 pre-2010 hearing dates are implausible. Two rows from a 2025 source parsed as 2000-10-12; ten rows from a 2024 source parsed as 2004-06-28.
- 185 blank case titles, 9 blank `outcome_text`, and 49 rows with mojibake/artifact markers.
- `body_text` is blank for all rows, but `full_text` is generally populated. One row has `full_text` under 50 characters.

Archive consistency is good locally: captures exist, source hashes are represented, and per-ruling PDF slices exist.

### Contra Costa

2,188 rows across 151 source hashes, date range 2025-11-20 to 2026-06-08. Departments are present, with primary Law & Motion departments 09, 10, 14, 16, 18, 32, 34, 39, Discovery 34, and several unspecified departments including 20 and 57. This makes sense for Contra Costa's mix of PDF and page-derived sources.

Issues:
- Division labels include embedded newlines and case variants such as `Law & Motion \nAdd On`, `Law & Motion Add ON`, and `Law & Motion \nAdd on 2`. This is mostly normalization debt, not necessarily bad parsing.
- 230 blank divisions and 316 blank motion types.
- 10 duplicate `(county, source_sha256, ruling_index)` combinations.
- 44 rows with text artifact markers.

Local source provenance is not auditable here: no capture log/source files/slices are present in this checkout for Contra Costa.

### El Dorado

656 rows across 71 source hashes, date range 2017-06-16 to 2026-06-08. Department/division distribution is mostly plausible: Law and Motion departments 4, 5, 12; Probate departments 4, 8, 9; and some unspecified division/dept rows.

High-priority defect:
- Duplicate `ruling_id` `06f69fa47ed3391d61cf0843fb979476` maps to two different probate cases from the same source and index: `22PR0258 ESTATE OF ARANDA DE RAMIREZ` and `25PR0007 GUARDIANSHIP OF SEBASTIAN Q.` This indicates the row identity algorithm or ruling indexing failed for that source.

Other notes: 184 blank divisions, 43 blank departments, 274 blank motion types, 45 blank bodies, and 45 rows where body contains boilerplate or is effectively empty. Local source provenance/slices are absent in this checkout.

### Fresno

162 rows across 37 source hashes, date range 2026-05-07 to 2026-06-04. Departments 403, 501, 502, and 503 look consistent with Fresno civil law and motion PDFs. Outcomes look plausible: continued 65, denied 44, granted 30, off calendar 20, other 3.

`body_text` is blank for all rows by parser design, but `full_text` is populated. Six blank motion types and two artifact rows are minor follow-up items. Captures, source files, and per-ruling slices are locally consistent.

### Merced

237 rows across 18 source hashes, date range 2023-03-17 to 2026-06-08. Departments 8, 9, 10, 12, 1, 2 and unspecified appear across Case Management Conference, Civil Law and Motion, and Short Cause Court Trials.

Issues:
- 13 rows have `full_text` under 50 characters. These appear to be court address blocks misparsed as rows, with `case_number` like `2260 N Street, Merced` and `case_title` like `627 W. 21st Street, Merced`.
- 28 blank departments, 48 blank motions, and 26 blank outcome texts.
- `body_text` is blank for all rows by parser design.

Archive provenance and slices are consistent locally.

### Nevada

689 rows across 70 source hashes, date range 2026-01-12 to 2026-06-08. Divisions cover Case Management, Law and Motion, Probate, Guardianship, and supported DOCX CMC output. Department values include 6, A, and unspecified, plausibly reflecting Nevada's locations/department hints.

Issues are moderate: 266 blank departments, 549 blank motion types, 1 blank `outcome_text`, and 1 very short `full_text` row. The short row is a bare case line for `CU0002305 Christ, Jason v. Hannah, Jordan`. Captures, source files, and slices are consistent locally.

### Orange

1,480 rows across 168 source hashes, date range 2023-09-15 to 2026-06-08. Department distribution is broad and plausible for Orange: Civil departments such as C11, C12, C13, C15, C23, C25, C32, C33, CX103, CX105, N14, N15, W15, plus Probate and Family Law departments.

Issues:
- 1,332 blank motion types. This appears structural for the Orange parser, but it materially limits search/filter quality.
- 95 blank case titles, 19 blank outcome texts, and 57 artifact rows.
- 14 rows have `full_text` under 50 characters; several are plausible off-calendar/no-tentative entries, but several look chopped.
- 29 rows use `archive://orange/...pdf` as `source_url`, indicating missing capture URL provenance.
- Local source files and slices are absent in this checkout.

### Placer

374 rows across 33 source hashes, date range 2026-02-27 to 2026-06-08. Departments include Civil Law and Motion 3, 14, 33, 42 and probate/unspecified 30, 32, 40. That is broader than the current README detail and appears plausible for Placer.

High-priority defect:
- Exact duplicate row `fdbfe52a4680c1776d68db35783c0e89`, case `S-CV-0050336 BAL, GURMAN v. AMERIO, ASHLEY`, 2026-05-29, department 14.

Other notes: 67 blank divisions, 160 blank outcome texts, and all 374 rows have blank body text. Local source files/slices are absent in this checkout.

### Plumas

113 rows across 6 source hashes, date range 2025-12-22 to 2026-06-08. All rows are Department 2 and split among Case Management Conference, Law and Motion, and Probate. This looks coherent for Plumas Department 2 PDFs.

Minor issues: 31 blank motion types and blank `body_text` by parser design. Archive provenance and slices are consistent locally.

### Riverside

83 rows across 26 source hashes, date range 2026-06-05 to 2026-06-08. Departments 1, 2, 3, 4, 5, 6, 10, C1, M301, MV1, PS1, PS2, R5, R8, RI, SW look plausible for Riverside regional/department PDFs.

No schema or provenance defects found. `body_text` is blank by parser design. Three rows have text artifact markers. Archive provenance and slices are consistent locally.

### San Bernardino

104 rows across 82 source hashes, date range 2022-12-10 to 2026-06-04. Departments R12, R17, S14, S17, S22, S24, S29, S36, S37 look plausible for the civil table/list source.

Issues:
- 52 rows have `archive://san-bernardino/...pdf` fallback `source_url` values. Captures and source files exist locally, so this probably reflects missing capture rows for those particular legacy files or parse path fallback, not absent source bytes.
- 40 blank motion types and 2 blank case titles.
- `body_text` is blank by parser design.

Per-ruling slices are present.

### San Francisco

250 rows across 34 source hashes, date range 2026-03-26 to 2026-06-04. This dataset is correctly limited to UFC Family Law departments 403, 404, and 414. Department distribution: 403 has 127 rows, 404 has 118, and 414 has 5.

Issues are mostly provenance-related: no local capture log/source files/slices in this checkout. `body_text` is populated with judge metadata, not ruling narrative, so 232 short bodies are expected. One artifact row found.

### Santa Clara

543 rows across 79 source hashes, date range 2024-06-24 to 2026-06-05. Department distribution includes Civil Law and Motion departments 6, 10, 12, 13, 16; Law and Motion 1 and 19; Complex Civil 22; Probate Law and Motion 2.

Issues:
- 18 duplicate `(county, source_sha256, ruling_index)` combinations even though no duplicate `ruling_id`; inspect whether multi-motion rows are being indexed too coarsely.
- 465 blank motion types and 124 blank outcome texts.
- 19 blank/suspicious case titles.
- 7 rows have very short `full_text`, including rows where the title is only punctuation such as comma/and fragments.
- 21 artifact rows.
- Local source files/slices are absent in this checkout.

### Shasta

1,101 rows across 58 source hashes, date range 2022-06-06 to 2026-06-08. Divisions/departments look coherent for Shasta: Law and Motion 63/64/53, Conservatorships 44, Trusts 44, Civil / Probate / Family Law 42, plus unspecified groups from older or differently formatted sources.

Issues:
- 161 blank departments, 170 blank motions, and 170 blank outcome texts.
- `body_text` is short for all rows because the parser stores the hearing time or blank, not the ruling narrative.
- Local source files/slices are absent in this checkout.

### Solano

212 rows across 47 source hashes, date range 2023-12-28 to 2026-06-08. Departments 3, 7, 8, 22, 5 and divisions Civil / Probate-Civil look plausible.

Issues:
- 18 rows use `archive://solano/...pdf` fallback `source_url` values.
- 20 artifact rows.
- `body_text` is judge metadata or blank, so all 212 rows are short by that metric.
- Local source files/slices are absent in this checkout.

### Tuolumne

17 rows across 1 source hash, all Civil Law and Motion Department 2 on 2026-06-03. This is a small, coherent output. One blank motion type, one blank outcome text, and two artifact rows. Captures, source files, and slices are consistent locally.

## Outcome distribution notes

No county has invalid outcome enum values. Outcome distributions are generally plausible, but these counties are worth reviewing for classifier usefulness rather than hard correctness:

- Calaveras: `other` is 6,988/9,200 rows (76.0%), suggesting weak disposition classification for that county.
- Santa Clara: `other` is 303/543 rows (55.8%), plus 124 blank outcome texts.
- Tuolumne: `other` is 9/17 rows (52.9%), small sample.
- San Bernardino: `denied` is 62/104 rows (59.6%), plausible for law-and-motion but high enough to spot-check.
- Amador and Plumas have many `appearance_required` rows, which appears plausible because those calendars often say no tentative ruling or appearance/hearing required.

## Tooling and validation limits

Validated successfully:
- Loaded every local Parquet file with pandas.
- Checked required columns against `schema/ruling.py`.
- Checked outcome enum values, date ranges, duplicate IDs, duplicate source/ruling indexes, URL shape, blank required fields, short text, text artifacts, division/department distributions, parser versions/styles, and archive/slice path presence.
- Compared parser code enough to confirm that blank or short `body_text` is intentional for several counties.

Could not fully validate:
- Live source URL reachability. I checked URL shape, not HTTP status, because this was an output audit and broad live court requests were not necessary.
- Source PDF content for counties whose source archives are absent in this checkout.
- Full test suite status. `pytest counties ingest -q` did not complete before the 124 second timeout, so no pass/fail result is available from that run.
- Subagent parallel audit. No Agent tool was available in this Codex toolset, so I used parallel shell reads/validation instead.

## Recommended follow-up order

1. Fix or reparse the two duplicate-ID cases, starting with El Dorado because it merges two distinct matters under one ID.
2. Investigate Calaveras date parsing for 2024/2025 law-and-motion sources that become 2000/2004.
3. Restore or regenerate capture metadata/source archives for counties with `archive://` source URLs and missing local source/slice files.
4. Inspect Merced address-block rows and Santa Clara punctuation-title rows as likely false positives.
5. Normalize Contra Costa add-on division labels and review Santa Clara duplicate source/index rows.
6. Decide whether `body_text` should be redefined or ignored in the viewer/API, because current county parsers use it inconsistently.
