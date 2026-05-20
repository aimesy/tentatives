from datetime import date
from pathlib import Path

import pytest

from counties.santa_clara.scraper import parse_file

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.mark.parametrize("fixture,expected_date,expected_dept,min_rulings,division_hint", [
    ("dept-1.pdf", date(2026, 5, 14), "1", 5, "Civil Law and Motion"),
    ("dept-2.pdf", date(2026, 5, 18), "2", 1, "Probate"),
    ("dept-6.pdf", date(2026, 5, 21), "6", 4, "Civil Law and Motion"),
    ("dept-12.pdf", date(2026, 5, 15), "12", 5, "Civil Law and Motion"),
])
def test_metadata_and_count(fixture, expected_date, expected_dept, min_rulings, division_hint):
    rs = parse_file(str(FIXTURE_DIR / fixture), "x", division_hint=division_hint)
    assert len(rs) >= min_rulings, f"{fixture}: got {len(rs)}"
    for r in rs:
        assert r.hearing_date == expected_date
        assert r.county == "santa-clara"
        assert r.dept == expected_dept


def test_civil_case_number_format():
    rs = parse_file(str(FIXTURE_DIR / "dept-1.pdf"), "x")
    assert all(r.case_number.startswith("2") and "CV" in r.case_number for r in rs)


def test_probate_case_number_format():
    rs = parse_file(str(FIXTURE_DIR / "dept-2.pdf"), "x")
    nums = {r.case_number for r in rs}
    assert any("PR" in n for n in nums)


def test_judge_in_body_text():
    rs = parse_file(str(FIXTURE_DIR / "dept-1.pdf"), "x")
    assert all(r.body_text == "Eunice Lee" for r in rs)


def test_division_from_header_overrides_hint_for_probate():
    """Page 1 header says 'PROBATE LAW AND MOTION TENTATIVE RULINGS' for dept 2."""
    rs = parse_file(str(FIXTURE_DIR / "dept-2.pdf"), "x", division_hint="Civil")
    assert all(r.division == "Probate Law and Motion" for r in rs)


def test_division_hint_used_when_header_missing():
    """Dept 12's page 1 omits a division word; hint is the fallback."""
    rs = parse_file(str(FIXTURE_DIR / "dept-12.pdf"), "x", division_hint="Civil Law and Motion")
    assert all(r.division == "Civil Law and Motion" for r in rs)


def test_outcomes_classified():
    rs = parse_file(str(FIXTURE_DIR / "dept-1.pdf"), "x")
    outcomes = {r.outcome for r in rs}
    assert len(outcomes) >= 2


def test_ruling_ids_unique_and_stable():
    a = parse_file(str(FIXTURE_DIR / "dept-1.pdf"), "x")
    b = parse_file(str(FIXTURE_DIR / "dept-1.pdf"), "x")
    ids = [r.ruling_id for r in a]
    assert len(set(ids)) == len(ids)
    assert ids == [r.ruling_id for r in b]
