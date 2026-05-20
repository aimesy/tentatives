"""Tuolumne County tentative-ruling discovery."""

from __future__ import annotations

import re
from urllib.parse import ParseResult

from counties.static_pdf import discover_static_pdfs

BASE = "https://www.tuolumne.courts.ca.gov/online-services/tentative-rulings-and-case-notes"
LANDING_PAGES = [BASE]


def _dept_hint(parsed: ParseResult, text: str, _page_url: str) -> str | None:
    hay = f"{parsed.path} {text}"
    m = re.search(r"(?:department|dept|tr[-_ ]?d|case[-_ ]?notes?[-_ ]?d)(?:[-_ ]?)(\d+)", hay, re.I)
    return m.group(1) if m else None


def _division_hint(parsed: ParseResult, text: str, _page_url: str) -> str | None:
    hay = f"{parsed.path} {text}"
    if re.search(r"case[-_ ]?notes?", hay, re.I):
        return "Case Notes"
    return "Civil Law and Motion"


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"www.tuolumne.courts.ca.gov", "tuolumne.courts.ca.gov"},
        path_test=lambda parsed, text: (
            "/system/files/tentative-rulings/" in parsed.path
        ),
        dept_hint=_dept_hint,
        division_hint=_division_hint,
    )
