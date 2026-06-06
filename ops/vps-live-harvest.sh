#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${GATE_PACIFIC_5PM:-0}" == "1" ]]; then
  pacific_hour="$(TZ=America/Los_Angeles date +%H)"
  if [[ "$pacific_hour" != "17" ]]; then
    echo "not 5 PM Pacific (hour=$pacific_hour); skipping duplicate UTC slot"
    exit 0
  fi
fi

exec 9>"$ROOT/.tentatives-live-harvest.lock"
if ! flock -n 9; then
  echo "another tentatives live harvest is already running"
  exit 0
fi

git fetch origin master
git checkout master
git pull --ff-only origin master

if [[ -d .venv-vps ]] && ! .venv-vps/bin/python -m pip --version >/dev/null 2>&1; then
  echo "removing incomplete .venv-vps without pip"
  rm -rf .venv-vps
fi

if [[ ! -d .venv-vps ]]; then
  python3 -m venv .venv-vps
fi

# Keep this idempotent; requirements are small, and the VPS should survive
# dependency changes without a separate manual step.
.venv-vps/bin/python -m pip install -r requirements.txt

set -o pipefail
.venv-vps/bin/python -m ingest.backfill --county all --live --continue-on-error | tee vps-live-harvest.log

if ! grep -Eq '^[-[:alnum:]]+: archived/logged [1-9][0-9]* refs$' vps-live-harvest.log; then
  echo "scheduled live harvest archived zero capture refs" >&2
  exit 1
fi

if git diff --quiet -- archive/; then
  echo "no archive changes"
  exit 0
fi

git config user.name "tentatives-bot"
git config user.email "tentatives-bot@users.noreply.github.com"
git add archive/
git commit -m "archive: backfill captures"

for attempt in 1 2 3; do
  git pull --rebase origin master
  if git push origin master; then
    exit 0
  fi
  sleep $((attempt * 5))
done

exit 1
