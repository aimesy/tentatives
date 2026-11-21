# Daily Harvest

Courts delete tentative rulings within days, so a missed harvest loses them.
The daily harvest runs on counsel-factory to keep its downloads and Git
transfers off courtproj. Court fetches and local rechecks use existing VPN
lanes. The GitHub Actions capture fallback is disabled.

## Counsel-factory

`tentatives-harvest-live.timer` starts `tentatives-harvest@live.service` at
5 PM America/Los_Angeles. The service runs `/usr/local/sbin/tentatives-harvest`
(`ops/tentatives-harvest`), which clones this repository into a fresh
directory under `/var/tmp` and runs that checkout's `ops/courtproj-harvest.sh`,
so a push here changes the next harvest. The directory, court files included,
is removed when the run ends; logs go to `/var/log/tentatives-harvest.log` and
`/var/log/tentatives-harvest/`.

`ops/courtproj-harvest.sh`:

1. Clones `aimesy/tentatives-data` sparsely: the capture logs, `data/`,
   `status/`, the README, LIVE and the county list, but no court files.
2. Copies `ingest/`, `counties/`, `schema/` and the update scripts beside the
   data, as the Actions workflows do.
3. Marks the day's harvest as running in `status/harvest.json` and pushes it.
4. Runs `ingest.backfill --county all --live --continue-on-error
   --summary-json`, records the result in `status/harvest.json`
   (`ops/harvest_status.py`), and pushes the raw captures before anything
   else can fail.
5. Checks out the sources captured in the last 14 days that no parquet row
   names yet (`ops/materialize_recent.py`), then OCRs, parses, slices,
   refreshes LIVE (in a sparse checkout `update-readme.py` reads the archive's
   file sizes from GitHub's tree API, since `git ls-tree -l` would fetch every
   blob) and builds the viewer data, and pushes that.
6. Fetches the counties to recheck again, through the fallback VPN lane
   (`TENTATIVES_FALLBACK_LANES` in /etc/tentatives-harvest.env), and pushes
   them. After its own pushes it starts Parse new PDFs if parsing failed, and
   Deploy site when the county list changed. It no longer starts Backfill
   captures: that workflow fetches from GitHub's IP, and it is disabled
   (2026-11-18). Every court fetch goes through a Surfshark or PIA lane:
   tentatives-harvest@.service runs the harvest through `ops/vpn-lane-exec`,
   which refuses to run when no lane is up.

Every harvest commit says `[skip ci]`, so none starts a workflow.
`tentatives-harvest-wayback.timer` runs the bounded Wayback check (50 refs a
county) Sundays at 4:17 AM Pacific through the same script.

## Repeat downloads

A harvest downloads a file only when it may be new. `ingest.backfill` keeps
`archive/<county>/fetch-state.ndjson`, one row per fetch URL, beside the
capture logs (so the sparse clone checks it out and the capture commit pushes
it):

- a live file or GET page is requested with the `ETag` (`If-None-Match`) and
  `Last-Modified` (`If-Modified-Since`) the server sent with the archived
  copy; a 304 answer downloads nothing and counts as that file checked, as a
  repeat download did before (`archived/logged N refs` and `refs` in the
  summary still include it, so the zero-capture checks behave as before);
- a URL the court answered 404 or 410 for is recorded as gone and not
  requested again;
- a Wayback capture already in `captures.ndjson` (same URL and timestamp) is
  not fetched again, and is skipped before `--limit` applies, so the weekly
  bounded run spends its 50 on captures it does not have.

Listing pages are still read every day to discover new files. A server that
sends no validators is downloaded and compared by sha256 as before. Delete a
row (or the file) to force a fresh download of that URL.

## Rechecks

`ops/harvest_status.py` marks a county for a recheck through another VPN lane when:

- its discovery failed or it raised an error;
- a fetch failed for any reason but 404 or 410 (a court removing an old file
  is not something a second network can fix), such as Marin answering
  courtproj with 403;
- it captured nothing although it captured something in the last 14 days.

A county that has captured nothing for longer is not rechecked every day;
`status/harvest.json` keeps each county's `last_productive` date. If the
capture fails as a whole (the backfill exits with an error, or no county
captures anything), the recheck is every county.

## The 6 PM check (disabled 2026-11-18)

Backfill captures is disabled (`gh workflow disable`), because it fetches
from GitHub's IP rather than a VPN lane. What follows describes it as it was.

Backfill captures (`.github/workflows/backfill.yml` in
`aimesy/tentatives-data`) has two cron slots, 01:00 and 02:00 UTC, and keeps
the one that is 6 PM Pacific. Its `plan` job reads `status/harvest.json` and
starts the harvest job only when:

- courtproj has not recorded today's harvest at all;
- the capture failed, or has been running for more than three hours;
- counties need a recheck and no fallback ran today, three hours after
  courtproj started (before that, courtproj starts the recheck itself).

GitHub starts cron runs late, by hours at times, so the check is a backstop:
courtproj starts its own fallback runs, and a dispatched run starts at once.
A run that does nothing costs one billed minute. A fallback run records itself
under `fallback` in `status/harvest.json`, so the check does not repeat it.

## Install on the harvest host

```bash
install -m 755 ops/tentatives-harvest /usr/local/sbin/tentatives-harvest
install -m 644 ops/systemd/tentatives-harvest@.service ops/systemd/tentatives-harvest-live.timer ops/systemd/tentatives-harvest-wayback.timer /etc/systemd/system/
# Paths only; the token stays in its file.
printf 'TENTATIVES_TOKEN_FILE=%s\nTENTATIVES_CREDENTIAL_HELPER=%s\n' <token file> <credential helper> > /etc/tentatives-harvest.env
chmod 600 /etc/tentatives-harvest.env
systemctl daemon-reload
systemctl enable --now tentatives-harvest-live.timer tentatives-harvest-wayback.timer
```

Also set `TENTATIVES_HOST=counsel-factory`, `TENTATIVES_PRIMARY_LANES` and
`TENTATIVES_FALLBACK_LANES` in the environment file. Lane values are
space-separated lists of existing Surfshark or PIA network namespaces on
that host. The host label appears in `status/harvest.json` and commit messages.

The service uses one CPU at most, low CPU and I/O priority, a 4 GiB memory
pressure threshold, an 8 GiB memory limit, and no swap. Systemd IP accounting
records its network usage.

Before enabling replacement timers, verify a small capture and private data
repository access, then stop and disable the old host's two timers while no
harvest is running. Keep the old installation and logs for rollback.

The credential helper must read the token from the file; never put a token on
a command line, where every local account can read it.

## Verify

```bash
systemctl list-timers 'tentatives-harvest*'
systemctl start tentatives-harvest@live.service    # a full run now
journalctl -u tentatives-harvest@live.service -n 50
tail -n 50 /var/log/tentatives-harvest.log
```

In `aimesy/tentatives-data`, `status/harvest.json` shows the last live run,
including its host and counties needing a recheck. The GitHub Actions
Backfill captures workflow remains disabled; rerun the live service to retry
through VPN lanes.

## County files over GitHub's limit

GitHub refuses any file over 100 MiB. `ingest/rulings_store.py` writes a
county's rulings as `data/<county>/rulings.parquet` alone while that stays
under 90 MiB, and otherwise splits the rows, in order, into `rulings.parquet`,
`rulings-002.parquet`, `rulings-003.parquet`, ... each under 90 MiB. Los
Angeles crossed the limit on 2026-11-11 and every parsed-data push failed
until this was added. Read a county through `read_county_table`, never
`rulings.parquet` alone.
