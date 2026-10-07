#!/usr/bin/env python3
"""Record the courtproj harvest in status/harvest.json and pick the counties
GitHub Actions should recheck (docs/harvest.md).

The status file lives in aimesy/tentatives-data. The 6 PM fallback check in
its Backfill captures workflow reads it to decide whether to run at all.

  harvest_status.py start   STATUS --date YYYY-MM-DD --code SHA
  harvest_status.py capture STATUS --summary SUMMARY.json --exit N
  harvest_status.py parse   STATUS --result ok|failed

`capture` prints the counties to recheck, separated by commas: nothing when
every county is fine, `all` when the capture as a whole failed.

A county is rechecked when discovery failed, when it raised, when a fetch
failed for any reason but 404 or 410 (a court removing an old file is not
something a second network can fix), or when it captured nothing although it
captured something in the last 14 days.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PRODUCTIVE_DAYS = 14
GONE = {404, 410}
HTTP_STATUS = re.compile(r"\b([1-5]\d\d) (?:Client|Server) Error")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def recheck_reason(result: dict, previous: dict, today: str) -> str | None:
    if "skipped" in result:
        return None
    if "exception" in result:
        return f"error: {result['exception'][:200]}"
    errors = [line for line in result.get("failures", []) if line.startswith("ERROR")]
    for line in errors:
        if "discovery" in line:
            return f"discovery: {line[:200]}"
    for line in errors:
        status = HTTP_STATUS.search(line)
        if status and int(status.group(1)) in GONE:
            continue
        return f"fetch: {line[:200]}"
    if not result.get("refs") and not result.get("pages"):
        last = previous.get("last_productive")
        if last and date.fromisoformat(today) - date.fromisoformat(last) <= timedelta(days=PRODUCTIVE_DAYS):
            return f"captured nothing; last captured {last}"
    return None


def cmd_start(args: argparse.Namespace) -> None:
    previous = load(args.status)
    save(args.status, {
        "date": args.date,
        "host": "courtproj",
        "code": args.code,
        "started_at": now(),
        "stage": "capturing",
        "capture": "running",
        "parse": "pending",
        "recheck": {},
        "counties": previous.get("counties", {}),
        "fallback": previous.get("fallback"),
    })


def cmd_capture(args: argparse.Namespace) -> None:
    status = load(args.status)
    today = status["date"]
    summary = load(args.summary) if args.summary.exists() else {}
    counties = dict(status.get("counties", {}))
    recheck: dict[str, str] = {}
    for slug, result in sorted(summary.items()):
        previous = counties.get(slug, {})
        if "skipped" in result:
            counties[slug] = {"skipped": result["skipped"], "last_productive": previous.get("last_productive")}
            continue
        entry = {key: result.get(key, 0) for key in ("discovered", "refs", "pages")}
        entry["failures"] = len(result.get("failures", []))
        if "exception" in result:
            entry["exception"] = result["exception"][:300]
        entry["last_productive"] = today if (result.get("refs") or result.get("pages")) else previous.get("last_productive")
        reason = recheck_reason(result, previous, today)
        if reason:
            entry["recheck"] = reason
            recheck[slug] = reason
        counties[slug] = entry
    captured = any(result.get("refs") for result in summary.values())
    ok = args.exit == 0 and captured
    status.update(
        capture="ok" if ok else "failed",
        stage="captured" if ok else "failed",
        capture_finished_at=now(),
        counties=counties,
        recheck=recheck if ok else {"all": "capture failed" if args.exit else "no county captured anything"},
    )
    save(args.status, status)
    print(",".join(recheck) if ok else "all")


def cmd_parse(args: argparse.Namespace) -> None:
    status = load(args.status)
    status.update(parse=args.result, stage="done", finished_at=now())
    save(args.status, status)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("status", type=Path)
    start.add_argument("--date", required=True)
    start.add_argument("--code", required=True)
    start.set_defaults(run=cmd_start)
    capture = sub.add_parser("capture")
    capture.add_argument("status", type=Path)
    capture.add_argument("--summary", type=Path, required=True)
    capture.add_argument("--exit", type=int, required=True)
    capture.set_defaults(run=cmd_capture)
    parse = sub.add_parser("parse")
    parse.add_argument("status", type=Path)
    parse.add_argument("--result", choices=["ok", "failed"], required=True)
    parse.set_defaults(run=cmd_parse)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
