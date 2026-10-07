# California Tentative Decisions Database

California superior court tentative rulings, court calendar notes, and other perishable ruling-adjacent material.

The point is preservation first, parsing second. The archive keeps the court source material. The data pipeline normalizes counties only after the parser has fixtures and tests.

> San Francisco Superior Court's general civil, housing, probate, and asbestos litigation departments live in a sibling repo: **[aimesy/sfsc](https://sfsc.amyc.us/)** ([searchable viewer](https://sfsc.amyc.us/)). The San Francisco rows in this repo are the **Unified Family Court** (UFC) calendars only. Everything else SF posts - Departments 204 (Probate), 301 (Discovery), 302 (Civil Law and Motion), 304 (Asbestos Law and Motion), and 501 (Real Property) - is over there.

- Viewer: [tentatives.amyc.us](https://tentatives.amyc.us/)
- Chrome extension: [tentatives-extension.zip](https://tentatives.amyc.us/downloads/tentatives-extension.zip)
- Firefox extension: [tentatives-extension-firefox.zip](https://tentatives.amyc.us/downloads/tentatives-extension-firefox.zip)
- Contact: me@amyc.us

## Repositories

This repository holds the code: the county scrapers and parsers, the ingest pipeline, the browser extension, the viewer and its Workers.

The court sources and parsed data live in the private [aimesy/tentatives-data](https://github.com/aimesy/tentatives-data): `archive/`, `data/`, `LIVE.md` and `site/counties.json`, with the LIVE table, the coverage tables, the releases, the issues and the Actions history. Until 2026-10-07 both lived in one repository named `aimesy/tentatives`. It was renamed to `tentatives-data`, and this repository took the name; the code's history before the split is there.

The daily harvest runs on courtproj and pushes to `tentatives-data`; GitHub Actions there harvests only when courtproj fails or a county needs a recheck ([docs/harvest.md](docs/harvest.md)). The workflows that write data run in `tentatives-data`: Backfill captures, Parse new PDFs, OCR textless PDFs and Deploy site. Each checks out this repository at `master` (or at its `code_ref` input) into `.code/` and copies `ingest/`, `counties/`, `schema/` and the update scripts beside the data, because the modules find `archive/` and `data/` next to themselves. A push here starts the data workflows it affects through `.github/workflows/data.yml`: viewer, Worker and extension changes start Deploy site, and parser changes start Parse new PDFs. The daily harvest always uses `master`.

This repository's workflows need one secret, `TENTATIVES_DATA_CI`: a fine-grained GitHub token for `aimesy/tentatives-data` alone, with Contents read and Actions read and write. Tests use it to fetch the archived regression sources, and `data.yml` uses it to start the data workflows.

To run anything that reads `archive/` or `data/` locally, make a sparse clone of `aimesy/tentatives-data` and copy the code into it, as the workflows do:

```bash
git clone --filter=blob:none --sparse https://github.com/aimesy/tentatives-data.git
cd tentatives-data
git sparse-checkout set data/el-dorado archive/el-dorado
cp -a ../tentatives/ingest ../tentatives/counties ../tentatives/schema ../tentatives/update-readme.py ../tentatives/update-site-counties.py ../tentatives/requirements.txt .
```

## Status

Capture support means this code can find and archive court source material.

Parser support means archived material is converted into normalized rows in `data/<county>/rulings.parquet`.

| County | Capture | Parser | Notes |
|---|---:|---:|---|
| Amador | legacy/Wayback | yes | Legacy dropdown PDFs from public archive/Wayback sources. Current post-02/15/2022 access appears portal-based, so routine daily live checks skip Amador. |
| Butte | yes | yes | Static Drupal PDF lists, including civil/probate/exchange-style calendars. |
| Calaveras | yes | yes | Case-management and civil law-and-motion PDFs. |
| Contra Costa | yes | yes | PDFs, archive pages, and changed HTML page captures for ruling pages and probate calendar notes. |
| El Dorado | yes | yes | Probate, civil law and motion, probate calendar, and family law PDF styles. |
| Fresno | yes | yes | Law and Motion department PDFs. |
| Imperial | yes | yes | Static public PDF surface is captured when live links exist; initial section parser handles the current multi-ruling PDF shape. |
| Los Angeles | yes | yes | Public WebForms department/date result pages parsed from captured HTML. |
| Marin | yes | yes | Static civil, family, and probate PDFs. Recheck after the court's announced July 2, 2026 access change. |
| Merced | yes | yes | Weekday civil law-and-motion PDFs. |
| Monterey | yes | yes | Public tentative-ruling API responses decoded into source PDFs. |
| Napa | yes | yes | Public Google Drive PDFs. |
| Nevada | yes | yes | Static ruling page. Word documents are archived and parsed when their text structure is supported. |
| Orange | yes | yes | Stable current PDF URLs; changed hashes matter. |
| Placer | yes | yes | Civil law and motion PDFs; live pages use relative court-hosted PDF links. |
| Plumas | yes | yes | Department 2 PDFs. |
| Riverside | yes | yes | Regional and department PDF links; landing-page discovery uses a reader fallback when direct HTTP is Cloudflare-blocked. |
| San Benito | yes | yes | Homepage/news PDF links. |
| San Bernardino | yes | yes | Legacy civil table. |
| San Francisco | yes | yes | Unified Family Court (UFC) family-law PDFs only. Departments 204 / 301 / 302 / 304 / 501 (civil, probate, discovery, asbestos, real property) live in [`aimesy/sfsc`](https://sfsc.amyc.us/). |
| San Luis Obispo | yes | yes | Public Google Drive department/probate folders. |
| San Mateo | yes | yes | Static weekday PDFs for civil, probate, family, and related calendars. |
| Santa Barbara | yes | yes | Public Drupal tentative-ruling detail pages. |
| Santa Clara | yes | yes | Department PDF pages; changed hashes matter. |
| Santa Cruz | yes | yes | Public Google Drive weekday PDFs. |
| Shasta | yes | yes | Department PDFs; changed hashes matter. |
| Sierra | yes | yes | Public Google Drive category PDFs; often sparse. |
| Solano | yes | yes | Civil and probate department PDFs. |
| Sonoma | yes | yes | Public Drupal civil, family, and probate page tree parsed from captured HTML. |
| Stanislaus | yes | yes | Public Drupal civil/family/probate-note pages parsed from captured HTML. |
| Tulare | yes | yes | Civil HTML page plus probate PDFs. |
| Tuolumne | yes | yes | Tentative rulings and Case Notes. |
| Ventura | yes | yes | Public date-search form with ViewFile PDFs. |
| Yolo | yes | yes | FullCalendar document links expose law-and-motion tentative-ruling PDFs and probate-note PDFs; password-protected confidential probate PDFs are archived but not parsed. |

See [docs/county-plans.md](docs/county-plans.md) for the broader county triage.

## Data Quality Notes

The current parser-output audit is in [docs/parser-output-audit-2026-06-24.md](docs/parser-output-audit-2026-06-24.md). Use it for current parser sanity findings and semantic follow-up areas. The LIVE table and the detailed coverage tables, generated from current parquet data, are in the [aimesy/tentatives-data](https://github.com/aimesy/tentatives-data) README.

## How It Works

1. The extension or `ingest.backfill` discovers public court material.
2. Source files are fetched, hashed, and stored once at `archive/<county>/<sha[:2]>/<sha>.<ext>`.
3. Source fetches are logged in `archive/<county>/captures.ndjson`.
4. Contra Costa HTML page captures are stored at `archive/contra-costa/pages/<sha[:2]>/<sha>.html`.
5. HTML page captures are logged in `archive/contra-costa/page-captures.ndjson`.
6. Page-layout fingerprints are stored at `archive/<county>/layouts/<sha[:2]>/<sha>.json`.
7. Layout captures are logged in `archive/<county>/layout-captures.ndjson`.
8. `python -m ingest.orchestrate` parses archived material into Parquet.
9. `python -m ingest.slice_rulings` stores per-ruling PDFs at `archive/<county>/rulings/<ruling_id[:2]>/<ruling_id>.pdf` whenever the parsed source is a PDF. For parsed DOCX sources, it writes a derived text PDF while retaining the original DOCX bytes.
10. `python -m ingest.build_viewer_data` derives metadata summaries and individual complete text records from the preserved Parquet sources. `site/` loads only metadata on startup and requests text when a ruling opens.

Re-capture is cheap. For ordinary source-file URLs, the extension skips URLs already logged. For Orange, Santa Clara, Shasta, and Tuolumne, it fetches and hashes first because courts reuse the same filenames while changing the contents. For Contra Costa HTML pages and layout fingerprints, only changed hashes are logged.

## Hosting

The data repository is private, and GitHub Pages cannot serve a private repository on the free plan, so the viewer and its data run as two Cloudflare Workers in `worker/`. Deploy site (`.github/workflows/site.yml` in `aimesy/tentatives-data`) deploys both from this repository's code, the data Worker first; the viewer deploy waits for it, so a failed Worker deploy leaves the current viewer live.

The viewer is the Worker `tentatives` on [tentatives.amyc.us](https://tentatives.amyc.us/) (`worker/site/`): `site/` as static assets, with no script. `worker/site/build.mjs` copies `site/` into `worker/site/dist/` without `site/data/`, `CNAME` or `check-static.mjs`, adds `worker/site/robots.txt` unchanged, and retains conservative build guards of 20,000 files and 25 MiB a file. Static asset requests have no Workers request or CPU charges.

The data is the Worker `tentatives-data` on `tentatives-data.amyc.us` (`worker/data/`, adapted from aimesy/mfa). It holds a GitHub token that can only read `aimesy/tentatives-data`, and serves that repository at URLs that mirror raw.githubusercontent.com:

| Path | Answer |
|---|---|
| `/<commit>/data/<county>/summary.json` | county metadata without disposition, body, or full ruling text |
| `/<commit>/data/<county>/rulings/<id>.json` | one complete ruling text record, metered with its PDF |
| `/<commit>/archive/<county>/rulings/<xx>/<id>.pdf` | the PDF slice of one ruling, cached for a year |
| `/<commit>/LIVE.md` | the metrics table the amyc.us home page shows |
| `/master/<path>` | the same files at the head of `master`, cached for five minutes |
| `/ref` | the commit at `master`, as text, cached for five minutes |
| `/robots.txt` | disallows everything; every answer also carries `X-Robots-Tag: noindex` |

Anything else is a 404. `DATA_PATH` in `site/app.js` and in `worker/data/release.js` must stay equal; `site/check-static.mjs` fails if they differ. The viewer asks `/ref` once a visit and reads every file at that commit, so new data shows up within five minutes without a deploy.

The default entrypoint is never cached. It answers CORS preflights, refuses (403) any request whose `Origin`, or failing that `Referer`, is not in `ALLOWED_ORIGINS` in `worker/data/wrangler.toml` (the viewer and `https://amyc.us`), and limits each address (an IPv4 address, or an IPv6 /64) to 300 requests a minute, answering 429 with `Retry-After` past that. It then sends the cached `Release` entrypoint a fresh request built from the path and `Range` alone. `Release` fetches the file from raw.githubusercontent.com with the token; Workers Caching stores the whole file and answers byte ranges from the stored copy. A PDF slice opened from the viewer passes by its `Referer`; the same link opened from anywhere else gets 403.

Then come the browser check and the document limits in `worker/data/gate.js`, the same file every data Worker carries (canonical copy in aimesy/mfa). The viewer passes Cloudflare Turnstile (`site/data-session.js`), invisibly unless Cloudflare wants a click, and posts the token to `/session`; the Worker answers with a session cookie for 12 hours, bound to the address, and on the first check a browser ID cookie for 400 days. With `REQUIRE_SESSION = "true"` a request without a session gets 401, except the open summary files in `OPEN_PATHS` (`/master/LIVE.md`, which the home page reads). Documents are individual rulings (`documentKey` in `worker/data/release.js`). Complete text and the same ruling’s PDF share one document allowance, independent of commit and byte range. Metadata summaries never count. Source Parquet tables and internal record files are refused at every ref. A ruling counts once a UTC day however often it is reopened. Each check allows 100 distinct rulings, then a visible check gives the next 100; a browser may open 500 a UTC day and 1,000 in any 7 days, an address 2,000 a day. Past those the Worker answers 429 "File limit exceeded. For bulk access, please email db@amyc.us." More than 50 in a minute ends the session and asks for a visible check after 10 minutes. A slice link is checked with a HEAD request before its tab opens. A trusted key (`TRUSTED_KEY_HASHES`, made with `scripts/new-trusted-key.mjs` in aimesy/mfa) lifts the document limits for 30 days. Every number is a variable in `worker/data/wrangler.toml`, and the `DailyQuota` Durable Object keeps the counts; counter failures preserve the specified fail-open behavior.

GitHub's REST API allows 5,000 requests an hour, shared by every token Amy owns. Only `/ref` uses it; files come from raw.githubusercontent.com. Workers Caching is tiered, so a cold page load costs at most one REST call (`/ref`, once per five minutes per cache) and one raw fetch for each selected county file not yet cached at that commit; a warm load costs no GitHub calls. Each deploy of the data Worker empties its cache, so Deploy site redeploys it only when a push here changes `worker/data/`, when the workflow changed, on a manual run, or when the account does not have it.

The account uses Workers Paid, confirmed on 2026-10-03. Dynamic requests and CPU usage follow the account’s [Workers Paid billing](https://developers.cloudflare.com/workers/platform/pricing/), including monthly allowances and usage charges. The former Free plan cutoff of 100,000 requests a day no longer applies. The browser and document limits above remain enforced by this application.

Secrets, in the Actions secrets of `aimesy/tentatives-data`:

- `TENTATIVES_DATA_ACCESS`: a fine-grained GitHub token with read access to the contents of `aimesy/tentatives-data` and nothing else. The workflow stores it as the Worker secret `TENTATIVES_DATA_TOKEN` through a private temporary file.
- `TURNSTILE_SECRET_KEY`: the secret key of the Turnstile widget the five amyc.us viewers share; its site key is in `site/data-session.js`. The workflow stores it as the Worker secret of the same name, with a new random `SESSION_KEY` on each deploy. Without it the Worker still deploys, but `/session` answers 503.
- `CLOUDFLARE_API_KEY`: a Cloudflare API token from the "Edit Cloudflare Workers" template, limited to the account and the `amyc.us` zone. The workflow hands it to Wrangler as `CLOUDFLARE_API_TOKEN`.

After each deploy the workflow checks both Workers from the runner. Bot Fight Mode on `amyc.us` may answer GitHub's runners with a challenge; the check then warns instead of failing.

Before deployment, the workflow builds and verifies all viewer outputs with `python -m ingest.build_viewer_data` and `python -m ingest.build_viewer_data --check`, then commits the complete private dataset. It preserves source Parquet files and ruling text. Oversized legacy title and motion labels are omitted from the metadata index and remain complete in the metered detail record. Browser search covers metadata and text already opened during the visit; CSV exports contain metadata. Protected responses use `private, no-store`; the internal Release cache remains enabled.

Locally, `node worker/worker.test.mjs` tests the data Worker, and `node worker/site/build.mjs` builds and checks the viewer's assets. Served from `localhost`, the viewer reads prepared `data/` from a local data checkout with this code copied in (Repositories, above) instead of the Worker; run `python -m ingest.build_viewer_data` first. To run the data Worker itself, put `TENTATIVES_DATA_TOKEN=<token>` and `ALLOWED_ORIGINS=<an origin to test with>` in `worker/data/.dev.vars` (git ignores it), run `npx wrangler@4 dev` in `worker/data/`, and send its paths that origin in an `Origin` header.

## Extension

Install the public viewer download for your browser, linked above. The viewer deploy and extension release workflow use `.github/scripts/package_extension.py`, so both publish the same browser packages. For Firefox development, load `extension/` unpacked. For Chrome side-panel development, use the generated Chrome zip. Uploading captures requires write access to `aimesy/tentatives-data`; contact [me@amyc.us](mailto:me@amyc.us) for access.

Open Settings and set a GitHub token with Contents read/write access. Owner, repo, and branch default to `aimesy/tentatives-data@master`. Version 0.7.1 moves a saved `aimesy/tentatives` setting to `aimesy/tentatives-data` when it updates.

The side panel can:

- upload PDFs from the active supported court tab;
- fetch one listed court page;
- scan every page for one county;
- scan selected counties, with all configured counties selected by default;
- shell-scan selected counties in parallel browser tabs, pausing if a page needs manual attention;
- pause, resume, or stop a long scan;
- retry a failed landing page three times before moving on.
- document page layout fingerprints the first time a page is scanned, then again only when the structure changes.

For Contra Costa page snapshots, open the public court pages rather than the internal iframe URLs. The extension keeps `cc-courts.org` permission because the official Contra Costa pages load that host in an iframe, and the content script must read the frame. PDF backfill now uses the public retired.cc-courts.org iframe URL directly.

## Backfill

Run live or Wayback capture from the command line:

```bash
python -m ingest.backfill --county all --live --continue-on-error
python -m ingest.backfill --county all --wayback --continue-on-error --limit 25 --dry-run
python -m ingest.backfill --county amador --wayback --url-from-year 2020 --url-to-year 2022
python -m ingest.backfill --county orange --live --wayback --limit 25
```

`--county all` means the configured CLI-backed counties. Contra Costa PDFs are included through a direct adapter for the public retired.cc-courts.org iframe URL. Browser-only work is limited to extension page snapshots or future public sites that still need active page execution after direct HTTP fails.

Courtproj runs live capture daily at 5 PM America/Los_Angeles and a bounded Wayback check weekly, because current URLs may acquire archived versions later. Backfill captures in `aimesy/tentatives-data` runs only as the fallback: for counties courtproj could not capture, or for every county when courtproj did not harvest at all. [docs/harvest.md](docs/harvest.md) covers both and the recheck rules; the maintainer loop is in [docs/maintainer-routine.md](docs/maintainer-routine.md).

Wayback has not been exhaustively backfilled yet. The local archive currently has 518 capture-manifest rows with `wayback_ts` across Amador, Calaveras, El Dorado, Fresno, Merced, Nevada, Orange, Placer, Plumas, San Bernardino, Santa Clara, Shasta, and Solano. Start bounded, then widen.

## Parse

Install dependencies and run tests:

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt pytest
pytest
python -m ingest.orchestrate --dry-run
```

The county tests also read archived regression sources from `archive/`, and `ingest.orchestrate` reads the archive, so run them from a data checkout with this code copied in (Repositories, above). In CI, `.github/scripts/test_archive_paths.py` lists those sources and the Tests workflow fetches only them.

Run one county:

```bash
python -m ingest.orchestrate --county contra-costa --dry-run
python -m ingest.orchestrate --county contra-costa --reparse-existing --dry-run
python -m ingest.orchestrate --max-sources-per-county 50
```

By default, `ingest.orchestrate` skips source hashes already represented in Parquet. Use `--reparse-existing` for parser migrations, or `--max-sources-per-county` for bounded local smoke runs. The data repository's workflows parse all new archived sources after capture, slices parsed PDF rulings, and files a failure report if a new source shape breaks parsing. The parser registry is derived from county modules with a callable `parse`; counties without a parser stay in the archive until representative fixtures and tests exist.

Daily backfill runs an OCR sidecar pass before parsing. For manual re-runs, use the `OCR textless PDFs` workflow or run `python -m ingest.ocr_missing_text --county <slug>` locally. OCR output is non-destructive: raw court PDFs stay in `archive/<county>/<sha[:2]>/<sha>.pdf`, while searchable sidecars are written under `archive/<county>/ocr/<sha[:2]>/<sha>.pdf`. `ingest.orchestrate` uses the sidecar for parsing when present but keeps the original source hash and URL.

## Layout

```text
schema/                          shared Capture and Ruling records
counties/<county>/scraper.py     discovery and parser code
counties/<county>/tests/         fixtures and parser/discovery tests
ingest/backfill.py               live and Wayback capture into archive/
ingest/orchestrate.py            archive -> data/<county>/rulings.parquet
archive/<county>/captures.ndjson source capture provenance
archive/<county>/rulings/        per-ruling PDF slices when source is a PDF
archive/<county>/pages/          changed HTML page captures, currently Contra Costa
archive/<county>/layouts/        changed page-layout fingerprints
data/<county>/rulings.parquet    normalized rows for the viewer
extension/                       browser capture extension
site/                            static viewer
```

`archive/` and `data/` are in `aimesy/tentatives-data`.

## Adding A County

1. Add `counties/<slug>/__init__.py` with `COUNTY_SLUG` and `PARSER_VERSION`.
2. Add discovery in `counties/<slug>/scraper.py`.
3. Add fixture HTML and discovery tests.
4. Add parser tests only after you have representative source files.
5. Implement `parse(...) -> list[Ruling]`.
6. Make `parse` callable from `counties/<slug>/scraper.py`; the registry is derived dynamically.
7. Add extension support only when the browser path is needed or useful.

Filename and link-text hints are allowed for capture. Parser facts should come from the source document or page text whenever possible.

## Sharp Edges

- Capture support is not parser support.
- Existing rows are keyed by `ruling_id`; changing `parser_version` alone does not force a reparse.
- `captures.ndjson` may contain several rows for one SHA.
- Nevada can publish `.docx`; this repo archives those source files, parses supported Word-text calendars, and can emit derived per-ruling text PDFs while retaining the original DOCX.
- Contra Costa page captures are normalized as page rows, not as PDF rulings.
- Login-backed or authenticated systems are out of scope unless there is a public lawful access path.
- Before treating a source as not automatically scrapeable, try direct HTTP, sessioned form replay, headless browser, and a headed browser in a VPS virtual display. `docs/county-plans.md` tracks the current blockers and app/desktop fallbacks.
