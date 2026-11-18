from datetime import date

from counties.santa_cruz.scraper import parse
from counties.tuolumne.tests.test_parse import _pdf


def test_titled_case_layout_since_2026_09():
    pdf = _pdf([
        [
            "Page 1 of 2",
            "Law & Motion Tentative Rulings",
            "November 17, 2026 8:30 a.m.",
            "Tentative rulings are not posted in unlawful detainer cases.",
            "Matias et al. v. Hospitality Staffing Solutions, LLC, et al. (23CV00490)",
            "Motion for Final Approval of Class Action Settlement",
            "The motion is granted and the Court will sign the proposed order.",
            "Rocha et al. v. FCA US LLC (25CV03559)",
            "Plaintiffs' Motion to Compel Special Interrogatories Nos. 10 and 26, and for Monetary",
            "Sanctions",
            "The motion to compel special interrogatories nos. 10 and 26 is granted.",
        ],
        [
            "Page 2 of 2",
            "Further responses shall be served no later than December 18, 2026.",
            "Swanson v. Toga LLC (26CV01485)",
            "Plaintiff's Motion to Be Relieved",
            "The unopposed motion is granted.",
        ],
    ])
    rulings = parse(pdf, "https://example.test/santa-cruz-tuesday.pdf")
    assert [r.case_number for r in rulings] == ["23CV00490", "25CV03559", "26CV01485"]
    assert {r.hearing_date for r in rulings} == {date(2026, 11, 17)}
    assert rulings[0].case_title == "Matias et al. v. Hospitality Staffing Solutions, LLC, et al."
    assert rulings[1].motion_type.endswith("and for Monetary Sanctions")
    assert "December 18, 2026" in rulings[1].body_text
    assert "Page 2 of 2" not in rulings[1].body_text


def test_old_layout_with_space_before_comma_in_date():
    pdf = _pdf([[
        "LAW AND MOTION TENTATIVE RULINGS",
        "DATE: SEPTEMBER 3 , 2026 TIME: 8:30 A.M.",
        "No. 25CV00519",
        "HANSEN v. PIZZUTI",
        "PLAINTIFF'S DEMURRER",
        "The demurrer is overruled.",
    ]])
    rulings = parse(pdf, "https://example.test/santa-cruz-thursday.pdf")
    assert [(r.case_number, r.hearing_date) for r in rulings] == [("25CV00519", date(2026, 9, 3))]


def test_empty_calendar_has_no_rulings():
    pdf = _pdf([["Law & Motion Tentative Rulings", "November 4, 2026 8:30 a.m.",
                 "There are no civil law and motion matters on calendar."]])
    assert parse(pdf, "https://example.test/santa-cruz-wednesday.pdf") == []
