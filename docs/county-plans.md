# County Plans

This file separates source structure from implementation status. It is not a
parser promise. Keep it current whenever scraper, parser, viewer, or scheduling
behavior changes.

## Parser Registry Status

`ingest.orchestrate` derives parser registration dynamically from
`counties/<county>/scraper.py`: any module with a callable `parse` feeds
`data/<county>/rulings.parquet`; a callable `parse_page_capture` adds HTML page
capture rows.

Current registered parsers:

| County | Parser coverage | Tests present |
|---|---|---|
| Amador | Legacy PDF parser for archived/Wayback dropdown PDFs. | Discovery and parse tests. |
| Contra Costa | PDF parser plus HTML page-capture parser. CLI discovery uses the public retired.cc-courts.org iframe URL. | Discovery and parse tests. |
| El Dorado | Probate, civil law-and-motion, probate calendar, and family-law PDF parser. | Discovery and parse tests. |
| Nevada | Static-page PDF parser. `.docx` links are discovered as a source issue but not parsed. | Discovery and parse tests. |
| Orange | Civil, family, and probate PDF parser for stable current URLs. | Discovery and parse tests. |
| Placer | Civil law-and-motion PDF parser. | Discovery and parse tests. |
| San Francisco | Unified Family Court PDF parser for departments 403, 404, and 414. | Discovery and parse tests. |
| Santa Clara | Department-page PDF parser. | Parse tests. |
| Shasta | Department PDF parser. | Parse tests. |
| Solano | Civil/probate PDF parser. | Parse tests. |

Capture-only counties in the implemented-source table are archived with
provenance, but do not produce viewer rows until representative fixtures and
parser tests are added.

## Implemented Capture Sources

| County | Source | Structure | Current plan | Parser status |
|---|---|---|---|---|
| Amador | `https://www.amadorcourt.org/os-tentativerulings.aspx` | Four legacy dropdowns with direct PDF option values. | Capture live dropdown PDFs and Wayback prefix captures for `www.amadorcourt.org/tentativeRulings/*`, especially 2020-2022. Current post-02/15/2022 access appears portal-based. | Parser registered for legacy PDFs. |
| Calaveras | `https://www.calaveras.courts.ca.gov/online-services/tentative-rulings` | Static case-management and civil law-and-motion lists with many historical PDFs. | Capture both list pages. Do not assume filename regularity; use link text and URL. | Capture-only. |
| Contra Costa | `https://retired.cc-courts.org/civil/motions-hearings-tentative.aspx`, embedded by the public Contra Costa tentative-rulings page. | ASP.NET iframe page with direct PDF anchors under `/civil/TR/`. | Capture current PDFs directly in `ingest.backfill`; keep the extension for page snapshots and manual browser scans. | Parser registered for captured PDFs and page captures. |
| El Dorado | Court tentative-ruling pages. | Static direct PDF links across several divisions/styles. | Keep live capture and Wayback checks; maintain parser fixtures for each PDF family. | Parser registered. |
| Fresno | `https://www.fresno.courts.ca.gov/online-services/tentative-rulings` | Static Law and Motion page with department PDF links. | Capture direct PDFs and infer department from filenames such as `dept-503`. | Capture-only. |
| Merced | `https://www.merced.courts.ca.gov/online-services/tentative-rulings` | Static weekday PDF links, `tr-monday.pdf` through `tr-friday.pdf`. | Capture weekday PDFs; use hashes and Wayback for overwritten-file history. | Capture-only. |
| Nevada | `https://www.nevada.courts.ca.gov/online-services/tentative-rulings` | Static Drupal page with Nevada City and Truckee sections. | Capture court-hosted PDFs under `/system/files/tentative-rulings/`; add `.docx` capture/parsing separately. | Parser registered for PDFs. |
| Orange | `https://www.occourts.org/online-services/tentative-rulings` | Router to civil, family, and probate index pages, each linking stable current PDFs. | Capture current PDFs from the three index pages. Use exact Wayback CDX queries against stable PDF URLs for history. | Parser registered. |
| Placer | Court tentative-ruling page. | Static civil law-and-motion PDFs. | Continue live and Wayback capture; preserve date/dept hints from source metadata. | Parser registered. |
| Plumas | `https://plumas.courts.ca.gov/online-services/tentative-rulings` | Static Department 2 list with direct PDF links. | Capture direct PDFs with Department 2 hint. | Capture-only. |
| Riverside | `https://www.riverside.courts.ca.gov/online-services/tentative-rulings` | Regional/department page linking department ruling PDFs. | Capture direct PDFs and infer department from URL/text where possible. | Capture-only. |
| San Bernardino | `https://old.sb-court.org/GeneralInfo/TentativeRulings.aspx` | Legacy table with date, civil division, and direct PDF filename. | Capture the legacy table; infer civil department from filenames such as `CVS36052026.pdf`. | Capture-only. |
| San Francisco | `https://webapps.sftc.org/ufctr/ufctr.dll` | Static UFC family-law page with current and previous PDF links. | Capture PDFs for departments 403, 404, and 414. | Parser registered for UFC PDFs. |
| Santa Clara | `https://santaclara.courts.ca.gov/online-services/tentative-rulings` | Index links department pages; department pages link stable PDF files. | Capture department pages for civil, probate, and complex departments. | Parser registered. |
| Shasta | `https://shasta.courts.ca.gov/online-services/tentative-rulings` | Static department list with direct PDFs under `/system/files/tentative/`. | Capture direct PDFs and map old department labels when filenames expose them. | Parser registered. |
| Solano | `https://solano.courts.ca.gov/divisions/civil-court/tentative-rulings` | Static civil/probate page with direct department PDFs. | Capture the ruling PDFs and skip request-for-argument forms. | Parser registered. |
| Tuolumne | `https://www.tuolumne.courts.ca.gov/online-services/tentative-rulings-and-case-notes` | Static tentative-ruling and Case Notes links. | Capture tentative-ruling PDFs and Case Notes, tagged by division hint. | Capture-only. |

## Automation Constraints and Fallbacks

Before marking a source as "not automatically scrapeable," try the least
intrusive options in order: direct HTTP, sessioned HTTP with form tokens,
headless browser, headed browser in Xvfb/virtual desktop, then extension or
desktop app in a human-maintained profile. Treat login-backed systems as out of
scope unless there is a lawful public access path.

| Source | Current CLI status | Why it is not fully automatic today | Potential desktop/app solution |
|---|---|---|---|
| Contra Costa page snapshots | PDF capture is now automatic through the public retired.cc-courts.org iframe URL; HTML page snapshots remain extension-backed. | CLI backfill stores PDFs only. The extension still captures changed visible text/layout pages. | Use the browser extension or a future Playwright/Xvfb pass only when page snapshots, not PDFs, need refresh. |
| Amador post-02/15/2022 | Legacy PDFs/Wayback are automatic; current portal is not. | Current access appears portal/account-based rather than public static PDFs. | If there is a public unauthenticated portal path, automate it with Playwright in a virtual window; otherwise keep to legacy public archive/Wayback. |
| Nevada `.docx` links | PDF links are automatic; `.docx` links are not archived. | Pipeline is PDF-first and does not yet store or parse Word documents. | Add document capture for `.docx`, convert or parse with `python-docx`, and add fixtures before enabling parser rows. |
| Google Drive folders (Napa, San Luis Obispo, Santa Cruz backlog) | Not implemented. | Drive folder markup and download URLs are unstable under basic HTML scraping. | Prefer Drive API or public folder JSON extraction; fallback to headed Chromium that enumerates visible files and downloads PDFs. |
| SharePoint folder (Kings backlog) | Not implemented. | Basic requests redirect toward Microsoft login. Anonymous folder enumeration may or may not be available. | Try public sharing-link APIs first; if login is required, do not automate absent a lawful public access path. A desktop profile can verify whether files are public. |
| ASP.NET/token forms (Los Angeles, Ventura backlog) | Not implemented. | Requires session cookies, hidden fields, validation tokens, and POST replay. | Build a reusable sessioned form adapter; fallback to Playwright in a virtual window if JavaScript or bot checks mutate tokens. |
| Tyler/re:SearchCA (Mendocino backlog) | Blocked. | Sends users to a login/portal system with likely terms and authentication constraints. | Use only a user-authorized desktop session for manual research unless a public export path exists. Do not fold authenticated content into the public archive without review. |
| Mixed HTML/PDF pages (Santa Barbara, Sonoma, Stanislaus, Tulare, Yolo backlog) | Not implemented. | Needs per-site HTML detail parsers or document-node discovery; not a fundamental scraping block. | Direct crawler first; headed browser only if client-side rendering or 403s block document discovery. |
| Static current-window PDFs (San Mateo backlog) | Not implemented. | Straightforward, but current-window files may overwrite and need hash-based recapture. | Direct HTTP capture with hash comparison; browser automation likely unnecessary. |

## Researched Backlog

| County | Structure | Scrape plan | Risk |
|---|---|---|---|
| Kings | County site links to a SharePoint folder. | Try anonymous SharePoint folder enumeration before any desktop-session approach. | High. Redirects to Microsoft login in basic requests. |
| Los Angeles | ASP.NET form with hidden fields and a courtroom/date dropdown. | Sessioned GET, parse `__VIEWSTATE` and `__EVENTVALIDATION`, POST selected dropdown values, parse returned HTML. | Medium. Form-state handling required. |
| Mendocino | County page sends users to Tyler re:SearchCA. | No public county-hosted scraper plan yet. | High. Login/portal terms likely block automation. |
| Napa | Public Google Drive folder of PDFs. | Drive folder adapter, then PDF download and parse. | Medium. Drive dependency. |
| San Benito | Current PDFs linked from homepage, not only the notice page. | Homepage PDF-link harvest. | Low. Confidential family matters not posted. |
| San Luis Obispo | Court page links Google Drive folders. | Drive folder adapter for department folders. | Medium. Drive dependency. |
| San Mateo | Static category pages with weekday PDFs on `web.sanmateocourt.org`. | Direct weekday PDF harvest by category. | Low. Files are current-window, not full archive. |
| Santa Barbara | Drupal search/list pages with individual HTML ruling detail pages. | Crawl search pages and parse detail HTML. | Low to medium. HTML parser needed, not PDF parser. |
| Santa Cruz | Static page links Google Drive weekday PDFs. | Drive file-id extraction and PDF download. | Medium. Drive dependency. |
| Sonoma | Static civil/family/probate pages, some inline text and some PDFs. | Crawl calendar pages, parse inline HTML first, then follow PDFs. | Medium. Mixed source styles. |
| Stanislaus | Static civil and family HTML pages; older PDFs exist opportunistically. | HTML parser for current pages, optional PDF harvest for older indexed files. | Low to medium. |
| Tulare | Static HTML with labeled ruling blocks. | HTML parser under "Current Tentative Rulings." | Low. |
| Ventura | ASP.NET-style POST search with anti-forgery token. | Sessioned GET, token extraction, POST date search, download result documents. | Medium. Token/cookie handling required. |
| Yolo | Drupal document nodes and date-coded PDFs. | Discover document nodes first, then download linked PDFs. | Medium. Direct PDF routes may 403. |

## Implementation Order

1. Keep daily direct-HTTP capture running for implemented `LANDING_PAGES`.
2. Add parsers only after representative fixtures and parser tests exist.
3. Add static PDF-list counties first, then Google Drive support once for Napa,
   San Luis Obispo, and Santa Cruz.
4. Add a reusable sessioned-form adapter for Los Angeles and Ventura.
5. Add a VPS/headed-browser lane only for future public sites that genuinely
   require active page execution after direct HTTP and sessioned HTTP fail.
6. Treat SharePoint, Tyler/re:SearchCA, and login-backed portals as blocked
   until a lawful public access path is confirmed.
