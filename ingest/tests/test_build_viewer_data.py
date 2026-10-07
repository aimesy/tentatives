"""visibility: non-public:private"""
import json

import pyarrow as pa
import pyarrow.parquet as pq

from ingest.build_viewer_data import OPENING_EXCERPT, OUTCOME_EXCERPT, TEXT_FIELDS, build_county, clip, digest, ready


def test_index_carries_excerpts_and_complete_text_stays_out(tmp_path):
    source = tmp_path / "el-dorado" / "rulings.parquet"
    source.parent.mkdir()
    ruling_id = "ab" + "1" * 30
    row = {"ruling_id": ruling_id, "case_number": "25CV1", "case_title": "Case title", "county": "el-dorado",
           "outcome": "granted", "outcome_text": "The motion is GRANTED.",
           "body_text": "Plaintiff moves for trial preference. " + "Long analysis. " * 200,
           "full_text": "SECRET FULL TEXT", "new_private_text_column": "SECRET FUTURE FIELD"}
    pq.write_table(pa.Table.from_pylist([row]), source)
    before = digest(source)
    assert build_county(source) == 1
    assert digest(source) == before
    summary = json.loads((source.parent / "summary.json").read_text())
    assert summary[0]["case_number"] == "25CV1"
    assert summary[0]["outcome_text"] == "The motion is GRANTED."
    assert summary[0]["body_text"].startswith("Plaintiff moves for trial preference. Long analysis.")
    assert len(summary[0]["body_text"]) <= OPENING_EXCERPT + 1 and summary[0]["body_text"].endswith("\u2026")
    assert "full_text" not in summary[0]
    assert "SECRET" not in (source.parent / "summary.json").read_text()
    record_path = source.parent / "ruling-text" / "ab" / f"{ruling_id}.json"
    record = json.loads(record_path.read_text())
    for field in TEXT_FIELDS:
        assert record[field] == row[field]
    assert ready(source)
    assert build_county(source) == 0
    record_path.write_text("{}")
    assert not ready(source)
    assert build_county(source) == 1
    assert ready(source)


def test_pending_classification_survives_without_the_notes(tmp_path):
    source = tmp_path / "placer" / "rulings.parquet"
    source.parent.mkdir()
    row = {"ruling_id": "cd" + "2" * 30, "full_text": "Calendar notes are not yet available. Check back for updated notes."}
    pq.write_table(pa.Table.from_pylist([row]), source)
    build_county(source)
    summary = json.loads((source.parent / "summary.json").read_text())
    assert summary[0]["status"] == "pending"
    assert "notes" not in json.dumps(summary)


def test_same_text_recapture_preserves_both_metadata_rows(tmp_path):
    source = tmp_path / "orange" / "rulings.parquet"
    source.parent.mkdir()
    ruling_id = "ef" + "3" * 30
    pq.write_table(pa.Table.from_pylist([
        {"ruling_id": ruling_id, "full_text": "same complete text", "page_start": 1},
        {"ruling_id": ruling_id, "full_text": "same complete text", "page_start": 2},
    ]), source)
    assert build_county(source) == 2
    assert len(json.loads((source.parent / "summary.json").read_text())) == 2
    assert json.loads((source.parent / "ruling-text" / "ef" / f"{ruling_id}.json").read_text())["full_text"] == "same complete text"


def test_oversized_legacy_labels_are_only_in_metered_record(tmp_path):
    source = tmp_path / "orange" / "rulings.parquet"
    source.parent.mkdir()
    ruling_id = "01" + "4" * 30
    motion = "SECRET RULING " * 100
    title = "SECRET CASE TEXT " * 100
    pq.write_table(pa.Table.from_pylist([{"ruling_id": ruling_id, "motion_type": motion, "case_title": title}]), source)
    build_county(source)
    summary = json.loads((source.parent / "summary.json").read_text())
    assert summary[0]["motion_type"] == summary[0]["case_title"] == ""
    record = json.loads((source.parent / "ruling-text" / "01" / f"{ruling_id}.json").read_text())
    assert record["motion_type"] == motion
    assert record["case_title"] == title


def test_clip_keeps_short_text_and_cuts_long_text_at_a_word():
    assert clip("  GRANTED.\n\n  Appearances   required. ", OUTCOME_EXCERPT) == "GRANTED. Appearances required."
    long = "word " * 400
    clipped = clip(long, OUTCOME_EXCERPT)
    assert len(clipped) <= OUTCOME_EXCERPT + 1 and clipped.endswith("word\u2026")
