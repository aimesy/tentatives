from datetime import date

from counties.merced.scraper import parse


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


def test_parse_merced_calendar_rows_and_sections():
    pdf = _pdf([[
        "SUPERIOR COURT OF CALIFORNIA",
        "Monday, June 1st, 2026",
        "Civil Law and Motion Tentative Rulings",
        "Courtroom 8",
        "Case No. Title / Description",
        "22CV-03950 Dignity Health vs Premier Surgical Group Corporation, et al.",
        "Order Show Cause re: Status of Corporation",
        "Appearance required.",
        "23CV-02663 Jocelyn Bartlett, et al. vs AVN Farms, LLC, et al.",
        "Motion to be Relieved as Counsel",
        "The motion to be relieved as counsel is DENIED WITHOUT PREJUDICE.",
    ]])

    rows = parse(pdf, "https://www.merced.courts.ca.gov/system/files/tentative-rulings/tr-monday.pdf")

    assert len(rows) == 2
    assert rows[0].hearing_date == date(2026, 6, 1)
    assert rows[0].dept == "8"
    assert rows[0].division == "Civil Law and Motion"
    assert rows[0].outcome == "appearance_required"
    assert rows[0].motion_type == "Order Show Cause re: Status of Corporation"
    assert rows[1].case_number == "23CV-02663"
    assert rows[1].outcome == "denied"


def test_app_case_suffixes_are_anchors_but_body_related_cases_are_not():
    pdf = _pdf([[
        "SUPERIOR COURT OF CALIFORNIA",
        "Monday, June 1st, 2026",
        "Civil Law and Motion Tentative Rulings",
        "Courtroom 8",
        "22CV-03146-APP Mendez vs. County of Merced",
        "Motion for Writ",
        "The matter is continued to July 6, 2026.",
        "21CR-06339 and #22CR-03670.",
        "This line refers to related criminal matters in the same body.",
    ]])

    rows = parse(pdf, "https://www.merced.courts.ca.gov/system/files/tentative-rulings/tr-monday.pdf")

    assert len(rows) == 1
    assert rows[0].case_number == "22CV-03146-APP"
    assert "21CR-06339" in rows[0].full_text
