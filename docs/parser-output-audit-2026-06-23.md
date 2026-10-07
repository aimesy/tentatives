# Parser Output Audit - 2026-06-23

Six jurisdictional batches audited the archive and parsed rows:

- Amador, Calaveras, Contra Costa
- El Dorado, Placer, Solano
- Fresno, Merced, Tuolumne
- Nevada, Orange, San Francisco
- Plumas, Riverside, San Bernardino
- Santa Clara, Shasta, viewer links

## Validation

After parser fixes, reparsing, and forced slice regeneration, the row-link
invariant check passed across 20,866 parsed rows in 17 counties:

- Duplicate `ruling_id`: 0
- Missing source PDF/DOCX files for parsed rows: 0
- Missing per-ruling slice PDFs: 0
- Invalid PDF page ranges: 0

The full test suite passed: `251 passed`.

## Source Coverage

The earlier "missing two hundred-ish" issue was not a row-link problem. It was
archived source PDFs with no parquet row. The initial coverage pass found 526
unrepresented source PDFs, including 96 likely real parser misses. Those real
misses have been addressed where the source supports a reliable row.

Final source coverage now finds 380 unique archived source PDFs with no parquet
row. None are currently classified as a source-supported real parser miss.

| Bucket | Count |
|---|---:|
| Contra Costa probate examiner/calendar | 311 |
| Explicit no-ruling/unavailable notice | 23 |
| CMC/calendar-note style | 14 |
| Unsafe missing hearing date | 12 |
| Unsafe no printed case number | 10 |
| Calendar/motion-list only | 5 |
| Admin/form-language only | 3 |
| Blank template/no case rows | 2 |

The remaining unsafe files contain ruling-like language but lack source-supported
metadata needed for a normalized row. Examples include Calaveras one-off PDFs
whose filenames are only `728-clmc.pdf`, `84-clmc.pdf`, or
`silveira-demurrer-tentative-ruling.pdf`, a Solano `misc_dept.pdf` with no
hearing date, and several San Bernardino/Shasta/Santa Clara packets without a
printed case number. These should stay out of `rulings.parquet` unless a source
page, capture context, or court filename can supply the missing hearing date or
case number reliably.

## Current Row Counts

| County | Rows |
|---|---:|
| Amador | 206 |
| Calaveras | 9,370 |
| Contra Costa | 2,361 |
| El Dorado | 807 |
| Fresno | 246 |
| Merced | 303 |
| Nevada | 761 |
| Orange | 2,914 |
| Placer | 554 |
| Plumas | 188 |
| Riverside | 244 |
| San Bernardino | 184 |
| San Francisco | 312 |
| Santa Clara | 751 |
| Shasta | 1,305 |
| Solano | 343 |
| Tuolumne | 17 |

## Fixes Applied

- Viewer share/modal links use the unique `ruling_id` row key instead of the
  display-only short id, so duplicate-looking rows open the correct raw slice.
- Placer IDs include the section ordinal, fixing repeated case headers for
  separate motions in the same PDF.
- Fresno no longer lets continued-cover rows cross into unrelated no-tentative
  rows, and strips oral-argument boilerplate from motion labels.
- Merced recognizes `-APP` case-number suffixes and skips body related-case
  references as false anchors.
- Tuolumne handles no-timestamp Case Notes pages and avoids treating generic
  `Petition` body text as tracking metadata.
- Calaveras now handles short compact URL dates, single-digit compact URL dates
  such as `772023`, `Case No.` labels, bare legacy case numbers, legacy time-row
  calendars with or without AM/PM markers, and `In the Matter of` captions.
- Contra Costa handles URL filename date/department fallback and dotless index
  variants. Department 30/38 probate examiner calendars remain non-ruling
  source material unless modeled separately.
- El Dorado handles split-date normalization and multiline case-header fallback;
  no-ruling notices remain excluded.
- Orange handles reduced year case numbers, two-digit year case numbers, wrapped
  modern case numbers, ordinal dates, title-only rows, multi-date packets, and
  table row anchors. It now excludes admin-only and blank-template PDFs instead
  of producing false rows.
- Nevada handles single-case packets where the hearing date is only in the
  source URL.
- Riverside splits embedded table-header blocks and recognizes `Summary of
  Ruling:` sections.
- San Bernardino handles spaced `CIVSB` numbers and `LLTSB` unlawful detainer
  numbers. The remaining R17 packets have no printed case number.
- Santa Clara avoids false case numbers from addresses/citations, recognizes
  additional formal/date styles, and parses formal order-style packets. Remaining
  one-offs lack a reliable hearing date or printed case number.
- Shasta recognizes `20UD0069`-style case numbers and mixed-case `v.` captions.
- Solano recognizes legacy `FCS058890` case numbers.
- Plumas recognizes ordinal hearing dates such as `March 9th, 2026`.

## Form-Language Follow-Up

The project is not yet doing SFSC-viewer-style boilerplate/form-language
segregation in a normalized way. The current `Ruling` schema has
`outcome_text`, `body_text`, and `full_text`, but no dedicated
`form_language`, `notice_text`, or `admin_text` field. Some parsers strip or
avoid county-specific boilerplate ad hoc, and Orange now excludes admin-only
packets, but repeated court instructions still live inside many row bodies.

Recommended follow-up: add a normalized boilerplate/admin-text lane and viewer
treatment analogous to the SFSC tentative viewer, then migrate repeated
appearance, court-reporter, remote-hearing, submission, and local-rule language
out of per-row ruling bodies where it is repeated across a packet or department.

## Known Follow-Up

No source/slice/page-link failures remain for rows that exist. The open product
questions are now semantic, not link-integrity bugs:

- Decide whether Contra Costa Department 30/38 probate examiner calendars should
  become a separate non-ruling dataset rather than `Ruling` rows.
- Do not parse unsafe one-off PDFs without a source-supported hearing date and
  case number.
- Add normalized form-language segregation if the viewer should match the SFSC
  treatment of repeated court boilerplate.
