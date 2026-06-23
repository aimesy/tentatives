from datetime import date
from pathlib import Path

import pytest

from counties.riverside.scraper import parse


def _pdf(lines_by_page: list[list[str]]) -> bytes:
    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids: list[str] = []
    pages: list[tuple[int, int, list[str]]] = []
    next_obj = 4
    for lines in lines_by_page:
        page_obj = next_obj
        content_obj = next_obj + 1
        next_obj += 2
        kids.append(f"{page_obj} 0 R")
        pages.append((page_obj, content_obj, lines))
    objects.append(f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for _page_obj, content_obj, lines in pages:
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj} 0 R >>"
        )
        body = "BT\n/F1 10 Tf\n72 740 Td\n12 TL\n" + "".join(
            f"({esc(line)}) Tj\nT*\n" for line in lines
        ) + "ET\n"
        objects.append(f"<< /Length {len(body.encode('latin-1'))} >>\nstream\n{body}endstream")
    out = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode("latin-1")
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1")
    return out


def test_parse_riverside_numbered_table():
    pdf = _pdf([[
        "Tentative Rulings for June 5, 2026",
        "Department 10",
        "1.",
        "CASE # CASE NAME HEARING NAME",
        "CVME2513565 JAFARI VS CILING MOTION FOR SALE OF DWELLING",
        "Tentative Ruling:",
        "The Court GRANTS the Motion for Sale of Dwelling.",
        "2.",
        "CASE # CASE NAME HEARING NAME",
        "CVRI2502372",
        "MENA VS ALCANTAR CONSTRUCTION GROUP INC.",
        "MOTION TO BE RELIEVED AS COUNSEL FOR ALCANTAR CONSTRUCTION GROUP INC.",
        "Tentative Ruling: No tentative ruling; appearances requested, either in person or telephonically.",
    ]])

    rows = parse(pdf, "https://www.riverside.courts.ca.gov/system/files/2023-10/Riv10ruling102323.pdf")

    assert len(rows) == 2
    assert rows[0].hearing_date == date(2026, 6, 5)
    assert rows[0].dept == "10"
    assert rows[0].case_title == "JAFARI VS CILING"
    assert rows[0].motion_type == "MOTION FOR SALE OF DWELLING"
    assert rows[0].outcome == "granted"
    assert rows[1].case_number == "CVRI2502372"
    assert rows[1].outcome == "appearance_required"


def test_embedded_table_header_without_new_item_marker_splits_new_ruling():
    source = Path("archive/riverside/cb/cb7944bae86be489c008a5616369ba91bb35bfcba35c9b3f7c2540e0d05c11b6.pdf")
    if not source.exists():
        pytest.skip("full Riverside archive source is not materialized")
    rows = parse(source.read_bytes(), "x")
    by_case = {r.case_number: r for r in rows}
    assert "CVRI2504589" in by_case
    assert "CVRI2502062" in by_case
    assert by_case["CVRI2504589"].page_end < by_case["CVRI2502062"].page_end
    assert by_case["CVRI2502062"].motion_type == "Demurrer to 1st Amended Complaint"
