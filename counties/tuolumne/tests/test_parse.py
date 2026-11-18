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
    assert rows[0].body_text.startswith("This is a petition")
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
    assert rows[0].body_text.startswith("This is a special proceeding")


def _header(day: str) -> list[str]:
    return [
        "SUPERIOR COURT OF CALIFORNIA",
        "COUNTY OF TUOLUMNE",
        f"TENTATIVE RULINGS FOR {day}",
        "DEPT. 2",
        "JUDICIAL OFFICER: SARAH J. CARRILLO",
        "The Tentative Ruling will become the ruling of the court if the court has not directed oral",
        "argument by its Tentative Ruling, and notice of intent to appear has not been given.",
    ]


def test_parse_tuolumne_stacked_labels_layout_dedupes_repeated_page():
    first = _header("NOVEMBER 13, 2026") + [
        "Case No.:", "Case Title:", "Case Type:", "Hearing Type:",
        "CV67962",
        "Megan Gallegos v. Peter Edward Bippart, M.D.",
        "Medical Malpractice",
        "Hospital's Motion to Compel Discovery Responses",
        "This medical malpractice case arises from a medical procedure.",
        "11Pagc",
    ]
    second = [
        "1 [Page",
        "Hospital's Motion to Compel is GRANTED.",
        "Case No.:", "Case Title:", "Case Type:", "Hearing Type:",
        "CV68690",
        "Jonathan Avrett v. Kevin P Cobden",
        "Breach of Contract - Real Property",
        "Demurrer to First Amended Complaint and Motion for Leave to File",
        "Cross-Complaint",
        "This case arises from a real property dispute.",
        "Plaintiff's Demurrer is OVERRULED.",
    ]
    rulings = parse(_pdf([first, first, second]), "https://example.test/tr-d2-11132026.pdf")
    assert [r.case_number for r in rulings] == ["CV67962", "CV68690"]
    assert {(r.hearing_date, r.dept) for r in rulings} == {(date(2026, 11, 13), "2")}
    assert rulings[0].motion_type == "Hospital's Motion to Compel Discovery Responses"
    assert "GRANTED" in rulings[0].body_text and "Pag" not in rulings[0].body_text
    assert rulings[1].motion_type.endswith("Motion for Leave to File Cross-Complaint")
    assert rulings[1].page_start == 3


def test_parse_tuolumne_inline_labels_and_numbered_layouts():
    inline = _pdf([[
        "SUPERIOR COURT OF CALIFORNIA",
        "COUNTY OF TUOLUMNE",
        "TENTATIVE RULINGS- September 8, 2026",
        "HEARING DATE: September 9, 2026",
        "DEPT.: Two (2)",
        "JUDICIAL OFFICER: Honorable Sarah J. Carrillo",
        "__________________________________",
        "Case No.: CV68545",
        "Case Title: Mark Rose vs. FCA US et al",
        "Case Type: Breach of Contract Warranty",
        "Hearing Type: Defendant FCA's Demurrer to Plaintiff's First Amended Complaint",
        "Background",
        "The demurrer is SUSTAINED.",
    ]])
    [ruling] = parse(inline, "https://example.test/tr_d2_09092026.pdf")
    assert (ruling.case_number, ruling.hearing_date, ruling.dept) == ("CV68545", date(2026, 9, 9), "2")
    assert ruling.case_title == "Mark Rose vs. FCA US et al"

    numbered = _pdf([[
        "CIVIL TENTATIVE RULINGS DEPT. 5 November 4, 2026",
        "Debra Medina v. City of Sonora et al. (CV68817)",
        "This matter is before the Court on Petitioner's petition. The Court intends to grant it.",
        "2. Barclays Bank Delaware v. Yanine Lugo (CVL66893)",
        "This matter is before the Court on Plaintiff's motion.",
    ]])
    rulings = parse(numbered, "https://example.test/tr-d5-11042026.pdf")
    assert [(r.case_number, r.dept) for r in rulings] == [("CV68817", "5"), ("CVL66893", "5")]
    assert rulings[1].case_title == "Barclays Bank Delaware v. Yanine Lugo"

    number_first = _pdf([[
        "Dept. 2",
        "Civil Law and Motion Tentative Rulings for Friday, August 14, 2026, at 8:30 a.m.",
        "1. CV66705 Pagni v. City of Sonora et al",
        "Hearing on: Motions for Leave to File Third Amended Petition and",
        "Augment the Administrative Record",
        "Moving Party: Petitioner",
        "Tentative Ruling: n/a",
    ]])
    [ruling] = parse(number_first, "https://example.test/tr_d2_08142026.pdf")
    assert ruling.hearing_date == date(2026, 8, 14)
    assert ruling.motion_type == "Motions for Leave to File Third Amended Petition and Augment the Administrative Record"
