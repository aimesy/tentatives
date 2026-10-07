"""visibility: non-public:private"""
import json

import pyarrow as pa
import pyarrow.parquet as pq

from ingest.build_viewer_data import TEXT_FIELDS, build_county, digest, ready


def test_complete_text_stays_out_of_index_and_source_is_preserved(tmp_path):
    source = tmp_path / "el-dorado" / "rulings.parquet"
    source.parent.mkdir()
    ruling_id = "ab" + "1" * 30
    row = {"ruling_id": ruling_id, "case_number": "25CV1", "case_title": "Case title", "county": "el-dorado",
           "outcome": "granted", "outcome_text": "SECRET DISPOSITION", "body_text": "SECRET BODY", "full_text": "SECRET FULL TEXT", "new_private_text_column": "SECRET FUTURE FIELD"}
    pq.write_table(pa.Table.from_pylist([row]), source)
    before = digest(source)
    assert build_county(source) == 1
    assert digest(source) == before
    summary = json.loads((source.parent / "summary.json").read_text())
    assert summary[0]["case_number"] == "25CV1"
    assert all(field not in summary[0] for field in TEXT_FIELDS)
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
