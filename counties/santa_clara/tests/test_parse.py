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


def test_scroll_down_toc_rows_do_not_replace_full_ruling_blocks():
    source = Path("archive/santa-clara/02/0281f6b7ae31c8dc170adbfae3ac325b01208c2f153a2d94e321a6ba55e6a8cf.pdf")
    if not source.exists():
        pytest.skip("full Santa Clara archive source is not materialized")
    rs = parse_file(str(source), "x", division_hint="Civil Law and Motion")
    by_case = {r.case_number: r for r in rs}
    assert by_case["24CV442138"].case_title == "Gary Cayton et al vs El Camino Hospital et al"
    assert by_case["24CV442138"].motion_type == "Motion to Strike"
    assert "Before the court is defendant El Camino Hospital" in by_case["24CV442138"].outcome_text
    assert by_case["25CV467301"].case_title == "Fernando Hernandez et al vs Peter Singler et al"
    assert by_case["25CV467301"].motion_type.startswith("Demurrer")


def test_probate_index_only_scroll_down_instruction_trimmed_from_title():
    source = Path("archive/santa-clara/75/75eb1b7dedfd1b7001a450ec75b85d10f1bccd3763ff65ee222ae0d9d501a094.pdf")
    if not source.exists():
        pytest.skip("full Santa Clara archive source is not materialized")
    rs = parse_file(str(source), "x", division_hint="Probate")
    row = next(r for r in rs if r.case_number == "24PR196632")
    assert row.case_title == "1990 Kelly Family Trust dated September 2, 1990"
    assert "Scroll down" not in row.case_title


def test_no_comma_date_table_packet_parses():
    source = Path("archive/santa-clara/ab/aba3de8dfec5bd80bff36ca64413cc5b57018e3e832ebf9410c1bfcd1645c076.pdf")
    if not source.exists():
        pytest.skip("full Santa Clara archive source is not materialized")
    rs = parse_file(str(source), "x", division_hint="Civil Law and Motion", dept_hint="6")

    assert len(rs) >= 8
    assert rs[0].hearing_date == date(2026, 6, 18)
    assert rs[0].case_number == "22CV395876"


def test_probate_all_caps_date_and_case_name_colon_parses():
    source = Path("archive/santa-clara/96/96ea127bf5f0117a0998f522856e9bd2b2b9f0d41391bc969bc7997cb985df31.pdf")
    if not source.exists():
        pytest.skip("full Santa Clara archive source is not materialized")
    rs = parse_file(str(source), "x", division_hint="Probate", dept_hint="7")

    assert len(rs) == 1
    assert rs[0].hearing_date == date(2026, 5, 15)
    assert rs[0].case_number == "25PR200162"
    assert rs[0].case_title == "Estate of Donald Hollenbach"


def test_formal_order_style_packet_parses_one_lead_case():
    source = Path("archive/santa-clara/64/645d53bcd985a0690a97ed63de8246e8d84969bc3d9e48ddaae0441ebc43a826.pdf")
    if not source.exists():
        pytest.skip("full Santa Clara archive source is not materialized")
    rs = parse_file(str(source), "x", division_hint="Probate", dept_hint="7")

    assert len(rs) == 1
    assert rs[0].hearing_date == date(2026, 5, 29)
    assert rs[0].case_number == "22PR192746"
    assert rs[0].case_title == "The Anne M. Sorden Living Trust"
