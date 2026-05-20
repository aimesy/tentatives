from datetime import date
from pathlib import Path

import pytest

from counties.shasta.scraper import parse_file

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.mark.parametrize("fixture,expected_date,expected_dept,min_rulings", [
    ("civil-dept63.pdf", date(2026, 5, 18), "63", 20),
    ("civil-dept64.pdf", date(2026, 5, 18), "64", 15),
    ("probate-dept44.pdf", date(2026, 5, 18), "44", 30),
    ("probate-old.pdf", date(2024, 6, 10), "24", 1),
])
def test_metadata_and_count(fixture, expected_date, expected_dept, min_rulings):
    rs = parse_file(str(FIXTURE_DIR / fixture), "x")
    assert len(rs) >= min_rulings, f"{fixture}: got {len(rs)}"
    for r in rs:
        assert r.hearing_date == expected_date
        assert r.county == "shasta"
        assert r.dept == expected_dept


def test_case_number_formats():
    rs = parse_file(str(FIXTURE_DIR / "civil-dept63.pdf"), "x")
    nums = {r.case_number for r in rs}
    assert any(n.startswith("26CV-") for n in nums)
    assert any(n.startswith("25CVG-") for n in nums)
    assert any(n.startswith("CVCV") for n in nums)


def test_conservatorship_section_captured_as_division():
    rs = parse_file(str(FIXTURE_DIR / "probate-dept44.pdf"), "x")
    # The CONSERVATORSHIPS section assigns "Conservatorships" to division
    # for everything in that block.
    assert any(r.division == "Conservatorships" for r in rs)


def test_split_word_repair():
    """pypdf inserts spaces inside words ('CONSERV ATORSHIP'); the parser normalizes."""
    rs = parse_file(str(FIXTURE_DIR / "probate-dept44.pdf"), "x")
    titles = " ".join(r.case_title for r in rs)
    assert "CONSERV ATORSHIP" not in titles
    assert "CONSERVATORSHIP" in titles


def test_motion_type_extracted_from_tentative_ruling_on_clause():
    rs = parse_file(str(FIXTURE_DIR / "civil-dept63.pdf"), "x")
    motions = [r.motion_type for r in rs if r.motion_type]
    assert any("Set Aside Default" in m for m in motions)


def test_outcomes_classified():
    rs = parse_file(str(FIXTURE_DIR / "civil-dept64.pdf"), "x")
    outcomes = {r.outcome for r in rs}
    assert len(outcomes) >= 3, outcomes


def test_continued_to_extracted():
    rs = parse_file(str(FIXTURE_DIR / "probate-dept44.pdf"), "x")
    cont = [r for r in rs if r.continued_to is not None]
    assert cont, "expected at least one ruling with continued_to set"


def test_ruling_ids_unique_and_stable():
    a = parse_file(str(FIXTURE_DIR / "civil-dept63.pdf"), "x")
    b = parse_file(str(FIXTURE_DIR / "civil-dept63.pdf"), "x")
    ids = [r.ruling_id for r in a]
    assert len(set(ids)) == len(ids)
    assert ids == [r.ruling_id for r in b]
