# VPS Daily Harvest

This repo already has a GitHub Actions live harvest. A VPS timer is useful as a
second forward-capture path, especially for sites where a real browser or
desktop session may later be needed.

The VPS timer runs at 5 PM America/Los_Angeles every day. It uses two UTC
systemd calendar slots, 00:00 and 01:00, then gates inside the script using
`TZ=America/Los_Angeles`; this keeps the schedule correct across Pacific DST
without changing the VPS system timezone.

## Install

On the VPS:

```bash
sudo mkdir -p /opt/aimesy
sudo chown "$USER":"$USER" /opt/aimesy
git clone https://github.com/aimesy/tentatives.git /opt/aimesy/tentatives
cd /opt/aimesy/tentatives
chmod +x ops/vps-live-harvest.sh

sudo cp ops/systemd/tentatives-live-harvest.service /etc/systemd/system/
sudo cp ops/systemd/tentatives-live-harvest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tentatives-live-harvest.timer
```

The clone must be able to push to `aimesy/tentatives`. Use a deploy key, a
machine account, or Git Credential Manager. Do not put tokens in the repo or in
the unit file.

The VPS lane intentionally runs the same `ingest.backfill` entry point as
GitHub Actions. County-specific fallbacks stay in the repo code:

- Amador is skipped for routine all-county live runs because the public page is
  historical-only.
- Riverside uses reader fallback for discovery when direct HTTP sees
  Cloudflare.
- Placer has a scoped TLS-verification exception for court-hosted source files.
- Santa Clara departments 16, 19, and 22 use `dept-N` page slugs.

## Verify

```bash
systemctl list-timers tentatives-live-harvest.timer
sudo systemctl start tentatives-live-harvest.service
journalctl -u tentatives-live-harvest.service -n 200 --no-pager
```

If the manual start is not during the 5 PM Pacific hour, the service exits
cleanly with a "skipping duplicate UTC slot" message. To force a manual run:

```bash
cd /opt/aimesy/tentatives
GATE_PACIFIC_5PM=0 ops/vps-live-harvest.sh
```

## What It Does

1. Fast-forwards `master` from GitHub.
2. Creates or reuses `.venv-vps`.
3. Runs `python -m ingest.backfill --county all --live --continue-on-error`.
4. Refuses a scheduled run that archives zero refs.
5. Commits archive changes and rebases before pushing, preserving bot/archive
   commits if `master` moved.

Pushing archive changes triggers the existing `Parse new PDFs` GitHub workflow,
which updates Parquet and the Pages viewer.
