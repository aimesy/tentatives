from datetime import date
from pathlib import Path

import pytest

from counties.plumas.scraper import parse


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


def test_parse_plumas_case_no_calendar():
    pdf = _pdf([[
        "Tentative Rulings",
        "Law & Motion and Family Law Calendar for May 11, 2026",
        "Department Two - Judge William Abramson",
        "PROBATE CALENDAR - 9:00 a.m.",
        "Case No. PR23-00058 Conservatorship of Schake, Charles",
        "Tentative Ruling: Appearance Required: Petition for Limited Appraisal, court will hear argument.",
        "LAW & MOTION CALENDAR - 9:30 a.m.",
        "Case No. CV23-00203 Cohoon, Ben C. et al vs. Indian Valley Forests, LLC",
        "Tentative Ruling: No Appearance Required: Absent objection, the court will grant the Petition.",
    ]])

    rows = parse(pdf, "https://plumas.courts.ca.gov/system/files/tentative-ruling/tentative-ruling-may-11-2026.pdf")

    assert len(rows) == 2
    assert rows[0].hearing_date == date(2026, 5, 11)
    assert rows[0].dept == "2"
    assert rows[0].division == "Probate"
    assert rows[0].outcome == "appearance_required"
    assert rows[1].division == "Law and Motion"
    assert rows[1].outcome == "granted"


def test_ordinal_date_archive_calendar_packet():
    source = Path("archive/plumas/0f/0f386dfd5095160ef6a2ba02d9fc394498dfb315ddc7f2c03efe089ba5ba5b1a.pdf")
    if not source.exists():
        pytest.skip("full Plumas archive source is not materialized")
    rows = parse(
        source.read_bytes(),
        "https://plumas.courts.ca.gov/system/files/tentative-ruling/tentative-rulings-march-9-2026-complete.pdf",
        source_sha256="0f386dfd5095160ef6a2ba02d9fc394498dfb315ddc7f2c03efe089ba5ba5b1a",
        dept_hint="2",
        division_hint="Civil / Probate / Family Law",
    )

    assert len(rows) >= 20
    assert rows[0].hearing_date == date(2026, 3, 9)
    assert rows[0].case_number == "PR23-00042"
    assert rows[0].division == "Probate"
