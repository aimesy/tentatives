import hashlib
import json
from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ingest import orchestrate
from schema import Ruling


def _ruling(source_sha256: str, source_url: str, ruling_index: int = 1) -> Ruling:
    ruling_id = hashlib.sha256(f"{source_sha256}:{ruling_index}".encode("utf-8")).hexdigest()[:32]
    return Ruling(
        ruling_id=ruling_id,
        county="fake",
        division="Civil",
        dept="1",
        hearing_date=date(2026, 5, 21),
        ruling_index=ruling_index,
        case_number="TEST-1",
        case_title="Test Case",
        motion_type="Motion",
        outcome="other",
        outcome_text="",
        conditional=False,
        continued_to=None,
        body_text="",
        full_text="Test ruling",
        page_start=1,
        page_end=1,
        source_sha256=source_sha256,
        source_url=source_url,
        parser_version="test-v1",
    )


def _patch_roots(monkeypatch, tmp_path):
    repo = tmp_path
    monkeypatch.setattr(orchestrate, "REPO", repo)
    monkeypatch.setattr(orchestrate, "ARCHIVE", repo / "archive")
    monkeypatch.setattr(orchestrate, "DATA", repo / "data")
    return repo


def test_write_parquet_atomic_preserves_existing_on_failure(tmp_path, monkeypatch):
    parquet_path = tmp_path / "rulings.parquet"
    original = pa.table({"ruling_id": ["old"], "source_sha256": ["a" * 64]})
    pq.write_table(original, parquet_path, compression="zstd")
    original_bytes = parquet_path.read_bytes()

    def fail_write(table, path, compression):
        path.write_bytes(b"partial parquet")
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(orchestrate.pq, "write_table", fail_write)

    with pytest.raises(RuntimeError, match="simulated write failure"):
        orchestrate.write_parquet_atomic(
            pa.table({"ruling_id": ["new"], "source_sha256": ["b" * 64]}),
            parquet_path,
        )

    assert parquet_path.read_bytes() == original_bytes
    assert not list(tmp_path.glob(".rulings.parquet.*.tmp"))


def test_process_county_quarantines_and_skips_hash_mismatch(tmp_path, monkeypatch):
    repo = _patch_roots(monkeypatch, tmp_path)
    declared_sha = "a" * 64
    content = b"%PDF-1.4\nmismatched content\n"
    pdf_path = orchestrate.ARCHIVE / "fake" / declared_sha[:2] / f"{declared_sha}.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(content)

    calls = []

    def parser(*args, **kwargs):
        calls.append((args, kwargs))
        return []

    monkeypatch.setattr(orchestrate, "PARSERS", {"fake": parser})
    monkeypatch.setattr(orchestrate, "PAGE_PARSERS", {})

    assert orchestrate.process_county("fake") == 0

    quarantine_pdf = (
        repo / "archive" / "fake" / "quarantine" / "hash-mismatch" / pdf_path.name
    )
    marker = quarantine_pdf.with_suffix(".badsha.json")
    assert calls == []
    assert not pdf_path.exists()
    assert quarantine_pdf.exists()
    metadata = json.loads(marker.read_text(encoding="utf-8"))
    assert metadata["declared_sha256"] == declared_sha
    assert metadata["actual_sha256"] == hashlib.sha256(content).hexdigest()


def test_process_county_skips_page_capture_path_traversal(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    county_archive = orchestrate.ARCHIVE / "fake"
    county_archive.mkdir(parents=True)
    (county_archive / "page-captures.ndjson").write_text(
        json.dumps(
            {
                "source_sha256": "b" * 64,
                "source_url": "https://example.test/page",
                "archive_path": "archive/fake/pages/../../outside.html",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def page_parser(html, capture):
        raise AssertionError("unsafe page capture should not be parsed")

    monkeypatch.setattr(orchestrate, "PARSERS", {"fake": lambda *a, **kw: []})
    monkeypatch.setattr(orchestrate, "PAGE_PARSERS", {"fake": page_parser})

    assert orchestrate.process_county("fake") == 0


def test_process_county_ruling_ids_stay_stable_for_same_source(tmp_path, monkeypatch):
    _patch_roots(monkeypatch, tmp_path)
    content = b"%PDF-1.4\nstable source\n"
    source_sha = hashlib.sha256(content).hexdigest()
    pdf_path = orchestrate.ARCHIVE / "fake" / source_sha[:2] / f"{source_sha}.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(content)

    seen_ids = []

    def parser(content_bytes, *, source_url, source_sha256, dept_hint=None):
        row = _ruling(source_sha256, source_url)
        seen_ids.append(row.ruling_id)
        return [row]

    monkeypatch.setattr(orchestrate, "PARSERS", {"fake": parser})
    monkeypatch.setattr(orchestrate, "PAGE_PARSERS", {})

    assert orchestrate.process_county("fake", dry_run=True) == 1
    assert orchestrate.process_county("fake", dry_run=True) == 1
    assert len(seen_ids) == 2
    assert seen_ids[0] == seen_ids[1]
