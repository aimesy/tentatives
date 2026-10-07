from datetime import date
from pathlib import Path

import pytest

from counties.san_francisco.scraper import parse_file

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.mark.parametrize("fixture,expected_date,expected_dept,min_rulings", [
    ("dept-403.pdf", date(2026, 4, 21), "403", 5),
    ("dept-404.pdf", date(2026, 4, 21), "404", 5),
    ("dept-414.pdf", date(2026, 3, 26), "414", 1),
])
def test_metadata_and_count(fixture, expected_date, expected_dept, min_rulings):
    rs = parse_file(str(FIXTURE_DIR / fixture), "x")
    assert len(rs) >= min_rulings, f"{fixture}: got {len(rs)}"
    for r in rs:
        assert r.hearing_date == expected_date
        assert r.county == "san-francisco"
        assert r.dept == expected_dept
        assert r.division == "Family Law"


def test_case_number_formats():
    rs = parse_file(str(FIXTURE_DIR / "dept-403.pdf"), "x")
    nums = {r.case_number for r in rs}
    # FDI (dissolution) and FPT (paternity) prefixes both appear in SF UFC.
    assert any(n.startswith("FDI") for n in nums)


def test_parties_extracted_as_vs_title():
    rs = parse_file(str(FIXTURE_DIR / "dept-403.pdf"), "x")
    # At least one ruling should have a "X vs Y" title.
    assert any(" vs " in r.case_title for r in rs)


def test_motion_type_is_request_for_order():
    rs = parse_file(str(FIXTURE_DIR / "dept-403.pdf"), "x")
    motions = [r.motion_type for r in rs if r.motion_type]
    assert any("REQUEST FOR ORDER" in m for m in motions)


def test_judge_in_body_text():
    rs = parse_file(str(FIXTURE_DIR / "dept-403.pdf"), "x")
    assert all(r.body_text == "BOBBY P. LUNA" for r in rs)


def test_outcomes_classified():
    rs = parse_file(str(FIXTURE_DIR / "dept-404.pdf"), "x")
    outcomes = {r.outcome for r in rs}
    assert len(outcomes) >= 3, outcomes


def test_per_ruling_hearing_date():
    """Multiple rulings in one PDF can have different per-ruling hearing dates;
    the parser reads from each ruling's own Hearing Date field."""
    rs = parse_file(str(FIXTURE_DIR / "dept-403.pdf"), "x")
    dates = {r.hearing_date for r in rs}
    # All rulings on this calendar share one date here.
    assert dates == {date(2026, 4, 21)}


def test_ruling_ids_unique_and_stable():
    a = parse_file(str(FIXTURE_DIR / "dept-403.pdf"), "x")
    b = parse_file(str(FIXTURE_DIR / "dept-403.pdf"), "x")
    ids = [r.ruling_id for r in a]
    assert len(set(ids)) == len(ids)
    assert ids == [r.ruling_id for r in b]
