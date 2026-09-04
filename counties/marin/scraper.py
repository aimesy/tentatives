"""Marin County public tentative-ruling source discovery."""

from __future__ import annotations

from urllib.parse import ParseResult

from counties.new_county_parsers import parse_marin as parse
from counties.static_pdf import discover_static_pdfs

BASE = "https://www.marin.courts.ca.gov/online-services/tentative-rulings"
LANDING_PAGES = [BASE]
WAYBACK_PDF_PATTERNS = [
    "https://www.marin.courts.ca.gov/system/files/tentative-rulings/*.pdf",
]


def _division_hint(parsed: ParseResult, text: str, _page_url: str) -> str | None:
    hay = f"{parsed.path} {text}".lower()
    if "family" in hay:
        return "Family Law"
    if "probate" in hay:
        return "Probate"
    if "civil" in hay:
        return "Civil"
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"www.marin.courts.ca.gov", "marin.courts.ca.gov"},
        path_test=lambda parsed, _text: "/system/files/tentative-rulings/" in parsed.path.lower(),
        division_hint=_division_hint,
    )
