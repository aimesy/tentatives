"""Santa Clara County tentative-ruling discovery."""

from __future__ import annotations

import re
from urllib.parse import ParseResult

from counties.static_pdf import discover_static_pdfs

BASE = "https://santaclara.courts.ca.gov/online-services/tentative-rulings"
DEPARTMENTS = [1, 2, 6, 7, 10, 12, 13, 16, 19, 22]
LANDING_PAGES = [
    f"https://santaclara.courts.ca.gov/online-services/tentative-rulings/department-{dept}-tentative-rulings"
    for dept in DEPARTMENTS
]


def _dept_hint(parsed: ParseResult, _text: str, page_url: str) -> str | None:
    m = re.search(r"dept[-_ ]?(\d+)", parsed.path, re.I)
    if not m:
        m = re.search(r"department-(\d+)-", page_url, re.I)
    return m.group(1) if m else None


def _division_hint(_parsed: ParseResult, _text: str, page_url: str) -> str | None:
    if "department-2-" in page_url or "department-7-" in page_url:
        return "Probate"
    if "department-19-" in page_url or "department-22-" in page_url:
        return "Complex Civil"
    return "Civil Law and Motion"


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"santaclara.courts.ca.gov", "www.santaclara.courts.ca.gov"},
        path_test=lambda parsed, _text: "/system/files/tentative-ruling/" in parsed.path,
        dept_hint=_dept_hint,
        division_hint=_division_hint,
    )
