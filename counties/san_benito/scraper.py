"""San Benito County public tentative-ruling source discovery."""

from __future__ import annotations

from urllib.parse import ParseResult

from counties.new_county_parsers import parse_san_benito as parse
from counties.static_pdf import discover_static_pdfs

BASE = "https://www.sanbenito.courts.ca.gov"
LANDING_PAGES = [
    BASE,
    f"{BASE}/news/tentative-rulings",
]
WAYBACK_PDF_PATTERNS = [
    "https://www.sanbenito.courts.ca.gov/system/files/tentative-rulings/*.pdf",
]


def _division_hint(parsed: ParseResult, text: str, _page_url: str) -> str | None:
    hay = f"{parsed.path} {text}".lower()
    if "family" in hay:
        return "Family Law"
    if "civil" in hay:
        return "Civil"
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"www.sanbenito.courts.ca.gov", "sanbenito.courts.ca.gov"},
        path_test=lambda parsed, text: (
            "/system/files/tentative-rulings/" in parsed.path.lower()
            or "tentative" in f"{parsed.path} {text}".lower()
        ),
        division_hint=_division_hint,
    )
