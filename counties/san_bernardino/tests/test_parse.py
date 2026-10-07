from datetime import date
from pathlib import Path

import pytest

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


def test_numbered_list_without_case_no_label_keeps_title_and_motion_separate():
    source = Path("archive/san-bernardino/30/301c89b59908eb58e72b1d554e051c28618ec6a8f1122cad7b3505fb6bd4e761.pdf")
    if not source.exists():
        pytest.skip("full San Bernardino archive source is not materialized")
    rows = parse(source.read_bytes(), "https://old.sb-court.org/DesktopModules/TentativeRulings/TentativeRulings/CVS17052626.pdf")
    by_case = {row.case_number: row for row in rows}

    assert "CIVSB2431410" in by_case
    assert by_case["CIVSB2431410"].case_title == "Balouch, et al, v. Chowdhury, et al"
    assert by_case["CIVSB2431410"].motion_type.startswith("Gomez Law")
    assert "CIVSB2128630" in by_case


def test_formal_packet_with_title_after_case_number():
    source = Path("archive/san-bernardino/04/04d2cccaf97657ef095f9cace7ffba32619244725ea16df9e6bfb2ca67f06ffa.pdf")
    if not source.exists():
        pytest.skip("full San Bernardino archive source is not materialized")
    rows = parse(source.read_bytes(), "https://old.sb-court.org/DesktopModules/TentativeRulings/TentativeRulings/CVS37060126.pdf")

    assert len(rows) == 1
    assert rows[0].case_number == "CIVSB2224020"
    assert rows[0].case_title == "Ruiz vs. Tayrien"
    assert rows[0].motion_type.startswith("Defendants Steven and Maria")


def test_numbered_case_number_table_packet_splits_each_row():
    source = Path("archive/san-bernardino/5b/5bd5f8e26f6eb8a8852cf863dc5c51bbbc058e6744f0ad24285d60bfebddae8f.pdf")
    if not source.exists():
        pytest.skip("full San Bernardino archive source is not materialized")
    rows = parse(source.read_bytes(), "https://old.sb-court.org/DesktopModules/TentativeRulings/TentativeRulings/CVR17052926.pdf")
    by_case = {row.case_number: row for row in rows}

    assert {"CIVRS2508307", "CIVSB2510514", "CIVSB2503117"}.issubset(by_case)
    assert by_case["CIVSB2510514"].case_title.startswith("Efren Angel Marquez")
    assert by_case["CIVSB2503117"].motion_type.startswith("Defendant One Up")


def test_formal_multi_packet_splits_repeated_case_blocks():
    source = Path("archive/san-bernardino/16/1619535da3d277b0f8be74d005f45cb2c15585cc556d30bbcf66b22cf4649e43.pdf")
    if not source.exists():
        pytest.skip("full San Bernardino archive source is not materialized")
    rows = parse(source.read_bytes(), "https://old.sb-court.org/DesktopModules/TentativeRulings/TentativeRulings/CVS14051526.pdf")
    by_case = {row.case_number: row for row in rows}

    assert {"CIVSB2426802", "CIVSB2508090"}.issubset(by_case)
    assert by_case["CIVSB2426802"].case_title == "First Carrier v. IDX West et al"
    assert by_case["CIVSB2508090"].case_title == "Conrad vs. GM"


def test_formal_companion_caption_uses_caption_above_case_number_line():
    source = Path("archive/san-bernardino/7e/7ebed36fb7bd867b7e150dbaa1232ba23152dfadc43d48415d7225ba9f25220b.pdf")
    if not source.exists():
        pytest.skip("full San Bernardino archive source is not materialized")
    rows = parse(source.read_bytes(), "https://old.sb-court.org/DesktopModules/TentativeRulings/TentativeRulings/CVS29060226.pdf")

    assert len(rows) == 1
    assert rows[0].case_number == "CIVSB2303245"
    assert rows[0].case_title.startswith("CALIFORNIA ARROYO FUND, INC., et al. v. CITY OF HESPERIA")
    assert rows[0].motion_type == "Motions for Judgment on the Pleadings (x 4)"


def test_formal_packet_accepts_spaced_case_number():
    source = Path("archive/san-bernardino/31/31ee76b6a59460048611119361a32d222b7508fcb59cd1fe107e780ceec1f0a3.pdf")
    if not source.exists():
        pytest.skip("full San Bernardino archive source is not materialized")
    rows = parse(source.read_bytes(), "https://old.sb-court.org/DesktopModules/TentativeRulings/TentativeRulings/CVS29042826.pdf")

    assert len(rows) == 1
    assert rows[0].case_number == "CIVSB2438559"
    assert rows[0].motion_type.startswith("1. Demurrer")


def test_formal_packet_accepts_llt_unlawful_detainer_case_number():
    source = Path("archive/san-bernardino/88/881e5b209963dc1e0fbb8e4855b67df0e52ea83b45e38b4e797998afc581b7af.pdf")
    if not source.exists():
        pytest.skip("full San Bernardino archive source is not materialized")
    rows = parse(source.read_bytes(), "https://old.sb-court.org/DesktopModules/TentativeRulings/TentativeRulings/CVS22052826.pdf")

    assert len(rows) == 1
    assert rows[0].case_number == "LLTSB2500117"
    assert rows[0].case_title.startswith("E STREET INVESTMENTS")
