# VPS Daily Harvest (Retired)

The scheduled live harvest now runs in GitHub Actions. Do not install or keep a
persistent VPS checkout for this repository.

The old VPS timer cloned the repository to `/opt/aimesy/tentatives` and reused
that working tree. Because archive sources are tracked in the repo, that left a
full copy of every archived source PDF on the SFSC VPS. That is not the default
architecture anymore. GitHub Actions is the canonical scheduled lane, and it
commits `archive/` plus parsed `data/` updates directly to the repository.

## Canonical Automation

- `.github/workflows/backfill.yml` runs the daily live harvest at 5 PM
  America/Los_Angeles and the weekly Wayback check.
- The same workflow parses archived sources and slices PDF rulings before
  committing `archive/` and `data/`.
- Pushing archive changes updates the Pages viewer through the existing site
  workflow.

## Retiring an Old VPS Install

On any VPS that still has the old timer:

```bash
sudo systemctl disable --now tentatives-live-harvest.timer || true
sudo systemctl stop tentatives-live-harvest.service || true
sudo rm -f /etc/systemd/system/tentatives-live-harvest.service
sudo rm -f /etc/systemd/system/tentatives-live-harvest.timer
sudo systemctl daemon-reload
```

Before deleting `/opt/aimesy/tentatives`, verify it has no active process and no
unpushed work:

```bash
cd /opt/aimesy/tentatives
git fetch origin master
git status --short --branch
git rev-list --left-right --count HEAD...origin/master
```

If the checkout is clean and aligned, remove it:

```bash
sudo rm -rf --one-file-system /opt/aimesy/tentatives
sudo rmdir /opt/aimesy 2>/dev/null || true
```

## Temporary VPS Fallback

Use this only when GitHub Actions cannot reach a source and a real VPS network
path is needed. Run it from a temporary clone, then delete the clone in the same
shell:

```bash
workdir="$(mktemp -d /var/tmp/aimesy-tentatives-live.XXXXXX)"
trap 'rm -rf "$workdir"' EXIT
git clone --depth 1 https://github.com/aimesy/tentatives.git "$workdir/repo"
cd "$workdir/repo"
GATE_PACIFIC_5PM=0 ops/vps-live-harvest.sh
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
gh workflow run "Backfill captures" -f county=all -f mode=live
gh run list --workflow "Backfill captures" --limit 5
```

For a temporary VPS fallback, verify the temporary working tree is gone after
the shell exits and that the VPS has no retained PDFs:

```bash
find / -xdev -type f -iname '*.pdf' 2>/dev/null
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
