from datetime import date
from pathlib import Path

import pytest

from counties.solano.scraper import parse_file

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.mark.parametrize("fixture,expected_date,expected_dept,min_rulings", [
    ("dept_3-2026-05-19.pdf", date(2026, 5, 19), "3", 3),
    ("dept_7-2026-05-19.pdf", date(2026, 5, 19), "7", 5),
    ("dept_8-2026-05-19.pdf", date(2026, 5, 20), "8", 2),
    ("dept_22-2026-05-19.pdf", date(2026, 5, 20), "22", 10),
    ("misc_dept-2026-05-19.pdf", date(2025, 12, 23), "5", 1),
])
def test_metadata_and_count(fixture, expected_date, expected_dept, min_rulings):
    rs = parse_file(str(FIXTURE_DIR / fixture), "x")
    assert len(rs) >= min_rulings, f"{fixture}: got {len(rs)}"
    for r in rs:
        assert r.hearing_date == expected_date
        assert r.county == "solano"
        assert r.dept == expected_dept


def test_dept_word_to_number():
    """'DEPARTMENT TWENTY-TWO' -> '22'."""
    rs = parse_file(str(FIXTURE_DIR / "dept_22-2026-05-19.pdf"), "x")
    assert all(r.dept == "22" for r in rs)


def test_civil_uses_case_no_prefix():
    rs = parse_file(str(FIXTURE_DIR / "dept_3-2026-05-19.pdf"), "x")
    assert all(r.case_number.startswith(("CL", "CU")) for r in rs)


def test_probate_uses_pregrant_order_anchor():
    """Probate dept PDFs use 'PREGRANT ORDER' for pre-approved matters."""
    rs = parse_file(str(FIXTURE_DIR / "dept_22-2026-05-19.pdf"), "x")
    nums = {r.case_number for r in rs}
    # ELISEO MONTEJANO BARRIGA trust is a PREGRANT ORDER block.
    assert "PR24-00307" in nums


def test_motion_type_extracted():
    rs = parse_file(str(FIXTURE_DIR / "dept_3-2026-05-19.pdf"), "x")
    by_case = {r.case_number: r for r in rs}
    assert "Final Approval" in by_case["CU23-04949"].motion_type


def test_judge_in_body_text():
    """The page-1 judge name is stashed in body_text."""
    rs = parse_file(str(FIXTURE_DIR / "dept_7-2026-05-19.pdf"), "x")
    assert all(r.body_text == "TIM P. KAM" for r in rs)


def test_arbitration_granted_not_misclassified():
    """An 'objection overruled' inside a granted petition body should not flip outcome."""
    rs = parse_file(str(FIXTURE_DIR / "dept_8-2026-05-19.pdf"), "x")
    by_case = {r.case_number: r for r in rs}
    assert by_case["CU26-00205"].outcome == "granted"


def test_continued_to_extracted():
    rs = parse_file(str(FIXTURE_DIR / "dept_7-2026-05-19.pdf"), "x")
    cont = [r for r in rs if r.continued_to is not None]
    assert cont, "expected at least one continued ruling"


def test_ruling_ids_unique_and_stable():
    a = parse_file(str(FIXTURE_DIR / "dept_22-2026-05-19.pdf"), "x")
    b = parse_file(str(FIXTURE_DIR / "dept_22-2026-05-19.pdf"), "x")
    ids = [r.ruling_id for r in a]
    assert len(set(ids)) == len(ids)
    assert ids == [r.ruling_id for r in b]
