"""Riverside County tentative-ruling discovery."""

from __future__ import annotations

import re
from urllib.parse import ParseResult

from counties.static_pdf import discover_static_pdfs

BASE = "https://www.riverside.courts.ca.gov/online-services/tentative-rulings"
LANDING_PAGES = [BASE]


def _dept_hint(parsed: ParseResult, text: str, _page_url: str) -> str | None:
    hay = f"{parsed.path} {text}"
    m = re.search(r"(?:department|dept\.?|^|/)([A-Z]{1,3}\d{1,3})", hay, re.I)
    return m.group(1).upper() if m else None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"www.riverside.courts.ca.gov", "riverside.courts.ca.gov"},
        path_test=lambda parsed, text: (
            parsed.path.lower().endswith(".pdf")
            and ("ruling" in parsed.path.lower() or "ruling" in text.lower())
        ),
        default_division="Law and Motion",
        dept_hint=_dept_hint,
    )
