"""San Bernardino County tentative-ruling discovery."""

from __future__ import annotations

import re
from urllib.parse import ParseResult

from counties.static_pdf import discover_static_pdfs

BASE = "https://old.sb-court.org/GeneralInfo/TentativeRulings.aspx"
LANDING_PAGES = [BASE]


def _dept_hint(parsed: ParseResult, _text: str, _page_url: str) -> str | None:
    m = re.search(r"CV([RS]\d{2})\d{6}\.pdf", parsed.path, re.I)
    return m.group(1).upper() if m else None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"old.sb-court.org"},
        path_test=lambda parsed, _text: (
            "/desktopmodules/tentativerulings/tentativerulings/" in parsed.path.lower()
        ),
        default_division="Civil",
        dept_hint=_dept_hint,
    )
