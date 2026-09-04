"""Smoke tests for ingest/slice_rulings.py."""
from __future__ import annotations

from pathlib import Path

import pikepdf
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ingest import slice_rulings


def _make_pdf(path: Path, pages: int = 5) -> None:
    pdf = pikepdf.Pdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(72, 72))
    pdf.save(str(path))


def test_slice_writes_requested_pages(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    out = tmp_path / "out.pdf"
    _make_pdf(src, pages=5)
    slice_rulings.slice_ruling(src, out, page_start=2, page_end=4)
    with pikepdf.open(str(out)) as result:
        assert len(result.pages) == 3


def test_slice_clamps_overshoot(tmp_path: Path) -> None:
    """If a parser over-shoots page_end (rare but observed), we clamp."""
    src = tmp_path / "src.pdf"
    out = tmp_path / "out.pdf"
    _make_pdf(src, pages=3)
    slice_rulings.slice_ruling(src, out, page_start=1, page_end=10)
    with pikepdf.open(str(out)) as result:
        assert len(result.pages) == 3


def test_process_county_skips_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src_sha = "ab" * 32
    ruling_id = "cd" * 16
    archive_root = tmp_path / "archive"
    data_root = tmp_path / "data"
    src_pdf = archive_root / "x" / src_sha[:2] / f"{src_sha}.pdf"
    src_pdf.parent.mkdir(parents=True)
    _make_pdf(src_pdf, pages=2)

    parquet = data_root / "x" / "rulings.parquet"
    parquet.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist([{
            "ruling_id": ruling_id,
            "source_sha256": src_sha,
            "page_start": 1,
            "page_end": 2,
        }]),
        parquet,
    )

    monkeypatch.setattr(slice_rulings, "ARCHIVE", archive_root)
    monkeypatch.setattr(slice_rulings, "DATA", data_root)

    made1, skipped1, _ = slice_rulings.process_county("x", force=False)
    assert (made1, skipped1) == (1, 0)

    # Second run is a no-op.
    made2, skipped2, _ = slice_rulings.process_county("x", force=False)
    assert (made2, skipped2) == (0, 1)

    out_path = archive_root / "x" / "rulings" / ruling_id[:2] / f"{ruling_id}.pdf"
    assert out_path.exists()


def test_process_county_writes_derived_pdf_for_docx_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src_sha = "ef" * 32
    ruling_id = "12" * 16
    archive_root = tmp_path / "archive"
    data_root = tmp_path / "data"
    src_docx = archive_root / "x" / src_sha[:2] / f"{src_sha}.docx"
    src_docx.parent.mkdir(parents=True)
    src_docx.write_bytes(b"PK\x03\x04placeholder")

    parquet = data_root / "x" / "rulings.parquet"
    parquet.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist([{
            "ruling_id": ruling_id,
            "county": "x",
            "division": "Civil",
            "dept": "1",
            "hearing_date": "2026-06-05",
            "case_number": "CV123",
            "case_title": "Smith v. Jones",
            "motion_type": "Case Management Conference",
            "outcome_text": "The matter is continued.",
            "full_text": "CV123 Smith v. Jones\nThe matter is continued.",
            "source_url": "https://example.test/ruling.docx",
            "source_sha256": src_sha,
            "page_start": 1,
            "page_end": 1,
        }]),
        parquet,
    )

    monkeypatch.setattr(slice_rulings, "ARCHIVE", archive_root)
    monkeypatch.setattr(slice_rulings, "DATA", data_root)

    made, skipped, missing = slice_rulings.process_county("x", force=False)

    assert (made, skipped, missing) == (1, 0, 0)
    out_path = archive_root / "x" / "rulings" / ruling_id[:2] / f"{ruling_id}.pdf"
    with pikepdf.open(str(out_path)) as result:
        assert len(result.pages) >= 1
