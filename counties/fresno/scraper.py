"""Fresno County tentative-ruling discovery."""

from __future__ import annotations

import re
from urllib.parse import ParseResult

from counties.static_pdf import discover_static_pdfs

BASE = "https://www.fresno.courts.ca.gov/online-services/tentative-rulings"
LANDING_PAGES = [BASE]


def _dept_hint(parsed: ParseResult, _text: str, _page_url: str) -> str | None:
    m = re.search(r"dept[-_ ]?(\d+)", parsed.path, re.I)
    return m.group(1) if m else None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"www.fresno.courts.ca.gov", "fresno.courts.ca.gov"},
        path_test=lambda parsed, _text: "/system/files/tentative-rulings/" in parsed.path,
        default_division="Civil Law and Motion",
        dept_hint=_dept_hint,
    )
