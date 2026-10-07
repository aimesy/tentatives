from datetime import date
from pathlib import Path

import pytest

from counties.el_dorado.scraper import parse_file

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------- Style A: dept 9 probate


@pytest.fixture
def style_a():
    return parse_file(
        str(FIXTURE_DIR / "tr-d-09-2026-05-18.pdf"),
        source_url="https://www.eldorado.courts.ca.gov/system/files/tentative-rulings/tr-d-09-2026-05-18.pdf",
        dept_hint="9",
    )


def test_style_a_extracts_fifteen_rulings(style_a):
    assert len(style_a) == 15
    assert [r.ruling_index for r in style_a] == list(range(1, 16))


def test_style_a_metadata(style_a):
    for r in style_a:
        assert r.hearing_date == date(2026, 5, 18)
        assert r.dept == "9"
        assert r.division == "Probate"
        assert r.style == "probate-dept-header"


def test_style_a_case_numbers_and_titles(style_a):
    by_idx = {r.ruling_index: r for r in style_a}
    assert by_idx[1].case_number == "25PR0206"
    assert by_idx[1].case_title == "MATTER OF ANDRESEN TRUST"
    assert by_idx[10].case_number == "PP20200121"  # legacy format
    assert by_idx[13].case_number == "26PR0079"


def test_style_a_outcomes(style_a):
    by_idx = {r.ruling_index: r for r in style_a}
    assert by_idx[1].outcome == "continued"
    assert by_idx[1].continued_to == date(2026, 7, 6)
    assert by_idx[2].outcome == "denied"
    assert by_idx[4].outcome == "granted"
    assert by_idx[4].conditional is True
    assert by_idx[11].outcome == "denied"


# ---------------------------------------------------------------- Style B: dept 4 law & motion


@pytest.fixture
def style_b():
    return parse_file(
        str(FIXTURE_DIR / "lawandmotionmay152026.pdf"),
        source_url="https://www.eldorado.courts.ca.gov/system/files/tentative-rulings/lawandmotionmay152026.pdf",
        dept_hint="4",
    )


def test_style_b_extracts_nine_rulings(style_b):
    assert len(style_b) == 9
    assert [r.ruling_index for r in style_b] == list(range(1, 10))


def test_style_b_metadata(style_b):
    for r in style_b:
        assert r.hearing_date == date(2026, 5, 15)
        assert r.dept == "4"  # from dept_hint — not in PDF header
        assert r.division == "Law and Motion"
        assert r.style == "lawandmotion-calendar"


def test_style_b_case_numbers_title_after_case(style_b):
    """Style B has 'TITLE, CASE_NUMBER' — title before, number after comma."""
    by_idx = {r.ruling_index: r for r in style_b}
    assert by_idx[1].case_number == "25CV1362"
    assert by_idx[1].case_title == "CAPITAL ONE, N.A. v. McGINNIS"
    # Multi-motion ruling: motion_type contains both (A) and (B).
    assert "(A)" in by_idx[5].motion_type
    assert "(B)" in by_idx[5].motion_type
    # Legacy SC format
    assert by_idx[3].case_number == "SC20210148"


def test_style_b_outcomes(style_b):
    by_idx = {r.ruling_index: r for r in style_b}
    assert by_idx[1].outcome == "granted"
    assert by_idx[7].outcome == "denied"  # motion for sanctions denied
    assert by_idx[8].outcome == "denied"


# ---------------------------------------------------------------- Style C: dept 4 probate calendar


@pytest.fixture
def style_c():
    return parse_file(
        str(FIXTURE_DIR / "probatemay152026.pdf"),
        source_url="https://www.eldorado.courts.ca.gov/system/files/tentative-rulings/probatemay152026.pdf",
        dept_hint="4",
    )


def test_style_c_extracts_eight_rulings(style_c):
    assert len(style_c) == 8


def test_style_c_metadata(style_c):
    for r in style_c:
        assert r.hearing_date == date(2026, 5, 15)
        assert r.dept == "4"
        assert r.division == "Probate"
        assert r.style == "probate-calendar"


def test_style_c_case_numbers(style_c):
    by_idx = {r.ruling_index: r for r in style_c}
    assert by_idx[1].case_number == "24PR0124"
    assert by_idx[1].case_title == "ESTATE OF WESTFALL"
    # Legacy SP format (Special Proceedings).
    assert by_idx[7].case_number == "SP20140014"


def test_style_c_outcomes_include_off_calendar(style_c):
    by_idx = {r.ruling_index: r for r in style_c}
    assert by_idx[6].outcome == "off_calendar"  # "MATTER IS DROPPED FROM THE CALENDAR"


# ---------------------------------------------------------------- Style D: dept 12 family law


@pytest.fixture
def style_d():
    return parse_file(
        str(FIXTURE_DIR / "dept-12-20260513.pdf"),
        source_url="https://www.eldorado.courts.ca.gov/system/files/tentative-rulings/dept-12-20260513.pdf",
        # dept-12 PDFs DO have 'DEPARTMENT 12' in the header, so no hint needed.
    )


def test_style_d_extracts_four_rulings(style_d):
    assert len(style_d) == 4


def test_style_d_metadata(style_d):
    for r in style_d:
        assert r.hearing_date == date(2026, 5, 13)
        assert r.dept == "12"  # from PDF header, no hint needed
        assert r.style == "lawandmotion-tentative-rulings"


def test_style_d_case_numbers_whitespace_separated(style_d):
    """Style D has 'TITLE      CASE_NUMBER' (no comma)."""
    by_idx = {r.ruling_index: r for r in style_d}
    assert by_idx[1].case_number == "SFL20210053"  # legacy SFL prefix
    assert by_idx[1].case_title == "MARIA DE LA CRUZ V. JUAN DE LA CRUZ VAZQUEZ"
    # Modern FL prefix
    assert by_idx[2].case_number == "24FL0473"
    assert by_idx[2].case_title == "ROBERT SOUZA V. ARIANA MARTINEZ"


# ---------------------------------------------------------------- cross-style invariants


@pytest.mark.parametrize("fixture", [
    ("tr-d-09-2026-05-18.pdf", "9"),
    ("lawandmotionmay152026.pdf", "4"),
    ("probatemay152026.pdf", "4"),
    ("dept-12-20260513.pdf", None),
])
def test_ruling_ids_stable_and_unique(fixture):
    fname, hint = fixture
    a = parse_file(str(FIXTURE_DIR / fname), "x", dept_hint=hint)
    b = parse_file(str(FIXTURE_DIR / fname), "x", dept_hint=hint)
    ids = [r.ruling_id for r in a]
    assert len(set(ids)) == len(ids), "ruling_ids must be unique within one PDF"
    assert [r.ruling_id for r in a] == [r.ruling_id for r in b], "ruling_ids must be stable across parses"


# ---------------------------------------------------------------- dept fallbacks
# Style B/C PDFs from the wild rarely carry a dept_hint (no landing page), so
# the parser has to recover the dept from the source_url filename or fall back
# to the court convention (dept 4 for both Law and Motion / Probate Calendar).


def test_dept_falls_back_to_source_url_filename():
    """For tr-d-NN-... PDFs we lift the dept from the filename."""
    rulings = parse_file(
        str(FIXTURE_DIR / "tr-d-09-2026-05-18.pdf"),
        source_url="https://www.eldorado.courts.ca.gov/system/files/tentative-rulings/tr-d-09-2026-05-18.pdf",
        # no dept_hint
    )
    assert rulings
    assert all(r.dept == "9" for r in rulings)


def test_dept_falls_back_to_style_for_law_and_motion_calendar():
    """No filename hint and no header dept -> default to dept 4 by convention."""
    rulings = parse_file(
        str(FIXTURE_DIR / "lawandmotionmay152026.pdf"),
        source_url="https://example.com/some-other-filename.pdf",
        # no dept_hint
    )
    assert rulings
    assert all(r.dept == "4" for r in rulings)
    assert all(r.style == "lawandmotion-calendar" for r in rulings)


def test_dept_falls_back_to_style_for_probate_calendar():
    rulings = parse_file(
        str(FIXTURE_DIR / "probatemay152026.pdf"),
        source_url="https://example.com/some-other-filename.pdf",
        # no dept_hint
    )
    assert rulings
    assert all(r.dept == "4" for r in rulings)
    assert all(r.style == "probate-calendar" for r in rulings)


@pytest.mark.parametrize("fixture", [
    "tr-d-09-2026-05-18.pdf",
    "lawandmotionmay152026.pdf",
    "probatemay152026.pdf",
    "dept-12-20260513.pdf",
])
def test_page_spans_valid(fixture):
    rs = parse_file(str(FIXTURE_DIR / fixture), "x", dept_hint="X")
    for r in rs:
        assert 1 <= r.page_start <= r.page_end, (
            f"{fixture} #{r.ruling_index}: pages {r.page_start}-{r.page_end}"
        )


@pytest.mark.parametrize("fixture", [
    "tr-d-09-2026-05-18.pdf",
    "lawandmotionmay152026.pdf",
    "probatemay152026.pdf",
    "dept-12-20260513.pdf",
])
def test_outcome_text_strips_appearance_boilerplate(fixture):
    rs = parse_file(str(FIXTURE_DIR / fixture), "x", dept_hint="X")
    for r in rs:
        upper = r.outcome_text.upper()
        assert "INSTRUCTIONS FOR REMOTE" not in upper, f"#{r.ruling_index}: {r.outcome_text!r}"
        assert "CAL.RULE CT" not in upper, f"#{r.ruling_index}: {r.outcome_text!r}"
        assert "NO HEARING ON THIS MATTER WILL BE HELD" not in upper, f"#{r.ruling_index}"
