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
| Calaveras | Case-management and civil law-and-motion PDF parser. | Discovery and parse tests. |
| Contra Costa | PDF parser plus HTML page-capture parser. CLI discovery uses the public retired.cc-courts.org iframe URL. | Discovery and parse tests. |
| El Dorado | Probate, civil law-and-motion, probate calendar, and family-law PDF parser. | Discovery and parse tests. |
| Fresno | Law-and-motion PDF parser, including cover-page continued matters. | Parse tests. |
| Merced | Weekday civil law-and-motion PDF parser. | Parse tests. |
| Nevada | Static-page PDF parser plus supported DOCX case-management parser. | Discovery and parse tests. |
| Orange | Civil, family, and probate PDF parser for stable current URLs. | Discovery and parse tests. |
| Placer | Civil law-and-motion PDF parser. | Discovery and parse tests. |
| Plumas | Department 2 PDF parser. | Parse tests. |
| Riverside | Regional/department numbered-table PDF parser. | Discovery and parse tests. |
| San Bernardino | Legacy civil-table PDF parser. | Parse tests. |
| San Francisco | Unified Family Court PDF parser for departments 403, 404, and 414. | Discovery and parse tests. |
| Santa Clara | Department-page PDF parser. | Parse tests. |
| Shasta | Department PDF parser. | Parse tests. |
| Solano | Civil/probate PDF parser. | Parse tests. |
| Tuolumne | Consolidated tentative-ruling PDF parser. | Parse tests. |

## Implemented Capture Sources

| County | Source | Structure | Current plan | Parser status |
|---|---|---|---|---|
| Amador | `https://www.amadorcourt.org/os-tentativerulings.aspx` | Four legacy dropdowns with direct PDF option values. | Keep Wayback prefix captures for `www.amadorcourt.org/tentativeRulings/*`, especially 2020-2022. Routine daily live checks skip Amador because the public legacy page is historical-only and current post-02/15/2022 access appears portal-based. | Parser registered for legacy PDFs. |
| Calaveras | `https://www.calaveras.courts.ca.gov/online-services/tentative-rulings` | Static case-management and civil law-and-motion lists with many historical PDFs. | Capture both list pages. Do not assume filename regularity; use link text and URL. | Parser registered. |
| Contra Costa | `https://retired.cc-courts.org/civil/motions-hearings-tentative.aspx`, embedded by the public Contra Costa tentative-rulings page. | ASP.NET iframe page with direct PDF anchors under `/civil/TR/`. | Capture current PDFs directly in `ingest.backfill`; keep the extension for page snapshots and manual browser scans. | Parser registered for captured PDFs and page captures. |
| El Dorado | Court tentative-ruling pages. | Static direct PDF links across several divisions/styles. | Keep live capture and Wayback checks; maintain parser fixtures for each PDF family. | Parser registered. |
| Fresno | `https://www.fresno.courts.ca.gov/online-services/tentative-rulings` | Static Law and Motion page with department PDF links. | Capture direct PDFs and infer department from filenames such as `dept-503`. | Parser registered. |
| Merced | `https://www.merced.courts.ca.gov/online-services/tentative-rulings` | Static weekday PDF links, `tr-monday.pdf` through `tr-friday.pdf`. | Capture weekday PDFs; use hashes and Wayback for overwritten-file history. | Parser registered. |
| Nevada | `https://www.nevada.courts.ca.gov/online-services/tentative-rulings` | Static Drupal page with Nevada City and Truckee sections. | Capture court-hosted PDFs and DOCX files under `/system/files/tentative-rulings/`; parse supported Word-text calendars directly. | Parser registered for PDFs and supported DOCX. |
| Orange | `https://www.occourts.org/online-services/tentative-rulings` | Router to civil, family, and probate index pages, each linking stable current PDFs. One current family-law PDF may be served from `live-jcc-oc.pantheonsite.io`. | Capture current PDFs from the three index pages and allow the court's Pantheon host for source files. Use exact Wayback CDX queries against stable PDF URLs for history. | Parser registered. |
| Placer | Court tentative-ruling page. | Static civil law-and-motion PDFs and calendar-note PDFs under relative `/sites/default/files/...pdf` links. | Continue live and Wayback capture; preserve date/dept hints from source metadata. Python disables TLS verification only for this host because its certificate chain does not complete in some Python/OpenSSL builds, while browser and host-restricted PDF fetches work. | Parser registered. |
| Plumas | `https://plumas.courts.ca.gov/online-services/tentative-rulings` | Static Department 2 list with direct PDF links. | Capture direct PDFs with Department 2 hint. | Parser registered. |
| Riverside | `https://www.riverside.courts.ca.gov/online-services/tentative-rulings` | Regional/department page linking department ruling PDFs. | Capture direct PDFs and infer department from URL/text where possible; use reader fallback for landing-page discovery when direct HTTP gets Cloudflare. Chrome verification showed the real page loads after a Cloudflare browser challenge and exposes the same court-hosted PDF links. | Parser registered. |
| San Bernardino | `https://old.sb-court.org/GeneralInfo/TentativeRulings.aspx` | Legacy table with date, civil division, and direct PDF filename. | Capture the legacy table; infer civil department from filenames such as `CVS36052026.pdf`. | Parser registered. |
| San Francisco | `https://webapps.sftc.org/ufctr/ufctr.dll` | Static UFC family-law page with current and previous PDF links. | Capture PDFs for departments 403, 404, and 414. | Parser registered for UFC PDFs. |
| Santa Clara | `https://santaclara.courts.ca.gov/online-services/tentative-rulings` | Index links department pages; department pages link stable PDF files. Departments 16, 19, and 22 use `dept-N-tentative-rulings` slugs, not `department-N`. | Capture department pages for civil, probate, and complex departments. | Parser registered. |
| Shasta | `https://shasta.courts.ca.gov/online-services/tentative-rulings` | Static department list with direct PDFs under `/system/files/tentative/`. | Capture direct PDFs and map old department labels when filenames expose them. | Parser registered. |
| Solano | `https://solano.courts.ca.gov/divisions/civil-court/tentative-rulings` | Static civil/probate page with direct department PDFs. | Capture the ruling PDFs and skip request-for-argument forms. | Parser registered. |
| Tuolumne | `https://www.tuolumne.courts.ca.gov/online-services/tentative-rulings-and-case-notes` | Static tentative-ruling and Case Notes links. | Capture tentative-ruling PDFs and Case Notes, tagged by division hint. | Parser registered. |

## Daily Capture Sources Pending Parsers

The 2026-06-23 live-capture expansion registers these public sources with
`ingest.backfill --county all --live`. These counties are now raw-archived
daily, but they do not yet publish parsed rows in `data/<county>/rulings.parquet`
until parser fixtures and county parsers are added.

| County | Raw surface now captured | Archive type | Parser status |
|---|---|---|---|
| Butte | Static Drupal page with direct court-hosted PDFs. | PDF source captures. | Pending. |
| Imperial | Static tentative-ruling page/news page with direct PDFs. | PDF source captures. | Pending. |
| Los Angeles | Public WebForms department/date result pages. | HTML page captures. | Pending HTML parser. |
| Marin | Static Drupal page with direct PDFs. | PDF source captures. | Pending; recheck after July 2, 2026 access change. |
| Monterey | Public JSON API with base64 PDF document contents. | PDF source captures decoded from API JSON. | Pending. |
| Napa | Public Google Drive folder. | PDF source captures through shared Drive adapter. | Pending. |
| San Benito | Homepage/news tentative-ruling PDF links. | PDF source captures. | Pending. |
| San Luis Obispo | Public Google Drive department/probate folders. | Recursive PDF source captures through shared Drive adapter. | Pending. |
| San Mateo | Static category pages with weekday PDFs on `web.sanmateocourt.org`. | PDF source captures. | Pending. |
| Santa Barbara | Public Drupal tentative-rulings index/detail pages. | HTML page captures. | Pending HTML parser. |
| Santa Cruz | Official page links public Google Drive weekday PDFs. | PDF source captures through shared Drive adapter. | Pending. |
| Sierra | Official page links public Google Drive category PDFs. | PDF source captures through shared Drive adapter. | Pending. |
| Sonoma | Public Drupal civil/family/probate tentative-ruling pages. | HTML page captures. | Pending HTML parser. |
| Stanislaus | Public Drupal civil/family/probate-note pages. | HTML page captures. | Pending HTML parser. |
| Tulare | Civil tentative-ruling page plus probate PDFs. | HTML page capture plus PDF source captures. | Pending mixed HTML/PDF parser. |
| Ventura | Public date-search form with ViewFile PDFs. | PDF source captures. | Pending. |
| Yolo | Public tentative-ruling and probate-note calendar pages. | HTML page captures. | Pending direct document-node/PDF discovery and parser. |

## Implemented Surface Gap Notes

These are not known parser failures. They are adjacent official surfaces or
coverage caveats to check before describing an implemented county as completely
covered.

| County | Gap / caveat | Next action |
|---|---|---|
| Contra Costa | The public tentative-rulings page includes civil and probate material, including probate Departments 30 and 38. The implemented notes emphasize the civil iframe and should verify probate capture explicitly. | Check whether the existing `retired.cc-courts.org` capture contains probate PDFs; if not, add probate fixtures before widening parser claims. |
| Fresno | Law-and-motion PDFs are implemented. Probate Examiner Notes are a separate case-number search, not a broad public list. | Leave probate notes out of daily broad capture unless a date/list surface is found; document any case-number-only support separately. |
| Placer | The official home advertises Law and Motion Tentative Rulings, CMC Notes, OSC Calendar, and Calendar Notes. Current docs mention law-and-motion and calendar-note PDFs. | Verify whether CMC/OSC are already covered by calendar-note capture; add source labels if they are. |
| San Bernardino | Legacy civil-table PDFs are implemented. Probate notes are separately available through CAP. | Triage the CAP probate-notes surface before treating it as extractable. |
| San Francisco | This project implements only UFC Departments 403, 404, and 414. The official SF page also lists asbestos, law-and-motion/discovery, probate, real property/housing, and family-law surfaces, with some owned by the sibling `aimesy/sfsc-tentatives` project. | Mirror the SFSC split here and specifically verify Department 210 / housing coverage. |

## Automation Constraints and Fallbacks

Before marking a source as "not automatically scrapeable," try the least
intrusive options in order: direct HTTP, sessioned HTTP with form tokens,
headless browser, headed browser in Xvfb/virtual desktop, then extension or
desktop app in a human-maintained profile. Treat login-backed systems as out of
scope unless there is a lawful public access path.

| Source family | Counties / sources | Current status | Potential solution |
|---|---|---|---|
| Existing page snapshots | Contra Costa page snapshots. | PDF capture is automatic through the public `retired.cc-courts.org` iframe URL; HTML page snapshots remain extension-backed. | Use the browser extension or a future Playwright/Xvfb pass only when visible page snapshots, not PDFs, need refresh. |
| Legacy / archived public PDFs | Amador post-02/15/2022. | Legacy PDFs/Wayback are automatic; routine daily live checks are disabled because current access appears portal/account-based rather than public static PDFs. | If a public unauthenticated portal path appears, automate it with Playwright; otherwise keep to legacy public archive/Wayback. |
| Word calendars | Nevada `.docx` links. | PDF and supported `.docx` links are automatic. | Retain original DOCX bytes and add fixtures before expanding parser coverage for unsupported Word layouts. |
| Browser-challenged discovery | Riverside landing page. | Landing-page discovery uses a reader fallback because basic `requests` receives Cloudflare 403; source PDFs are still fetched directly from the court host. | Keep the reader fallback scoped to discovery. If it breaks, use a headed browser scan to refresh court-hosted PDF links. |
| Static court-hosted PDFs / HTML | Butte, Imperial, Marin, San Benito, San Mateo, Santa Barbara, Sonoma, Stanislaus, Tulare. | Daily raw capture is implemented. PDF counties archive source PDFs; HTML counties archive page snapshots. | Add parser fixtures and parsers. |
| Google Drive files/folders | Napa, San Luis Obispo, Santa Cruz, Sierra. | Daily raw capture is implemented through a shared public Drive adapter. | Add parser fixtures and parsers; keep Drive metadata tests current. |
| ASP.NET / token forms | Los Angeles, Ventura. | Daily raw capture is implemented for public no-login paths. Los Angeles archives result HTML pages; Ventura archives ViewFile PDFs. | Add parsers. Use Playwright only if token/form behavior changes. |
| Public API-backed portal | Monterey. | Daily raw capture is implemented. API JSON document responses are decoded into archived PDF bytes. | Add parser fixtures and parser; keep date-window/API drift tests current. |
| ROA / case-document portals | San Diego, San Joaquin. | Not implemented. San Diego appears public but lacks a simple countywide feed. San Joaquin is case-number or portal constrained. | Use only public calendar/case leads; keep terms/cookie handling explicit. Treat broad capture as higher risk than static pages. |
| SharePoint folder | Kings. | Not implemented. The official link redirects toward Microsoft login in basic requests. | Try anonymous SharePoint sharing APIs first; if login is required, mark blocked absent a lawful public access path. |
| Login-backed Tyler / re:Search / JournalTech | Alameda, Mendocino, Sacramento. | Blocked for unattended public capture. | Use only a user-authorized desktop session for manual research unless a public export path is confirmed. |
| Calendar/document-node pages | Yolo. | Daily page capture is implemented for official tentative/probate calendar pages, but direct document-node/PDF discovery is still pending. | Add document-node discovery if the calendar JS exposes stable file nodes. |
| Adjacent probate notes only | Yuba. | Probate-note PDFs are public, but the court says they are not tentative rulings; civil tentative implementation has not gone live. | Optional probate-notes parser only if the project wants adjacent notes; do not count as civil tentative-ruling coverage. |
| No public tentative surface | Alpine, Colusa, Del Norte, Glenn, Humboldt, Inyo, Kern, Lake, Lassen, Madera, Mariposa, Modoc, Mono, Siskiyou, Sutter, Tehama, Trinity. | No parser target as of 2026-06-23. Several courts expressly say no tentatives; others expose only calendars or case portals. | Store as monitored negatives and recheck on a schedule. Do not scrape calendars as if they were rulings. |

## Non-Implemented County Surface Audit

This audit covers every California county that does not already have a
registered parser above, current as of 2026-06-23.

### Public Broad Extractable Surfaces

| County | Official surface | Structure | Capture / parser plan | Risk |
|---|---|---|---|---|
| Butte | [Tentative Rulings](https://www.butte.courts.ca.gov/online-services/tentative-rulings) | Static Drupal page with direct court-hosted PDFs under `/system/files/tentative-rulings/`. | Scrape landing page, capture every PDF href, hash bytes, parse PDFs, and tag civil/probate/exchange from section text and filename. | Low to medium. |
| Imperial | [Tentative Rulings](https://www.imperial.courts.ca.gov/general-information/tentative-rulings) | Static HTML listing with direct PDFs. | Crawl page, extract metadata and PDF links, parse or OCR PDFs. | Low technical risk; medium coverage risk because the live page appears sparse/stale. |
| Los Angeles | [Civil tentative rulings](https://www.lacourt.ca.gov/tentativeRulingNet/ui/main.aspx?casetype=civil) | ASP.NET/WebForms with location/department/date or case-number search. | Sessioned GET, parse `__VIEWSTATE` / `__EVENTVALIDATION`, POST selected department/date, parse result HTML. | Medium. |
| Marin | [Tentative Rulings](https://www.marin.courts.ca.gov/online-services/tentative-rulings) | Static Drupal page with direct PDFs. | Capture all `/system/files/tentative-rulings/*.pdf` links after 2 p.m.; parse PDFs by civil/family/probate section. | Low now; recheck after the announced July 2, 2026 access change. |
| Monterey | [Tentative Rulings](https://www.monterey.courts.ca.gov/online-services/tentative-rulings) and [portal](https://portal.monterey.courts.ca.gov/calendars/tentative-rulings) | Angular portal backed by public JSON and base64 PDF endpoints. | Query `https://api.monterey.courts.ca.gov/api/tentativerulings/date?date=YYYY-MM-DD`, then fetch `/api/tentativerulings/{caseId}/doc/{documentId}`. | Medium because the API is observed, not documented. |
| Napa | [Tentative Rulings](https://www.napa.courts.ca.gov/online-services/tentative-rulings) | Public Google Drive folder of PDFs. | Add Drive folder adapter, enumerate file IDs, download PDFs, hash file ID plus bytes, parse PDFs. | Medium Drive dependency. |
| San Benito | [Court homepage](https://www.sanbenito.courts.ca.gov/) and [tentative-rulings notice](https://www.sanbenito.courts.ca.gov/news/tentative-rulings) | Static page links to direct court-hosted PDFs under `/system/files/tentative-rulings/`. | Scrape homepage tentative section first, then the notice page; normalize relative PDF URLs and parse PDFs. | Low. |
| San Diego | [Civil tentative rulings](https://www.sdcourt.ca.gov/sdcourt/civil2/civiltentativerulings), [probate tentative rulings](https://www.sdcourt.ca.gov/sdcourt/probate2/tentativerulings), [ROA portal](https://odyroa.sdcourt.ca.gov/) | Register of Actions portal/search; tentative rulings are ROA documents. | Use public date/case leads, then ROA case pages and tentative-ruling document endpoints; parse PDFs. | Medium-high; no simple countywide list and terms/cookies must be handled carefully. |
| San Luis Obispo | [Tentative Rulings](https://www.slo.courts.ca.gov/online-services/tentative-rulings) | Public Google Drive department/probate folders. | Add recursive Drive folder adapter and parse PDFs by source folder/department. | Medium Drive dependency. |
| San Mateo | [Tentative Rulings](https://sanmateo.courts.ca.gov/online-services/tentative-rulings) | Static category pages with weekday direct PDFs on `web.sanmateocourt.org`. | Scrape category pages, follow weekday PDF links, hash overwritten PDFs daily, parse by category and weekday. | Low; retained five calendar days. |
| Santa Barbara | [Tentative Rulings](https://www.santabarbara.courts.ca.gov/online-services/tentative-rulings) and [query/list endpoint](https://www.santabarbara.courts.ca.gov/tentative-rulings) | Drupal/static HTML search, judge filters, paginated lists, and detail pages. | Enumerate judge filters/pages, follow detail links, and parse fields from detail HTML. | Low. |
| Santa Cruz | [Civil Tentative Rulings](https://www.santacruz.courts.ca.gov/online-services/civil-tentative-rulings) | Official page links public Google Drive weekday PDFs. | Convert Drive file IDs to download URLs, parse/OCR PDFs, split by weekday and case headings. | Medium Drive dependency. |
| Sierra | [Tentative Rulings](https://www.sierra.courts.ca.gov/online-services/tentative-rulings) | Official page links public Google Drive PDFs for law and motion, probate, CMC, and guardianships. | Download stable Drive file IDs, parse/OCR PDFs by category, and tolerate blank/stale small-county calendars. | Medium-low. |
| Sonoma | [Tentative Rulings](https://sonoma.courts.ca.gov/online-services/tentative-rulings) | Static Drupal tree for civil, family, and probate pages. | Crawl index pages, follow child calendar links, parse heading/date/case blocks, and hash page snapshots. | Medium mixed HTML/page structure. |
| Stanislaus | [Tentative Rulings](https://www.stanislaus.courts.ca.gov/online-services/tentative-rulings) | Static Drupal pages with inline civil/family rulings and probate notes. | Fetch civil/family/probate pages and split by date, department, and case-number patterns. | Medium. |
| Tulare | [Tentative Rulings](https://www.tulare.courts.ca.gov/general-information/tentative-rulings) | Static HTML civil blocks plus direct probate PDFs. | Snapshot HTML page, parse "Current Tentative Rulings" blocks, and hash/download Visalia and SCJC probate PDFs. | Low. |
| Ventura | [Tentative Rulings & Probate Notes](https://www2.ventura.courts.ca.gov/CaseInquiry/TentativeRulings) | ASP.NET/session POST form with result rows linking direct PDFs. | Sessioned GET, extract anti-forgery token, POST hearing date, parse result table, download `/CaseInquiry/ViewFile/<id>` PDFs. | Medium. |
| Yolo | [Tentative Rulings Calendar](https://www.yolo.courts.ca.gov/online-services/tentative-rulings-calendar) and [Probate Note Calendar](https://www.yolo.courts.ca.gov/online-services/probate-note-calendar) | Drupal document nodes and direct date-coded PDFs such as `ATO-TEN-YYMMDD.pdf` and `ATO-PRB-YYMMDD.pdf`. | Prefer document-node discovery plus direct filename probing for date windows. | Medium; some filenames include suffixes and lightweight HTML may omit links. |

### Online But Blocked, Partial, Or Not Broadly Listable

| County | Official surface | Structure | Capture / parser plan | Risk |
|---|---|---|---|---|
| Alameda | [Tentative Rulings](https://www.alameda.courts.ca.gov/divisions/civil/tentative-rulings) and [eCourt portal](https://eportal.alameda.courts.ca.gov/?q=Home) | JournalTech/eCourt portal; PDFs inside authenticated case/department workflow. | Do not treat as an unauthenticated daily target. Consider only with an approved account/session and explicit auth policy. | High. |
| Kings | [Court homepage](https://www.kings.courts.ca.gov/) and [Civil](https://www.kings.courts.ca.gov/divisions/civil) link a SharePoint tentative-rulings folder. | Official SharePoint/Office 365 folder. | Try anonymous SharePoint file listing/download first; if blocked, mark as needs court fix or approved manual profile. | High; basic requests redirect to Microsoft login. |
| Mendocino | [Tentative Rulings](https://www.mendocino.courts.ca.gov/tentative-rulings) and [case portal](https://www.mendocino.courts.ca.gov/portal) | re:SearchCA / Tyler case search. | Do not treat as public daily list. Rulings are posted to individual cases after 3 p.m. and viewed by signing in. | High. |
| Sacramento | [Civil](https://www.saccourt.ca.gov/divisions/civil), [civil home courts](https://www.saccourt.ca.gov/divisions/civil/civil-home-courts), and [public portal](https://prod-portal-sacramento-ca.journaltech.com/public-portal/?q=node%2F425) | JournalTech public portal/search; PDFs behind portal; phone fallback. | Treat as high-risk portal source. Use only a user-authorized account/session if approved. | High. |
| San Joaquin | [Probate notes & tentative rulings](https://www.sjcourts.org/probate-notes-tentative-rulings), [Civil](https://www.sjcourts.org/civil), and [FullCourt portal](https://cms.sjcourts.org/fullcourtweb/start.do) | Mixed case-number search/API for probate and FullCourt public portal for civil case documents. | Probate endpoint can support known case numbers; broad civil capture needs calendar/case leads and portal-session triage. | High for broad capture. |
| Yuba | [Probate Division](https://www.yuba.courts.ca.gov/divisions/probate-division) and [local rules](https://www.yuba.courts.ca.gov/system/files/local-rules/126-final-superior-court-ca-county-yuba-local-rules.pdf) | Probate-note PDFs are static; civil tentative procedure is adopted but not technically implemented. | Optional probate-notes parser only; do not count as civil tentative-ruling coverage. | Medium; probate notes are expressly not tentative rulings. |

### No Public Tentative-Ruling Surface Found

| County | Official check | Finding | Next action |
|---|---|---|---|
| Alpine | [Civil Division](https://www.alpine.courts.ca.gov/divisions/civil) | Court expressly says it does not publish tentative rulings. | Skip; monitor periodically. |
| Colusa | [Civil Division](https://www.colusa.courts.ca.gov/divisions/civil) | Court expressly says it does not offer tentative rulings and appearances are necessary for law and motion. | Skip; monitor periodically. |
| Del Norte | [Civil Division](https://www.delnorte.courts.ca.gov/divisions/civil-division) and [case inquiry](https://www.delnorte.courts.ca.gov/case-inquiry-public-access) | No tentative surface found; case portal is for case data. | Monitor official site/search and local rules. |
| Glenn | [Case Search](https://www.glenn.courts.ca.gov/self-help/case-search) and [Court Calendars](https://www.glenn.courts.ca.gov/self-help/court-calendars) | Tyler public case/calendar search exists, but no tentative page or PDF surface was found. | Monitor; do not treat calendars as rulings. |
| Humboldt | [Online Services](https://www.humboldt.courts.ca.gov/online-services) and [calendars/judicial assignments](https://www.humboldt.courts.ca.gov/general-information/remote-and-telephonic-appearances/judicial-assignmentscalendars) | Static court info/calendars only; no tentative page or portal surface found. | Monitor site search/navigation. |
| Inyo | [Court Calendar](https://www.inyo.courts.ca.gov/general-information/court-calendar) and [Online Services](https://www.inyo.courts.ca.gov/online-services) | Calendars are capturable, but no tentative surface was found. | Mark unsupported; monitor. |
| Kern | [Case Information Search](https://www.kern.courts.ca.gov/online-services/case-information-search) and [Civil and Small Claims](https://www.kern.courts.ca.gov/divisions/civil-and-small-claims) | No public tentative surface found; case portal is registered-user oriented. | Do not build a tentative parser unless a hidden official source appears. |
| Lake | [Courtrooms and Holidays](https://lake.courts.ca.gov/general-information/courtrooms-and-holidays) | Court expressly says it does not publish tentative rulings. | Skip; optional calendar capture only. |
| Lassen | [Case Index & Calendar Portal](https://www.lassen.courts.ca.gov/online-services/case-index-calendar-portal) and [Law & Motion Calendars](https://www.lassen.courts.ca.gov/general-information/law-motion-calendars) | Public calendar portal, but no ruling surface found. | Do not treat calendars as tentatives. |
| Madera | [Civil](https://www.madera.courts.ca.gov/divisions/civil-limited-unlimited-cases) | Local rule says the court does not routinely issue advance tentatives; if it does, parties are notified directly. | Skip live capture. |
| Mariposa | [Case Information](https://www.mariposa.courts.ca.gov/online-services/case-information) and [Local Rules](https://www.mariposa.courts.ca.gov/general-information/local-rules) | Tyler public case information only; no tentative publication surface found. | Skip tentative capture. |
| Modoc | [Public Case Portal](https://www.modoc.courts.ca.gov/online-services/public-case-portal) | Public case portal exists, but no tentative surface found. | Skip; local rules contemplate possible future tentative procedure. |
| Mono | [Court Calendars](https://www.mono.courts.ca.gov/general-information/court-calendars) and [Civil Division](https://www.mono.courts.ca.gov/divisions/civil-division) | Google Drive weekly calendars exist, but they are not rulings. | Skip tentative capture. |
| Siskiyou | [Online Services](https://www.siskiyou.courts.ca.gov/online-services), [courtroom calendar](https://www.siskiyou.courts.ca.gov/general-information/courtroom-calendar), and [case portal](https://caseportal.siskiyou.courts.ca.gov/) | No public tentative feed found; portal/calendar only. | Monitor; local rules allow a future procedure. |
| Sutter | [Tentative Rulings](https://www.sutter.courts.ca.gov/online-services/tentative-rulings) and [civil FAQ](https://www.sutter.courts.ca.gov/divisions/civil/civil-faqs) | Court expressly says it does not issue tentative rulings and appearances are required. | Store as no-tentatives county and periodically recheck. |
| Tehama | [Online Services](https://www.tehama.courts.ca.gov/online-services) and [calendar portal](https://www.tehama.courts.ca.gov/online-services/calendar-portal) | Calendar portal is hearings/info only; no tentative-ruling surface found. | Monitor online services/local rules. |
| Trinity | [Online Services](https://www.trinity.courts.ca.gov/online-services), [court calendars](https://www.trinity.courts.ca.gov/online-services/court-calendars), and [civil](https://www.trinity.courts.ca.gov/divisions/civil) | Weekly calendars exist, but no rulings/notes surface was found. | Monitor. |

## Implementation Order

1. Keep daily direct-HTTP capture running for implemented `LANDING_PAGES`.
2. Add parsers only after representative fixtures and parser tests exist.
3. Add parsers for the new daily-capture counties, starting with PDF sources
   that have stable layouts: Butte, Imperial, Marin, San Benito, San Mateo,
   Santa Cruz, Sierra, Ventura, Monterey, Napa, and San Luis Obispo.
4. Add HTML parsers for Los Angeles, Santa Barbara, Sonoma, Stanislaus, Tulare
   civil, and Yolo once representative page snapshots are in fixtures.
5. Finish Yolo direct document-node/PDF discovery if a stable public route is
   confirmed.
6. Triage San Diego separately because public ROA access appears possible but
   not broad-list friendly.
7. Treat Alameda, Kings, Mendocino, Sacramento, and broad San Joaquin capture as
   blocked or case-led until a lawful public access path is confirmed.
8. Keep no-surface counties as monitored negatives; do not scrape calendars as
   tentative rulings.
