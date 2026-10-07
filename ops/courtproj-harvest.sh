#!/usr/bin/env bash
# One tentatives harvest on courtproj (docs/harvest.md). ops/tentatives-harvest
# clones this repository into a fresh work directory and runs this script:
#   courtproj-harvest.sh WORK live      the daily capture, 5 PM Pacific
#   courtproj-harvest.sh WORK wayback   the weekly bounded Wayback check
#
# It clones aimesy/tentatives-data sparsely (logs, data/, status/; no court
# files), copies the code beside the data, captures, pushes the raw captures,
# then OCRs, parses, slices and refreshes LIVE and the viewer data, and pushes
# those. Every commit says [skip ci], so none of them starts a GitHub Actions
# run. The script starts one itself only as a fallback, after its own pushes:
#   Backfill captures  for the counties to recheck (all, if the capture failed)
#   Parse new PDFs     if parsing failed
#   Deploy site        if the county list changed
#
# Environment (EnvironmentFile of tentatives-harvest@.service):
#   TENTATIVES_TOKEN_FILE         file holding a GitHub token that can push to
#                                 the data repository and start its workflows
#   TENTATIVES_CREDENTIAL_HELPER  git credential helper that reads that file
set -euo pipefail
WORK="$1"
MODE="${2:-live}"
: "${TENTATIVES_TOKEN_FILE:?}" "${TENTATIVES_CREDENTIAL_HELPER:?}"
DATA_REPO="${TENTATIVES_DATA_REPO:-aimesy/tentatives-data}"
VENV="${TENTATIVES_VENV:-/var/lib/tentatives-harvest/venv}"
CODE="$WORK/code"
DATA="$WORK/data"
# The empty helper comes first so no global helper stores the token.
export GIT_CONFIG_COUNT=2
export GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0=
export GIT_CONFIG_KEY_1=credential.helper GIT_CONFIG_VALUE_1="$TENTATIVES_CREDENTIAL_HELPER $TENTATIVES_TOKEN_FILE"
TODAY="$(TZ=America/Los_Angeles date +%F)"

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

# Start a workflow in the data repository. The token reaches curl on stdin.
dispatch() {
  local workflow="$1"; shift
  local body
  body="$(python3 -c 'import json, sys; print(json.dumps({"ref": "master", "inputs": dict(a.split("=", 1) for a in sys.argv[1:])}))' "$@")"
  if printf 'Authorization: Bearer %s\n' "$(tr -d '\r\n' < "$TENTATIVES_TOKEN_FILE")" \
      | curl -sS --fail-with-body --max-time 60 -H @- -H "Accept: application/vnd.github+json" \
          -X POST -d "$body" "https://api.github.com/repos/$DATA_REPO/actions/workflows/$workflow/dispatches" >/dev/null; then
    log "started $workflow $*"
  else
    log "COULD NOT START $workflow $*; the 6 PM check in Backfill captures is the backstop"
  fi
}

# Commit the given paths and push, rebasing over anything pushed meanwhile.
commit_push() {
  local message="$1"; shift
  git add --sparse -- "$@"
  if git diff --cached --quiet; then
    log "nothing to commit: $message"
    return 0
  fi
  git commit -q -m "$message [skip ci]"
  local attempt
  for attempt in 1 2 3 4 5; do
    # --autostash: a failed parse leaves derived files uncommitted.
    if git pull -q --rebase --autostash origin master && git push -q origin HEAD:master; then
      log "pushed $(git rev-parse --short HEAD): $message"
      return 0
    fi
    git rebase --abort 2>/dev/null || true
    sleep $((attempt * 10))
  done
  log "PUSH FAILED: $message"
  return 1
}

log "tentatives $MODE harvest, code $(git -C "$CODE" rev-parse --short HEAD)"
git clone -q --filter=blob:none --depth 1 --no-checkout "https://github.com/$DATA_REPO.git" "$DATA"
# Capture logs must be on disk: the backfill appends to them, and orchestrate
# and materialize_recent.py read them.
git -C "$DATA" sparse-checkout set --no-cone /.gitattributes /README.md /LIVE.md /site/counties.json /status/ /data/ '/archive/*/*.ndjson'
git -C "$DATA" checkout -q master
git -C "$DATA" config user.name tentatives-bot
git -C "$DATA" config user.email tentatives-bot@users.noreply.github.com
cp -a "$CODE"/{ingest,counties,schema,update-readme.py,update-site-counties.py} "$DATA"/
log "data at $(git -C "$DATA" rev-parse --short HEAD)"

requirements="$(sha256sum "$CODE/requirements.txt" | cut -c1-16)"
if [ "$(cat "$VENV/.requirements" 2>/dev/null)" != "$requirements" ]; then
  log "building the Python environment"
  rm -rf -- "$VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q -r "$CODE/requirements.txt"
  echo "$requirements" > "$VENV/.requirements"
fi
PY="$VENV/bin/python"
STATUS=status/harvest.json
cd "$DATA"

recheck=""
if [ "$MODE" = live ]; then
  "$PY" "$CODE/ops/harvest_status.py" start "$STATUS" --date "$TODAY" --code "$(git -C "$CODE" rev-parse HEAD)"
  commit_push "status: courtproj harvest started" status/
  set +e
  "$PY" -u -m ingest.backfill --county all --live --continue-on-error --summary-json "$WORK/summary.json" 2>&1 | tee "$WORK/backfill.log"
  capture_exit=${PIPESTATUS[0]}
  set -e
  recheck="$("$PY" "$CODE/ops/harvest_status.py" capture "$STATUS" --summary "$WORK/summary.json" --exit "$capture_exit")"
  log "capture exit $capture_exit; recheck: ${recheck:-none}"
  if ! commit_push "archive: raw captures (courtproj)" archive/ status/; then
    dispatch backfill.yml county=all mode=live reason="courtproj could not push its captures"
    exit 1
  fi
  if [ "$recheck" = all ]; then
    dispatch backfill.yml county=all mode=live reason="courtproj capture failed"
    exit 1
  fi
else
  "$PY" -u -m ingest.backfill --county all --wayback --continue-on-error --limit 50 2>&1 | tee "$WORK/backfill.log"
  commit_push "archive: Wayback captures (courtproj)" archive/
fi

counties_before="$(git rev-parse -q --verify HEAD:site/counties.json || true)"
parsed=true
if ! {
  "$PY" "$CODE/ops/materialize_recent.py" &&
  "$PY" -u -m ingest.ocr_missing_text --county all &&
  "$PY" -u -m ingest.orchestrate &&
  "$PY" -u -m ingest.slice_rulings &&
  # LIVE needs the archive's sizes, which a sparse clone reads from the API.
  GITHUB_TOKEN="$(tr -d '\r\n' < "$TENTATIVES_TOKEN_FILE")" "$PY" -u update-readme.py &&
  "$PY" -u -m ingest.build_viewer_data
} 2>&1 | tee "$WORK/parse.log"; then
  parsed=false
fi

if [ "$parsed" = true ]; then
  [ "$MODE" = live ] && "$PY" "$CODE/ops/harvest_status.py" parse "$STATUS" --result ok
  if ! commit_push "archive: parsed data (courtproj)" archive/ data/ site/counties.json README.md LIVE.md status/; then
    parsed=false
  elif [ "$counties_before" != "$(git rev-parse -q --verify HEAD:site/counties.json || true)" ]; then
    dispatch site.yml deploy_worker=false
  fi
else
  log "parsing failed"
  if [ "$MODE" = live ]; then
    "$PY" "$CODE/ops/harvest_status.py" parse "$STATUS" --result failed
    commit_push "status: courtproj parse failed" status/ || true
  fi
fi

# Fallback runs start only now, after this run's pushes, so they never race
# them; a Backfill captures run parses everything, so it also covers a failed
# parse here.
if [ -n "$recheck" ]; then
  dispatch backfill.yml county="$recheck" mode=live reason="courtproj recheck"
elif [ "$parsed" != true ]; then
  dispatch parse.yml
fi
[ "$parsed" = true ] || exit 1
log "done"
