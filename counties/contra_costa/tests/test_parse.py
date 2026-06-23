from datetime import date
from pathlib import Path

import pytest

from counties.contra_costa.scraper import parse_file, parse_page_capture

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[3]


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


@pytest.mark.parametrize("archive_rel,source_url,expected_dept,expected_date,expected_cases,min_rulings", [
    (
        "archive/contra-costa/e1/e1ce6a886c4acd643c5a8794dfdb635ed6ca1b663ca353d87dbccb0abc790e9d.pdf",
        "https://retired.cc-courts.org/civil/TR/Department%2014%20-%20Judge%20Athanasiou/14_042826.pdf",
        "14",
        date(2026, 4, 28),
        {"L22-01760", "L23-05788"},
        15,
    ),
    (
        "archive/contra-costa/30/30f0eda9d17b08943f844b0c75a96b90358a70a1a36da6bdbb879f7399515519.pdf",
        "https://retired.cc-courts.org/civil/TR/Department%2057%20-%20Comm%20Yamamoto/57_031126%20f.pdf",
        "57",
        date(2026, 3, 11),
        {"C23-03249"},
        1,
    ),
    (
        "archive/contra-costa/4a/4a648c7cccaf71d2be28b36e7cf07d9110b1cecb67298668d26a7c617a889b97.pdf",
        "https://retired.cc-courts.org/civil/TR/Department%2057%20-%20Comm%20Yamamoto/57_042426%20f%20amended.pdf",
        "57",
        date(2026, 4, 24),
        {"C24-02287"},
        1,
    ),
    (
        "archive/contra-costa/e3/e3c28d250265be7dae5afe150dcdb4dc9fe06bc7899bfabc63ca8673b63b7ace.pdf",
        "https://retired.cc-courts.org/civil/TR/Department%2057%20-%20Comm%20Yamamoto/57_042926%20f.pdf",
        "57",
        date(2026, 4, 29),
        {"C24-03218", "C25-00345", "C23-02085"},
        3,
    ),
])
def test_archive_backed_contra_costa_parser_misses(
    archive_rel,
    source_url,
    expected_dept,
    expected_date,
    expected_cases,
    min_rulings,
):
    path = REPO_ROOT / archive_rel
    rs = parse_file(str(path), source_url)
    assert len(rs) >= min_rulings
    assert {r.source_sha256 for r in rs} == {path.stem}
    assert {r.dept for r in rs} == {expected_dept}
    assert {r.hearing_date for r in rs} == {expected_date}
    assert expected_cases <= {r.case_number for r in rs}


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
