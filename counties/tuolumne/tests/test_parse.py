from datetime import date

from counties.tuolumne.scraper import parse


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


def test_parse_tuolumne_page_oriented_calendar():
    pdf = _pdf([
        [
            "Consolidated Calendar",
            "Superior Court of California, County of Tuolumne",
            "Department 2 June 3, 2026 8:30 am Date Filed DA Case #",
            "CV68039 01/27/2026 1 Petition in re: 16760 Woodside Wy Sonora, CA 95370",
            "Attorney: Yet Not Entered 16760 Woodside Wy Sonora, CA",
            "Case Management Conference",
            "FURTHER - POS?",
            "01/27/2026 Petition File Tracking",
            "5/27/2026 2:07 pm",
            "This is a petition to deposit surplus funds.",
            "The petition cannot be summarily granted and will be set for hearing on notice.",
        ],
        [
            "Consolidated Calendar",
            "Department 2 June 3, 2026 8:30 am Date Filed DA Case #",
            "CVL66996 02/25/2025 3 Bank of America, N.A. vs. Maria M. Ramirez",
            "Attorney: Donald Sherrill Bank of America, N.A.",
            "Motion Hearing - Other",
            "for Order of Admissions of Truth Be Deemed Admitted",
            "5/27/2026 2:07 pm",
            "Motion to deem admitted DENIED without prejudice.",
        ],
    ])

    rows = parse(pdf, "https://www.tuolumne.courts.ca.gov/system/files/tentative-rulings/tr_d2_06032026.pdf")

    assert len(rows) == 2
    assert rows[0].hearing_date == date(2026, 6, 3)
    assert rows[0].dept == "2"
    assert rows[0].case_number == "CV68039"
    assert rows[0].page_start == 1
    assert "Case Management Conference" in rows[0].motion_type
    assert rows[1].case_number == "CVL66996"
    assert rows[1].outcome == "denied"


def test_missing_timestamp_uses_blank_line_before_narrative_body():
    pdf = _pdf([[
        "Consolidated Calendar",
        "Department 2 June 3, 2026 8:30 am Date Filed DA Case #",
        "CV68350 04/22/2026 4 Edward Bolitho vs. Roger Perkins",
        "Attorney: Gary Dambacher Edward Bolitho",
        "Petition Hearing - Other",
        "Cancel and Release Mechanics Lien",
        "04/22/2026 Petition File Tracking",
        "04/24/2026 High Density",
        "",
        "This is a special proceeding to release a mechanics lien.",
        "The petition cannot be summarily granted.",
    ]])

    rows = parse(pdf, "https://www.tuolumne.courts.ca.gov/system/files/tentative-rulings/tr_d2_06032026.pdf")

    assert len(rows) == 1
    assert rows[0].motion_type == "Petition Hearing - Other / Cancel and Release Mechanics Lien"
    assert rows[0].outcome_text.startswith("This is a special proceeding")
