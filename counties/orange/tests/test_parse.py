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


def test_probate_title_before_case_number_and_motion_after():
    source = Path("archive/orange/0d/0d7b8ceb305503c22e3b787bec6f358ccfaa89e4e0a138bd3540955f989dc98f.pdf")
    if not source.exists():
        pytest.skip("full Orange archive source is not materialized")
    rs = parse_file(str(source), "x", division_hint="Probate")
    row = next(r for r in rs if r.case_number == "2020-01140947")
    assert row.case_title == "Geisler \u2013 Trust"
    assert row.motion_type == "Motion for Fees"


def test_probate_modern_case_title_before_case_number():
    source = Path("archive/orange/11/111dff341e84cc1709721840731d1d44cce7c34a771703ce8cf8848c7c891ccf.pdf")
    if not source.exists():
        pytest.skip("full Orange archive source is not materialized")
    rs = parse_file(str(source), "x", division_hint="Probate")
    row = next(r for r in rs if r.case_number == "30-2025-01523808")
    assert row.case_title == "Zor \u2013 Trust"
    assert row.motion_type == "MOTION FOR ORDERS"


def test_civil_bare_numeric_date_under_tentative_header():
    source = Path("archive/orange/7f/7f31477536064806426dc14c6de1a656f41db3442de6d6152ad2b6d961943b57.pdf")
    if not source.exists():
        pytest.skip("full Orange archive source is not materialized")
    rs = parse_file(str(source), "x", division_hint="Civil")

    assert len(rs) >= 10
    assert rs[0].hearing_date == date(2026, 5, 21)
    assert rs[0].dept == "CX102"
    assert rs[0].case_number == "2019-01051868"
    assert rs[0].case_title.startswith("Zepeda")


def test_reduced_year_case_number_archive_packet():
    source = Path("archive/orange/0b/0be009299e5528892f0d22a08e013a09716f8f09f84b0babe3d22cd8e19891a8.pdf")
    if not source.exists():
        pytest.skip("full Orange archive source is not materialized")
    rs = parse_file(
        str(source),
        "https://www.occourts.org/media-relations/civil/ssteinerrulings.pdf",
        division_hint="Civil",
    )

    assert rs
    assert rs[0].hearing_date == date(2026, 5, 27)
    assert any(r.case_number == "2025-1489617" for r in rs)


def test_two_digit_year_case_number_archive_packet():
    source = Path("archive/orange/0b/0bc32a06f8cc1b5fac3f61a1efaf6e9c953b6b03f72f9aa85aa7b6ffcb979534.pdf")
    if not source.exists():
        pytest.skip("full Orange archive source is not materialized")
    rs = parse_file(
        str(source),
        "https://www.occourts.org/media-relations/civil/thowardrulings.pdf",
        division_hint="Civil",
    )

    assert rs
    assert rs[0].hearing_date == date(2023, 9, 28)
    assert rs[0].case_number == "22-1277422"
    assert rs[0].case_title.startswith("Pitman")


def test_hearing_date_and_wrapped_modern_case_number_archive_packet():
    source = Path("archive/orange/0b/0b44f2ac0c76117f86202ba5056c2cef89af2075f5dd76ca4425fd53e194851e.pdf")
    if not source.exists():
        pytest.skip("full Orange archive source is not materialized")
    rs = parse_file(
        str(source),
        "https://www.occourts.org/media-relations/civil/kknillrulings.pdf",
        division_hint="Civil",
    )

    assert len(rs) >= 2
    assert rs[0].hearing_date == date(2026, 5, 22)
    assert rs[0].case_number == "30-2024-01440872-CU-FR-CJC"
    assert rs[0].case_title.startswith("Callahan")


def test_ordinal_date_reduced_wrapped_case_number_archive_packet():
    source = Path("archive/orange/d1/d1896334de7dfd43fcdeb278c2480a165d1ff0cb6b3ebb769961fd9ce775998a.pdf")
    if not source.exists():
        pytest.skip("full Orange archive source is not materialized")
    rs = parse_file(
        str(source),
        "https://www.occourts.org/media-relations/civil/cluegerulings.pdf",
        division_hint="Civil",
    )

    assert rs
    assert rs[0].hearing_date == date(2026, 6, 12)
    assert rs[0].case_number == "24-01381102"


def test_title_only_table_archive_packet():
    source = Path("archive/orange/48/48b8550f3dc03a4d482e771e88129ce3607a8eb24bae16c2090b0a4cebb078e3.pdf")
    if not source.exists():
        pytest.skip("full Orange archive source is not materialized")
    rs = parse_file(
        str(source),
        "https://www.occourts.org/media-relations/civil/cgriffinrulings.pdf",
        division_hint="Civil",
    )

    assert len(rs) >= 4
    assert rs[0].hearing_date == date(2026, 6, 15)
    assert rs[0].case_number == ""
    assert rs[0].case_title.startswith("Tarakji v. Secure")
    assert rs[1].outcome == "granted"


def test_title_only_calendar_without_dispositions_is_not_parsed():
    source = Path("archive/orange/4d/4d21abb8276455911e537d972323f0e606f1cddf8aec208d6bfc00045aa68535.pdf")
    if not source.exists():
        pytest.skip("full Orange archive source is not materialized")
    rs = parse_file(
        str(source),
        "https://www.occourts.org/media-relations/civil/sreciorulings.pdf",
        division_hint="Civil",
    )

    assert rs == []


def test_multi_date_archive_packet_uses_row_anchors():
    source = Path("archive/orange/12/12a5f8b075d8c06664a41fdfae33c41ddd31f370795c56bff60cf8dca7695aee.pdf")
    if not source.exists():
        pytest.skip("full Orange archive source is not materialized")
    rs = parse_file(
        str(source),
        "https://www.occourts.org/sites/default/files/oc/default/tentative-rulings/lmelzerrulings.pdf",
        division_hint="Civil",
    )

    assert len(rs) == 13
    assert rs[0].hearing_date == date(2025, 4, 16)
    assert rs[0].case_title == "People of the State of California vs. Auerbach"
    assert rs[1].hearing_date == date(2025, 4, 17)
    assert rs[1].case_title == "Johnson vs. Olive Crest"
    assert rs[2].case_number == "2024-01385636"
    assert rs[2].case_title == "Stevens vs. Monsanto Company"
    assert rs[2].page_start == 4
