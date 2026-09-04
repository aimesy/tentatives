from datetime import date
from pathlib import Path

import pytest

from counties.placer.scraper import parse_file

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.mark.parametrize("fixture,expected_date,expected_dept,min_rulings", [
    ("050126_Web.pdf", date(2026, 5, 1), "33", 5),
    ("050526_web.pdf", date(2026, 5, 5), "42", 10),
    ("043026_Web.pdf", date(2026, 4, 30), "3", 10),
])
def test_metadata_and_count(fixture, expected_date, expected_dept, min_rulings):
    rs = parse_file(str(FIXTURE_DIR / fixture), "x")
    assert len(rs) >= min_rulings, f"{fixture}: got {len(rs)}"
    for r in rs:
        assert r.hearing_date == expected_date
        assert r.dept == expected_dept
        assert r.county == "placer"
        assert r.division == "Civil Law and Motion"


def test_case_number_formats():
    rs = parse_file(str(FIXTURE_DIR / "050126_Web.pdf"), "x")
    nums = {r.case_number for r in rs}
    # Dashed format
    assert any(n.startswith("M-CV-") for n in nums)
    assert any(n.startswith("S-CV-") for n in nums)


def test_jccp_case_number():
    """JCCP cases use a different format (letters then digits, no dashes)."""
    rs = parse_file(str(FIXTURE_DIR / "043026_Web.pdf"), "x")
    by_idx = {r.ruling_index: r for r in rs}
    assert by_idx[1].case_number == "JCCP5336"
    assert by_idx[1].case_title == "TOPGOLF PAYROLL WAGE AND HOUR CASES"


def test_outcomes_classified():
    rs = parse_file(str(FIXTURE_DIR / "050526_web.pdf"), "x")
    outcomes = {r.outcome for r in rs}
    assert len(outcomes) >= 3, outcomes


def test_ruling_ids_unique_and_stable():
    a = parse_file(str(FIXTURE_DIR / "050526_web.pdf"), "x")
    b = parse_file(str(FIXTURE_DIR / "050526_web.pdf"), "x")
    ids = [r.ruling_id for r in a]
    assert len(set(ids)) == len(ids)
    assert ids == [r.ruling_id for r in b]


def test_ruling_ids_unique_when_same_case_header_repeats():
    source = Path("archive/placer/d5/d5aff08d5a734ce84f6daa85679d3e388555202eadc0c4f3e589326b08efe10c.pdf")
    if not source.exists():
        pytest.skip("full Placer archive source is not materialized")
    rs = parse_file(str(source), "x")
    ids = [r.ruling_id for r in rs]
    assert len(set(ids)) == len(ids)
    matching = [r for r in rs if r.case_number == "S-CV-0050336"]
    assert len(matching) == 2
    assert {r.motion_type for r in matching} == {
        "Defendant’s Motion for Attorney’s Fees After Appeal",
        "Ruling on Request for Judicial Notice",
    }
