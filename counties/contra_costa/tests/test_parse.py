from datetime import date
from pathlib import Path

import pytest

from counties.contra_costa.scraper import parse_file, parse_page_capture

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.mark.parametrize("fixture,expected_dept,expected_date,min_rulings", [
    ("dept-09-2025-12-22.pdf", "09", date(2025, 12, 22), 20),
    ("dept-10-2026-05-14.pdf", "10", date(2026, 5, 14), 15),
    ("dept-14-2026-05-19.pdf", "14", date(2026, 5, 19), 10),
    ("dept-16-2026-05-13.pdf", "16", date(2026, 5, 13), 15),
    ("dept-18-2025-12-26.pdf", "18", date(2025, 12, 26), 10),
])
def test_metadata_and_count(fixture, expected_dept, expected_date, min_rulings):
    rs = parse_file(str(FIXTURE_DIR / fixture), "x")
    assert len(rs) >= min_rulings, f"{fixture}: got {len(rs)}"
    for r in rs:
        assert r.dept == expected_dept, f"{fixture} #{r.ruling_index}: dept={r.dept}"
        assert r.hearing_date == expected_date
        assert r.county == "contra-costa"


def test_case_numbers_with_dashes():
    rs = parse_file(str(FIXTURE_DIR / "dept-09-2025-12-22.pdf"), "x")
    numbers = {r.case_number for r in rs}
    # Modern CCC format
    assert "C22-01552" in numbers
    # MSC legacy format
    assert any(n.startswith("MSC") for n in numbers), numbers
    # N legacy format
    assert any(n.startswith("N") and "-" in n for n in numbers), numbers


def test_outcomes_classified():
    rs = parse_file(str(FIXTURE_DIR / "dept-09-2025-12-22.pdf"), "x")
    outcomes = {r.outcome for r in rs}
    # We should see multiple distinct outcome classes from a typical calendar.
    assert len(outcomes) >= 3, outcomes


def test_ruling_ids_unique_and_stable():
    rs1 = parse_file(str(FIXTURE_DIR / "dept-16-2026-05-13.pdf"), "x")
    rs2 = parse_file(str(FIXTURE_DIR / "dept-16-2026-05-13.pdf"), "x")
    ids = [r.ruling_id for r in rs1]
    assert len(set(ids)) == len(ids)
    assert [r.ruling_id for r in rs1] == [r.ruling_id for r in rs2]


def test_parse_probate_calendar_note_page_capture():
    html = """
    <!doctype html>
    <title>Probate Calendar</title>
    <h1>Probate Calendar Notes</h1>
    <p>Estate of Test Person, case P24-00001. Appearance required.</p>
    """
    rows = parse_page_capture(html, {
        "source_sha256": "a" * 64,
        "source_url": "https://contracosta.courts.ca.gov/probate-calendar",
        "page_kind": "probate_calendar_notes",
        "title": "Probate Calendar",
        "captured_at": "2026-05-20T12:00:00",
    })
    assert len(rows) == 1
    row = rows[0]
    assert row.division == "Probate Calendar Notes"
    assert row.motion_type == "Calendar note"
    assert row.case_title == "Probate Calendar"
    assert row.hearing_date == date(2026, 5, 20)
    assert row.page_start == 0
    assert "Estate of Test Person" in row.full_text
