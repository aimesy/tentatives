from datetime import date
from pathlib import Path

from counties.el_dorado.scraper import parse_file

FIXTURE = Path(__file__).parent.parent / "fixtures" / "tr-d-09-2026-05-18.pdf"


def _rulings():
    return parse_file(
        str(FIXTURE),
        source_url="https://www.eldorado.courts.ca.gov/system/files/tentative-rulings/tr-d-09-2026-05-18.pdf",
    )


def test_extracts_fifteen_rulings():
    rs = _rulings()
    assert len(rs) == 15, [r.ruling_index for r in rs]
    assert [r.ruling_index for r in rs] == list(range(1, 16))


def test_metadata_from_page_header_not_filename():
    rs = _rulings()
    for r in rs:
        assert r.hearing_date == date(2026, 5, 18)
        assert r.dept == "9"
        assert r.division == "Probate"
        assert r.county == "el-dorado"


def test_case_numbers_and_titles():
    rs = _rulings()
    by_idx = {r.ruling_index: r for r in rs}
    assert by_idx[1].case_number == "25PR0206"
    assert by_idx[1].case_title == "MATTER OF ANDRESEN TRUST"
    assert by_idx[1].motion_type == "Discovery Motions & Motion for Relief"
    # Legacy case-number format
    assert by_idx[10].case_number == "PP20200121"
    assert by_idx[10].case_title == "ESTATE OF KNOLL"
    # 26-prefix format
    assert by_idx[13].case_number == "26PR0079"


def test_outcomes_classified():
    rs = _rulings()
    by_idx = {r.ruling_index: r for r in rs}
    # #1: HEARING CONTINUED TO MONDAY, JULY 6, 2026
    assert by_idx[1].outcome == "continued"
    assert by_idx[1].continued_to == date(2026, 7, 6)
    # #2: PETITION TO DETERMINE TITLE ... IS DENIED. APPEARANCES ARE REQUIRED ...
    assert by_idx[2].outcome == "denied"
    # #4: ABSENT OBJECTION THE PETITION IS GRANTED AS REQUESTED.
    assert by_idx[4].outcome == "granted"
    assert by_idx[4].conditional is True
    # #8: APPEARANCES ARE REQUIRED ... A STATUS OF ADMINISTRATION HEARING IS SET ...
    assert by_idx[8].outcome == "appearance_required"
    # #11: PETITION DENIED.
    assert by_idx[11].outcome == "denied"
    # #15: PETITION DENIED.
    assert by_idx[15].outcome == "denied"


def test_ruling_ids_are_stable_and_unique():
    rs = _rulings()
    ids = [r.ruling_id for r in rs]
    assert len(set(ids)) == len(ids)
    # Re-parse must give identical IDs.
    rs2 = _rulings()
    assert [r.ruling_id for r in rs] == [r.ruling_id for r in rs2]


def test_page_spans_make_sense():
    rs = _rulings()
    for r in rs:
        assert 1 <= r.page_start <= r.page_end
    # #1 is just one page (short continuance ruling).
    by_idx = {r.ruling_index: r for r in rs}
    assert by_idx[1].page_end == 1
    # #2 spans multiple pages (long narrative).
    assert by_idx[2].page_end > by_idx[2].page_start


def test_body_text_excludes_disposition():
    rs = _rulings()
    by_idx = {r.ruling_index: r for r in rs}
    # body_text is what comes BEFORE "TENTATIVE RULING #N:"
    assert "TENTATIVE RULING #" not in by_idx[2].body_text
    # And the header line itself shouldn't be in body
    assert "25PR0304 ESTATE OF ANDERSON" not in by_idx[2].body_text
    # Body is non-trivial for long rulings
    assert len(by_idx[2].body_text) > 500


def test_outcome_text_strips_remote_boilerplate():
    rs = _rulings()
    by_idx = {r.ruling_index: r for r in rs}
    for r in rs:
        assert "INSTRUCTIONS FOR REMOTE" not in r.outcome_text.upper(), (
            f"#{r.ruling_index}: {r.outcome_text!r}"
        )
