"""Sierra County public Drive-file tentative-ruling discovery."""

from __future__ import annotations

from counties.drive import DRIVE_ALLOWED_SOURCE_HOSTS, drive_file_ref
from counties.new_county_parsers import parse_sierra as parse

BASE = "https://www.sierra.courts.ca.gov/online-services/tentative-rulings"
LANDING_PAGES = [BASE]
ALLOWED_SOURCE_HOSTS = DRIVE_ALLOWED_SOURCE_HOSTS
DRIVE_FILES = [
    ("17RJ4PEhce-1OvPpZY8yRs01k-wAULiTN", "sierra-law-and-motion.pdf", "Law and Motion"),
    ("16SmHyFfWh90LTCfM7N4WNw_5f9zvVThu", "sierra-probate.pdf", "Probate"),
    ("1vHcw_sNqo-3wPePXorO_T5nNBGXrVl5i", "sierra-cmc.pdf", "Case Management Conference"),
    ("16hoZfiSfS7nnckxmR45XvN_oxVHUPVBM", "sierra-guardianships.pdf", "Guardianships"),
]
WAYBACK_ALLOW_NON_EXTENSION = True
WAYBACK_PDF_PATTERNS = [
    f"https://drive.google.com/uc?export=download&id={file_id}"
    for file_id, _filename, _division in DRIVE_FILES
]
_FILE_BY_ID = {file_id: (filename, division) for file_id, filename, division in DRIVE_FILES}


def discover_live(_html: str, page_url: str | None = None, base_url: str = BASE):
    return []


def discover_live_extra(session, errors=None):
    return [
        drive_file_ref(
            file_id,
            filename,
            source_page_url=BASE,
            division_hint=division,
            link_text=f"Sierra {division}",
        )
        for file_id, filename, division in DRIVE_FILES
    ]


def ref_from_wayback_url(url: str, wayback_ts: str | None = None):
    for file_id, (filename, division) in _FILE_BY_ID.items():
        if file_id not in url:
            continue
        ref = drive_file_ref(
            file_id,
            filename,
            source_page_url=BASE,
            division_hint=division,
            link_text=f"Sierra {division}",
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
    return drive_file_ref("unknown", "sierra-wayback.pdf", source_page_url=BASE)
