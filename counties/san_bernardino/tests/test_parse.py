from datetime import date

from counties.san_bernardino.scraper import parse


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


def test_parse_san_bernardino_formal_packet_with_url_date():
    pdf = _pdf([[
        "TENTATIVE RULING FOR CIVSB2523628",
        "Department S24 - Judge Carlos M. Cabrera",
        "Capers v. City of Fontana, et al",
        "Motion: Demurrer and Motion to Strike",
        "Movant: City of Fontana",
        "RELEVANT FACTUAL AND PROCEDURAL BACKGROUND",
        "RULING",
        "Defendant's Demurrer is SUSTAINED WITH LEAVE TO AMEND.",
        "Motion to Strike is deemed MOOT.",
    ]])

    rows = parse(pdf, "https://old.sb-court.org/DesktopModules/TentativeRulings/TentativeRulings/CVS24060426.pdf")

    assert len(rows) == 1
    assert rows[0].hearing_date == date(2026, 6, 4)
    assert rows[0].dept == "S24"
    assert rows[0].case_number == "CIVSB2523628"
    assert rows[0].case_title == "Capers v. City of Fontana, et al"
    assert rows[0].outcome == "granted"


def test_parse_san_bernardino_numbered_list():
    pdf = _pdf([[
        "Tentative Rulings",
        "June 3, 2026",
        "Department S-17",
        "13. Espinosa v. FCA US, LLC, et al, Case No. CIVSB2436711",
        "Defendant FCA's Motion to Compel Deposition of Plaintiff",
        "6/3/26, 9:00 a.m., S-17",
        "Tentative Rulings",
        "The Court would GRANT sanctions in the amount of $960.",
        "*** *** ***",
        "14. Wylie v. New Rez LLC, et al, Case No. CIVSB2513110",
        "Defendant's Demurrer to Second Amended Complaint",
        "6/3/26, 9:00 a.m., Dept. S-17",
        "The Court would SUSTAIN this unopposed demurrer.",
    ]])

    rows = parse(pdf, "https://old.sb-court.org/DesktopModules/TentativeRulings/TentativeRulings/CVS17060326.pdf")

    assert len(rows) == 2
    assert rows[0].hearing_date == date(2026, 6, 3)
    assert rows[0].dept == "S17"
    assert rows[0].outcome == "granted"
    assert rows[1].case_number == "CIVSB2513110"
    assert rows[1].motion_type.startswith("Defendant's Demurrer")
