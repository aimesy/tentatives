from datetime import date

from counties.calaveras.scraper import parse


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


def test_parse_calaveras_case_management_calendar():
    pdf = _pdf([[
        "June 3, 2026",
        "1:30 P.M. Civil Case Management",
        "22CV46467 DAVID ZAMORA,",
        "TRUSTEE, ON BEHALF OF ESTATE OF GUS Y. ZAMORA",
        "Appearances are required to address attorney representation.",
        "23CV47105 PNC BANK, NATIONAL ASSOCIATION v STOCK",
        "The case has settled. No Request for Dismissal was filed. The matter is ordered dismissed.",
        "2:00 P.M. Family Law Case Management",
        "23FL46763 CRAGGS v",
        "CRAGGS",
        "There is proper service of the Petition and Summons.",
    ]])

    rows = parse(pdf, "https://www.calaveras.courts.ca.gov/system/files/general/06032026-cmc.pdf")

    assert len(rows) == 3
    assert rows[0].hearing_date == date(2026, 6, 3)
    assert rows[0].division == "Civil Case Management"
    assert rows[0].outcome == "appearance_required"
    assert rows[1].outcome == "denied"
    assert rows[2].division == "Family Law Case Management"


def test_parse_calaveras_law_motion_uses_url_date():
    pdf = _pdf([[
        "SANCHEZ v SENDERS MARKET, INC., et al",
        "24CV47302",
        "DEFENDANT ROTH INDUSTRIES MOTION TO COMPEL RESPONSES",
        "This is a breach of contract claim.",
        "Accordingly, the motion is DENIED, without prejudice.",
    ]])

    rows = parse(
        pdf,
        "https://www.calaveras.courts.ca.gov/system/files/general/6-5-26-lm-tentatives.pdf",
        division_hint="Civil Law and Motion",
    )

    assert len(rows) == 1
    assert rows[0].hearing_date == date(2026, 6, 5)
    assert rows[0].case_number == "24CV47302"
    assert rows[0].case_title == "SANCHEZ v SENDERS MARKET, INC., et al"
    assert rows[0].motion_type == "DEFENDANT ROTH INDUSTRIES MOTION TO COMPEL RESPONSES"
    assert rows[0].outcome == "denied"
