"""Shasta County tentative-ruling discovery."""

from __future__ import annotations

import re
from urllib.parse import ParseResult

from counties.static_pdf import discover_static_pdfs

BASE = "https://shasta.courts.ca.gov/online-services/tentative-rulings"
LANDING_PAGES = [BASE]

_OLD_TO_CURRENT_DEPT = {
    "d10": "24",
    "d7": "44",
    "d5": "51",
    "d6": "52",
    "d11": "53",
    "d8": "63",
    "d3": "64",
}


def _dept_hint(parsed: ParseResult, text: str, _page_url: str) -> str | None:
    hay = f"{parsed.path} {text}".lower()
    m = re.search(r"department\s+(\d+)", hay)
    if m:
        return m.group(1)
    for old, current in _OLD_TO_CURRENT_DEPT.items():
        if old in hay:
            return current
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"shasta.courts.ca.gov", "www.shasta.courts.ca.gov"},
        path_test=lambda parsed, _text: "/system/files/tentative/" in parsed.path,
        default_division="Civil / Probate / Family Law",
        dept_hint=_dept_hint,
    )
