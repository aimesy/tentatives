"""Walk archive/, parse any source files not yet in data/<county>/rulings.parquet, append rows.

Designed to be idempotent and to be run by GitHub Actions after the browser
extension commits new source files to archive/. Also runnable locally:

    python -m ingest.orchestrate                     # parse everything
    python -m ingest.orchestrate --county el-dorado  # one county only
    python -m ingest.orchestrate --dry-run           # don't write parquet
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from counties.registry import page_parser_functions, parser_functions, parser_source_extensions

REPO = Path(__file__).parent.parent
ARCHIVE = REPO / "archive"
DATA = REPO / "data"

PARSERS = parser_functions()
PARSER_EXTENSIONS = parser_source_extensions()
PAGE_PARSERS = page_parser_functions()


class UnsafeArchivePath(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_existing_column(parquet_path: Path, column: str) -> set[str]:
    if not parquet_path.exists():
        return set()
    try:
        table = pq.read_table(parquet_path, columns=[column])
        return {value for value in table.column(column).to_pylist() if value}
    except Exception as e:
        raise RuntimeError(
            f"refusing to append to unreadable parquet {parquet_path}: {e}"
        ) from e


def existing_ruling_ids(parquet_path: Path) -> set[str]:
    return _read_existing_column(parquet_path, "ruling_id")


def existing_source_shas(parquet_path: Path) -> set[str]:
    return _read_existing_column(parquet_path, "source_sha256")


def parser_kwargs(parser, *, source_url: str, source_sha256: str, capture: dict) -> dict:
    kwargs = {
        "source_url": source_url,
        "source_sha256": source_sha256,
        "dept_hint": capture.get("dept_hint"),
    }
    try:
        params = inspect.signature(parser).parameters
    except (TypeError, ValueError):
        return kwargs
    if "division_hint" in params:
        kwargs["division_hint"] = capture.get("division_hint")
    if "capture" in params:
        kwargs["capture"] = capture
    return kwargs


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


def iter_content_addressed_sources(county_archive: Path, extensions: set[str]) -> list[Path]:
    """Only content-addressed files under archive/<county>/<two-hex>/<sha>.<ext> are parse inputs."""
    paths: list[Path] = []
    for prefix_dir in county_archive.iterdir() if county_archive.exists() else []:
        if not prefix_dir.is_dir() or not re_fullmatch_hex2(prefix_dir.name):
            continue
        for ext in sorted(extensions):
            paths.extend(sorted(prefix_dir.glob(f"*{ext}")))
    return sorted(paths)


def iter_content_addressed_pdfs(county_archive: Path) -> list[Path]:
    return iter_content_addressed_sources(county_archive, {".pdf"})


def re_fullmatch_hex2(value: str) -> bool:
    return len(value) == 2 and all(c in "0123456789abcdef" for c in value.lower())


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(1, 1000):
        candidate = path.with_name(f"{path.stem}-{i}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find unique quarantine path for {path}")


def quarantine_hash_mismatch(
    county: str,
    pdf_path: Path,
    declared_sha: str,
    actual_sha: str,
    dry_run: bool,
) -> None:
    print(
        f"ERROR: hash mismatch at {pdf_path.relative_to(REPO)} "
        f"(declared {declared_sha}, actual {actual_sha}); skipping",
        file=sys.stderr,
    )
    if dry_run:
        return
    quarantine_dir = ARCHIVE / county / "quarantine" / "hash-mismatch"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    quarantine_pdf = _unique_path(quarantine_dir / pdf_path.name)
    pdf_path.replace(quarantine_pdf)
    marker = quarantine_pdf.with_suffix(".badsha.json")
    marker.write_text(
        json.dumps(
            {
                "archive_path": pdf_path.relative_to(REPO).as_posix(),
                "quarantine_path": quarantine_pdf.relative_to(REPO).as_posix(),
                "declared_sha256": declared_sha,
                "actual_sha256": actual_sha,
                "quarantined_at": utc_now().isoformat(),
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def resolve_archive_capture_path(county: str, archive_rel: str) -> Path:
    raw = Path(str(archive_rel))
    if raw.is_absolute() or raw.anchor:
        raise UnsafeArchivePath(f"absolute archive_path is not allowed: {archive_rel}")
    resolved = (REPO / raw).resolve()
    county_root = (ARCHIVE / county).resolve()
    pages_root = (ARCHIVE / county / "pages").resolve()
    try:
        resolved.relative_to(county_root)
    except ValueError as e:
        raise UnsafeArchivePath(f"archive_path escapes county archive: {archive_rel}") from e
    try:
        resolved.relative_to(pages_root)
    except ValueError as e:
        raise UnsafeArchivePath(f"page capture must live under archive/{county}/pages: {archive_rel}") from e
    return resolved


def write_parquet_atomic(table: pa.Table, parquet_path: Path) -> None:
    tmp_file = tempfile.NamedTemporaryFile(
        prefix=f".{parquet_path.name}.",
        suffix=".tmp",
        dir=parquet_path.parent,
        delete=False,
    )
    tmp = Path(tmp_file.name)
    tmp_file.close()
    try:
        # Keep published Parquet readable under the static viewer CSP without a WASM decompressor.
        pq.write_table(table, tmp, compression="NONE")
        os.replace(tmp, parquet_path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def merged_table_schema(existing_table: pa.Table, new_table: pa.Table) -> pa.Schema:
    """Return a schema that can hold both tables without pinning null columns."""
    fields: list[pa.Field] = []
    seen: set[str] = set()
    for schema in (existing_table.schema, new_table.schema):
        for field in schema:
            if field.name in seen:
                continue
            seen.add(field.name)
            existing_field = (
                existing_table.schema.field(field.name)
                if field.name in existing_table.schema.names
                else None
            )
            new_field = (
                new_table.schema.field(field.name)
                if field.name in new_table.schema.names
                else None
            )
            if existing_field is None:
                chosen = new_field
            elif new_field is None:
                chosen = existing_field
            elif pa.types.is_null(existing_field.type) and not pa.types.is_null(new_field.type):
                chosen = new_field
            else:
                chosen = existing_field
            if chosen is not None:
                fields.append(chosen.with_nullable(True))
    return pa.schema(fields)


def cast_table_to_schema(table: pa.Table, schema: pa.Schema) -> pa.Table:
    arrays = []
    for field in schema:
        if field.name in table.schema.names:
            column = table[field.name]
            if not column.type.equals(field.type):
                column = column.cast(field.type, safe=False)
        else:
            column = pa.nulls(table.num_rows, type=field.type)
        arrays.append(column)
    return pa.Table.from_arrays(arrays, schema=schema)


def process_county(
    county: str,
    dry_run: bool = False,
    reparse_existing: bool = False,
    max_sources: int | None = None,
) -> int:
    """Parse any unprocessed source files for the given county. Returns count of new rulings."""
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

    # When the caller asks for a full reparse we want the new parser output to
    # *replace* what's on disk, not append on top. Reset both gates so every
    # source gets parsed and every ruling row gets emitted; we also skip the
    # existing-table merge below.
    seen_ids = set() if reparse_existing else existing_ruling_ids(parquet_path)
    seen_source_shas = set() if reparse_existing else existing_source_shas(parquet_path)
    captures = captures_index(county_archive)

    new_rulings: list[dict] = []
    source_extensions = PARSER_EXTENSIONS.get(county, {".pdf"})
    source_paths = iter_content_addressed_sources(county_archive, source_extensions)
    skipped_existing = 0
    parsed_sources = 0
    for source_path in source_paths:
        if max_sources is not None and parsed_sources >= max_sources:
            break
        # sha256 is in the filename; verify by recomputing.
        declared_sha = source_path.stem
        if declared_sha in seen_source_shas:
            skipped_existing += 1
            continue
        content = source_path.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest()
        if declared_sha != actual_sha:
            quarantine_hash_mismatch(county, source_path, declared_sha, actual_sha, dry_run)
            continue
        if actual_sha in seen_source_shas:
            skipped_existing += 1
            continue
        cap = captures.get(actual_sha, {})
        source_url = cap.get("source_url") or f"archive://{county}/{actual_sha}{source_path.suffix.lower()}"

        rulings = parser(
            content,
            **parser_kwargs(
                parser,
                source_url=source_url,
                source_sha256=actual_sha,
                capture=cap,
            ),
        )
        parsed_sources += 1
        unseen = [r.to_row() for r in rulings if r.ruling_id not in seen_ids]
        new_rulings.extend(unseen)
        seen_ids.update(row["ruling_id"] for row in unseen)
        if rulings:
            print(
                f"  {source_path.name}: {len(rulings)} rulings"
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
        try:
            page_path = resolve_archive_capture_path(county, archive_rel)
        except UnsafeArchivePath as e:
            print(f"WARN: skipping unsafe page capture {archive_rel}: {e}", file=sys.stderr)
            continue
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
        f"{len(source_paths)} source files and {len(page_rows)} page captures"
        f" ({skipped_existing} existing source hashes skipped,"
        f" {parsed_sources} sources parsed)"
    )

    if not new_rulings:
        return 0
    if dry_run:
        print("  (dry-run; not writing)")
        return len(new_rulings)

    # Append to (or create) the parquet file. With reparse_existing we want a
    # full replacement, so skip the merge and write `new_rulings` straight out.
    county_data.mkdir(parents=True, exist_ok=True)
    new_table = pa.Table.from_pylist(new_rulings)
    if parquet_path.exists() and not reparse_existing:
        existing_table = pq.read_table(parquet_path)
        # Align schemas - either table may have null-only columns that need the
        # other table's concrete type.
        schema = merged_table_schema(existing_table, new_table)
        combined = pa.concat_tables(
            [
                cast_table_to_schema(existing_table, schema),
                cast_table_to_schema(new_table, schema),
            ]
        )
    else:
        combined = new_table
    write_parquet_atomic(combined, parquet_path)
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

    started = utc_now()
    counties = [args.county] if args.county else list(PARSERS)
    total = 0
    for c in counties:
        total += process_county(
            c,
            dry_run=args.dry_run,
            reparse_existing=args.reparse_existing,
            max_sources=args.max_sources_per_county,
        )
    elapsed = (utc_now() - started).total_seconds()
    print(f"\ntotal: {total} new rulings in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
