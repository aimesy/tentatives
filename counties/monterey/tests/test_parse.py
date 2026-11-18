from datetime import date

from counties.monterey.scraper import parse
from counties.tuolumne.tests.test_parse import _pdf

CAPTURE = {
    "discovered_filename": "2026-11-06-24CV004780-7443600.pdf",
    "source_page_url": "https://api.monterey.courts.ca.gov/api/tentativerulings/date?date=2026-11-06",
}


def test_hearing_date_line_layout():
    pdf = _pdf([[
        "TENTATIVE RULING",
        "Hearing Date: November 9, 2026",
    ]])
    # No case number: nothing to parse.
    assert parse(pdf, "https://example.test/doc/1") == []


def test_date_after_heading_layout():
    pdf = _pdf([[
        "1",
        "TENTATIVE RULING",
        "November 12, 2026",
        "Peninsula Radiation Oncology Specialists, et al. vs. Community Hospital of the Monterey",
        "Peninsula, et al.",
        "26CV000055",
        "Demurrer to Second Amended Complaint",
        "Summary",
        "The demurrer is OVERRULED.",
    ]])
    [ruling] = parse(pdf, "https://example.test/doc/2", capture=CAPTURE)
    assert ruling.hearing_date == date(2026, 11, 12)
    assert ruling.case_number == "26CV000055"
    assert ruling.case_title.endswith("Monterey Peninsula, et al.")
    assert ruling.motion_type == "Demurrer to Second Amended Complaint"
    assert "OVERRULED" in ruling.body_text


def test_no_date_in_text_uses_the_api_hearing_date():
    pdf = _pdf([[
        "TENTATIVE RULING",
        "Jason Asmus v. Sterling Management (24CV004780)",
        "Jason Asmus' Motion to Proceed by Clerk's Transcript on Appeal:",
        "By this motion, plaintiff seeks approval to select a Clerk's Transcript.",
        "The motion is GRANTED.",
    ]])
    [ruling] = parse(pdf, "https://example.test/doc/3", capture=CAPTURE)
    assert ruling.hearing_date == date(2026, 11, 6)
    assert ruling.case_title == "Jason Asmus v. Sterling Management"
    assert ruling.motion_type == "Jason Asmus' Motion to Proceed by Clerk's Transcript on Appeal"
    assert ruling.body_text.startswith("By this motion")
    # Without the capture there is no date, so no ruling.
    assert parse(pdf, "https://example.test/doc/3") == []
