#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# The scheduled harvest now runs in GitHub Actions. The old SFSC VPS install
# kept a full persistent checkout under /opt/aimesy/tentatives, which meant the
# VPS carried every archived source PDF. Manual VPS fallback runs should use a
# temporary clone and let the trap in the operator's wrapper delete it.
if [[ "${ALLOW_PERSISTENT_VPS_CHECKOUT:-0}" != "1" && "$ROOT" == "/opt/aimesy/tentatives" ]]; then
  echo "refusing to run from persistent /opt/aimesy/tentatives checkout" >&2
  echo "GitHub Actions is the canonical scheduled harvest; use a temporary clone for VPS fallback" >&2
  exit 2
fi

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

printf '\n== OCR textless PDFs ==\n' >> vps-live-harvest.log
.venv-vps/bin/python -m ingest.ocr_missing_text --county all | tee -a vps-live-harvest.log

printf '\n== parse archived sources ==\n' >> vps-live-harvest.log
.venv-vps/bin/python -m ingest.orchestrate | tee -a vps-live-harvest.log

printf '\n== slice parsed PDF rulings ==\n' >> vps-live-harvest.log
.venv-vps/bin/python -m ingest.slice_rulings | tee -a vps-live-harvest.log

.venv-vps/bin/python update-readme.py

if git diff --quiet -- archive/ data/ README.md LIVE.md; then
  echo "no archive, OCR, data, or LIVE changes"
  exit 0
fi

git config user.name "tentatives-bot"
git config user.email "tentatives-bot@users.noreply.github.com"
git add archive/ data/ README.md LIVE.md
git commit -m "archive: backfill captures and parsed data"

for attempt in 1 2 3; do
  git pull --rebase origin master
  if git push origin master; then
    exit 0
  fi
  sleep $((attempt * 5))
done

exit 1
