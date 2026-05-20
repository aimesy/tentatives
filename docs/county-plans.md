# County Plans

This file separates source structure from implementation status. It is not a parser promise.

## Implemented Capture Sources

| County | Source | Structure | Current plan |
|---|---|---|---|
| Amador | `https://www.amadorcourt.org/os-tentativerulings.aspx` | Four legacy dropdowns with direct PDF option values. | Capture live dropdown PDFs and Wayback prefix captures for `www.amadorcourt.org/tentativeRulings/*`, especially 2020-2022. Current post-02/15/2022 portal appears account-based. |
| San Francisco | `https://webapps.sftc.org/ufctr/ufctr.dll` | Static UFC family-law page with current and previous PDF links. | Capture PDFs for depts 403, 404, and 414. Parser is separate work. |
| Nevada | `https://www.nevada.courts.ca.gov/online-services/tentative-rulings` | Static Drupal page with Nevada City and Truckee sections. | Capture court-hosted PDFs under `/system/files/tentative-rulings/`. Current `.docx` links are noted but not archived by the PDF parser path. |
| Orange | `https://www.occourts.org/online-services/tentative-rulings` | Router to civil, family, and probate index pages, each linking stable current PDFs. | Capture current PDFs from the three index pages. Use exact Wayback CDX queries against those stable PDF URLs for history. |
| Calaveras | `https://www.calaveras.courts.ca.gov/online-services/tentative-rulings` | Static case-management and civil law-and-motion lists with many historical PDFs. | Capture both list pages. Do not assume filename regularity; use link text and URL. |
| Fresno | `https://www.fresno.courts.ca.gov/online-services/tentative-rulings` | Static Law and Motion page with department PDF links. | Capture direct PDFs and infer department from filenames such as `dept-503`. |
| Merced | `https://www.merced.courts.ca.gov/online-services/tentative-rulings` | Static weekday PDF links, `tr-monday.pdf` through `tr-friday.pdf`. | Capture the weekday PDFs; use hashes and Wayback for overwritten-file history. |
| Plumas | `https://plumas.courts.ca.gov/online-services/tentative-rulings` | Static Department 2 list with direct PDF links. | Capture direct PDFs with Department 2 hint. |
| Riverside | `https://www.riverside.courts.ca.gov/online-services/tentative-rulings` | Regional/department page linking department ruling PDFs. | Capture direct PDFs and infer department from URL/text where possible. |
| San Bernardino | `https://old.sb-court.org/GeneralInfo/TentativeRulings.aspx` | Legacy table with date, civil division, and direct PDF filename. | Capture the legacy table; infer civil department from filenames such as `CVS36052026.pdf`. |
| Santa Clara | `https://santaclara.courts.ca.gov/online-services/tentative-rulings` | Index links department pages; department pages link stable PDF files. | Capture department pages for civil, probate, and complex departments. |
| Shasta | `https://shasta.courts.ca.gov/online-services/tentative-rulings` | Static department list with direct PDFs under `/system/files/tentative/`. | Capture direct PDFs and map old department labels when filenames expose them. |
| Solano | `https://solano.courts.ca.gov/divisions/civil-court/tentative-rulings` | Static civil/probate page with direct department PDFs. | Capture the five ruling PDFs and skip request-for-argument forms. |
| Tuolumne | `https://www.tuolumne.courts.ca.gov/online-services/tentative-rulings-and-case-notes` | Static tentative-ruling and case-note links. | Capture tentative-ruling PDFs and Case Notes, tagged by division hint. |

## Researched Backlog

| County | Structure | Scrape plan | Risk |
|---|---|---|---|
| Kings | County site links to a SharePoint folder. | Try anonymous SharePoint folder enumeration. | High. Redirects to Microsoft login in basic requests. |
| Los Angeles | ASP.NET form with hidden fields and a courtroom/date dropdown. | Sessioned GET, parse `__VIEWSTATE` and `__EVENTVALIDATION`, POST selected dropdown values, parse returned HTML. | Medium. Form-state handling required. |
| Mendocino | County page sends users to Tyler re:SearchCA. | No public county-hosted scraper plan yet. | High. Login/portal terms likely block automation. |
| Napa | Public Google Drive folder of PDFs. | Drive folder adapter, then PDF download and parse. | Medium. Drive markup can change. |
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

1. Keep parser registration limited to counties with representative PDFs and tests.
2. Add static PDF-list counties to the extension in batches.
3. Add Google Drive support once for Napa, San Luis Obispo, and Santa Cruz.
4. Add form-session support once for Los Angeles and Ventura.
5. Treat SharePoint, Tyler/re:SearchCA, and login-backed portals as blocked until there is a lawful public access path.
