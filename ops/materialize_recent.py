#!/usr/bin/env python3
"""Check out recent sources that no parquet row names yet (docs/harvest.md).

The courtproj harvest works in a sparse clone of aimesy/tentatives-data that
holds only what the run itself captured. A source an earlier run captured but
never parsed (a capture-only night, a failed parse) is tracked but absent,
and ingest.orchestrate reads sources from disk. This adds the sources captured
in the last 14 days that no parquet row names, with their OCR sidecars, to the
sparse checkout. Older unparsed sources are left out: most never yield a row
(confidential or password-protected files), and a full checkout still parses
them. Run from the data checkout's root.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow.parquet as pq


def parse_time(value: object) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    tracked = set(subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", "archive"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines())
    want: set[str] = set()
    for county_dir in sorted(p for p in (root / "archive").iterdir() if p.is_dir()):
        county = county_dir.name
        parquet = root / "data" / county / "rulings.parquet"
        seen = set(pq.read_table(parquet, columns=["source_sha256"]).column(0).to_pylist()) if parquet.exists() else set()
        candidates = []
        for row in rows(county_dir / "captures.ndjson"):
            sha = row.get("source_sha256")
            moment = parse_time(row.get("fetched_at"))
            if not sha or sha in seen or moment is None or moment < cutoff:
                continue
            extension = row.get("archive_extension") or "pdf"
            candidates += [f"archive/{county}/{sha[:2]}/{sha}.{extension}", f"archive/{county}/ocr/{sha[:2]}/{sha}.pdf"]
        for row in rows(county_dir / "page-captures.ndjson"):
            moment = parse_time(row.get("captured_at"))
            if row.get("source_sha256") in seen or moment is None or moment < cutoff or not row.get("archive_path"):
                continue
            candidates.append(row["archive_path"])
        want.update(path for path in candidates if path in tracked and not (root / path).exists())
    print(f"{len(want)} recent unparsed sources and sidecars to check out")
    if want and not args.dry_run:
        subprocess.run(
            ["git", "sparse-checkout", "add", "--stdin"],
            input="".join(f"/{path}\n" for path in sorted(want)), text=True, check=True,
        )


if __name__ == "__main__":
    main()
