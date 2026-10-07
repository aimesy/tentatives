"""Santa Cruz County public Drive-file tentative-ruling discovery."""

from __future__ import annotations

from counties.drive import DRIVE_ALLOWED_SOURCE_HOSTS, drive_file_ref
from counties.new_county_parsers import parse_santa_cruz as parse

BASE = "https://www.santacruz.courts.ca.gov/online-services/civil-tentative-rulings"
LANDING_PAGES = [BASE]
ALLOWED_SOURCE_HOSTS = DRIVE_ALLOWED_SOURCE_HOSTS
DRIVE_FILES = [
    ("1QuRXS5RfYDffVYxQ3ufZIP31BuaXqAQG", "santa-cruz-monday.pdf", "Monday"),
    ("1OVosHcVeE9Jn6s-4j16PzodiHieN9dbr", "santa-cruz-tuesday.pdf", "Tuesday"),
    ("1ZAPp3HpcqWFteIFLuCQyZG3vvrhxaVph", "santa-cruz-wednesday.pdf", "Wednesday"),
    ("1BAo24z9BGMS4Tbk1t5nGFkCmrd0lvFY1", "santa-cruz-thursday.pdf", "Thursday"),
    ("1VBMVjzacqOq24YoY4I4XExuBHewopqfJ", "santa-cruz-friday.pdf", "Friday"),
]
WAYBACK_ALLOW_NON_EXTENSION = True
WAYBACK_PDF_PATTERNS = [
    f"https://drive.google.com/uc?export=download&id={file_id}"
    for file_id, _filename, _weekday in DRIVE_FILES
]
_FILE_BY_ID = {file_id: (filename, weekday) for file_id, filename, weekday in DRIVE_FILES}


def discover_live(_html: str, page_url: str | None = None, base_url: str = BASE):
    return []


def discover_live_extra(session, errors=None):
    return [
        drive_file_ref(
            file_id,
            filename,
            source_page_url=BASE,
            division_hint="Civil Law and Motion",
            link_text=f"Santa Cruz {weekday}",
        )
        for file_id, filename, weekday in DRIVE_FILES
    ]


def ref_from_wayback_url(url: str, wayback_ts: str | None = None):
    for file_id, (filename, weekday) in _FILE_BY_ID.items():
        if file_id not in url:
            continue
        ref = drive_file_ref(
            file_id,
            filename,
            source_page_url=BASE,
            division_hint="Civil Law and Motion",
            link_text=f"Santa Cruz {weekday}",
        )
        return type(ref)(
            url=url,
            filename=ref.filename,
            wayback_ts=wayback_ts,
            dept_hint=ref.dept_hint,
            division_hint=ref.division_hint,
            link_text=ref.link_text,
            source_page_url=ref.source_page_url,
        )
    return drive_file_ref("unknown", "santa-cruz-wayback.pdf", source_page_url=BASE)
