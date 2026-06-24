#!/usr/bin/env bash
# Open (or update) a GitHub issue describing a workflow failure, packing in
# enough context that a future LLM (or human) can reproduce and fix it
# without scrolling through the Actions UI. Intended to run from
# `if: failure()` steps in scheduled workflows.
#
# Env contract:
#   WORKFLOW_LABEL   short human name, e.g. "Backfill captures"      (required)
#   LOG_PATH         path to a log file we should excerpt             (optional)
#   EXTRA_CONTEXT    free-form markdown appended near the top         (optional)
#   GH_TOKEN         a token with `issues: write` on this repo        (required)
#
# Also reads GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_SHA, GITHUB_REF_NAME,
# GITHUB_WORKFLOW, GITHUB_EVENT_NAME from the runner environment.
#
# Idempotency: if an open issue already exists with the exact title for this
# day, we append a comment instead of opening a duplicate.

set -euo pipefail

: "${WORKFLOW_LABEL:?WORKFLOW_LABEL is required}"
: "${GH_TOKEN:?GH_TOKEN is required (give the step env: GH_TOKEN: \${{ secrets.GITHUB_TOKEN }})}"

REPO="${GITHUB_REPOSITORY:-unknown/unknown}"
RUN_URL="https://github.com/${REPO}/actions/runs/${GITHUB_RUN_ID:-0}"
TODAY="$(date -u +'%Y-%m-%d')"
TITLE="[${WORKFLOW_LABEL}] failed ${TODAY}"

body_file="$(mktemp)"
{
  echo "## What failed"
  echo
  echo "Workflow **${WORKFLOW_LABEL}** failed on $(date -u +'%Y-%m-%dT%H:%M:%SZ')."
  echo
  echo "- Run: ${RUN_URL}"
  echo "- Trigger: \`${GITHUB_EVENT_NAME:-unknown}\`"
  echo "- Branch: \`${GITHUB_REF_NAME:-unknown}\`"
  echo "- Commit: \`${GITHUB_SHA:-unknown}\`"
  echo
  if [ -n "${EXTRA_CONTEXT:-}" ]; then
    echo "### Context"
    echo
    printf '%s\n\n' "$EXTRA_CONTEXT"
  fi
  echo "## Log tail"
  echo
  echo '```'
  if [ -n "${LOG_PATH:-}" ] && [ -f "$LOG_PATH" ]; then
    tail -n 300 "$LOG_PATH"
  else
    echo "(no log file at \${LOG_PATH:-unset})"
  fi
  echo '```'
  echo
  echo "## Environment"
  echo
  echo "- Runner OS: \`${RUNNER_OS:-unknown}\`"
  echo "- Python: \`$(python --version 2>&1)\`"
  echo
  echo "Installed package versions:"
  echo
  echo '```'
  pip show pyarrow pikepdf pypdf requests 2>/dev/null | grep -E '^(Name|Version):' || true
  echo '```'
  echo
  echo "## Counties registered for live discovery"
  echo
  echo '```'
  python -c "
from counties.registry import discovery_modules
for slug, module in discovery_modules().items():
    landing = getattr(module, 'LANDING_PAGES', [])
    print(f'{slug:18} landing={len(landing)}')
" 2>&1 || true
  echo '```'
  echo
  echo "## Reproduce locally"
  echo
  echo '```bash'
  echo "git fetch origin && git checkout ${GITHUB_SHA:-HEAD}"
  echo "pip install -r requirements.txt"
  case "$WORKFLOW_LABEL" in
    *Backfill*)
      echo "python -m ingest.backfill --county all --live --continue-on-error"
      echo "python -m ingest.ocr_missing_text --county all"
      echo "python -m ingest.orchestrate"
      echo "python -m ingest.slice_rulings"
      echo "python update-readme.py"
      ;;
    *Parse*)
      echo "python -m ingest.ocr_missing_text --county all"
      echo "python -m ingest.orchestrate"
      echo "python -m ingest.slice_rulings"
      echo "python update-readme.py"
      ;;
    *OCR*)
      echo "python -m ingest.ocr_missing_text --county all"
      echo "python -m ingest.orchestrate"
      echo "python -m ingest.slice_rulings"
      echo "python update-readme.py"
      ;;
    *)
      echo "# see .github/workflows for the exact commands the runner used"
      ;;
  esac
  echo '```'
  echo
  echo "## Where to look"
  echo
  echo "- Workflow files: \`.github/workflows/\` (run URL above identifies which one fired)"
  echo "- Backfill driver: \`ingest/backfill.py\` (host allowlist + capture writer)"
  echo "- OCR sidecar driver: \`ingest/ocr_missing_text.py\`"
  echo "- Parse driver: \`ingest/orchestrate.py\`"
  echo "- Per-county discovery / parsing: \`counties/<slug>/scraper.py\`"
  echo "- Slice pipeline: \`ingest/slice_rulings.py\`"
  echo "- Maintainer runbook: \`docs/maintainer-routine.md\`"
  echo "- County registry: \`counties/registry.py\` (which counties are picked up by \`--county all\`)"
  echo
  echo "## Recent commits on this branch"
  echo
  echo '```'
  git log --oneline -10 2>/dev/null || echo "(git log unavailable)"
  echo '```'
  echo
  echo "## Likely failure modes"
  echo
  echo "- A county changed its CMS layout, breaking \`discover_live\`'s regex (look for a county printed in the log with zero refs)."
  echo "- A landing page returned non-200 (look for HTTP status codes in the log)."
  echo "- An archive directory grew past a transfer limit (look for HTTP 413 in the push step)."
  echo "- A parser raised on a newly-shaped PDF (look for a traceback in the log; the offending source_sha256 will usually appear nearby)."
  echo "- Dependency drift after a requirements bump (compare package versions above against the diff at \`requirements.txt\`)."
  echo
  echo "_Filed automatically by \`.github/scripts/file_failure_report.sh\`._"
} > "$body_file"

# De-dupe: if an open issue with this exact title already exists today, comment
# on it instead of opening a fresh one.
existing="$(gh issue list --state open --search "in:title \"$TITLE\"" --json number,title --jq '.[] | select(.title == "'"$TITLE"'") | .number' | head -1 || true)"

if [ -n "$existing" ]; then
  gh issue comment "$existing" --body-file "$body_file"
  echo "Commented on existing issue #$existing"
else
  gh issue create \
    --title "$TITLE" \
    --body-file "$body_file" \
    --label "automation-failure" \
    || gh issue create \
        --title "$TITLE" \
        --body-file "$body_file"
fi
