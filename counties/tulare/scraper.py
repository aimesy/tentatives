"""Tulare County public tentative-ruling source discovery."""

from __future__ import annotations

from counties.common import PageRef, PdfRef
from counties.new_county_parsers import parse_tulare_page as parse_page_capture
from counties.new_county_parsers import parse_tulare_pdf as parse
from counties.static_pdf import discover_static_pdfs

BASE = "https://www.tulare.courts.ca.gov/general-information/tentative-rulings"
LANDING_PAGES = [BASE]
WAYBACK_PDF_PATTERNS = [
    "https://www.tulare.courts.ca.gov/system/files/tentative-rulings/*.pdf",
]
PAGE_CAPTURE_URLS = [
    PageRef(url=BASE, title="Tulare Tentative Rulings", page_kind="tentative_rulings_page"),
]

PROBATE_REFS = [
    PdfRef(
        url="https://www.tulare.courts.ca.gov/system/files/tentative-rulings/probate-tentative-rulings-visalia.pdf",
        filename="probate-tentative-rulings-visalia.pdf",
        division_hint="Probate",
        link_text="Probate Tentative Rulings - Visalia",
        source_page_url=BASE,
    ),
    PdfRef(
        url="https://www.tulare.courts.ca.gov/system/files/tentative-rulings/probate-tentative-rulings-scjc.pdf",
        filename="probate-tentative-rulings-scjc.pdf",
        division_hint="Probate",
        link_text="Probate Tentative Rulings - SCJC",
        source_page_url=BASE,
    ),
]


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    refs = discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"www.tulare.courts.ca.gov", "tulare.courts.ca.gov"},
        path_test=lambda parsed, _text: "/system/files/tentative-rulings/" in parsed.path.lower(),
    )
    if (page_url or base_url) == BASE:
        refs.extend(PROBATE_REFS)
    return refs
