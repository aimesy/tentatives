"""Build metadata indexes and individual text records without changing source Parquet.

visibility: non-public:private
The data Worker exposes summary.json and one /rulings/<id>.json record.
The private source tables are never public routes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
VERSION = 3
ID = re.compile(r"^[0-9a-f]{32}$")
COUNTY = re.compile(r"^[a-z0-9-]+$")
TEXT_FIELDS = ("outcome_text", "body_text", "full_text")
SUMMARY_FIELDS = (
    "ruling_id", "county", "division", "dept", "judge", "judge_name",
    "hearing_date", "ruling_index", "case_number", "case_title", "motion_type",
    "outcome", "conditional", "continued_to", "page_start", "page_end",
    "source_url", "ingest_ts", "status", "previous_version_id",
)
PENDING = re.compile(r"calendar\s+notes\s+are\s+not\s+yet\s+available[\s\S]*check\s+back\s+for\s+updated\s+notes", re.I)
LABEL_LIMITS = {"case_title": 512, "motion_type": 256}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported viewer value {type(value).__name__}")


def encode(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=json_default) + "\n").encode("utf-8")


def write(path: Path, value) -> dict:
    payload = encode(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != payload:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def summary_row(row: dict, county: str) -> dict:
    result = {key: row[key] for key in SUMMARY_FIELDS if key in row}
    result["county"] = county
    # Some legacy parsers put pages of ruling text in a title or motion field.
    # Do not leak that text through a metadata label, or publish a clipped
    # quotation as if it were a title. Detail records retain the originals.
    for key, maximum in LABEL_LIMITS.items():
        if isinstance(result.get(key), str) and len(result[key]) > maximum:
            result[key] = ""
    # Preserve the viewer's pending-note classification without releasing notes.
    preview = next((str(row.get(key) or "") for key in TEXT_FIELDS if row.get(key)), "")
    result["status"] = "pending" if row.get("status") == "pending" or PENDING.search(preview) else "published"
    return result


def ready(source: Path, *, verify_outputs: bool = True) -> bool:
    manifest_path = source.parent / "_viewer.json"
    if not manifest_path.exists():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != VERSION or manifest.get("source_sha256") != digest(source):
        return False
    for relative, expected in manifest.get("outputs", {}).items():
        path = source.parent / relative
        if not path.is_file() or path.stat().st_size != expected["bytes"]:
            return False
        if verify_outputs and digest(path) != expected["sha256"]:
            return False
    return "summary.json" in manifest.get("outputs", {})


def build_county(source: Path) -> int:
    county = source.parent.name
    if not COUNTY.fullmatch(county):
        raise ValueError(f"invalid county directory: {county}")
    if ready(source):
        return 0
    table = pq.read_table(source)
    summaries = []
    records: dict[str, dict] = {}
    for row in table.to_pylist():
        ruling_id = str(row.get("ruling_id") or "")
        if not ID.fullmatch(ruling_id):
            raise ValueError(f"invalid ruling_id in {county}")
        summaries.append(summary_row(row, county))
        record = {
            "ruling_id": ruling_id, "county": county,
            "case_title": row.get("case_title") or "", "motion_type": row.get("motion_type") or "",
            **{key: row.get(key) or "" for key in TEXT_FIELDS},
        }
        # The existing corpus has a recapture with identical text and distinct
        # page/timestamp metadata. Preserve both summary rows, and share text.
        if ruling_id in records and records[ruling_id] != record:
            raise ValueError(f"conflicting text for duplicate ruling_id in {county}")
        records[ruling_id] = record
    outputs = {}
    for ruling_id, row in sorted(records.items()):
        relative = f"ruling-text/{ruling_id[:2]}/{ruling_id}.json"
        outputs[relative] = write(source.parent / relative, row)
    # Publish the index last. Existing indexes and all source files stay intact
    # if any earlier write fails; Git commits expose a complete snapshot.
    outputs["summary.json"] = write(source.parent / "summary.json", summaries)
    write(source.parent / "_viewer.json", {
        "version": VERSION, "visibility": "non-public:private",
        "source_sha256": digest(source), "rows": len(summaries), "outputs": outputs,
    })
    return len(summaries)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--county")
    parser.add_argument("--check", action="store_true", help="Verify every source has matching, complete viewer outputs")
    args = parser.parse_args(argv)
    if args.county and not COUNTY.fullmatch(args.county):
        parser.error("invalid county slug")
    sources = sorted(args.data_dir.glob(f"{args.county or '*'}/rulings.parquet"))
    if not sources:
        parser.error("no source Parquet files found")
    for source in sources:
        if args.check:
            if not ready(source):
                raise RuntimeError(f"missing or stale viewer data for {source.parent.name}")
        else:
            count = build_county(source)
            print(f"{source.parent.name}: {count} viewer records refreshed" if count else f"{source.parent.name}: viewer data current")
    print(f"Verified viewer data for {len(sources)} counties")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
