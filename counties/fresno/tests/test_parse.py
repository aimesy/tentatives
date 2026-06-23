from datetime import date

from counties.fresno.scraper import parse


def _pdf(lines_by_page: list[list[str]]) -> bytes:
    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    kids: list[str] = []
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    page_objects: list[tuple[int, int, list[str]]] = []
    next_obj = 4
    for lines in lines_by_page:
        page_obj = next_obj
        content_obj = next_obj + 1
        next_obj += 2
        kids.append(f"{page_obj} 0 R")
        page_objects.append((page_obj, content_obj, lines))
    objects.append(f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for _page_obj, content_obj, lines in page_objects:
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


def test_parse_fresno_formal_and_cover_continued_rows():
    pdf = _pdf([
        [
            "Tentative Rulings for June 4, 2026",
            "Department 403",
            "The court has continued the following cases.",
            "24CECG04001 Raymond Ghermezian APLC v. Comprehensive Pain Management Center, Inc. is continued to Thursday, July 16, 2026 at 3:30 p.m. in Department 502",
            "________________________________________________________________",
        ],
        [
            "(34)",
            "Tentative Ruling",
            "Re: Julia DeSantiago DeOrtiz v. Monu (Surname Unknown), et al.",
            "Superior Court Case No. 25CECG02992",
            "Hearing Date: June 4, 2026 (Dept. 403)",
            "Motion: by Insource Employment Solutions, Inc. for Leave to Intervene",
            "Tentative Ruling:",
            "To grant. Insource Employment Solutions, Inc. may intervene.",
            "Tentative Ruling",
            "Issued By: lmg on 6-3-26.",
        ],
    ])

    rows = parse(pdf, "https://www.fresno.courts.ca.gov/system/files/tentative-rulings/06-04-26-dept-403.pdf")

    assert [r.case_number for r in rows] == ["24CECG04001", "25CECG02992"]
    assert rows[0].outcome == "continued"
    assert rows[0].continued_to == date(2026, 7, 16)
    assert rows[1].hearing_date == date(2026, 6, 4)
    assert rows[1].dept == "403"
    assert rows[1].outcome == "granted"
    assert rows[1].motion_type.startswith("by Insource")


def test_cover_continuance_does_not_cross_from_no_tentative_case():
    pdf = _pdf([[
        "Tentative Rulings for June 3, 2026",
        "Department 502",
        "There are no tentative rulings for the following matters.",
        "24CECG03435 Example Plaintiff v. Example Defendant",
        "25CECG03846 Another Plaintiff v. Another Defendant is continued to Friday, July 10, 2026 at 3:30 p.m. in Department 502",
        "________________________________________________________________",
    ]])

    rows = parse(pdf, "https://www.fresno.courts.ca.gov/system/files/tentative-rulings/06-03-26-dept-502.pdf")

    assert [r.case_number for r in rows] == ["25CECG03846"]
    assert rows[0].outcome == "continued"
    assert rows[0].continued_to == date(2026, 7, 10)


def test_motion_type_strips_oral_argument_boilerplate():
    pdf = _pdf([[
        "Tentative Rulings for June 4, 2026",
        "Department 403",
        "Tentative Ruling",
        "Re: Sample Plaintiff v. Sample Defendant",
        "Superior Court Case No. 24CECG05010",
        "Hearing Date: June 4, 2026 (Dept. 403)",
        "Motion: by Defendant for Summary Judgment",
        "If oral argument is timely requested, appearances are required.",
        "Tentative Ruling:",
        "To deny the motion.",
    ]])

    rows = parse(pdf, "https://www.fresno.courts.ca.gov/system/files/tentative-rulings/06-04-26-dept-403.pdf")

    assert len(rows) == 1
    assert rows[0].motion_type == "by Defendant for Summary Judgment"
