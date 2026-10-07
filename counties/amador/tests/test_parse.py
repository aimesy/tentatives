from datetime import date
from pathlib import Path

import pytest

from counties.amador.scraper import parse_file

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.mark.parametrize("fixture,expected_date,expected_division,division_hint,min_rulings", [
    ("lawmotion-2020-01-10.pdf", date(2020, 1, 10), "Law and Motion", None, 3),
    # Dept-style header has no division word; orchestrate passes the hint from captures.ndjson.
    ("lawmotion-2022-04-11.pdf", date(2022, 4, 11), "Civil Law and Motion", "Civil Law and Motion", 3),
    ("cmc-fl-2020-02-03.pdf", date(2020, 2, 3), "Family Law Case Management", None, 2),
    ("dept1-2022-02-07.pdf", date(2022, 2, 7), "Law and Motion", None, 5),
])
def test_metadata_and_count(fixture, expected_date, expected_division, division_hint, min_rulings):
    rs = parse_file(str(FIXTURE_DIR / fixture), "x", division_hint=division_hint)
    assert len(rs) >= min_rulings, f"{fixture}: got {len(rs)}"
    for r in rs:
        assert r.hearing_date == expected_date
        assert r.county == "amador"
        assert r.division == expected_division


def test_case_number_formats():
    rs = parse_file(str(FIXTURE_DIR / "lawmotion-2022-04-11.pdf"), "x")
    nums = {r.case_number for r in rs}
    # Spaces in original ("21 FC 7597") get normalized to dashes.
    assert "21-FC-7597" in nums
    assert any(n.startswith("19-CVC-") for n in nums)


def test_dashes_preserved_for_modern_format():
    rs = parse_file(str(FIXTURE_DIR / "lawmotion-2020-01-10.pdf"), "x")
    nums = {r.case_number for r in rs}
    assert "18-CVC-10752" in nums


def test_outcomes_classified():
    rs = parse_file(str(FIXTURE_DIR / "lawmotion-2022-04-11.pdf"), "x")
    outcomes = {r.outcome for r in rs}
    assert "continued" in outcomes


def test_continued_to_extracted():
    rs = parse_file(str(FIXTURE_DIR / "lawmotion-2022-04-11.pdf"), "x")
    bonner = next((r for r in rs if r.case_number == "19-CVC-11019"), None)
    assert bonner is not None
    assert bonner.continued_to == date(2022, 4, 25)


def test_no_anchor_style_handled():
    """The Dept-N PDFs lack 'TENTATIVE RULING:' anchors and need the case-line fallback."""
    rs = parse_file(str(FIXTURE_DIR / "lawmotion-2022-04-11.pdf"), "x")
    # All three real rulings are caught despite missing anchors.
    nums = {r.case_number for r in rs}
    assert nums == {"19-CVC-11019", "21-FC-7597", "21-CVC-12114"}


def test_ruling_ids_unique_and_stable():
    a = parse_file(str(FIXTURE_DIR / "lawmotion-2020-01-10.pdf"), "x")
    b = parse_file(str(FIXTURE_DIR / "lawmotion-2020-01-10.pdf"), "x")
    ids = [r.ruling_id for r in a]
    assert len(set(ids)) == len(ids)
    assert ids == [r.ruling_id for r in b]
