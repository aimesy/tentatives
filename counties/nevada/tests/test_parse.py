from datetime import date
import io
from pathlib import Path
import zipfile

import pytest

from counties.nevada.scraper import parse, parse_file

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.mark.parametrize("fixture,expected_date,expected_division,min_rulings", [
    ("lawmotion-2026-01-12.pdf", date(2026, 1, 12), "Law and Motion", 5),
    ("probate-2026-01-12.pdf", date(2026, 1, 12), "Probate", 2),
    ("cmc-2026-03-22.pdf", date(2026, 3, 2), "Case Management", 20),
    ("guardianship-2026-05-07.pdf", date(2026, 5, 7), "Guardianship", 10),
])
def test_metadata_and_count(fixture, expected_date, expected_division, min_rulings):
    rs = parse_file(str(FIXTURE_DIR / fixture), "x")
    assert len(rs) >= min_rulings, f"{fixture}: got {len(rs)}"
    for r in rs:
        assert r.hearing_date == expected_date
        assert r.county == "nevada"
        assert r.division == expected_division


def test_case_number_formats():
    rs = parse_file(str(FIXTURE_DIR / "cmc-2026-03-22.pdf"), "x")
    nums = {r.case_number for r in rs}
    # CL and CU prefixes both present
    assert any(n.startswith("CL") for n in nums)
    assert any(n.startswith("CU") for n in nums)


def test_legacy_p_case_numbers():
    rs = parse_file(str(FIXTURE_DIR / "guardianship-2026-05-07.pdf"), "x")
    nums = {r.case_number for r in rs}
    assert any(n.startswith("P10-") or n.startswith("P12-") for n in nums)


def test_dept_extracted_from_header():
    rs = parse_file(str(FIXTURE_DIR / "guardianship-2026-05-07.pdf"), "x")
    # Guardianship PDF says "Department 3" in header.
    assert all(r.dept == "3" for r in rs), {r.dept for r in rs}


def test_location_captured_as_motion_type():
    rs = parse_file(str(FIXTURE_DIR / "lawmotion-2026-01-12.pdf"), "x")
    assert all(r.motion_type == "Truckee" for r in rs)


def test_outcomes_classified():
    rs = parse_file(str(FIXTURE_DIR / "cmc-2026-03-22.pdf"), "x")
    outcomes = {r.outcome for r in rs}
    # CMC continuances are common.
    assert "continued" in outcomes


def test_continued_to_extracted():
    rs = parse_file(str(FIXTURE_DIR / "cmc-2026-03-22.pdf"), "x")
    continued = [r for r in rs if r.continued_to is not None]
    assert continued, "expected at least one ruling with continued_to set"
    # Most continue to June 15, 2026.
    assert any(r.continued_to == date(2026, 6, 15) for r in continued)


def test_ruling_ids_unique_and_stable():
    a = parse_file(str(FIXTURE_DIR / "lawmotion-2026-01-12.pdf"), "x")
    b = parse_file(str(FIXTURE_DIR / "lawmotion-2026-01-12.pdf"), "x")
    ids = [r.ruling_id for r in a]
    assert len(set(ids)) == len(ids)
    assert ids == [r.ruling_id for r in b]


def _docx_with_paragraphs(paragraphs: list[str]) -> bytes:
    body = "".join(
        "<w:p><w:r><w:t>" + p.replace("&", "&amp;") + "</w:t></w:r></w:p>"
        for p in paragraphs
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types></Types>")
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_docx_case_management_parser():
    content = _docx_with_paragraphs([
        "May 15, 2026 Case Management Conference Tentative Rulings",
        "CL0003211\tLVNV Funding, LLC vs. Kathleen Mumaw",
        "No appearances are required. The Court sets the matter for a court trial.",
        "Trial: July 17, 2027, 10:30 a.m., Dept. A",
        "CU0001178\tGregory Ludlum vs. Joshua Terranova, Executor, et al.",
        "No appearances are required. The Court continues the case management conference to August 21, 2026 at 9:00 a.m., in Department A.",
    ])

    rs = parse(
        content,
        source_url="https://www.nevada.courts.ca.gov/system/files/tentative-rulings/cmc-51526-dept-truckee.docx",
        source_sha256="d" * 64,
        division_hint="Case Management",
    )

    assert [r.case_number for r in rs] == ["CL0003211", "CU0001178"]
    assert all(r.hearing_date == date(2026, 5, 15) for r in rs)
    assert all(r.division == "Case Management" for r in rs)
    assert all(r.dept == "A" for r in rs)
    assert all(r.motion_type == "Truckee" for r in rs)
    assert rs[1].outcome == "continued"
    assert rs[1].continued_to == date(2026, 8, 21)
    assert rs[0].style == "nevada-cmc-docx"


def test_single_case_packet_uses_url_date():
    source = Path("archive/nevada/a4/a45f1b8efe9e7f8724ca185d21e50e621c69e16bb9f9ceb9bbe6e0276b86ab5e.pdf")
    if not source.exists():
        pytest.skip("full Nevada archive source is not materialized")
    rs = parse_file(
        str(source),
        "https://www.nevada.courts.ca.gov/system/files/tentative-rulings/3-9-26-truckee-tr_botwinis-v-fleming.pdf",
    )
    assert len(rs) == 1
    assert rs[0].hearing_date == date(2026, 3, 9)
    assert rs[0].case_number == "CU0000657"
    assert rs[0].case_title == "Botwinis v. Fleming"
    assert rs[0].motion_type == "Truckee"


def test_shared_these_matters_ruling_backfills_blank_header():
    source = Path("archive/nevada/60/6066cf1efd5087b387de5b02fc9836ea07f19cb127db4343b5c043b474181329.pdf")
    if not source.exists():
        pytest.skip("full Nevada archive source is not materialized")
    rs = parse_file(str(source), "x")
    by_case = {r.case_number: r for r in rs}

    row = by_case["CU0002305"]
    assert row.case_title == "Christ, Jason v. Hannah, Jordan"
    assert row.outcome == "continued"
    assert "these matters are continued" in row.outcome_text
