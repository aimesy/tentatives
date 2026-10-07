# Daily Harvest

Courts delete tentative rulings within days, so a missed harvest loses them.
The daily harvest runs on courtproj, the SFSC server, and GitHub Actions in
`aimesy/tentatives-data` runs only when courtproj fails. Actions minutes on the
private data repository are metered; courtproj costs nothing extra.

## Courtproj

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
   refreshes LIVE (`update-readme.py` counts the archive from the Git tree
   in a sparse checkout) and builds the viewer data, and pushes that.
6. Starts a fallback in the data repository only after its own pushes:
   Backfill captures for the counties to recheck, or Parse new PDFs if
   parsing failed. It starts Deploy site when the county list changed.

Every courtproj commit says `[skip ci]`, so none starts a workflow.
`tentatives-harvest-wayback.timer` runs the bounded Wayback check (50 refs a
county) Sundays at 4:17 AM Pacific through the same script.

## Rechecks

`ops/harvest_status.py` marks a county for a recheck in GitHub Actions when:

- its discovery failed or it raised an error;
- a fetch failed for any reason but 404 or 410 (a court removing an old file
  is not something a second network can fix), such as Marin answering
  courtproj with 403;
- it captured nothing although it captured something in the last 14 days.

A county that has captured nothing for longer is not rechecked every day;
`status/harvest.json` keeps each county's `last_productive` date. If the
capture fails as a whole (the backfill exits with an error, or no county
captures anything), the recheck is every county.

## The 6 PM check

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

## Install on courtproj

```bash
install -m 755 ops/tentatives-harvest /usr/local/sbin/tentatives-harvest
install -m 644 ops/systemd/tentatives-harvest@.service ops/systemd/tentatives-harvest-live.timer ops/systemd/tentatives-harvest-wayback.timer /etc/systemd/system/
# Paths only; the token stays in its file.
printf 'TENTATIVES_TOKEN_FILE=%s\nTENTATIVES_CREDENTIAL_HELPER=%s\n' <token file> <credential helper> > /etc/tentatives-harvest.env
chmod 600 /etc/tentatives-harvest.env
systemctl daemon-reload
systemctl enable --now tentatives-harvest-live.timer tentatives-harvest-wayback.timer
```

The credential helper must read the token from the file; never put a token on
a command line, where every local account can read it.

## Verify

```bash
systemctl list-timers 'tentatives-harvest*'
systemctl start tentatives-harvest@live.service    # a full run now
journalctl -u tentatives-harvest@live.service -n 50
tail -n 50 /var/log/tentatives-harvest.log
```

In `aimesy/tentatives-data`, `status/harvest.json` shows the last run, and
`gh run list -R aimesy/tentatives-data --workflow backfill.yml` shows whether a
fallback ran. Run a fallback by hand with
`gh workflow run backfill.yml -R aimesy/tentatives-data -f county=marin,yolo -f mode=live`.
