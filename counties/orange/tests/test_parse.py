from datetime import date
from pathlib import Path

import pytest

from counties.orange.scraper import parse_file

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.mark.parametrize("fixture,expected_date,expected_dept,division_hint,min_rulings", [
    ("civil-adelacruzrulings.pdf", date(2026, 5, 14), "CM2", "Civil", 3),
    ("probate-CM3rulings.pdf", date(2026, 5, 6), "CM3", "Probate", 1),
    ("family-law-iclaustrorulings.pdf", date(2025, 12, 5), "C22", "Family Law", 3),
])
def test_metadata_and_count(fixture, expected_date, expected_dept, division_hint, min_rulings):
    rs = parse_file(str(FIXTURE_DIR / fixture), "x", division_hint=division_hint)
    assert len(rs) >= min_rulings, f"{fixture}: got {len(rs)}"
    for r in rs:
        assert r.hearing_date == expected_date
        assert r.county == "orange"
        assert r.dept == expected_dept


def test_modern_civil_case_number_with_suffix():
    rs = parse_file(str(FIXTURE_DIR / "civil-adelacruzrulings.pdf"), "x")
    nums = {r.case_number for r in rs}
    assert any(n.endswith("CU-PO-CJC") or n.endswith("CU-OE-CJC") for n in nums), nums


def test_family_law_case_number_format():
    rs = parse_file(str(FIXTURE_DIR / "family-law-iclaustrorulings.pdf"), "x")
    nums = {r.case_number for r in rs}
    assert any("D" in n for n in nums)


def test_probate_division_falls_back_to_hint():
    """The probate page-1 header doesn't say PROBATE; hint comes from the
    discovery URL (probate-tentative-rulings)."""
    rs = parse_file(
        str(FIXTURE_DIR / "probate-CM3rulings.pdf"), "x", division_hint="Probate"
    )
    assert all(r.division == "Probate" for r in rs)


def test_judge_in_body_text():
    rs = parse_file(str(FIXTURE_DIR / "civil-adelacruzrulings.pdf"), "x")
    assert all("De La Cruz" in r.body_text for r in rs)


def test_outcomes_classified():
    rs = parse_file(str(FIXTURE_DIR / "family-law-iclaustrorulings.pdf"), "x")
    outcomes = {r.outcome for r in rs}
    assert outcomes  # at minimum, some outcome was assigned


def test_ruling_ids_unique_and_stable():
    a = parse_file(str(FIXTURE_DIR / "civil-adelacruzrulings.pdf"), "x")
    b = parse_file(str(FIXTURE_DIR / "civil-adelacruzrulings.pdf"), "x")
    ids = [r.ruling_id for r in a]
    assert len(set(ids)) == len(ids)
    assert ids == [r.ruling_id for r in b]
