from datetime import date
from pathlib import Path

import pytest

from counties.nevada.scraper import parse_file

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.mark.parametrize("fixture,expected_date,expected_division,min_rulings", [
    ("lawmotion-2026-01-12.pdf", date(2026, 1, 12), "Law and Motion", 5),
    ("probate-2026-01-12.pdf", date(2026, 1, 12), "Probate", 2),
    ("cmc-2026-03-22.pdf", date(2026, 3, 2), "Case Management", 20),
    ("guardianship-2026-05-07.pdf", date(2026, 5, 7), "Guardianship", 10),
])
def test_metadata_and_count(fixture, expected_date, expected_division, min_rulings):
    rs = parse_file(str(FIXTURE_DIR / fixture), "x")
    assert len(rs) >= min_rulings, f"{fixture}: got {len(rs)}"
    for r in rs:
        assert r.hearing_date == expected_date
        assert r.county == "nevada"
        assert r.division == expected_division


def test_case_number_formats():
    rs = parse_file(str(FIXTURE_DIR / "cmc-2026-03-22.pdf"), "x")
    nums = {r.case_number for r in rs}
    # CL and CU prefixes both present
    assert any(n.startswith("CL") for n in nums)
    assert any(n.startswith("CU") for n in nums)


def test_legacy_p_case_numbers():
    rs = parse_file(str(FIXTURE_DIR / "guardianship-2026-05-07.pdf"), "x")
    nums = {r.case_number for r in rs}
    assert any(n.startswith("P10-") or n.startswith("P12-") for n in nums)


def test_dept_extracted_from_header():
    rs = parse_file(str(FIXTURE_DIR / "guardianship-2026-05-07.pdf"), "x")
    # Guardianship PDF says "Department 3" in header.
    assert all(r.dept == "3" for r in rs), {r.dept for r in rs}


def test_location_captured_as_motion_type():
    rs = parse_file(str(FIXTURE_DIR / "lawmotion-2026-01-12.pdf"), "x")
    assert all(r.motion_type == "Truckee" for r in rs)


def test_outcomes_classified():
    rs = parse_file(str(FIXTURE_DIR / "cmc-2026-03-22.pdf"), "x")
    outcomes = {r.outcome for r in rs}
    # CMC continuances are common.
    assert "continued" in outcomes


def test_continued_to_extracted():
    rs = parse_file(str(FIXTURE_DIR / "cmc-2026-03-22.pdf"), "x")
    continued = [r for r in rs if r.continued_to is not None]
    assert continued, "expected at least one ruling with continued_to set"
    # Most continue to June 15, 2026.
    assert any(r.continued_to == date(2026, 6, 15) for r in continued)


def test_ruling_ids_unique_and_stable():
    a = parse_file(str(FIXTURE_DIR / "lawmotion-2026-01-12.pdf"), "x")
    b = parse_file(str(FIXTURE_DIR / "lawmotion-2026-01-12.pdf"), "x")
    ids = [r.ruling_id for r in a]
    assert len(set(ids)) == len(ids)
    assert ids == [r.ruling_id for r in b]
