from datetime import date
from pathlib import Path

import pytest

from counties.el_dorado.scraper import parse_file


ARCHIVE_DIR = Path(__file__).resolve().parents[3] / "archive" / "el-dorado"
BASE_URL = "https://www.eldorado.courts.ca.gov/system/files/tentative-rulings"


def _archive_pdf(sha: str) -> Path:
    return ARCHIVE_DIR / sha[:2] / f"{sha}.pdf"


@pytest.mark.parametrize(
    (
        "sha",
        "filename",
        "expected_date",
        "expected_dept",
        "expected_style",
        "case_numbers",
        "title_checks",
    ),
    [
        (
            "e986339fa520936aed5f424a899bad08798c785b9a5fc6532d82b735ad390032",
            "20260415.pdf",
            date(2026, 4, 15),
            "12",
            "lawandmotion-tentative-rulings",
            [
                "SFL20140287",
                "26FL0160",
                "23FL0439",
                "23FL1077",
                "25FL0925",
                "23FL0924",
                "25FL1181",
                "SFL20110036",
            ],
            {
                0: "ALEXANDRA OLMSTEAD V. AUSTIN KUENZI",
                7: "TINA WALLICK V. MICHAEL SHOTT",
            },
        ),
        (
            "691863c886e5a51486d70e44e560adf0b1d8ca6a577347f8000a1ef8ef07731e",
            "20260422-v3.pdf",
            date(2026, 4, 22),
            "12",
            "lawandmotion-tentative-rulings",
            [
                "SFL20140287",
                "24FL0388",
                "25FL0271",
                "24FL0292",
                "22FL0794",
                "SFL20210053",
            ],
            {
                0: "ALEXANDRA OLMSTEAD V. AUSTIN KUENZI",
                5: "MARIA DE LA CRUZ V. JUAN DE LA CRUZ VAZQUEZ",
            },
        ),
        (
            "f515f73bde78a701526e0299a1a36640ffd8046f19ddae1cabc337f50e871ee8",
            "20260429.pdf",
            date(2026, 4, 29),
            "12",
            "lawandmotion-tentative-rulings",
            [
                "22FL0464",
                "22FL0110",
                "24FL0571",
                "23FL0924",
                "23FL0933",
                "25FL0929",
                "SFL20200150",
                "SFL20150167",
            ],
            {
                0: "ALLISON MCGRARY V. CHRISTOPHER MCGRARY",
                6: "YVETTE GREY V. SCOTT LABAR",
            },
        ),
        (
            "c461f0e9437dc581dc6f68de82ae25cec78a9866deef5f13c323f5907d702dae",
            "law-and-motion-april-24-2026.pdf",
            date(2026, 4, 24),
            "4",
            "lawandmotion-calendar",
            ["25CV1279", "26CV0581", "26CV0624", "24CV2285"],
            {
                0: "MANFREDI v. LAKELAND VILLAGE OWNERS ASSN., ET AL.",
                3: "JACKSON v. PG&E CORP., ET AL.",
            },
        ),
        (
            "9779e72783048be387543a4f1d878764c044eb1732403312fb225706cf17404d",
            "law-and-motion-may-1-2026.pdf",
            date(2026, 5, 1),
            "4",
            "lawandmotion-calendar",
            [
                "25CV1279",
                "25CV0687",
                "25CV1050",
                "25CV1991",
                "25CV3051",
                "26CV0532",
                "25CV2445",
                "22CV1622",
            ],
            {
                0: "MANFREDI v. LAKELAND VILLAGE OWNERS ASSN., ET AL.",
                7: "SPRING OAKS CAPITAL SPV, LLC v. COTTLE",
            },
        ),
        (
            "b05df506382795191a5e2dc0d8de8c8908e9c648b00a3cb93d03cf15777ab385",
            "probate-april-17-2026.pdf",
            date(2026, 4, 17),
            "4",
            "probate-calendar",
            ["26PR0053", "26PR0049", "25PR0014"],
            {
                0: "ESTATE OF RIVERA",
                2: "CONSERVATORSHIP OF MATTHEW J.",
            },
        ),
        (
            "f1c8b51dabdc3dc1b47f4c6cfeef3fc9e729ffb364c50770124f12a7c48a889a",
            "probate-april-24-2026.pdf",
            date(2026, 4, 24),
            "4",
            "probate-calendar",
            [
                "SP20120040",
                "25PR0051",
                "24PR0138",
                "24PR0227",
                "22PR0314",
                "24PR0191",
                "24PR0341",
            ],
            {
                0: "CONSERVATORSHIP OF TRENT J.",
                6: "ESTATE OF CAMPAU",
            },
        ),
    ],
)
def test_archive_split_date_and_multiline_case_headers(
    sha,
    filename,
    expected_date,
    expected_dept,
    expected_style,
    case_numbers,
    title_checks,
):
    path = _archive_pdf(sha)
    assert path.exists(), f"missing archive source PDF: {path}"

    rulings = parse_file(str(path), source_url=f"{BASE_URL}/{filename}")

    assert len(rulings) == len(case_numbers)
    assert [r.case_number for r in rulings] == case_numbers
    assert all(r.hearing_date == expected_date for r in rulings)
    assert all(r.dept == expected_dept for r in rulings)
    assert all(r.style == expected_style for r in rulings)
    for pos, expected_title in title_checks.items():
        assert rulings[pos].case_title == expected_title


def test_archive_no_tentative_notice_stays_empty():
    sha = "7a08cfbea28b0807538e69a1dd9ba550bde39539ef2eb60a339d06b9bcd5d715"
    path = _archive_pdf(sha)
    assert path.exists(), f"missing archive source PDF: {path}"

    rulings = parse_file(str(path), source_url=f"{BASE_URL}/tr-d-09-2026-06-18.pdf")

    assert rulings == []
