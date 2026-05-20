"""Solano County tentative-ruling discovery."""

from __future__ import annotations

import re
from urllib.parse import ParseResult

from counties.static_pdf import discover_static_pdfs

BASE = "https://solano.courts.ca.gov/divisions/civil-court/tentative-rulings"
LANDING_PAGES = [BASE]

_WORDS = {
    "three": "3",
    "seven": "7",
    "eight": "8",
    "twenty-two": "22",
}


def _dept_hint(parsed: ParseResult, text: str, _page_url: str) -> str | None:
    m = re.search(r"dept_(\d+)", parsed.path, re.I)
    if m:
        return m.group(1)
    lower = text.lower()
    for word, number in _WORDS.items():
        if word in lower:
            return number
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    allowed_names = {"dept_3.pdf", "dept_7.pdf", "dept_8.pdf", "dept_22.pdf", "misc_dept.pdf"}
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"solano.courts.ca.gov", "www.solano.courts.ca.gov"},
        path_test=lambda parsed, _text: parsed.path.rsplit("/", 1)[-1].lower() in allowed_names,
        default_division="Civil / Probate",
        dept_hint=_dept_hint,
    )
