"""Slice each ruling out of its source PDF and store under archive/<county>/rulings/.

For every row in data/<county>/rulings.parquet we open the archive PDF at
archive/<county>/<two-hex>/<source_sha256>.pdf, copy pages page_start..page_end
into a fresh PDF, and write it to:

    archive/<county>/rulings/<two-hex>/<ruling_id>.pdf

where <two-hex> is the first two characters of ruling_id (matches the existing
content-addressed layout used for source PDFs). pikepdf is used because it
reliably keeps font subsets and produces materially smaller per-page outputs
than pypdf for the multi-page court PDFs in this repo.

The script is idempotent: a slice is rewritten only if it doesn't already exist
or `--force` is passed.

    python -m ingest.slice_rulings                     # slice every county
    python -m ingest.slice_rulings --county el-dorado  # one county only
    python -m ingest.slice_rulings --force             # rewrite every slice
"""

from __future__ import annotations

import argparse
import sys
from io import BytesIO
from pathlib import Path

import pikepdf
import pyarrow.parquet as pq

REPO = Path(__file__).parent.parent
ARCHIVE = REPO / "archive"
DATA = REPO / "data"


def source_pdf_path(county: str, source_sha: str) -> Path:
    return ARCHIVE / county / source_sha[:2] / f"{source_sha}.pdf"


def slice_path(county: str, ruling_id: str) -> Path:
    return ARCHIVE / county / "rulings" / ruling_id[:2] / f"{ruling_id}.pdf"


def slice_ruling(
    source: Path,
    out: Path,
    page_start: int,
    page_end: int,
) -> int:
    """Write the page_start..page_end (1-indexed, inclusive) range of `source`
    into `out`. Returns the size of the written file.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.open(str(source)) as pdf:
        total = len(pdf.pages)
        # Clamp page range to actual pages; parsers can occasionally over-shoot.
        start = max(1, min(page_start, total))
        end = max(start, min(page_end, total))
        new = pikepdf.Pdf.new()
        for i in range(start - 1, end):
            new.pages.append(pdf.pages[i])
        new.remove_unreferenced_resources()
        buffer = BytesIO()
        new.save(
            buffer,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            deterministic_id=True,
        )
    out.write_bytes(buffer.getvalue())
    return out.stat().st_size


def process_county(county: str, *, force: bool) -> tuple[int, int, int]:
    """Slice every ruling for `county`. Returns (made, skipped, missing_source)."""
    parquet_path = DATA / county / "rulings.parquet"
    if not parquet_path.exists():
        return 0, 0, 0
    cols = ["ruling_id", "source_sha256", "page_start", "page_end"]
    table = pq.read_table(parquet_path, columns=cols)
    rows = table.to_pylist()
    made = skipped = missing_source = 0
    for row in rows:
        ruling_id = row["ruling_id"]
        source_sha = row["source_sha256"]
        page_start = row["page_start"]
        page_end = row["page_end"]
        if not (ruling_id and source_sha and page_start and page_end):
            continue
        source = source_pdf_path(county, source_sha)
        if not source.exists():
            # Page-capture rulings (HTML, no PDF) are an expected source-less case.
            missing_source += 1
            continue
        out = slice_path(county, ruling_id)
        if out.exists() and not force:
            skipped += 1
            continue
        try:
            slice_ruling(source, out, int(page_start), int(page_end))
            made += 1
        except Exception as e:
            print(
                f"  WARN {county}/{ruling_id}: {e}",
                file=sys.stderr,
            )
    print(
        f"{county}: {made} sliced, {skipped} already present, "
        f"{missing_source} source PDF missing (probably HTML captures)"
    )
    return made, skipped, missing_source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--county", help="Process only this county slug")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rewrite slices even when an existing file is present",
    )
    args = parser.parse_args(argv)

    counties = (
        [args.county]
        if args.county
        else [d.name for d in DATA.iterdir() if d.is_dir() and (d / "rulings.parquet").exists()]
    )
    total_made = 0
    for c in sorted(counties):
        made, _, _ = process_county(c, force=args.force)
        total_made += made
    print(f"\nTotal new slices: {total_made}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
