"""Create non-destructive OCR PDF sidecars for textless archived PDFs.

Raw court PDFs stay at archive/<county>/<sha[:2]>/<sha>.pdf. OCR output is
written to archive/<county>/ocr/<sha[:2]>/<sha>.pdf, and ingest.orchestrate
will use that sidecar for parsing when present while preserving the original
source SHA and URL.
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pypdf

REPO = Path(__file__).parent.parent
ARCHIVE = REPO / "archive"


def re_fullmatch_hex2(value: str) -> bool:
    return len(value) == 2 and all(c in "0123456789abcdef" for c in value.lower())


def iter_source_pdfs(county: str) -> list[Path]:
    county_dir = ARCHIVE / county
    paths: list[Path] = []
    for prefix_dir in county_dir.iterdir() if county_dir.exists() else []:
        if not prefix_dir.is_dir() or not re_fullmatch_hex2(prefix_dir.name):
            continue
        paths.extend(sorted(prefix_dir.glob("*.pdf")))
    return sorted(paths)


def county_names() -> list[str]:
    return sorted(path.name for path in ARCHIVE.iterdir() if path.is_dir())


def ocr_sidecar_path(county: str, source_sha256: str) -> Path:
    return ARCHIVE / county / "ocr" / source_sha256[:2] / f"{source_sha256}.pdf"


def extractable_text_chars(path: Path) -> int | None:
    try:
        reader = pypdf.PdfReader(io.BytesIO(path.read_bytes()))
        if reader.is_encrypted and not reader.decrypt(""):
            return None
        return sum(len((page.extract_text() or "").strip()) for page in reader.pages)
    except Exception:
        return None


def run_ocr(source: Path, target: Path, force: bool = False) -> None:
    ocrmypdf = shutil.which("ocrmypdf")
    if not ocrmypdf:
        raise RuntimeError("ocrmypdf is not installed or not on PATH")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = tempfile.NamedTemporaryFile(
        prefix=f".{target.stem}.",
        suffix=".ocr.pdf",
        dir=target.parent,
        delete=False,
    )
    tmp = Path(tmp_file.name)
    tmp_file.close()
    try:
        cmd = [
            ocrmypdf,
            "--skip-text",
            "--rotate-pages",
            "--deskew",
            "--optimize",
            "0",
            str(source),
            str(tmp),
        ]
        if force:
            cmd.insert(1, "--force-ocr")
        subprocess.run(cmd, check=True)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def process_county(
    county: str,
    *,
    min_text_chars: int,
    limit: int | None,
    force: bool,
    dry_run: bool,
) -> tuple[int, int, int]:
    created = 0
    skipped_text = 0
    skipped_other = 0
    for source in iter_source_pdfs(county):
        if limit is not None and created >= limit:
            break
        source_sha = source.stem
        target = ocr_sidecar_path(county, source_sha)
        if target.exists() and not force:
            skipped_other += 1
            continue
        text_chars = extractable_text_chars(source)
        if text_chars is None:
            print(f"{county}: skip encrypted/unreadable {source.name}")
            skipped_other += 1
            continue
        if text_chars >= min_text_chars and not force:
            skipped_text += 1
            continue
        print(f"{county}: OCR {source.relative_to(REPO)} -> {target.relative_to(REPO)}")
        if not dry_run:
            run_ocr(source, target, force=force)
        created += 1
    return created, skipped_text, skipped_other


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--county", default="all", help="County slug or all")
    parser.add_argument("--limit", type=int, help="Maximum OCR sidecars to create per run")
    parser.add_argument("--min-text-chars", type=int, default=40)
    parser.add_argument("--force", action="store_true", help="OCR even when text exists or sidecar is present")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    counties = county_names() if args.county == "all" else [args.county]
    total_created = 0
    total_skipped_text = 0
    total_skipped_other = 0
    for county in counties:
        created, skipped_text, skipped_other = process_county(
            county,
            min_text_chars=args.min_text_chars,
            limit=args.limit,
            force=args.force,
            dry_run=args.dry_run,
        )
        total_created += created
        total_skipped_text += skipped_text
        total_skipped_other += skipped_other
        print(
            f"{county}: {created} OCR sidecars, {skipped_text} text-backed skipped, "
            f"{skipped_other} existing/encrypted/unreadable skipped"
        )
    print(
        f"total: {total_created} OCR sidecars, {total_skipped_text} text-backed skipped, "
        f"{total_skipped_other} existing/encrypted/unreadable skipped"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
