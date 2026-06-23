from datetime import date
from pathlib import Path

import pytest

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
        "The body references December 6, 2023, but that is not the hearing date.",
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


def test_case_management_title_after_bare_case_number():
    pdf = _pdf([[
        "June 3, 2026",
        "1:30 P.M. Civil Case Management",
        "19PA44397",
        "EVANS v ANDERSON",
        "Appearances are required to address case management.",
    ]])

    rows = parse(pdf, "https://www.calaveras.courts.ca.gov/system/files/general/06032026-cmc.pdf")

    assert len(rows) == 1
    assert rows[0].case_number == "19PA44397"
    assert rows[0].case_title == "EVANS v ANDERSON"
    assert rows[0].motion_type == "Case Management Conference"


def test_short_compact_url_date_archive_law_motion():
    source = Path("archive/calaveras/8c/8cd0106ece690d4dbabd12b1883694ee05d7f1e325ce9e664f1f4cd783c7ff7b.pdf")
    if not source.exists():
        pytest.skip("full Calaveras archive source is not materialized")
    rows = parse(
        source.read_bytes(),
        "https://www.calaveras.courts.ca.gov/system/files/tentative-ruling/81823-law-and-motion.pdf",
        source_sha256="8cd0106ece690d4dbabd12b1883694ee05d7f1e325ce9e664f1f4cd783c7ff7b",
        division_hint="Civil Law and Motion",
    )

    assert len(rows) >= 4
    assert rows[0].hearing_date == date(2023, 8, 18)
    assert rows[0].case_number == "22CV46287"
    assert rows[0].motion_type.startswith("DEBTOR")


def test_legacy_bare_case_number_archive_law_motion():
    source = Path("archive/calaveras/e4/e456daeeee71d2e25e13febb50a55711f159e1402e7c56db03a33efdfbd0b7f7.pdf")
    if not source.exists():
        pytest.skip("full Calaveras archive source is not materialized")
    rows = parse(
        source.read_bytes(),
        "https://www.calaveras.courts.ca.gov/system/files/2-24-23-additional-tentative-oex.pdf",
        source_sha256="e456daeeee71d2e25e13febb50a55711f159e1402e7c56db03a33efdfbd0b7f7",
        division_hint="Civil Law and Motion",
    )

    assert len(rows) == 1
    assert rows[0].case_number == "CV34353"
    assert rows[0].case_title.startswith("GOLD STRIKE")


def test_legacy_time_row_civil_calendar_archive():
    source = Path("archive/calaveras/03/036704a326e77c1f7dc771f664489417bfb2be16823b3b861036dedbb07fa9db.pdf")
    if not source.exists():
        pytest.skip("full Calaveras archive source is not materialized")
    rows = parse(
        source.read_bytes(),
        "https://www.calaveras.courts.ca.gov/system/files/tentative-ruling/6-18-2021-civil-lm-tentative-rulings.pdf",
        source_sha256="036704a326e77c1f7dc771f664489417bfb2be16823b3b861036dedbb07fa9db",
        division_hint="Civil Law and Motion",
    )

    assert len(rows) == 1
    assert rows[0].hearing_date == date(2021, 6, 18)
    assert rows[0].case_number == "18CV43474"
    assert rows[0].case_title.startswith("City of Angels Camp")
    assert rows[0].motion_type.startswith("Motion by Petnr")


def test_legacy_time_row_probate_calendar_archive():
    source = Path("archive/calaveras/13/1363e2f66965aefee6906eeddd36229c777e269d49f3212621aecd77166a4398.pdf")
    if not source.exists():
        pytest.skip("full Calaveras archive source is not materialized")
    rows = parse(
        source.read_bytes(),
        "https://www.calaveras.courts.ca.gov/system/files/tentative-ruling/7-23-2021-probate-law-motion-tentative-rulings.pdf",
        source_sha256="1363e2f66965aefee6906eeddd36229c777e269d49f3212621aecd77166a4398",
        division_hint="Probate Law and Motion",
    )

    assert len(rows) == 1
    assert rows[0].hearing_date == date(2021, 7, 23)
    assert rows[0].division == "Probate Law and Motion"
    assert rows[0].case_number == "20PR8284"
    assert rows[0].case_title.startswith("Griffin, Carol")


def test_single_digit_compact_url_date_archive_law_motion():
    source = Path("archive/calaveras/10/1095fd13155d10c04f7a8fee5a9e999bff08505c40e51f16a4983372fcd10588.pdf")
    if not source.exists():
        pytest.skip("full Calaveras archive source is not materialized")
    rows = parse(
        source.read_bytes(),
        "https://www.calaveras.courts.ca.gov/system/files/tentative-ruling/772023-lm-tentative-rulings2.pdf",
        source_sha256="1095fd13155d10c04f7a8fee5a9e999bff08505c40e51f16a4983372fcd10588",
        division_hint="Civil Law and Motion",
    )

    assert len(rows) == 5
    assert rows[0].hearing_date == date(2023, 7, 7)
    assert rows[0].case_number == "21CF13559"
    assert rows[0].case_title.startswith("In The Matter of $4,940.00")


def test_case_no_label_archive_law_motion_packet():
    source = Path("archive/calaveras/c1/c10833d06a8c43495b13d4346f120d431b9e59836423e3f2457bb55a8f56178e.pdf")
    if not source.exists():
        pytest.skip("full Calaveras archive source is not materialized")
    rows = parse(
        source.read_bytes(),
        "https://www.calaveras.courts.ca.gov/system/files/tentative-ruling/10-6-2023-clmc_0.pdf",
        source_sha256="c10833d06a8c43495b13d4346f120d431b9e59836423e3f2457bb55a8f56178e",
        division_hint="Civil Law and Motion",
    )

    assert len(rows) == 4
    assert rows[0].hearing_date == date(2023, 10, 6)
    assert rows[0].case_number == "23CV46786"
    assert rows[0].case_title == "MICHAEL HATFIELD v. UNION PUBLIC UTILITY DISTRICT"


def test_legacy_time_row_without_am_pm_archive():
    source = Path("archive/calaveras/d8/d8b13d7036c552874a5730600a06940855a90b44989563f2fb4213d2b860d50a.pdf")
    if not source.exists():
        pytest.skip("full Calaveras archive source is not materialized")
    rows = parse(
        source.read_bytes(),
        "https://www.calaveras.courts.ca.gov/system/files/tentative-ruling/7-30-2021-civil-tentative-ruling.pdf",
        source_sha256="d8b13d7036c552874a5730600a06940855a90b44989563f2fb4213d2b860d50a",
        division_hint="Civil Law and Motion",
    )

    assert len(rows) == 1
    assert rows[0].hearing_date == date(2021, 7, 30)
    assert rows[0].case_number == "14CV40119"
