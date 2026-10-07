from pathlib import Path

import pytest

from counties.butte import scraper as butte
from counties.imperial import scraper as imperial
from counties.los_angeles import scraper as los_angeles
from counties.san_benito import scraper as san_benito
from counties.san_mateo import scraper as san_mateo
from counties.santa_barbara import scraper as santa_barbara
from counties.sierra import scraper as sierra
from counties.stanislaus import scraper as stanislaus
from counties.sonoma import scraper as sonoma
from counties.tulare import scraper as tulare
from counties.ventura import scraper as ventura
from counties.yolo import scraper as yolo


def test_butte_discovers_system_tentative_pdf():
    refs = butte.discover_live(
        '<a href="/system/files/tentative-rulings/civil-tentative-rulings.pdf">Civil Tentative Rulings</a>'
    )

    assert refs[0].filename == "civil-tentative-rulings.pdf"
    assert refs[0].division_hint == "Civil Law and Motion"


def test_butte_probate_rows_keep_page_local_spans():
    sha = "627fde287a4b045887b5215148238ded5dff89541c1b9fdf0991b5c3da9936a5"
    path = Path("archive/butte") / sha[:2] / f"{sha}.pdf"
    if not path.exists():
        pytest.skip("Butte archive fixture not present in this checkout")

    rows = butte.parse(
        path.read_bytes(),
        "https://www.butte.courts.ca.gov/system/files/tentative-rulings/2026-06-23-current-probate-tentative-rulings-judge-mosbarger_san.pdf",
        source_sha256=sha,
    )

    probate_rows = [row for row in rows if row.style == "butte-probate-table"]
    assert len(probate_rows) > 10
    assert len({row.page_start for row in probate_rows}) > 1
    assert max(row.page_end - row.page_start for row in probate_rows) <= 1


def test_butte_probate_legacy_pr_rows_are_separate():
    sha = "03d9173fe39b51acf4c34e424ee620773bc185ed98a6d50eb20430797ccf3b1e"
    path = Path("archive/butte") / sha[:2] / f"{sha}.pdf"
    if not path.exists():
        pytest.skip("Butte archive fixture not present in this checkout")

    rows = butte.parse(
        path.read_bytes(),
        "https://www.butte.courts.ca.gov/system/files/tentative-rulings/2026-06-09-current-probate-tentative-rulings-ada5_0.pdf",
        source_sha256=sha,
    )
    by_case = {row.case_number: row for row in rows}

    assert "PR-25424" in by_case
    assert "PR-34929" in by_case
    assert "PR-37326" in by_case
    assert "PR-25424" not in by_case["26PR00218"].full_text


def test_tulare_probate_table_keeps_status_type_and_page_boundary():
    sha = "6e08bc6bf9a8179cb896e9a411ecc944184d83c388e2d4f1f8b82373be05499f"
    path = Path("archive/tulare") / sha[:2] / f"{sha}.pdf"
    if not path.exists():
        pytest.skip("Tulare archive fixture not present in this checkout")

    rows = tulare.parse(
        path.read_bytes(),
        "https://www.tulare.courts.ca.gov/system/files/tentative-rulings/probate-tentative-rulings-visalia.pdf",
        source_sha256=sha,
    )
    by_case = {row.case_number: row for row in rows}

    assert by_case["VPR053745"].page_end == 1
    assert "Case Number Case Name" not in by_case["VPR053745"].full_text
    assert by_case["VPR053745"].motion_type == "Appoint Conservator"
    assert by_case["VPR053745"].outcome == "appearance_required"


def test_san_benito_trims_end_of_tentatives_footer():
    sha = "0856e1c0a2a0778c70cdfdda71adb06b06445555bed44285ed91746d9d51fd50"
    path = Path("archive/san-benito") / sha[:2] / f"{sha}.pdf"
    if not path.exists():
        pytest.skip("San Benito archive fixture not present in this checkout")

    rows = san_benito.parse(
        path.read_bytes(),
        "https://www.sanbenito.courts.ca.gov/system/files/tentative-rulings/probate-tentative-rulings.pdf",
        source_sha256=sha,
    )

    row = next(r for r in rows if r.case_number == "PR-26-00039")
    assert "END OF TENTATIVE" not in row.full_text
    assert "END OF TENTATIVE" not in row.body_text


def test_sonoma_trims_end_of_tentatives_footer():
    sha = "8214e89baef32190f05475b91f4afcbbdc2c056a8f7dd2c4a93c816996f0da6b"
    path = Path("archive/sonoma/pages") / sha[:2] / f"{sha}.html"
    if not path.exists():
        pytest.skip("Sonoma archive fixture not present in this checkout")

    rows = sonoma.parse_page_capture(
        path.read_text(encoding="utf-8"),
        {
            "source_sha256": sha,
            "source_url": "https://sonoma.courts.ca.gov/online-services/tentative-rulings/probate-tentative-rulings/guardianship-tentative-rulings",
        },
    )

    row = next(r for r in rows if r.case_number == "SPR095654")
    assert "End of Tentative Rulings" not in row.full_text
    assert "End of Tentative Rulings" not in row.body_text
    assert "Guardianship CMC Tentative Rulings" not in row.full_text


def test_imperial_parses_current_single_ruling_pdf():
    sha = "ea52a1ef685025a3f4a3ebc759ca69b1e57073199991ae4460915caa5e6b9b06"
    path = Path("archive/imperial") / sha[:2] / f"{sha}.pdf"
    if not path.exists():
        pytest.skip("Imperial archive fixture not present in this checkout")

    rows = imperial.parse(
        path.read_bytes(),
        "https://www.imperial.courts.ca.gov/system/files/tentative-rulings/imperial-demurrer-mtn-strike-mtn-dismiss-ecu003561.pdf",
        source_sha256=sha,
    )

    assert len(rows) == 3
    assert {row.case_number for row in rows} == {"ECUO03561"}
    assert {row.hearing_date.isoformat() for row in rows} == {"2024-11-07"}
    assert [row.motion_type for row in rows] == ["Demurrer", "Motion to Strike", "Motion for Entry of Default"]
    assert rows[0].outcome == "granted"
    assert rows[2].outcome == "denied"


def test_sierra_splits_multiple_motion_rulings_in_one_case():
    sha = "e32d1d6945d3cd8af284aae36c331ad1377e94ef0357c4dd329f77942224977c"
    path = Path("archive/sierra") / sha[:2] / f"{sha}.pdf"
    if not path.exists():
        pytest.skip("Sierra archive fixture not present in this checkout")

    rows = sierra.parse(
        path.read_bytes(),
        "https://drive.google.com/uc?export=download&id=17RJ4PEhce-1OvPpZY8yRs01k-wAULiTN",
        source_sha256=sha,
    )

    assert len(rows) == 2
    assert {row.case_number for row in rows} == {"26CU0020"}
    assert rows[0].motion_type.startswith("Plaintiff Steven Nightingale")
    assert rows[0].outcome == "granted"
    assert rows[1].motion_type.startswith("Defendant Charles Durrett")
    assert rows[1].outcome == "off_calendar"


def test_sierra_parses_ocr_guardianship_rulings():
    fixtures = [
        (
            "7cff558939630a3e9c3c8633af798045f0a1b196728df1618345c9c3de9b7bd1",
            "PR2092",
            "Mason Robert Pasquetti",
            "2026-05-20",
        ),
        (
            "04bd3c9835be41a3924647acca7bdaf948d47176c454602ea2c3e5021b951c72",
            "PR2093",
            "Celeste and Claire Quintana",
            "2026-06-24",
        ),
    ]
    for sha, case_number, case_title, hearing_date in fixtures:
        path = Path("archive/sierra/ocr") / sha[:2] / f"{sha}.pdf"
        if not path.exists():
            pytest.skip("Sierra OCR archive fixture not present in this checkout")

        rows = sierra.parse(
            path.read_bytes(),
            "https://drive.google.com/uc?export=download&id=16hoZfiSfS7nnckxmR45XvN_oxVHUPVBM",
            source_sha256=sha,
            division_hint="Guardianships",
        )

        assert len(rows) == 1
        row = rows[0]
        assert row.case_number == case_number
        assert row.case_title == case_title
        assert row.hearing_date.isoformat() == hearing_date
        assert row.division == "Guardianships"
        assert row.motion_type == "Tentative Guardianship Ruling"
        assert row.style == "sierra-guardianship"
        assert "NO APPEARANCE REQUIRED" in row.body_text
        assert row.outcome != "appearance_required"


def test_stanislaus_prefers_explicit_page_date_over_reporter_citation():
    html = """
    <main>
    Date: 6/24/2026
    Department #21
    CV-24-001234 - Example Plaintiff v. Example Defendant - Motion to Compel - The court cites Smith v. Jones (2012) 204 Cal.App.4th 1. The motion is denied.
    </main>
    """

    rows = stanislaus.parse_page_capture(
        html,
        {
            "source_sha256": "stanislaus-date-fixture",
            "source_url": "https://www.stanislaus.courts.ca.gov/online-services/tentative-rulings/civil-tentative-rulings",
        },
    )

    assert len(rows) == 1
    assert rows[0].hearing_date.isoformat() == "2026-06-24"


def test_san_mateo_accepts_web_sanmateocourt_pdf():
    refs = san_mateo.discover_live(
        '<a href="https://web.sanmateocourt.org/tentative/tr-monday.pdf">Civil Tentative Monday</a>',
        page_url="https://sanmateo.courts.ca.gov/online-services/tentative-rulings/civil-law-motion-tentative-rulings",
    )

    assert refs[0].url.startswith("https://web.sanmateocourt.org/")
    assert refs[0].division_hint == "Civil Law and Motion"


def test_santa_barbara_discovers_detail_page_refs():
    pages = santa_barbara.discover_live_pages(
        '<a href="/tentative-ruling/24CV12345">Ruling detail</a>',
        page_url="https://www.santabarbara.courts.ca.gov/tentative-rulings",
    )

    assert pages[0].url.endswith("/tentative-ruling/24CV12345")
    assert pages[0].page_kind == "tentative_ruling_detail"


def test_los_angeles_builds_post_page_refs():
    html = """
    <input type="hidden" name="__VIEWSTATE" value="vs" />
    <input type="hidden" name="__VIEWSTATEGENERATOR" value="vg" />
    <input type="hidden" name="__EVENTVALIDATION" value="ev" />
    <option value="LAM,307,06/24/2026">(Stanley Mosk Courthouse: Dept. 307) June 24, 2026</option>
    """

    class _Session:
        def get(self, url, timeout=60):
            class _Response:
                text = html

                def raise_for_status(self):
                    pass

            return _Response()

    refs = los_angeles.discover_live_page_extra(session=_Session())

    assert refs[0].method == "POST"
    assert "dept_date=LAM%2C307%2C06%2F24%2F2026" in refs[0].source_url
    assert refs[0].data[los_angeles.SELECT_NAME] == "LAM,307,06/24/2026"


def test_ventura_extracts_token_and_viewfile_refs():
    assert ventura._token('<input name="__RequestVerificationToken" type="hidden" value="tok" />') == "tok"
    matches = list(ventura.VIEW_FILE_RE.finditer('<a href="/CaseInquiry/ViewFile/123">PDF</a>'))
    assert matches[0].group("id") == "123"


def test_yolo_discovers_escaped_fullcalendar_document_paths():
    html = r'''"url\u0022:\u0022\\\/document\\\/tentative-rulings-769\u0022'''

    refs = yolo.discover_live_pages(
        html,
        page_url="https://www.yolo.courts.ca.gov/online-services/tentative-rulings-calendar",
    )

    assert len(refs) == 1
    assert refs[0].url == "https://www.yolo.courts.ca.gov/document/tentative-rulings-769"
    assert refs[0].page_kind == "document_page"


def test_yolo_parses_law_motion_pdf():
    sha = "006afd6e58ab56e0b0fddaa16d27afca89ad3226732a2d3428dcfd3f595d0176"
    path = Path("archive/yolo") / sha[:2] / f"{sha}.pdf"
    if not path.exists():
        pytest.skip("Yolo archive fixture not present in this checkout")

    rows = yolo.parse(
        path.read_bytes(),
        "https://www.yolo.courts.ca.gov/sites/default/files/yolo/default/2026-06/ATO-TEN-260612.pdf",
        source_sha256=sha,
    )

    assert len(rows) == 1
    assert rows[0].case_number == "CV2026-1435"
    assert rows[0].case_title == "Chang v. Ferrian"
    assert rows[0].division == "Law and Motion"
    assert rows[0].page_start == 2


def test_yolo_parses_probate_notes_pdf():
    sha = "00a1442d916e1aff3b59841f36358d21f209d07ea378dfc47852b44dd229a7cd"
    path = Path("archive/yolo") / sha[:2] / f"{sha}.pdf"
    if not path.exists():
        pytest.skip("Yolo archive fixture not present in this checkout")

    rows = yolo.parse(
        path.read_bytes(),
        "https://www.yolo.courts.ca.gov/sites/default/files/yolo/default/2026-05/ATO-PRB-260519.pdf",
        source_sha256=sha,
    )

    assert len(rows) == 2
    assert rows[0].case_number == "PR2026-0097"
    assert rows[0].case_title == "Estate of Brienes"
    assert rows[0].division == "Probate Notes"
    assert rows[0].dept == "11"
    assert rows[1].case_number == "PR2025-0310"
    assert rows[1].dept == "14"
