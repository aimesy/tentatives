"""Walk archive/, parse any PDFs not yet in data/<county>/rulings.parquet, append rows.

Designed to be idempotent and to be run by GitHub Actions after the browser
extension commits new PDFs to archive/. Also runnable locally:

    python -m ingest.orchestrate                     # parse everything
    python -m ingest.orchestrate --county el-dorado  # one county only
    python -m ingest.orchestrate --dry-run           # don't write parquet
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from counties.amador import scraper as amador
from counties.el_dorado import scraper as el_dorado
from counties.contra_costa import scraper as contra_costa
from counties.nevada import scraper as nevada
from counties.orange import scraper as orange
from counties.placer import scraper as placer
from counties.san_francisco import scraper as san_francisco
from counties.santa_clara import scraper as santa_clara
from counties.shasta import scraper as shasta
from counties.solano import scraper as solano
from schema import Ruling

REPO = Path(__file__).parent.parent
ARCHIVE = REPO / "archive"
DATA = REPO / "data"

PARSERS = {
    "amador": amador.parse,
    "el-dorado": el_dorado.parse,
    "contra-costa": contra_costa.parse,
    "nevada": nevada.parse,
    "orange": orange.parse,
    "placer": placer.parse,
    "san-francisco": san_francisco.parse,
    "santa-clara": santa_clara.parse,
    "shasta": shasta.parse,
    "solano": solano.parse,
}

PAGE_PARSERS = {
    "contra-costa": contra_costa.parse_page_capture,
}


def existing_ruling_ids(parquet_path: Path) -> set[str]:
    if not parquet_path.exists():
        return set()
    try:
        table = pq.read_table(parquet_path, columns=["ruling_id"])
        return set(table.column("ruling_id").to_pylist())
    except Exception as e:
        print(f"warning: could not read {parquet_path}: {e}", file=sys.stderr)
        return set()


def existing_source_shas(parquet_path: Path) -> set[str]:
    if not parquet_path.exists():
        return set()
    try:
        table = pq.read_table(parquet_path, columns=["source_sha256"])
        return {sha for sha in table.column("source_sha256").to_pylist() if sha}
    except Exception as e:
        print(f"warning: could not read source shas from {parquet_path}: {e}", file=sys.stderr)
        return set()


def captures_index(county_dir: Path) -> dict[str, dict]:
    """Read captures.ndjson into a dict keyed by source_sha256."""
    ndjson = county_dir / "captures.ndjson"
    if not ndjson.exists():
        return {}
    by_sha: dict[str, dict] = {}
    for line in ndjson.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            by_sha[row["source_sha256"]] = row
        except (json.JSONDecodeError, KeyError):
            continue
    return by_sha


def page_captures(county_dir: Path) -> list[dict]:
    ndjson = county_dir / "page-captures.ndjson"
    if not ndjson.exists():
        return []
    rows: list[dict] = []
    for line in ndjson.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def process_county(
    county: str,
    dry_run: bool = False,
    reparse_existing: bool = False,
    max_sources: int | None = None,
) -> int:
    """Parse any unprocessed PDFs for the given county. Returns count of new rulings."""
    parser = PARSERS.get(county)
    if parser is None:
        print(f"no parser registered for county={county}", file=sys.stderr)
        return 0

    county_archive = ARCHIVE / county
    county_data = DATA / county
    parquet_path = county_data / "rulings.parquet"

    if not county_archive.exists():
        print(f"no archive at {county_archive}")
        return 0

    seen_ids = existing_ruling_ids(parquet_path)
    seen_source_shas = set() if reparse_existing else existing_source_shas(parquet_path)
    captures = captures_index(county_archive)

    new_rulings: list[dict] = []
    pdf_paths = sorted(county_archive.glob("*/*.pdf"))
    skipped_existing = 0
    parsed_sources = 0
    for pdf_path in pdf_paths:
        if max_sources is not None and parsed_sources >= max_sources:
            break
        # sha256 is in the filename; verify by recomputing.
        declared_sha = pdf_path.stem
        if declared_sha in seen_source_shas:
            skipped_existing += 1
            continue
        content = pdf_path.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest()
        if declared_sha != actual_sha:
            print(
                f"WARN: hash mismatch at {pdf_path.relative_to(REPO)} "
                f"(declared {declared_sha}, actual {actual_sha})",
                file=sys.stderr,
            )
        if actual_sha in seen_source_shas:
            skipped_existing += 1
            continue
        cap = captures.get(actual_sha, {})
        source_url = cap.get("source_url") or f"archive://{county}/{actual_sha}.pdf"

        rulings = parser(
            content,
            source_url=source_url,
            source_sha256=actual_sha,
            dept_hint=cap.get("dept_hint"),
            division_hint=cap.get("division_hint"),
        )
        parsed_sources += 1
        unseen = [r.to_row() for r in rulings if r.ruling_id not in seen_ids]
        new_rulings.extend(unseen)
        seen_ids.update(row["ruling_id"] for row in unseen)
        if rulings:
            print(
                f"  {pdf_path.name}: {len(rulings)} rulings"
                f" ({len(unseen)} new)"
            )

    page_parser = PAGE_PARSERS.get(county)
    page_rows = page_captures(county_archive) if page_parser else []
    for cap in page_rows:
        if max_sources is not None and parsed_sources >= max_sources:
            break
        archive_rel = cap.get("archive_path")
        source_sha = cap.get("source_sha256")
        if source_sha in seen_source_shas:
            skipped_existing += 1
            continue
        if not archive_rel:
            continue
        page_path = REPO / archive_rel
        if not page_path.exists():
            print(f"WARN: missing page capture {archive_rel}", file=sys.stderr)
            continue
        html = page_path.read_text(encoding="utf-8", errors="replace")
        rulings = page_parser(html, cap)
        parsed_sources += 1
        unseen = [r.to_row() for r in rulings if r.ruling_id not in seen_ids]
        new_rulings.extend(unseen)
        seen_ids.update(row["ruling_id"] for row in unseen)
        if rulings:
            print(
                f"  {page_path.name}: {len(rulings)} page rows"
                f" ({len(unseen)} new)"
            )

    print(
        f"\n{county}: {len(new_rulings)} new rows across "
        f"{len(pdf_paths)} PDFs and {len(page_rows)} page captures"
        f" ({skipped_existing} existing source hashes skipped,"
        f" {parsed_sources} sources parsed)"
    )

    if not new_rulings:
        return 0
    if dry_run:
        print("  (dry-run; not writing)")
        return len(new_rulings)

    # Append to (or create) the parquet file.
    county_data.mkdir(parents=True, exist_ok=True)
    new_table = pa.Table.from_pylist(new_rulings)
    if parquet_path.exists():
        existing_table = pq.read_table(parquet_path)
        # Align schemas - new_table may have null cols where existing has typed
        combined = pa.concat_tables(
            [existing_table, new_table.cast(existing_table.schema, safe=False)]
        )
    else:
        combined = new_table
    pq.write_table(combined, parquet_path, compression="zstd")
    print(f"  wrote {parquet_path.relative_to(REPO)}")
    return len(new_rulings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--county",
        help="Process only this county slug (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse but don't write parquet",
    )
    parser.add_argument(
        "--reparse-existing",
        action="store_true",
        help="Re-parse sources already represented in parquet",
    )
    parser.add_argument(
        "--max-sources-per-county",
        type=int,
        help="Maximum unprocessed source hashes to parse per county",
    )
    args = parser.parse_args(argv)

    started = datetime.utcnow()
    counties = [args.county] if args.county else list(PARSERS)
    total = 0
    for c in counties:
        total += process_county(
            c,
            dry_run=args.dry_run,
            reparse_existing=args.reparse_existing,
            max_sources=args.max_sources_per_county,
        )
    elapsed = (datetime.utcnow() - started).total_seconds()
    print(f"\ntotal: {total} new rulings in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
